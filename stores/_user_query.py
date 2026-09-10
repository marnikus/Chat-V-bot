"""UserMemory query helpers — extracted (AREA B)."""

from __future__ import annotations

from typing import Optional

from stores.user_memory import UserRecord

class UserQuery:
    def __init__(self, mem):
        self.mem = mem

    async def get_queue(self) -> list[UserRecord]:
        cur = await self.mem._db.execute(
            "SELECT nick,gender,registered,anonymous,guest,first_seen,last_seen,messaged,message_count,last_messaged,notes FROM users WHERE messaged=0 ORDER BY first_seen DESC")
        return [self.mem._row(r) for r in await cur.fetchall()]

    async def get_all(self) -> list[UserRecord]:
        cur = await self.mem._db.execute(
            "SELECT nick,gender,registered,anonymous,guest,first_seen,last_seen,messaged,message_count,last_messaged,notes FROM users ORDER BY first_seen DESC")
        return [self.mem._row(r) for r in await cur.fetchall()]

    async def count_unmessaged(self) -> int:
        cur = await self.mem._db.execute("SELECT COUNT(*) FROM users WHERE messaged=0")
        row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def get_stats(self) -> dict:
        cur = await self.mem._db.execute("SELECT COUNT(*) FROM users")
        total = (await cur.fetchone())[0]
        cur = await self.mem._db.execute("SELECT COUNT(*) FROM users WHERE messaged=0")
        queued = (await cur.fetchone())[0]
        return {"total": total, "queued": queued, "done": total - queued}

    async def get_user(self, nick: str) -> Optional[UserRecord]:
        cur = await self.mem._db.execute(
            "SELECT nick,gender,registered,anonymous,guest,first_seen,last_seen,messaged,message_count,last_messaged,notes FROM users WHERE nick=?", (nick,))
        row = await cur.fetchone()
        return self.mem._row(row) if row else None
