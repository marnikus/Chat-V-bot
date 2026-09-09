"""HistoryDB mixin1 base (<150)."""
import asyncio, json, logging, re
from typing import Iterable, Optional, Any
import aiosqlite

class HistoryDBMixin1:
    def __init__(self, path: str, use_fts: bool = True):
        self.path = path
        self._want_fts = use_fts
        self.fts_enabled = False
        self._conn: Optional[aiosqlite.Connection] = None

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
        folder = os.path.dirname(os.path.abspath(self.path))
        if folder:
            os.makedirs(folder, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        stored_version = None
        try:
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
            # their original error.
            try:
                await self._verify_schema()
            except Exception as schema_error:        # noqa: BLE001
                raise RuntimeError(str(schema_error)) from exc
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
        """Live column names of `table`, or None when it does not exist."""
        cur = await self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,))
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return None
        cur = await self._conn.execute(f"PRAGMA table_info({table})")
        names = [row[1] for row in await cur.fetchall()]
        await cur.close()
        return names

    async def _repair_tables(self) -> None:
        """Bring every table to the canonical shape before anything reads it.

        Missing tables are created; existing ones are compared column by
        column and widened in place. A `messages` table from before the
        persons model (no `person_id`) is rebuilt with its rows attributed
        to persons — the open must never fail with "no such column:
        person_id" and never leave the file broken for the next connect.
        """
        repaired = False
        for name in TABLE_ORDER:
            columns = await self._table_columns(name)
            if columns is None:
                await self._conn.execute(TABLE_SQL[name])
                continue
            if name == "messages" and "person_id" not in columns:
                await self._rebuild_legacy_messages(columns)
                repaired = True
                continue
            if name == "messages" and \
                    await self._has_legacy_messages_constraint():
                await self._rebuild_messages_constraint()
                repaired = True
                continue
            have = set(columns)
            missing = [(col, decl) for col, decl in TABLE_COLUMNS[name]
                       if col not in have]
            for col, decl in missing:
                try:
                    await self._conn.execute(
                        f"ALTER TABLE {name} ADD COLUMN {col} {decl}")
                    log.info("%s: added missing column %s.%s",
                             os.path.basename(self.path), name, col)
                    repaired = True
                except Exception as e:              # noqa: BLE001
                    log.warning("cannot add %s.%s: %s", name, col, e)
        if repaired:
            await self._conn.commit()
            log.info("%s: schema repaired (v%s)",
                     os.path.basename(self.path), SCHEMA_VERSION)

