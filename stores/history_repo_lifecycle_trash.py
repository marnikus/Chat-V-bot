"""Lifecycle trash — extracted from history_repo_lifecycle (H-C5 split)

Soft-delete, purge, erase, ≤150 LOC.
"""

from __future__ import annotations

import logging

from stores.history_repo_restore import _hidden_row_key as _restore_hidden_key

log = logging.getLogger("chatbot")


def _hidden_row_key(row: dict) -> str:
    return _restore_hidden_key(row)


async def _delete_hidden(owner, nick: str, person) -> None:
    if not nick:
        await owner.db.execute("DELETE FROM messages WHERE deleted_at<>''")
        await _erase_tombstones(owner)
        return
    await owner.db.execute("DELETE FROM messages WHERE deleted_at<>'' AND person_id=?", (int(person["id"]),))
    if person.get("deleted_at"):
        await _erase_person(owner, int(person["id"]))


async def _erase_person(owner, pid: int) -> None:
    for table in ("messages", "cursors", "gaps"):
        await owner.db.execute(f"DELETE FROM {table} WHERE person_id=?", (pid,))
    await owner.db.execute("DELETE FROM persons WHERE id=?", (pid,))


async def _erase_tombstones(owner) -> None:
    for table in ("messages", "cursors", "gaps"):
        await owner.db.execute(
            f"DELETE FROM {table} WHERE person_id IN (SELECT id FROM persons WHERE deleted_at<>'')"
        )
    await owner.db.execute("DELETE FROM persons WHERE deleted_at<>''")


class LifecycleTrash:
    def __init__(self, owner):
        self._owner = owner

    async def soft_delete_message(self, nick: str, message_id: int, token: str = "") -> str:
        person = await self._owner.get_person(nick)
        if not person:
            return ""
        stamp = token or self._owner.new_op_token()
        cur = await self._owner.db.execute(
            "UPDATE messages SET deleted_at=? WHERE id=? AND person_id=? AND deleted_at=''",
            (stamp, int(message_id), int(person["id"])),
        )
        if not cur.rowcount:
            await self._owner.db.commit()
            return ""
        await self._owner.db.commit()
        await self._owner._recount(int(person["id"]))
        return stamp

    async def soft_delete_history(self, nick: str, token: str = "") -> str:
        person = await self._owner.get_person(nick)
        if not person:
            return ""
        stamp = token or self._owner.new_op_token()
        cur = await self._owner.db.execute(
            "UPDATE messages SET deleted_at=?, dup_key='' WHERE person_id=? AND deleted_at=''",
            (stamp, int(person["id"])),
        )
        hidden = int(cur.rowcount or 0)
        await self._owner.db.commit()
        if not hidden:
            return ""
        await self._owner._recount(int(person["id"]))
        await self._owner.reset_cursor(nick)
        return stamp

    async def deleted_count(self, nick: str = "") -> int:
        if nick:
            person = await self._owner.get_person(nick)
            if not person:
                return 0
            return int(
                await self._owner.db.scalar(
                    "SELECT COUNT(*) FROM messages WHERE person_id=? AND deleted_at<>''",
                    (int(person["id"]),),
                    0,
                )
            )
        return int(await self._owner.db.scalar("SELECT COUNT(*) FROM messages WHERE deleted_at<>''", (), 0))

    async def purge_deleted(self, nick: str = "") -> int:
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
