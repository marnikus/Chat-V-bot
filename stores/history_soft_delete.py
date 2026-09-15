"""Message-level soft delete and restore (Round H step H-C4).

One named concept: the tombstone ladder. A message is soft-deleted by flag, a
whole conversation's messages by the same flag in one pass, and `restore`
walks the tombstones back — `_restore_rows` decides which rows come back and
`_restore_one_row` clears one. `purge_deleted` is the irreversible half and
lives here because it reads exactly the set `deleted_count` reports.

Split out of `stores/history_repo_lifecycle.py` by the plan's H-C4 rule (a
helper named for a responsibility, §16.1.1). `PersonLifecycle` keeps the
person-level operations and the cursor bookkeeping; this mixin inherits into
it, so `HistoryRepo`'s delegators resolve exactly as before.

Import direction: `stores.history_models` / `stores.history_requests` for the
record and request values; nothing imports back.
"""

from __future__ import annotations

from stores.history_models import LineIdentity, dedupe_key





def _hidden_row_key(row: dict) -> str:
    """The identity a hidden row would have once it is visible again."""
    return dedupe_key(LineIdentity(row.get("direction") or "in",
                                   row.get("from_nick") or "",
                                   row.get("ts_display") or "",
                                   row.get("kind") or "text",
                                   row.get("media_url") or row.get("text") or ""))


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


class SoftDeleteMixin:
    """Tombstone, restore and purge archived messages; on ``PersonLifecycle``."""

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
