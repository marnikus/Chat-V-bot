"""Lifecycle person — extracted from history_repo_lifecycle (H-C5 split)

Delete/restore/merge person, ≤150 LOC.
"""

from __future__ import annotations

import json
import logging

from stores.history_repo_lifecycle_trash import _erase_person
from stores.history_repo_restore import RestoreLadder

log = logging.getLogger("chatbot")


class LifecyclePerson:
    def __init__(self, owner):
        self._owner = owner
        self._restore = RestoreLadder(owner)

    async def _restore_rows(self, person_id: int, token: str) -> int:
        return await self._restore._restore_rows(person_id, token)

    async def _restore_one_row(self, row, token: str, alive: set) -> bool:
        return await self._restore._restore_one_row(row, token, alive)

    async def restore_deleted(self, nick: str, token: str) -> int:
        person = await self._owner.get_person(nick)
        if not person or not token:
            return 0
        restored = await self._restore_rows(int(person["id"]), str(token))
        if restored:
            await self._resequence(int(person["id"]))
            await self._owner._recount(int(person["id"]))
        return restored

    async def delete_person(self, nick: str, hard: bool = False, token: str = "") -> bool:
        person = await self._owner.get_person(nick)
        if not person:
            return False
        pid = int(person["id"])
        if hard:
            await _erase_person(self._owner, pid)
        else:
            stamp = token or self._owner.new_op_token()
            await self._owner.db.execute(
                "UPDATE messages SET deleted_at=?, dup_key='' WHERE person_id=? AND deleted_at=''",
                (stamp, pid),
            )
            await self._owner.db.execute("UPDATE persons SET deleted_at=? WHERE id=?", (stamp, pid))
        await self._owner.db.commit()
        if not hard:
            await self._owner._recount(pid)
            await self._owner.reset_cursor(nick)
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
        if token and str(token) != str(person.get("deleted_at") or "") and not restored:
            return False
        await self._owner.db.execute("UPDATE persons SET deleted_at=NULL WHERE id=?", (pid,))
        await self._owner.db.commit()
        await self._resequence(pid)
        await self._owner._recount(pid)
        return True

    async def merge_persons(self, from_nick: str, into_nick: str) -> int:
        source = await self._owner.get_person(from_nick)
        target = await self._owner.get_person(into_nick)
        if not source or not target or source["id"] == target["id"]:
            return 0
        src, dst = int(source["id"]), int(target["id"])
        moved = 0
        rows = await self._owner.db.fetchall("SELECT id FROM messages WHERE person_id=? ORDER BY ord", (src,))
        for row in rows:
            cur = await self._owner.db.execute(
                "UPDATE OR IGNORE messages SET person_id=? WHERE id=?", (dst, int(row[0]))
            )
            moved += int(cur.rowcount or 0)
        await self._owner.db.execute("DELETE FROM messages WHERE person_id=?", (src,))
        await self._owner.db.execute("UPDATE gaps SET person_id=? WHERE person_id=?", (dst, src))
        await self._owner.db.execute("DELETE FROM cursors WHERE person_id=?", (src,))
        nicks = list(dict.fromkeys(list(target.get("my_nicks") or []) + list(source.get("my_nicks") or [])))
        await self._owner.db.execute(
            "UPDATE persons SET my_nicks=? WHERE id=?", (json.dumps(nicks, ensure_ascii=False), dst)
        )
        await self._owner.db.execute("DELETE FROM persons WHERE id=?", (src,))
        await self._owner.db.commit()
        await self._resequence(dst)
        await self._owner._recount(dst)
        return moved
