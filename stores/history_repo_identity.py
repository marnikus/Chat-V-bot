"""Who a line belongs to, and how it becomes a row.

H-C4: alignment/day helpers moved to `history_repo_identity_helpers.py`
(≤200 LOC) named by responsibility. This file keeps person lifecycle.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from stores.history_models import LineIdentity, MessageRecord, dedupe_key, fingerprint
from stores.history_repo_identity_helpers import (
    _UI_BODY_SPECS,
    _UI_HEAD_SPECS,
    _UI_TAIL_SPECS,
    _as_record,
    _record_fields,
    _ui_media_payload,
    align_batch,
    resolve_days,
)
from stores.history_requests import PaneSignature, PlacedRecord

log = logging.getLogger("chatbot")
TAIL_FP_LIMIT = 200


class ConversationIdentity:
    def __init__(self, owner):
        self._owner = owner

    async def ensure_person(self, nick: str) -> int:
        clean = self._owner.normalise_nick(nick)
        if not clean:
            raise ValueError("a person needs a nick")
        row = await self._owner.db.fetchone("SELECT id FROM persons WHERE nick=?", (clean,))
        if row:
            return int(row[0])
        stamp = datetime.now().isoformat(timespec="seconds")
        await self._owner.db.execute(
            "INSERT OR IGNORE INTO persons(nick, nick_lc, first_seen, last_seen, created_at) VALUES(?,?,?,?,?)",
            (clean, clean.lower(), stamp, stamp, stamp),
        )
        await self._owner.db.commit()
        row = await self._owner.db.fetchone("SELECT id FROM persons WHERE nick=?", (clean,))
        return int(row[0])

    async def get_person(self, nick: str) -> Optional[dict]:
        row = await self._owner.db.fetchone(
            "SELECT * FROM persons WHERE nick=?", (self._owner.normalise_nick(nick),)
        )
        return self._owner._person_dict(row) if row else None

    async def get_person_by_id(self, person_id: int) -> Optional[dict]:
        row = await self._owner.db.fetchone("SELECT * FROM persons WHERE id=?", (person_id,))
        return self._owner._person_dict(row) if row else None

    async def possible_duplicates(self) -> list[dict]:
        rows = await self._owner.db.fetchdicts(
            "SELECT nick_lc, GROUP_CONCAT(nick, char(10)) AS nicks, COUNT(*) AS n, GROUP_CONCAT(id, ',') AS ids "
            "FROM persons WHERE deleted_at IS NULL GROUP BY nick_lc HAVING n > 1"
        )
        out = []
        for row in rows:
            out.append(
                {
                    "nick_lc": row["nick_lc"],
                    "nicks": (row["nicks"] or "").split("\n"),
                    "ids": [int(i) for i in (row["ids"] or "").split(",") if i],
                    "count": int(row["n"]),
                }
            )
        return out

    async def _ui_record(self, placed: PlacedRecord) -> dict:
        rec = placed.rec
        media = await self._ui_media(placed.media_id, rec) if placed.media_id else None
        item = {"ord": int(placed.ord_value or 0)}
        item.update(_record_fields(rec, _UI_HEAD_SPECS))
        item["my_nick"] = placed.my_nick or ""
        item.update(_record_fields(rec, _UI_BODY_SPECS))
        item["media"] = media
        item.update(_record_fields(rec, _UI_TAIL_SPECS))
        item["day"] = placed.day or ""
        item["occ"] = int(rec.occ or 0)
        return item

    async def _ui_media(self, media_id, rec: MessageRecord):
        row = await self._read_media_row(media_id)
        if not row:
            return None
        return _ui_media_payload(row, media_id, rec)

    async def _read_media_row(self, media_id):
        if self._owner.media is not None:
            return await self._owner.media.get(media_id)
        row = await self._owner.db.fetchone("SELECT * FROM media WHERE id=?", (media_id,))
        return dict(row) if row else None

    async def _media_id(self, rec: MessageRecord, nick: str = "", day: str = "") -> Optional[int]:
        if not rec.media_url:
            return None
        if self._owner.media is not None:
            return await self._owner.media.register(rec.media_url, rec.media_kind or rec.kind, nick=nick, day=day)
        stamp = datetime.now().isoformat(timespec="seconds")
        await self._owner.db.execute(
            "INSERT INTO media(url, kind, state, ref_count, created_at, last_used) VALUES(?,?,'pending',1,?,?) "
            "ON CONFLICT(url) DO UPDATE SET ref_count=ref_count+1, last_used=excluded.last_used",
            (rec.media_url, rec.media_kind or rec.kind or "image", stamp, stamp),
        )
        row = await self._owner.db.fetchone("SELECT id FROM media WHERE url=?", (rec.media_url,))
        return int(row[0]) if row else None

    async def rename_if_same_conversation(
        self, old_nick: str, new_nick: str, pane: PaneSignature, pane_same: bool = False
    ) -> bool:
        if not pane_same:
            return False
        old = await self._owner.get_person(old_nick)
        if not old:
            return False
        clean = self._owner.normalise_nick(new_nick)
        if not clean or clean == old["nick"]:
            return False
        if await self._owner.get_person(clean):
            return False
        pid = int(old["id"])
        cursor = await self._owner.get_cursor(pid)
        if not self._same_conversation(cursor, pane):
            return False
        return await self._apply_rename(pid, str(old["nick"]), clean)

    def _same_conversation(self, cursor: dict, pane: PaneSignature) -> bool:
        if not cursor.get("bootstrapped"):
            return False
        if pane.dom_count >= 0 and int(cursor.get("dom_count") or -1) != pane.dom_count:
            return False
        return self._exact_match(cursor, pane.head_sig, pane.tail_sig) or self._any_match(
            cursor, pane.head_any, pane.tail_any
        )

    @staticmethod
    def _exact_match(cursor: dict, head_sig: str, tail_sig: str) -> bool:
        return bool(
            head_sig
            and tail_sig
            and head_sig == str(cursor.get("head_sig") or "")
            and tail_sig == str(cursor.get("tail_sig") or "")
        )

    @staticmethod
    def _any_match(cursor: dict, head_any: str, tail_any: str) -> bool:
        return bool(
            head_any
            and tail_any
            and str(cursor.get("head_any") or "")
            and head_any == str(cursor.get("head_any") or "")
            and tail_any == str(cursor.get("tail_any") or "")
        )

    async def _apply_rename(self, pid: int, old_nick: str, clean: str) -> bool:
        stamp = datetime.now().isoformat(timespec="seconds")
        await self._owner.db.execute(
            "UPDATE persons SET nick=?, nick_lc=?, last_seen=? WHERE id=?", (clean, clean.lower(), stamp, pid)
        )
        await self._owner.db.commit()
        moved = await self._reattribute(pid, old_nick, clean)
        log.info("partner “%s” is now “%s” — continues (%d re-attributed)", old_nick, clean, moved)
        return True

    async def _reattribute(self, pid: int, old_nick: str, clean: str) -> int:
        rows = await self._owner.db.fetchdicts(
            "SELECT m.id, m.occ, m.kind, m.text, m.ts_display, md.url AS media_url FROM messages m "
            "LEFT JOIN media md ON md.id = m.media_id WHERE m.person_id=? AND m.from_nick=?",
            (pid, old_nick),
        )
        for row in rows:
            payload = row.get("media_url") or row.get("text") or ""
            occ = int(row.get("occ") or 0)
            await self._owner.db.execute(
                "UPDATE messages SET from_nick=?, dup_key=?, fp=? WHERE id=?",
                (
                    clean,
                    dedupe_key(LineIdentity("in", clean, row.get("ts_display") or "", row.get("kind") or "text", payload)),
                    fingerprint(LineIdentity("in", clean, row.get("ts_display") or "", row.get("kind") or "text", payload), occ),
                    int(row["id"]),
                ),
            )
        if rows:
            await self._owner.db.commit()
        return len(rows)
