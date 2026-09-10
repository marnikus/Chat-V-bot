"""UserQuery — the read side of the People table.

`UserMemory` (AREA B2 split) had grown three near-identical SELECTs over the
same eleven columns plus two COUNTs; a caller asking "who is queued" and a
caller asking "how many are queued" walked different code to the same place.
The queries live here, one column list, one row walk; the aggregate keeps its
public names as delegations because `backend/`, the bridges and the actions
all read the queue through `UserMemory`.

The collaborator holds no state of its own: `_db` is read from the aggregate
at call time, so `switch_db()` (a world switch moves the connection) and
`close()` are seen here immediately.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:                                  # only for the annotation
    from stores.user_memory import UserMemory, UserRecord

log = logging.getLogger("chatbot")

class UserQuery:
    """Queued / all / single-person reads over `users`."""

    #: the eleven columns `_row` knows how to turn into a `UserRecord`
    COLUMNS = ("nick,gender,registered,anonymous,guest,first_seen,last_seen,"
               "messaged,message_count,last_messaged,notes")
    ORDER = "ORDER BY first_seen DESC"

    def __init__(self, owner: "UserMemory") -> None:
        self._owner = owner

    @property
    def _db(self):
        """The connection the aggregate holds right now."""
        return self._owner._db

    async def _rows(self, where: str = "",
                    params: tuple[Any, ...] = ()) -> list:
        cur = await self._db.execute(
            f"SELECT {self.COLUMNS} FROM users {where} {self.ORDER}".strip(),
            params)
        rows = await cur.fetchall()
        return [self._owner._row(r) for r in rows]

    # ── the queue ────────────────────────────────────────────────
    async def get_queue(self) -> list["UserRecord"]:
        """Everyone still waiting for a message, newest sighting first."""
        return await self._rows("WHERE messaged=0")

    async def get_all(self) -> list["UserRecord"]:
        return await self._rows()

    async def get_user(self, nick: str) -> Optional["UserRecord"]:
        cur = await self._db.execute(
            f"SELECT {self.COLUMNS} FROM users WHERE nick=?", (nick,))
        row = await cur.fetchone()
        return self._owner._row(row) if row else None

    # ── counters ─────────────────────────────────────────────────
    async def count_unmessaged(self) -> int:
        """Number of people still awaiting a message (the backlog).

        A single COUNT rather than materialising every row through get_all().
        """
        return await self._count("WHERE messaged=0")

    async def count_all(self) -> int:
        return await self._count("")

    async def _count(self, where: str) -> int:
        cur = await self._db.execute(
            f"SELECT COUNT(*) FROM users {where}".strip())
        row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def get_stats(self) -> dict:
        total = await self.count_all()
        queued = await self.count_unmessaged()
        return {"total": total, "queued": queued, "done": total - queued}
