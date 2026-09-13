"""Putting back what the trash took, and merging two people into one.

The restore half of `PersonLifecycle`, split out in Round H (step H5) when
stores/history_repo_lifecycle.py stood at 450 lines.

Measuring LCOM on that class returns ONE component, which is why earlier
rounds left it alone — but every method touches `self._owner`, the delegation
handle back to the repo facade, and a handle every method holds links every
method to every other. Discount it and the class has eight components; the
largest is this one: restore/merge/purge all walk hidden rows, re-key them,
and resequence. (That defect in the LCOM tool is what step H6 fixes.)

This is a MIXIN, not a new class: `PersonLifecycle` is a facade target —
stores/history_repo.py forwards a dozen public names to it by identity — so
the class must keep its name and its single instance. Only the file is split.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from stores.history_models import dedupe_key, sql_count
from stores.history_repo_identity import TAIL_FP_LIMIT

log = logging.getLogger("chatbot")


def _hidden_row_key(row: dict) -> str:
    """The identity a hidden row would have once it is visible again."""
    return dedupe_key(row.get("direction") or "in",
                      row.get("from_nick") or "",
                      row.get("ts_display") or "",
                      row.get("kind") or "text",
                      row.get("media_url") or row.get("text") or "")

async def _delete_hidden(owner, nick: str, person) -> None:
    """The row work of one purge: hidden messages, then tombstones."""
    if not nick:
        await owner.db.execute("DELETE FROM messages WHERE deleted_at<>''")
        await _erase_tombstones(owner)
        return
    await owner.db.execute(
        "DELETE FROM messages WHERE deleted_at<>'' AND person_id=?",
        (int(person["id"]),))
    if person.get("deleted_at"):
        await _erase_person(owner, int(person["id"]))

async def _erase_person(owner, pid: int) -> None:
    """Erase every row that belongs to one person, then the person."""
    for table in ("messages", "cursors", "gaps"):
        await owner.db.execute(f"DELETE FROM {table} WHERE person_id=?", (pid,))
    await owner.db.execute("DELETE FROM persons WHERE id=?", (pid,))

async def _erase_tombstones(owner) -> None:
    """Erase every row of every tombstoned person, then the persons."""
    for table in ("messages", "cursors", "gaps"):
        await owner.db.execute(
            f"DELETE FROM {table} WHERE person_id IN "
            "(SELECT id FROM persons WHERE deleted_at<>'')")
    await owner.db.execute("DELETE FROM persons WHERE deleted_at<>''")


class RestoreMixin:
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

    async def _restore_one_row(self, row, token: str, alive: set) -> bool:
        """Resurrect one hidden row, recomputing its identity.

        False means the row was purged instead: the same message was
        re-collected while it sat hidden, so the tombstone must not come
        back as a double. `alive` is the caller's set of visible identities
        and grows with every row this restores.
        """
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
        """Erase hidden rows — and a removed person — for good.

        With no nick this is the whole trash: hidden messages AND tombstoned
        persons go. With a nick it is that person's hidden messages, plus
        their tombstone when they are a removed person (a nick never keeps a
        row pointing at nothing).
        """
        person = None
        if nick:
            person = await self._owner.get_person(nick)
            if not person:
                return 0
        before = await self.deleted_count(nick)
        await _delete_hidden(self._owner, nick, person)
        await self._owner.db.commit()
        if person:
            await self._owner._recount(int(person["id"]))
        return before

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
