"""What happens to a whole conversation, not to one row.

The lifecycle half of `stores/history_repo.py`: the collector's rename when a
nick's case or spacing changed (only after the two histories proved to be the
same conversation), the per-person sync cursor the collector reads and moves,
and the trash — soft-delete/restore/purge with an operation token, deleting or
restoring a person, and merging one person into another.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime

from stores.history_models import dedupe_key, sql_count
from stores.history_repo_identity import TAIL_FP_LIMIT
from stores.history_repo_restore import RestoreMixin, _erase_person
from stores.history_requests import WriteContext

log = logging.getLogger("chatbot")


def _sig_or(current: dict, key: str, value):
    """`value` wins unless it is None, which means "leave the cursor as is"."""
    return current.get(key, "") if value is None else value


class PersonLifecycle(RestoreMixin):
    """What happens to a whole conversation, not to one row."""

    def __init__(self, owner):
        """`owner` is the `HistoryRepo` this part borrows state from."""
        self._owner = owner


    async def get_cursor(self, person_id: int) -> dict:
        row = await self._owner.db.fetchone(
            "SELECT * FROM cursors WHERE person_id=?", (person_id,))
        if not row:
            return {"person_id": person_id, "last_ord": 0, "dom_count": 0,
                    "head_sig": "", "tail_sig": "", "head_any": "",
                    "tail_any": "", "tail_fps": [],
                    "tail_keys": [], "bootstrapped": False,
                    "full_scan_complete": False, "full_scan_at": ""}
        data = dict(row)
        try:
            data["tail_fps"] = json.loads(data.get("tail_fps") or "[]")
        except Exception:                            # noqa: BLE001
            data["tail_fps"] = []
        try:
            data["tail_keys"] = json.loads(data.get("tail_keys") or "[]")
        except Exception:                            # noqa: BLE001
            data["tail_keys"] = []
        data["bootstrapped"] = bool(data.get("bootstrapped"))
        data["full_scan_complete"] = bool(data.get("full_scan_complete"))
        return data

    async def reset_cursor(self, nick: str) -> None:
        """Forget where we were in the DOM — the archive itself is untouched."""
        person_id = await self._owner.ensure_person(nick)
        await self._owner.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, "
            "tail_sig, head_any, tail_any, tail_fps, tail_keys, "
            "bootstrapped, full_scan_complete, full_scan_at, updated_at) "
            "VALUES(?,?,0,'','','','','[]','[]',0,0,'',?) "
            "ON CONFLICT(person_id) DO UPDATE SET dom_count=0, head_sig='', "
            "tail_sig='', head_any='', tail_any='', tail_fps='[]', "
            "tail_keys='[]', bootstrapped=0, "
            "full_scan_complete=0, full_scan_at='', "
            "updated_at=excluded.updated_at",
            (person_id, await self._last_ord(person_id),
             datetime.now().isoformat(timespec="seconds")))
        await self._owner.db.commit()

    async def _last_ord(self, person_id: int) -> int:
        return int(await self._owner.db.scalar(
            "SELECT MAX(ord) FROM messages WHERE person_id=?", (person_id,), 0))

    async def mark_backfilled(self, nick_or_id) -> None:
        """Record that the full-top-to-bottom scan for this person is done.

        Once set, the passive collector and the incremental `COLLECT_HISTORY`
        block do NOT spend another full history check on that conversation.
        """
        person_id = (int(nick_or_id) if isinstance(nick_or_id, int)
                     else await self._owner.ensure_person(str(nick_or_id)))
        stamp = datetime.now().isoformat(timespec="seconds")
        await self._owner.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, "
            "tail_sig, head_any, tail_any, tail_fps, tail_keys, "
            "bootstrapped, full_scan_complete, full_scan_at, updated_at) "
            "VALUES(?,0,0,'','','','','[]','[]',0,1,?,?) "
            "ON CONFLICT(person_id) DO UPDATE SET full_scan_complete=1, "
            "full_scan_at=excluded.full_scan_at, updated_at=excluded.updated_at",
            (person_id, stamp, stamp))
        await self._owner.db.commit()

    async def soft_delete_message(self, nick: str, message_id: int,
                                  token: str = "") -> str:
        """Hide ONE message. Returns the token that reverses it ('' = no-op)."""
        person = await self._owner.get_person(nick)
        if not person:
            return ""
        stamp = token or self._owner.new_op_token()
        cur = await self._owner.db.execute(
            "UPDATE messages SET deleted_at=? "
            "WHERE id=? AND person_id=? AND deleted_at=''",
            (stamp, int(message_id), int(person["id"])))
        if not cur.rowcount:
            await self._owner.db.commit()
            return ""
        await self._owner.db.commit()
        await self._owner._recount(int(person["id"]))
        return stamp

    async def soft_delete_history(self, nick: str, token: str = "") -> str:
        """Hide every visible message of a person, keeping the person.

        The hidden rows also LOSE their identity (`dup_key` is blanked):
        the collector must treat this conversation as never-collected and
        re-read it from the live chat on the next tick (Bug 3, 2026-09-08).
        The person record, its `my_nicks` and the cursor's `last_ord` floor
        survive — only the message history is cleared.
        """
        person = await self._owner.get_person(nick)
        if not person:
            return ""
        stamp = token or self._owner.new_op_token()
        cur = await self._owner.db.execute(
            "UPDATE messages SET deleted_at=?, dup_key='' "
            "WHERE person_id=? AND deleted_at=''",
            (stamp, int(person["id"])))
        hidden = int(cur.rowcount or 0)
        await self._owner.db.commit()
        if not hidden:
            return ""
        await self._owner._recount(int(person["id"]))
        await self.reset_cursor(nick)
        return stamp


    async def delete_person(self, nick: str, hard: bool = False,
                            token: str = "") -> bool:
        """Remove a person WITH their history.

        Soft (the default) tombstones the person and hides every message
        under one token, so a single Ctrl+Z brings both halves back. Like a
        history clear, the hidden rows lose their identity and the
        collection markers reset, so a re-visit re-collects from scratch
        (Bug 3, 2026-09-08). `hard` erases the rows — used only by an
        explicit purge.
        """
        person = await self._owner.get_person(nick)
        if not person:
            return False
        pid = int(person["id"])
        if hard:
            await _erase_person(self._owner, pid)
        else:
            stamp = token or self._owner.new_op_token()
            await self._owner.db.execute(
                "UPDATE messages SET deleted_at=?, dup_key='' WHERE "
                "person_id=? AND deleted_at=''", (stamp, pid))
            await self._owner.db.execute(
                "UPDATE persons SET deleted_at=? WHERE id=?", (stamp, pid))
        await self._owner.db.commit()
        if not hard:
            await self._owner._recount(pid)
            await self.reset_cursor(nick)
        return True


    async def _after_write(self, ctx: WriteContext) -> None:
        """Refresh counters and the resume cursor.

        `ctx.head_sig` / `ctx.tail_sig` (and their author-agnostic twins) of
        None mean "leave as is"; an empty string deliberately CLEARS the
        signature, which is how an interrupted read tells the next pass that
        it may not trust the shortcut. The eight values travel as one object
        because every caller already holds all eight (RULE 19 §19.4).
        """
        person_id = ctx.person_id
        await self._recount(person_id, ctx.my_nick)
        tail = [r for r in await self._owner.db.fetchall(
            "SELECT fp, dup_key FROM (SELECT fp, dup_key, ord FROM messages "
            "WHERE person_id=? ORDER BY ord DESC LIMIT ?) ORDER BY ord",
            (person_id, TAIL_FP_LIMIT))]
        tail_fps = [r[0] for r in tail]
        tail_keys = [r[1] for r in tail]
        current = await self._owner.get_cursor(person_id)
        flag = (current["bootstrapped"] if ctx.bootstrapped is None
                else ctx.bootstrapped)
        await self._owner.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, "
            "tail_sig, head_any, tail_any, tail_fps, tail_keys, "
            "bootstrapped, full_scan_complete, full_scan_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,0,'',?) "
            "ON CONFLICT(person_id) DO UPDATE SET last_ord=excluded.last_ord, "
            "dom_count=excluded.dom_count, head_sig=excluded.head_sig, "
            "tail_sig=excluded.tail_sig, head_any=excluded.head_any, "
            "tail_any=excluded.tail_any, tail_fps=excluded.tail_fps, "
            "tail_keys=excluded.tail_keys, "
            "bootstrapped=excluded.bootstrapped, updated_at=excluded.updated_at",
            (person_id, await self._owner._last_ord(person_id),
             ctx.dom_count or current.get("dom_count") or 0,
             _sig_or(current, "head_sig", ctx.head_sig),
             _sig_or(current, "tail_sig", ctx.tail_sig),
             _sig_or(current, "head_any", ctx.head_any),
             _sig_or(current, "tail_any", ctx.tail_any),
             json.dumps(tail_fps), json.dumps(tail_keys), 1 if flag else 0,
             datetime.now().isoformat(timespec="seconds")))
        await self._owner.db.commit()

    async def _recount(self, person_id: int, my_nick: str = "") -> None:
        # Counters describe what the user can SEE, so hidden (soft-deleted)
        # rows are excluded — while `last_ord` still spans every row so a
        # deletion can never make the next append reuse an ord.
        row = await self._owner.db.fetchone(
            "SELECT COUNT(*) AS n, "
            "SUM(direction='in') AS ins, SUM(direction='out') AS outs, "
            "SUM(media_id IS NOT NULL) AS media, "
            "MIN(ts_resolved) AS first_ts, MAX(ts_resolved) AS last_ts, "
            "(SELECT MAX(ord) FROM messages WHERE person_id=?) AS last_ord "
            "FROM messages WHERE person_id=? AND deleted_at=''",
            (person_id, person_id))
        nicks = await self._my_nicks_including(person_id, my_nick)
        await self._owner.db.execute(
            "UPDATE persons SET message_count=?, in_count=?, out_count=?, "
            "media_count=?, last_ord=?, my_nicks=?, "
            "first_seen=COALESCE(?, first_seen), last_seen=COALESCE(?, last_seen) "
            "WHERE id=?",
            (sql_count(row, "n"), sql_count(row, "ins"), sql_count(row, "outs"),
             sql_count(row, "media"), sql_count(row, "last_ord"),
             json.dumps(nicks, ensure_ascii=False),
             row["first_ts"], row["last_ts"], person_id))
        await self._owner.db.commit()

    async def _my_nicks_including(self, person_id: int, my_nick: str) -> list:
        """This person's known my_nicks, with `my_nick` added if it is new.

        The list only ever grows: a nick I used in this conversation once is
        still mine later, so a run that does not see it must not drop it.
        """
        person = await self._owner.get_person_by_id(person_id) or {}
        nicks = list(person.get("my_nicks") or [])
        clean = self._owner.normalise_nick(my_nick)
        if clean and clean not in nicks:
            nicks.append(clean)
        return nicks

    async def _touch_cursor(self, ctx: WriteContext) -> None:
        """Move the resume cursor, and nothing else.

        `my_nick` and `bootstrapped` are forced to their inert values on the way
        into `_after_write`, so no caller can change either by accident: a
        cursor touch must not add a nick to the person's `my_nicks` list (that
        is what `_recount` does with a non-empty nick), and must not claim the
        person was bootstrapped — it keeps whatever the cursor already says.
        """
        if not ctx.dom_count and ctx.head_sig is None and ctx.tail_sig is None:
            return
        await self._after_write(replace(ctx, my_nick="", bootstrapped=None))
