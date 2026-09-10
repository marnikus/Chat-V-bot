"""Write path of the message archive — facade (AREA B).

Append-only and idempotent; honest about holes.
Heavy lifting lives in ``_history_repo_*`` helpers (AREA B split).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence

from stores.history_db import HistoryDB
from stores.history_models import MessageRecord, AppendResult, Alignment, MAX_LIVE_ITEMS, dedupe_key, fingerprint
from stores._history_repo_alignment import align_batch, resolve_days, _minutes
from stores._history_repo_person import ConversationIdentity
from stores._history_repo_writer import AppendPlanner, _as_record, TAIL_FP_LIMIT
from stores._history_repo_recovery import MediaRecovery

log = logging.getLogger("chatbot")

class HistoryRepo:
    """Append-only writer for one archive database."""

    def __init__(self, db: HistoryDB, media=None, session_id: str = ""):
        self.db = db
        self.media = media
        self.session_id = session_id or ""
        self._scan_seq = 0
        self._persons = ConversationIdentity(self)
        self._writer = AppendPlanner(self)
        self._recovery = MediaRecovery(self)

    @staticmethod
    def normalise_nick(nick: str) -> str:
        return " ".join(str(nick or "").split()).strip()

    async def ensure_person(self, nick: str) -> int:
        return await self._persons.ensure_person(nick)

    async def get_person(self, nick: str) -> Optional[dict]:
        return await self._persons.get_person(nick)

    async def get_person_by_id(self, person_id: int) -> Optional[dict]:
        return await self._persons.get_person_by_id(person_id)

    @staticmethod
    def _person_dict(row) -> dict:
        return ConversationIdentity._person_dict(row)

    async def possible_duplicates(self) -> list[dict]:
        return await self._persons.possible_duplicates()

    async def rename_if_same_conversation(self, old_nick: str, new_nick: str, head_sig: str, tail_sig: str, head_any: str = "", tail_any: str = "", dom_count: int = -1, pane_same: bool = False) -> bool:
        return await self._persons.rename_if_same_conversation(old_nick, new_nick, head_sig, tail_sig, head_any, tail_any, dom_count, pane_same)

    async def get_cursor(self, person_id: int) -> dict:
        return await self._persons.get_cursor(person_id)

    async def reset_cursor(self, nick: str) -> None:
        return await self._persons.reset_cursor(nick)

    async def _last_ord(self, person_id: int) -> int:
        return await self._persons._last_ord(person_id)

    async def mark_backfilled(self, nick_or_id) -> None:
        return await self._persons.mark_backfilled(nick_or_id)

    async def append(self, nick: str, records: Iterable, my_nick: str = "", align: bool = True, expect_idx: Optional[int] = None, dom_count: int = 0, head_sig: Optional[str] = None, tail_sig: Optional[str] = None, now: Optional[datetime] = None, session_id: str = "", head_any: Optional[str] = None, tail_any: Optional[str] = None, prepend: bool = False) -> AppendResult:
        return await self._writer.append(nick, records, my_nick, align, expect_idx, dom_count, head_sig, tail_sig, now, session_id, head_any, tail_any, prepend)

    async def _prepend(self, person_id: int, recs, my_nick: str, now: datetime, dom_count: int, head_sig: Optional[str], tail_sig: Optional[str], session_id: str, nick: str = "", head_any: Optional[str] = None, tail_any: Optional[str] = None) -> AppendResult:
        return await self._writer._prepend(person_id, recs, my_nick, now, dom_count, head_sig, tail_sig, session_id, nick, head_any, tail_any)

    async def record_gap(self, nick_or_id, after_ord: int, reason: str, detail: str = "") -> None:
        person_id = (int(nick_or_id) if isinstance(nick_or_id, int) else await self.ensure_person(str(nick_or_id)))
        return await self._writer._record_gap(person_id, after_ord, reason, detail)

    async def _existing_dup_keys(self, person_id: int, keys) -> set:
        return await self._writer._existing_dup_keys(person_id, keys)

    async def _query_dup_keys(self, person_id: int, keys: list) -> set:
        return await self._writer._query_dup_keys(person_id, keys)

    @staticmethod
    def _slot_key(rec: MessageRecord) -> tuple:
        return AppendPlanner._slot_key(rec)

    async def _empty_slot_rows(self, person_id: int) -> list:
        return await self._writer._empty_slot_rows(person_id)

    @staticmethod
    def _slot_row_key(row) -> tuple:
        return AppendPlanner._slot_row_key(row)

    async def _take_empty_slot(self, person_id: int, rec: MessageRecord, used: dict, day: str = "", rows: Optional[list] = None) -> Optional[int]:
        return await self._writer._take_empty_slot(person_id, rec, used, day, rows)

    async def _fill_slot(self, slot_id: int, rec: MessageRecord, media_id: Optional[int]) -> None:
        return await self._writer._fill_slot(slot_id, rec, media_id)

    async def _ord_of(self, row_id: int) -> int:
        return await self._writer._ord_of(row_id)

    async def _media_id(self, rec: MessageRecord, nick: str = "", day: str = "") -> Optional[int]:
        return await self._writer._media_id(rec, nick, day)

    async def _ui_record(self, rec: MessageRecord, ord_value: int, day: str, my_nick: str, media_id) -> dict:
        return await self._writer._ui_record(rec, ord_value, day, my_nick, media_id)

    async def _record_gap(self, person_id: int, after_ord: int, reason: str, detail: str = "") -> None:
        return await self._writer._record_gap(person_id, after_ord, reason, detail)

    @staticmethod
    def _media_key(direction: str, from_nick: str, ts_display: str) -> str:
        return MediaRecovery._media_key(direction, from_nick, ts_display)

    async def recover_media(self, person_id: int, records, media=None, nick: str = "", now=None, requeue_failed: bool = True) -> dict:
        # default media is the repo’s media if not supplied
        eff_media = media if media is not None else self.media
        return await self._recovery.recover_media(person_id, records, eff_media, nick, now, requeue_failed)

    async def _all_person_keys(self, person_id: int) -> set:
        return await self._recovery._all_person_keys(person_id)

    async def has_repairable_media(self, person_id: int, include_failed: bool = False, rescan_after_s: int = 600) -> bool:
        return await self._recovery.has_repairable_media(person_id, include_failed, rescan_after_s)

    async def _touch_cursor(self, person_id: int, dom_count: int, head_sig: Optional[str], tail_sig: Optional[str], head_any: Optional[str] = None, tail_any: Optional[str] = None) -> None:
        return await self._writer._touch_cursor(person_id, dom_count, head_sig, tail_sig, head_any, tail_any)

    async def _after_write(self, person_id: int, my_nick: str, dom_count: int, head_sig: Optional[str], tail_sig: Optional[str], bootstrapped: Optional[bool], head_any: Optional[str] = None, tail_any: Optional[str] = None) -> None:
        return await self._writer._after_write(person_id, my_nick, dom_count, head_sig, tail_sig, bootstrapped, head_any, tail_any)

    async def _recount(self, person_id: int, my_nick: str = "") -> None:
        return await self._writer._recount(person_id, my_nick)

    @staticmethod
    def new_op_token() -> str:
        return (datetime.now().isoformat(timespec="seconds") + "#" + uuid.uuid4().hex[:8])

    async def soft_delete_message(self, nick: str, message_id: int, token: str = "") -> str:
        person = await self.get_person(nick)
        if not person:
            return ""
        stamp = token or self.new_op_token()
        cur = await self.db.execute("UPDATE messages SET deleted_at=? WHERE id=? AND person_id=? AND deleted_at=''", (stamp, int(message_id), int(person["id"])))
        if not cur.rowcount:
            await self.db.commit()
            return ""
        await self.db.commit()
        await self._recount(int(person["id"]))
        return stamp

    async def soft_delete_history(self, nick: str, token: str = "") -> str:
        person = await self.get_person(nick)
        if not person:
            return ""
        stamp = token or self.new_op_token()
        cur = await self.db.execute("UPDATE messages SET deleted_at=?, dup_key='' WHERE person_id=? AND deleted_at=''", (stamp, int(person["id"])))
        hidden = int(cur.rowcount or 0)
        await self.db.commit()
        if not hidden:
            return ""
        await self._recount(int(person["id"]))
        await self.reset_cursor(nick)
        return stamp

    async def restore_deleted(self, nick: str, token: str) -> int:
        person = await self.get_person(nick)
        if not person or not token:
            return 0
        restored = await self._restore_rows(int(person["id"]), str(token))
        if restored:
            await self._resequence(int(person["id"]))
            await self._recount(int(person["id"]))
        return restored

    async def _restore_rows(self, person_id: int, token: str) -> int:
        rows = await self.db.fetchdicts("SELECT m.id, m.direction, m.from_nick, m.kind, m.text, m.ts_display, md.url AS media_url FROM messages m LEFT JOIN media md ON md.id = m.media_id WHERE m.person_id=? AND m.deleted_at=?", (person_id, token))
        if not rows:
            return 0
        alive = {r[0] for r in await self.db.fetchall("SELECT dup_key FROM messages WHERE person_id=? AND deleted_at='' AND dup_key<>''", (person_id,))}
        restored = 0
        for row in rows:
            key = dedupe_key(row.get("direction") or "in", row.get("from_nick") or "", row.get("ts_display") or "", row.get("kind") or "text", row.get("media_url") or row.get("text") or "")
            if key and key in alive:
                await self.db.execute("DELETE FROM messages WHERE id=? AND deleted_at=?", (int(row["id"]), token))
                continue
            await self.db.execute("UPDATE messages SET deleted_at='', dup_key=? WHERE id=?", (key, int(row["id"])))
            if key:
                alive.add(key)
            restored += 1
        await self.db.commit()
        return restored

    async def deleted_count(self, nick: str = "") -> int:
        if nick:
            person = await self.get_person(nick)
            if not person:
                return 0
            return int(await self.db.scalar("SELECT COUNT(*) FROM messages WHERE person_id=? AND deleted_at<>''", (int(person["id"]),), 0))
        return int(await self.db.scalar("SELECT COUNT(*) FROM messages WHERE deleted_at<>''", (), 0))

    async def purge_deleted(self, nick: str = "") -> int:
        params: tuple = ()
        sql = "DELETE FROM messages WHERE deleted_at<>''"
        person = None
        if nick:
            person = await self.get_person(nick)
            if not person:
                return 0
            sql += " AND person_id=?"
            params = (int(person["id"]),)
        before = await self.deleted_count(nick)
        await self.db.execute(sql, params)
        await self.db.commit()
        if person:
            await self._recount(int(person["id"]))
        return before

    async def delete_person(self, nick: str, hard: bool = False, token: str = "") -> bool:
        person = await self.get_person(nick)
        if not person:
            return False
        pid = int(person["id"])
        if hard:
            await self.db.execute("DELETE FROM messages WHERE person_id=?", (pid,))
            await self.db.execute("DELETE FROM cursors WHERE person_id=?", (pid,))
            await self.db.execute("DELETE FROM gaps WHERE person_id=?", (pid,))
            await self.db.execute("DELETE FROM persons WHERE id=?", (pid,))
        else:
            stamp = token or self.new_op_token()
            await self.db.execute("UPDATE messages SET deleted_at=?, dup_key='' WHERE person_id=? AND deleted_at=''", (stamp, pid))
            await self.db.execute("UPDATE persons SET deleted_at=? WHERE id=?", (stamp, pid))
        await self.db.commit()
        if not hard:
            await self._recount(pid)
            await self.reset_cursor(nick)
        return True

    async def restore_person(self, nick: str, token: str = "") -> bool:
        person = await self.get_person(nick)
        if not person:
            return False
        pid = int(person["id"])
        stamp = token or (person.get("deleted_at") or "")
        restored = 0
        if stamp:
            restored = await self._restore_rows(pid, str(stamp))
        if token and str(token) != str(person.get("deleted_at") or "") and not restored:
            return False
        await self.db.execute("UPDATE persons SET deleted_at=NULL WHERE id=?", (pid,))
        await self.db.commit()
        await self._resequence(pid)
        await self._recount(pid)
        return True

    async def merge_persons(self, from_nick: str, into_nick: str) -> int:
        source = await self.get_person(from_nick)
        target = await self.get_person(into_nick)
        if not source or not target or source["id"] == target["id"]:
            return 0
        src, dst = int(source["id"]), int(target["id"])
        moved = 0
        rows = await self.db.fetchall("SELECT id FROM messages WHERE person_id=? ORDER BY ord", (src,))
        for row in rows:
            cur = await self.db.execute("UPDATE OR IGNORE messages SET person_id=? WHERE id=?", (dst, int(row[0])))
            moved += int(cur.rowcount or 0)
        await self.db.execute("DELETE FROM messages WHERE person_id=?", (src,))
        await self.db.execute("UPDATE gaps SET person_id=? WHERE person_id=?", (dst, src))
        await self.db.execute("DELETE FROM cursors WHERE person_id=?", (src,))
        nicks = list(dict.fromkeys(list(target.get("my_nicks") or []) + list(source.get("my_nicks") or [])))
        await self.db.execute("UPDATE persons SET my_nicks=? WHERE id=?", (json.dumps(nicks, ensure_ascii=False), dst))
        await self.db.execute("DELETE FROM persons WHERE id=?", (src,))
        await self.db.commit()
        await self._resequence(dst)
        await self._recount(dst)
        return moved

    async def _resequence(self, person_id: int) -> None:
        rows = await self.db.fetchall("SELECT id FROM messages WHERE person_id=? ORDER BY day, ts_display, ord, id", (person_id,))
        for index, row in enumerate(rows, start=1):
            await self.db.execute("UPDATE messages SET ord=? WHERE id=?", (index, int(row[0])))
        await self.db.commit()
