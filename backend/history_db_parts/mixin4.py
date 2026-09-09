"""HistoryDB mixin4 io (<150)."""
import asyncio, json, logging, re
from typing import Iterable, Optional, Any

class HistoryDBMixin4:
    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.commit()
            except Exception:                       # noqa: BLE001
                pass
            await self._conn.close()
            self._conn = None

    # ── helpers ──────────────────────────────────────────────────
    async def execute(self, sql: str, params: Iterable[Any] = ()):
        return await self.conn.execute(sql, tuple(params))

    async def executemany(self, sql: str, seq):
        return await self.conn.executemany(sql, seq)

    async def commit(self) -> None:
        await self.conn.commit()

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list:
        """Rows as plain tuples — the shape callers (and tests) compare."""
        cur = await self.conn.execute(sql, tuple(params))
        try:
            return [tuple(row) for row in await cur.fetchall()]
        finally:
            await cur.close()

    async def fetchdicts(self, sql: str, params: Iterable[Any] = ()) -> list:
        """Rows as dictionaries, for code that reads columns by name."""
        cur = await self.conn.execute(sql, tuple(params))
        try:
            return [dict(row) for row in await cur.fetchall()]
        finally:
            await cur.close()

    async def fetchone(self, sql: str, params: Iterable[Any] = ()):
        cur = await self.conn.execute(sql, tuple(params))
        try:
            return await cur.fetchone()
        finally:
            await cur.close()

    async def scalar(self, sql: str, params: Iterable[Any] = (), default=0):
        row = await self.fetchone(sql, params)
        if row is None or row[0] is None:
            return default
        return row[0]

    # ── metadata ─────────────────────────────────────────────────
    async def get_meta(self, key: str, default: str | None = None):
        row = await self.fetchone("SELECT value FROM schema_meta WHERE key=?",
                                  (key,))
        return row[0] if row else default

    async def set_meta(self, key: str, value: str) -> None:
        await self.execute(
            "INSERT INTO schema_meta(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)))

    def file_size(self) -> int:
        """Bytes on disk for this database — the file AND its WAL siblings.

        With `journal_mode=WAL` a freshly written database keeps a large part
        of its content in `-wal` until a checkpoint, so reporting only the
        main file would show a size that shrinks for no visible reason.
        """
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += os.path.getsize(self.path + suffix)
            except OSError:
                continue
        return total
