"""History repo 7a deletes a (<150)."""
import asyncio, json, logging, re
from datetime import datetime
from typing import Optional

class HistoryRepoMixin7a:
    def new_op_token() -> str:
        """One stamp shared by every row of a single delete operation.

        Undo is then a single `WHERE deleted_at=?` update, so the history
        entry stays tiny no matter how many messages were hidden.
        """
        return (datetime.now().isoformat(timespec="seconds") + "#" +
                uuid.uuid4().hex[:8])

    async def soft_delete_message(self, nick: str, message_id: int,
                                  token: str = "") -> str:
        """Hide ONE message. Returns the token that reverses it ('' = no-op)."""
        person = await self.get_person(nick)
        if not person:
            return ""
        stamp = token or self.new_op_token()
        cur = await self.db.execute(
            "UPDATE messages SET deleted_at=? "
            "WHERE id=? AND person_id=? AND deleted_at=''",
            (stamp, int(message_id), int(person["id"])))
        if not cur.rowcount:
            await self.db.commit()
            return ""
        await self.db.commit()
        await self._recount(int(person["id"]))
        return stamp

    async def soft_delete_history(self, nick: str, token: str = "") -> str:
        """Hide every visible message of a person, keeping the person.

        The hidden rows also LOSE their identity (`dup_key` is blanked):
        the collector must treat this conversation as never-collected and
        re-read it from the live chat on the next tick (Bug 3, 2026-09-08).
        The person record, its `my_nicks` and the cursor's `last_ord` floor
        survive — only the message history is cleared.
        """
        person = await self.get_person(nick)
        if not person:
            return ""
        stamp = token or self.new_op_token()
        cur = await self.db.execute(
            "UPDATE messages SET deleted_at=?, dup_key='' "
            "WHERE person_id=? AND deleted_at=''",
            (stamp, int(person["id"])))
        hidden = int(cur.rowcount or 0)
        await self.db.commit()
        if not hidden:
            return ""
        await self._recount(int(person["id"]))
        await self.reset_cursor(nick)
        return stamp

    async def restore_deleted(self, nick: str, token: str) -> int:
        """Exact reversal of one delete operation. Returns rows restored.

        Rows that were re-collected while they were hidden (their identity
        already exists on a visible row) do not come back as a second copy —
        their stale tombstone is dropped instead, because the content
        already lives in the re-collected twin (Bug 3, 2026-09-08).
        """
        person = await self.get_person(nick)
        if not person or not token:
            return 0
        restored = await self._restore_rows(int(person["id"]), str(token))
        if restored:
            await self._resequence(int(person["id"]))
            await self._recount(int(person["id"]))
        return restored

    async def _restore_rows(self, person_id: int, token: str) -> int:
        """Un-hide one operation's rows, recomputing each row's identity."""
        rows = await self.db.fetchdicts(
            "SELECT m.id, m.direction, m.from_nick, m.kind, m.text, "
            "m.ts_display, md.url AS media_url "
            "FROM messages m LEFT JOIN media md ON md.id = m.media_id "
            "WHERE m.person_id=? AND m.deleted_at=?",
            (person_id, token))
        if not rows:
            return 0
        alive = {r[0] for r in await self.db.fetchall(
            "SELECT dup_key FROM messages WHERE person_id=? AND "
            "deleted_at='' AND dup_key<>''", (person_id,))}
        restored = 0
        for row in rows:
            key = dedupe_key(row.get("direction") or "in",
                             row.get("from_nick") or "",
                             row.get("ts_display") or "",
                             row.get("kind") or "text",
                             row.get("media_url") or row.get("text") or "")
            if key and key in alive:
                # re-collected while hidden: the visible copy is the message
                # now; the stale tombstone must not resurrect as a double
                await self.db.execute(
                    "DELETE FROM messages WHERE id=? AND deleted_at=?",
                    (int(row["id"]), token))
                continue
            await self.db.execute(
                "UPDATE messages SET deleted_at='', dup_key=? WHERE id=?",
                (key, int(row["id"])))
            if key:
                alive.add(key)
            restored += 1
        await self.db.commit()
        return restored

