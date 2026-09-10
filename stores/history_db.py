"""The archive database: connection, schema and small query helpers.

`history.db` is deliberately a SEPARATE file from config.json and from the
People list. Nothing that filters, purges or forgets a person in the People
table may touch this store — it is the all-time archive.

The store is opened with aiosqlite so that collecting never blocks the Qt
event loop (and therefore never freezes the UI).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Iterable, Optional

import aiosqlite

# The schema lives in `stores/history_schema.py` now (the B2 split, design
# §2.4); these names are re-exported because `backend/history_db.py`, the
# bridges and the tests have always read them off this module.
from stores.history_schema import (                                   # noqa: F401
    FTS_SCHEMA,                                                       # noqa: F401
    INDEX_SQL,                                                        # noqa: F401
    LEGACY_MESSAGES_CONSTRAINT,                                       # noqa: F401
    SCHEMA,                                                           # noqa: F401
    SCHEMA_VERSION,                                                   # noqa: F401
    TABLE_COLUMNS,                                                    # noqa: F401
    TABLE_CONSTRAINTS,                                                # noqa: F401
    TABLE_ORDER,                                                      # noqa: F401
    TABLE_SQL,                                                        # noqa: F401
    _create_table_sql,                                                # noqa: F401
    _version_tuple,                                                   # noqa: F401
)

log = logging.getLogger("chatbot")

class HistoryDB:
    """Thin async wrapper around the archive's SQLite file."""

    def __init__(self, path: str, use_fts: bool = True):
        from stores.history_schema_repair import \
            SchemaMigrator                # local: it imports this package's
        # schema module, and `stores.history_db` is what that module's callers
        # reach for — importing it at module scope would close a cycle
        self.path = path
        self._want_fts = use_fts
        self.fts_enabled = False
        self._conn: Optional[aiosqlite.Connection] = None
        self.migrator = SchemaMigrator(self)

    # ── lifecycle ────────────────────────────────────────────────
    @property
    def is_open(self) -> bool:
        return self._conn is not None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("history database is not open")
        return self._conn

    async def init(self) -> "HistoryDB":
        if self._conn is not None:
            # Re-init reconnects cleanly instead of leaking the old handle
            # (and close() commits first, so pending writes survive).
            await self.close()
        folder = os.path.dirname(os.path.abspath(self.path))
        if folder:
            os.makedirs(folder, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        stored_version = None
        try:
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA synchronous=NORMAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")
            # Validate/repair BEFORE the script below: a legacy `messages`
            # table (no person_id) would make the index statements inside
            # `SCHEMA` fail and abort the whole open (Bug 1, 2026-09-08).
            await self._repair_tables()
            await self._conn.executescript(SCHEMA)
            stored_version = await self._read_version()
            # Created only AFTER the late columns exist: an old file reaches
            # this point without `messages.deleted_at`, and an index in
            # SCHEMA would make opening it fail outright.
            await self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_alive "
                "ON messages(person_id, deleted_at)")
            await self._migrate_dup_keys()
        except Exception as exc:                     # noqa: BLE001
            # A file the repair could not fix fails ONE open with a clear
            # message — never a different "no such column: …" on every
            # later query (Bug 1, 2026-09-08). Non-schema failures keep
            # their original error. Either way the broken handle is closed
            # so the instance is not left half-open (HDB-09).
            try:
                await self._verify_schema()
            except Exception as schema_error:        # noqa: BLE001
                await self.close()
                raise RuntimeError(str(schema_error)) from exc
            await self.close()
            raise
        if self._want_fts:
            self.fts_enabled = await self._try_fts()
        if stored_version and _version_tuple(stored_version) > \
                _version_tuple(SCHEMA_VERSION):
            log.warning(
                "%s was written by a newer app version (schema %s > %s) — "
                "continuing, but consider updating the app",
                os.path.basename(self.path), stored_version, SCHEMA_VERSION)
        await self.set_meta("schema_version", SCHEMA_VERSION)
        await self.set_meta("fts", "1" if self.fts_enabled else "0")
        await self._conn.commit()
        await self._verify_schema()
        return self

    # ── schema validation + repair (Bug 1 & 5, 2026-09-08) ──────
    async def _table_columns(self, table: str) -> Optional[list[str]]:
        """See `SchemaMigrator._table_columns` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return await self.migrator._table_columns(table)

    async def _repair_tables(self) -> None:
        """See `SchemaMigrator._repair_tables` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        await self.migrator._repair_tables()

    async def _rebuild_legacy_messages(self, columns: list[str]) -> None:
        """See `SchemaMigrator._rebuild_legacy_messages` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        await self.migrator._rebuild_legacy_messages(columns)

    async def _has_legacy_messages_constraint(self) -> bool:
        """See `SchemaMigrator._has_legacy_messages_constraint` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return await self.migrator._has_legacy_messages_constraint()

    async def _rebuild_messages_constraint(self) -> None:
        """See `SchemaMigrator._rebuild_messages_constraint` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        await self.migrator._rebuild_messages_constraint()

    async def _person_for_nick(self, nick: str) -> int:
        """See `SchemaMigrator._person_for_nick` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return await self.migrator._person_for_nick(nick)

    async def _count_rows(self, table: str) -> int:
        """See `SchemaMigrator._count_rows` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return await self.migrator._count_rows(table)

    async def db_fetch_legacy(self, table: str, columns: list[str]) -> list[dict]:
        """See `SchemaMigrator.db_fetch_legacy` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return await self.migrator.db_fetch_legacy(table, columns)

    async def _read_version(self) -> Optional[str]:
        """See `SchemaMigrator._read_version` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return await self.migrator._read_version()

    async def _verify_schema(self) -> None:
        """See `SchemaMigrator._verify_schema` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        await self.migrator._verify_schema()

    async def _add_missing_columns(self) -> None:
        """See `SchemaMigrator._add_missing_columns` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        await self.migrator._add_missing_columns()

    async def _migrate_dup_keys(self) -> None:
        """See `SchemaMigrator._migrate_dup_keys` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        await self.migrator._migrate_dup_keys()

    async def _try_fts(self) -> bool:
        """See `SchemaMigrator._try_fts` — the name stays on the
        facade so every caller and test keeps working (B2 split)."""
        return await self.migrator._try_fts()

    @staticmethod
    def normalise_nick(nick: str) -> str:
        return " ".join(str(nick or "").split()).strip()

    #: columns added after the first release — old files are upgraded in
    #: place. Kept as an alias of the canonical map: every missing column is
    #: now found by comparing against TABLE_COLUMNS (Bug 5, 2026-09-08).
    @property
    def LATE_COLUMNS(self) -> dict:
        return {name: list(cols) for name, cols in TABLE_COLUMNS.items()}

    async def close(self) -> None:
        # Swap the connection out FIRST so a concurrent close() (two
        # racing world switches) sees None and returns instead of
        # committing/closing an already-closed aiosqlite connection —
        # which used to hang the second caller forever.
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                await conn.commit()
            except Exception:                       # noqa: BLE001
                pass
            await conn.close()

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
