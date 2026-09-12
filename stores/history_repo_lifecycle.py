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
from datetime import datetime
from typing import Optional

from stores.history_models import dedupe_key
from stores.history_repo_identity import TAIL_FP_LIMIT

log = logging.getLogger("chatbot")


def _hidden_row_key(row: dict) -> str:
    """The fresh dedupe identity of one still-hidden message row."""
    return dedupe_key(row.get("direction") or "in",
                      row.get("from_nick") or "",
                      row.get("ts_display") or "",
                      row.get("kind") or "text",
                      row.get("media_url") or row.get("text") or "")


def _sig_or(current: dict, key: str, value):
    """`value` wins unless it is None ("leave as is")."""
    return current.get(key, "") if value is None else value


class PersonLifecycle:
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

    async def restore_deleted(self, nick: str, token: str) -> int:
        """Exact reversal of one delete operation. Returns rows restored.

        Rows that were re-collected while they were hidden (their identity
        already exists on a visible row) do not come back as a second copy —
        their stale tombstone is dropped instead, because the content
        already lives in the re-collected twin (Bug 3, 2026-09-08).
        """
        person = await self._owner.get_person(nick)
        if not person or not token:
            return 0
        restored = await self._restore_rows(int(person["id"]), str(token))
        if restored:
            await self._resequence(int(person["id"]))
            await self._owner._recount(int(person["id"]))
        return restored

    async def _restore_rows(self, person_id: int, token: str) -> int:
        """Un-hide one operation's rows, recomputing each row's identity."""
        rows = await self._owner.db.fetchdicts(
            "SELECT m.id, m.direction, m.from_nick, m.kind, m.text, "
            "m.ts_display, md.url AS media_url "
            "FROM messages m LEFT JOIN media md ON md.id = m.media_id "
            "WHERE m.person_id=? AND m.deleted_at=?",
            (person_id, token))
        if not rows:
            return 0
        alive = {r[0] for r in await self._owner.db.fetchall(
            "SELECT dup_key FROM messages WHERE person_id=? AND "
            "deleted_at='' AND dup_key<>''", (person_id,))}
        restored = 0
        for row in rows:
            if await self._restore_one_row(row, token, alive):
                restored += 1
        await self._owner.db.commit()
        return restored

    async def _restore_one_row(self, row: dict, token: str,
                               alive: set) -> bool:
        """Resurrect one hidden row (False: purged as a re-collected double)."""
        key = _hidden_row_key(row)
        if key and key in alive:
            # re-collected while hidden: the visible copy is the message
            # now; the stale tombstone must not resurrect as a double
            await self._owner.db.execute(
                "DELETE FROM messages WHERE id=? AND deleted_at=?",
                (int(row["id"]), token))
            return False
        await self._owner.db.execute(
            "UPDATE messages SET deleted_at='', dup_key=? WHERE id=?",
            (key, int(row["id"])))
        if key:
            alive.add(key)
        return True

    async def deleted_count(self, nick: str = "") -> int:
        if nick:
            person = await self._owner.get_person(nick)
            if not person:
                return 0
            return int(await self._owner.db.scalar(
                "SELECT COUNT(*) FROM messages WHERE person_id=? AND "
                "deleted_at<>''", (int(person["id"]),), 0))
        return int(await self._owner.db.scalar(
            "SELECT COUNT(*) FROM messages WHERE deleted_at<>''", (), 0))

    async def purge_deleted(self, nick: str = "") -> int:
        """Erase hidden rows for good — the ONLY path that removes bytes."""
        params: tuple = ()
        sql = "DELETE FROM messages WHERE deleted_at<>''"
        person = None
        if nick:
            person = await self._owner.get_person(nick)
            if not person:
                return 0
            sql += " AND person_id=?"
            params = (int(person["id"]),)
        before = await self.deleted_count(nick)
        await self._owner.db.execute(sql, params)
        await self._owner.db.commit()
        if person:
            await self._owner._recount(int(person["id"]))
        return before

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
            await self._owner.db.execute("DELETE FROM messages WHERE person_id=?", (pid,))
            await self._owner.db.execute("DELETE FROM cursors WHERE person_id=?", (pid,))
            await self._owner.db.execute("DELETE FROM gaps WHERE person_id=?", (pid,))
            await self._owner.db.execute("DELETE FROM persons WHERE id=?", (pid,))
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

    async def restore_person(self, nick: str, token: str = "") -> bool:
        person = await self._owner.get_person(nick)
        if not person:
            return False
        pid = int(person["id"])
        stamp = token or (person.get("deleted_at") or "")
        restored = 0
        if stamp:
            restored = await self._restore_rows(pid, str(stamp))
        if token and str(token) != str(person.get("deleted_at") or "") \
                and not restored:
            # A token that matches neither the person's tombstone nor any
            # hidden row refuses: silently undeleting the person while the
            # rows stay hidden would strand the archive (HRP-13).
            return False
        await self._owner.db.execute("UPDATE persons SET deleted_at=NULL WHERE id=?",
                              (pid,))
        await self._owner.db.commit()
        await self._resequence(pid)
        await self._owner._recount(pid)
        return True

    async def merge_persons(self, from_nick: str, into_nick: str) -> int:
        """Fold one nick's archive into another. Returns the rows moved."""
        source = await self._owner.get_person(from_nick)
        target = await self._owner.get_person(into_nick)
        if not source or not target or source["id"] == target["id"]:
            return 0
        src, dst = int(source["id"]), int(target["id"])
        moved = 0
        rows = await self._owner.db.fetchall(
            "SELECT id FROM messages WHERE person_id=? ORDER BY ord", (src,))
        for row in rows:
            cur = await self._owner.db.execute(
                "UPDATE OR IGNORE messages SET person_id=? WHERE id=?",
                (dst, int(row[0])))
            moved += int(cur.rowcount or 0)
        await self._owner.db.execute("DELETE FROM messages WHERE person_id=?", (src,))
        await self._owner.db.execute("UPDATE gaps SET person_id=? WHERE person_id=?",
                              (dst, src))
        await self._owner.db.execute("DELETE FROM cursors WHERE person_id=?", (src,))
        nicks = list(dict.fromkeys(list(target.get("my_nicks") or []) +
                                   list(source.get("my_nicks") or [])))
        await self._owner.db.execute("UPDATE persons SET my_nicks=? WHERE id=?",
                              (json.dumps(nicks, ensure_ascii=False), dst))
        await self._owner.db.execute("DELETE FROM persons WHERE id=?", (src,))
        await self._owner.db.commit()
        await self._resequence(dst)
        await self._owner._recount(dst)
        return moved

    async def _resequence(self, person_id: int) -> None:
        rows = await self._owner.db.fetchall(
            "SELECT id FROM messages WHERE person_id=? "
            "ORDER BY day, ts_display, ord, id", (person_id,))
        for index, row in enumerate(rows, start=1):
            await self._owner.db.execute("UPDATE messages SET ord=? WHERE id=?",
                                  (index, int(row[0])))
        await self._owner.db.commit()

    async def _after_write(self, person_id: int, my_nick: str, dom_count: int,
                           head_sig: Optional[str], tail_sig: Optional[str],
                           bootstrapped: Optional[bool],
                           head_any: Optional[str] = None,
                           tail_any: Optional[str] = None) -> None:
        """Refresh counters and the resume cursor.

        `head_sig` / `tail_sig` (and their author-agnostic twins) of None
        mean "leave as is"; an empty string deliberately CLEARS the
        signature, which is how an interrupted read tells the next pass that
        it may not trust the shortcut.
        """
        await self._recount(person_id, my_nick)
        tail = [r for r in await self._owner.db.fetchall(
            "SELECT fp, dup_key FROM (SELECT fp, dup_key, ord FROM messages "
            "WHERE person_id=? ORDER BY ord DESC LIMIT ?) ORDER BY ord",
            (person_id, TAIL_FP_LIMIT))]
        tail_fps = [r[0] for r in tail]
        tail_keys = [r[1] for r in tail]
        current = await self._owner.get_cursor(person_id)
        flag = current["bootstrapped"] if bootstrapped is None else bootstrapped
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
             dom_count or current.get("dom_count") or 0,
             _sig_or(current, "head_sig", head_sig),
             _sig_or(current, "tail_sig", tail_sig),
             _sig_or(current, "head_any", head_any),
             _sig_or(current, "tail_any", tail_any),
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
        person = await self._owner.get_person_by_id(person_id) or {}
        nicks = list(person.get("my_nicks") or [])
        clean = self._owner.normalise_nick(my_nick)
        if clean and clean not in nicks:
            nicks.append(clean)
        await self._owner.db.execute(
            "UPDATE persons SET message_count=?, in_count=?, out_count=?, "
            "media_count=?, last_ord=?, my_nicks=?, "
            "first_seen=COALESCE(?, first_seen), last_seen=COALESCE(?, last_seen) "
            "WHERE id=?",
            (int(row["n"] or 0), int(row["ins"] or 0), int(row["outs"] or 0),
             int(row["media"] or 0), int(row["last_ord"] or 0),
             json.dumps(nicks, ensure_ascii=False),
             row["first_ts"], row["last_ts"], person_id))
        await self._owner.db.commit()

    async def _touch_cursor(self, person_id: int, dom_count: int,
                            head_sig: Optional[str],
                            tail_sig: Optional[str],
                            head_any: Optional[str] = None,
                            tail_any: Optional[str] = None) -> None:
        if not dom_count and head_sig is None and tail_sig is None:
            return
        await self._after_write(person_id, "", dom_count, head_sig, tail_sig,
                                bootstrapped=None, head_any=head_any,
                                tail_any=tail_any)
