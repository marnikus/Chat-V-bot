
"""HistoryRepo person / cursor helpers — extracted (AREA B)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

log = logging.getLogger("chatbot")

class ConversationIdentity:
    def __init__(self, repo):
        self.repo = repo

    @property
    def db(self):
        return self.repo.db

    @staticmethod
    def normalise_nick(nick: str) -> str:
        return " ".join(str(nick or "").split()).strip()

    async def ensure_person(self, nick: str) -> int:
        clean = self.normalise_nick(nick)
        if not clean:
            raise ValueError("a person needs a nick")
        row = await self.db.fetchone("SELECT id FROM persons WHERE nick=?", (clean,))
        if row:
            return int(row[0])
        stamp = datetime.now().isoformat(timespec="seconds")
        await self.db.execute(
            "INSERT OR IGNORE INTO persons(nick, nick_lc, first_seen, last_seen, created_at) VALUES(?,?,?,?,?)",
            (clean, clean.lower(), stamp, stamp, stamp))
        await self.db.commit()
        row = await self.db.fetchone("SELECT id FROM persons WHERE nick=?", (clean,))
        return int(row[0])

    async def get_person(self, nick: str) -> Optional[dict]:
        row = await self.db.fetchone("SELECT * FROM persons WHERE nick=?", (self.normalise_nick(nick),))
        return self._person_dict(row) if row else None

    async def get_person_by_id(self, person_id: int) -> Optional[dict]:
        row = await self.db.fetchone("SELECT * FROM persons WHERE id=?", (person_id,))
        return self._person_dict(row) if row else None

    @staticmethod
    def _person_dict(row) -> dict:
        data = dict(row)
        try:
            data["my_nicks"] = json.loads(data.get("my_nicks") or "[]")
        except Exception:
            data["my_nicks"] = []
        data["deleted"] = bool(data.get("deleted_at"))
        return data

    async def possible_duplicates(self) -> list[dict]:
        rows = await self.db.fetchdicts(
            "SELECT nick_lc, GROUP_CONCAT(nick, char(10)) AS nicks, COUNT(*) AS n, GROUP_CONCAT(id, ',') AS ids FROM persons WHERE deleted_at IS NULL GROUP BY nick_lc HAVING n > 1")
        out = []
        for row in rows:
            out.append({"nick_lc": row["nick_lc"], "nicks": (row["nicks"] or "").split("\n"), "ids": [int(i) for i in (row["ids"] or "").split(",") if i], "count": int(row["n"])})
        return out

    async def rename_if_same_conversation(self, old_nick: str, new_nick: str, head_sig: str, tail_sig: str, head_any: str = "", tail_any: str = "", dom_count: int = -1, pane_same: bool = False) -> bool:
        if not pane_same:
            return False
        old = await self.get_person(old_nick)
        if not old:
            return False
        clean = self.normalise_nick(new_nick)
        if not clean or clean == old["nick"]:
            return False
        if await self.get_person(clean):
            return False
        cursor = await self.get_cursor(int(old["id"]))
        if not cursor.get("bootstrapped"):
            return False
        if dom_count >= 0 and int(cursor.get("dom_count") or -1) != dom_count:
            return False
        same_exact = bool(head_sig and tail_sig and head_sig == str(cursor.get("head_sig") or "") and tail_sig == str(cursor.get("tail_sig") or ""))
        same_any = bool(head_any and tail_any and str(cursor.get("head_any") or "") and head_any == str(cursor.get("head_any") or "") and tail_any == str(cursor.get("tail_any") or ""))
        if not (same_exact or same_any):
            return False
        stamp = datetime.now().isoformat(timespec="seconds")
        pid = int(old["id"])
        await self.db.execute("UPDATE persons SET nick=?, nick_lc=?, last_seen=? WHERE id=?", (clean, clean.lower(), stamp, pid))
        await self.db.commit()
        rows = await self.db.fetchdicts("SELECT m.id, m.occ, m.kind, m.text, m.ts_display, md.url AS media_url FROM messages m LEFT JOIN media md ON md.id = m.media_id WHERE m.person_id=? AND m.from_nick=?", (pid, old["nick"]))
        for row in rows:
            payload = row.get("media_url") or row.get("text") or ""
            occ = int(row.get("occ") or 0)
            from stores.history_models import dedupe_key, fingerprint
            await self.db.execute("UPDATE messages SET from_nick=?, dup_key=?, fp=? WHERE id=?",
                (clean, dedupe_key("in", clean, row.get("ts_display") or "", row.get("kind") or "text", payload),
                 fingerprint("in", clean, row.get("ts_display") or "", row.get("kind") or "text", payload, occ), int(row["id"])))
        if rows:
            await self.db.commit()
        log.info("partner \"%s\" is now \"%s\" — the same conversation continues under the new nick (%d stored line(s) re-attributed)", old["nick"], clean, len(rows))
        return True

    async def get_cursor(self, person_id: int) -> dict:
        row = await self.db.fetchone("SELECT * FROM cursors WHERE person_id=?", (person_id,))
        if not row:
            return {"person_id": person_id, "last_ord": 0, "dom_count": 0, "head_sig": "", "tail_sig": "", "head_any": "", "tail_any": "", "tail_fps": [], "tail_keys": [], "bootstrapped": False, "full_scan_complete": False, "full_scan_at": ""}
        data = dict(row)
        try:
            data["tail_fps"] = json.loads(data.get("tail_fps") or "[]")
        except Exception:
            data["tail_fps"] = []
        try:
            data["tail_keys"] = json.loads(data.get("tail_keys") or "[]")
        except Exception:
            data["tail_keys"] = []
        data["bootstrapped"] = bool(data.get("bootstrapped"))
        data["full_scan_complete"] = bool(data.get("full_scan_complete"))
        return data

    async def reset_cursor(self, nick: str) -> None:
        person_id = await self.ensure_person(nick)
        await self.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, tail_sig, head_any, tail_any, tail_fps, tail_keys, bootstrapped, full_scan_complete, full_scan_at, updated_at) "
            "VALUES(?,?,0,'','','','','[]','[]',0,0,'',?) ON CONFLICT(person_id) DO UPDATE SET dom_count=0, head_sig='', tail_sig='', head_any='', tail_any='', tail_fps='[]', tail_keys='[]', bootstrapped=0, full_scan_complete=0, full_scan_at='', updated_at=excluded.updated_at",
            (person_id, await self._last_ord(person_id), datetime.now().isoformat(timespec="seconds")))
        await self.db.commit()

    async def _last_ord(self, person_id: int) -> int:
        return int(await self.db.scalar("SELECT MAX(ord) FROM messages WHERE person_id=?", (person_id,), 0))

    async def mark_backfilled(self, nick_or_id) -> None:
        person_id = (int(nick_or_id) if isinstance(nick_or_id, int) else await self.ensure_person(str(nick_or_id)))
        stamp = datetime.now().isoformat(timespec="seconds")
        await self.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, tail_sig, head_any, tail_any, tail_fps, tail_keys, bootstrapped, full_scan_complete, full_scan_at, updated_at) VALUES(?,0,0,'','','','','[]','[]',0,1,?,?) ON CONFLICT(person_id) DO UPDATE SET full_scan_complete=1, full_scan_at=excluded.full_scan_at, updated_at=excluded.updated_at",
            (person_id, stamp, stamp))
        await self.db.commit()
