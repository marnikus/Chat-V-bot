"""A task-reentrant boundary for operations on the live message archive.

aiosqlite serializes SQL statements, not multi-await operations. A database
swap must wait for the *whole* append/query/download, including nested calls.
All collaborators keep this lock when their connection is rebound.
"""

from __future__ import annotations

import asyncio
from functools import wraps


class ArchiveLock:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._owner = None
        self._depth = 0

    async def __aenter__(self):
        task = asyncio.current_task()
        if task is not self._owner:
            await self._lock.acquire()
            self._owner = task
        self._depth += 1
        return self

    async def __aexit__(self, *_exc):
        if asyncio.current_task() is not self._owner:
            raise RuntimeError("archive operation released by another task")
        self._depth -= 1
        if not self._depth:
            self._owner = None
            self._lock.release()


def db_operation(method):
    """Serialize an entire repository/query/media/service operation."""
    @wraps(method)
    async def guarded(self, *args, **kwargs):
        db = self.db if hasattr(self, "db") else self.repo.db
        async with db.operation_lock:
            # A queued operation may acquire the stable lock only AFTER a
            # swap. Roll back the connection it actually uses, not the old
            # closed handle captured before waiting.
            db = self.db if hasattr(self, "db") else self.repo.db
            try:
                return await method(self, *args, **kwargs)
            except BaseException:
                if db.is_open:
                    await db.conn.rollback()
                raise
    return guarded
