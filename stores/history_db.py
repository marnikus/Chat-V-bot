"""The archive database: facade (AREA B).

`history.db` is deliberately a SEPARATE file from config.json and from the
People list. Nothing that filters, purges or forgets a person in the People
table may touch this store — it is the all-time archive.

The store is opened with aiosqlite so that collecting never blocks the Qt
event loop (and therefore never freezes the UI).

Schema migration lives in ``_history_db_schema.SchemaMigrator`` (AREA B split).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Iterable, Optional

import aiosqlite

log = logging.getLogger("chatbot")

SCHEMA_VERSION = "6"

TABLE_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "schema_meta": (
        ("key", "TEXT PRIMARY KEY"),
        ("value", "TEXT"),
    ),
    "persons": (
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("nick", "TEXT NOT NULL UNIQUE"),
        ("nick_lc", "TEXT NOT NULL"),
        ("first_seen", "TEXT"),
        ("last_seen", "TEXT"),
        ("message_count", "INTEGER NOT NULL DEFAULT 0"),
        ("in_count", "INTEGER NOT NULL DEFAULT 0"),
        ("out_count", "INTEGER NOT NULL DEFAULT 0"),
        ("media_count", "INTEGER NOT NULL DEFAULT 0"),
        ("last_ord", "INTEGER NOT NULL DEFAULT 0"),
        ("my_nicks", "TEXT NOT NULL DEFAULT '[]'"),
        ("note", "TEXT NOT NULL DEFAULT ''"),
        ("created_at", "TEXT"),
        ("deleted_at", "TEXT"),
    ),
    "media": (
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("url", "TEXT NOT NULL UNIQUE"),
        ("kind", "TEXT NOT NULL DEFAULT 'image'"),
        ("state", "TEXT NOT NULL DEFAULT 'pending'"),
        ("sha256", "TEXT"),
        ("bytes", "INTEGER NOT NULL DEFAULT 0"),
        ("cache_path", "TEXT NOT NULL DEFAULT ''"),
        ("owner", "TEXT NOT NULL DEFAULT ''"),
        ("day", "TEXT NOT NULL DEFAULT ''"),
        ("ref_count", "INTEGER NOT NULL DEFAULT 0"),
        ("fail_reason", "TEXT NOT NULL DEFAULT ''"),
        ("created_at", "TEXT"),
        ("last_used", "TEXT"),
        ("recovered_at", "TEXT NOT NULL DEFAULT ''"),
        ("recovery_attempts", "INTEGER NOT NULL DEFAULT 0"),
    ),
    "messages": (
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("person_id", "INTEGER NOT NULL DEFAULT 0"),
        ("ord", "INTEGER NOT NULL DEFAULT 0"),
        ("fp", "TEXT NOT NULL DEFAULT ''"),
        ("direction", "TEXT NOT NULL DEFAULT 'in'"),
        ("from_nick", "TEXT NOT NULL DEFAULT ''"),
        ("my_nick", "TEXT NOT NULL DEFAULT ''"),
        ("kind", "TEXT NOT NULL DEFAULT 'text'"),
        ("text", "TEXT NOT NULL DEFAULT ''"),
        ("text_lc", "TEXT NOT NULL DEFAULT ''"),
        ("media_id", "INTEGER"),
        ("ts_display", "TEXT NOT NULL DEFAULT ''"),
        ("ts_resolved", "TEXT NOT NULL DEFAULT ''"),
        ("day", "TEXT NOT NULL DEFAULT ''"),
        ("ts_exact", "INTEGER NOT NULL DEFAULT 0"),
        ("deleted_at", "TEXT NOT NULL DEFAULT ''"),
        ("occ", "INTEGER NOT NULL DEFAULT 0"),
        ("dom_idx", "INTEGER NOT NULL DEFAULT 0"),
        ("session_id", "TEXT NOT NULL DEFAULT ''"),
        ("created_at", "TEXT"),
        ("dup_key", "TEXT NOT NULL DEFAULT ''"),
        ("media_scan_at", "TEXT NOT NULL DEFAULT ''"),
        ("media_recovered_at", "TEXT NOT NULL DEFAULT ''"),
    ),
    "cursors": (
        ("person_id", "INTEGER PRIMARY KEY"),
        ("last_ord", "INTEGER NOT NULL DEFAULT 0"),
        ("dom_count", "INTEGER NOT NULL DEFAULT 0"),
        ("head_sig", "TEXT NOT NULL DEFAULT ''"),
        ("tail_sig", "TEXT NOT NULL DEFAULT ''"),
        ("head_any", "TEXT NOT NULL DEFAULT ''"),
        ("tail_any", "TEXT NOT NULL DEFAULT ''"),
        ("tail_fps", "TEXT NOT NULL DEFAULT '[]'"),
        ("tail_keys", "TEXT NOT NULL DEFAULT '[]'"),
        ("bootstrapped", "INTEGER NOT NULL DEFAULT 0"),
        ("full_scan_complete", "INTEGER NOT NULL DEFAULT 0"),
        ("full_scan_at", "TEXT NOT NULL DEFAULT ''"),
        ("updated_at", "TEXT"),
    ),
    "gaps": (
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("person_id", "INTEGER NOT NULL DEFAULT 0"),
        ("after_ord", "INTEGER NOT NULL DEFAULT 0"),
        ("reason", "TEXT NOT NULL DEFAULT ''"),
        ("detail", "TEXT NOT NULL DEFAULT ''"),
        ("created_at", "TEXT"),
    ),
    "users": (
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("nick", "TEXT UNIQUE NOT NULL"),
        ("gender", "TEXT DEFAULT 'unknown'"),
        ("registered", "BOOLEAN DEFAULT 0"),
        ("anonymous", "BOOLEAN DEFAULT 0"),
        ("guest", "BOOLEAN DEFAULT 0"),
        ("first_seen", "DATETIME"),
        ("last_seen", "DATETIME"),
        ("messaged", "BOOLEAN DEFAULT 0"),
        ("message_count", "INTEGER DEFAULT 0"),
        ("last_messaged", "DATETIME"),
        ("notes", "TEXT DEFAULT ''"),
    ),
    "labels": (
        ("id", "TEXT PRIMARY KEY"),
        ("name", "TEXT NOT NULL UNIQUE COLLATE NOCASE"),
        ("color", "TEXT NOT NULL DEFAULT '#ff3b30'"),
        ("created_at", "TEXT NOT NULL DEFAULT ''"),
    ),
    "label_assigns": (
        ("nick", "TEXT NOT NULL"),
        ("label_id", "TEXT NOT NULL"),
    ),
    "undo_history": (
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("seq", "INTEGER NOT NULL UNIQUE"),
        ("kind", "TEXT NOT NULL"),
        ("value", "TEXT NOT NULL"),
        ("created_at", "TEXT"),
    ),
    "gaze_data": (
        ("key", "TEXT PRIMARY KEY"),
        ("value", "TEXT NOT NULL"),
        ("updated_at", "TEXT"),
    ),
    "app_settings": (
        ("key", "TEXT PRIMARY KEY"),
        ("value", "TEXT NOT NULL"),
        ("updated_at", "TEXT"),
    ),
}

TABLE_CONSTRAINTS: dict[str, str] = {
    "label_assigns": "PRIMARY KEY (nick, label_id)",
}

LEGACY_MESSAGES_CONSTRAINT = "UNIQUE(person_id, fp, day)"

TABLE_ORDER = ("schema_meta", "persons", "media", "messages", "cursors", "gaps", "users", "labels", "label_assigns", "undo_history", "gaze_data", "app_settings")

def _create_table_sql(name: str) -> str:
    lines = [f"    {col} {decl}" for col, decl in TABLE_COLUMNS[name]]
    if name in TABLE_CONSTRAINTS:
        lines.append(f"    {TABLE_CONSTRAINTS[name]}")
    return f"CREATE TABLE IF NOT EXISTS {name} (\n" + ",\n".join(lines) + "\n);"

TABLE_SQL: dict[str, str] = {name: _create_table_sql(name) for name in TABLE_ORDER}

INDEX_SQL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_persons_lc ON persons(nick_lc)",
    "CREATE INDEX IF NOT EXISTS idx_media_sha ON media(sha256)",
    "CREATE INDEX IF NOT EXISTS idx_media_state ON media(state)",
    "CREATE INDEX IF NOT EXISTS idx_messages_person_ord ON messages(person_id, ord)",
    "CREATE INDEX IF NOT EXISTS idx_messages_lc ON messages(person_id, text_lc)",
    "CREATE INDEX IF NOT EXISTS idx_gaps_person ON gaps(person_id)",
    "CREATE INDEX IF NOT EXISTS idx_users_messaged ON users(messaged)",
    "CREATE INDEX IF NOT EXISTS idx_label_assigns_nick ON label_assigns(nick)",
    "CREATE INDEX IF NOT EXISTS idx_label_assigns_id ON label_assigns(label_id)",
)

SCHEMA = "\n\n".join([TABLE_SQL[name] for name in TABLE_ORDER] + [stmt + ";" for stmt in INDEX_SQL]) + "\n"

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text, content='messages', content_rowid='id', tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text)
        VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE OF text ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text)
        VALUES ('delete', old.id, old.text);
    INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
END;
"""

def _version_tuple(version: str) -> tuple:
    try:
        return tuple(int(part) for part in str(version).split("."))
    except (TypeError, ValueError):
        return (0,)

class HistoryDB:
    """Thin async wrapper around the archive's SQLite file."""

    def __init__(self, path: str, use_fts: bool = True):
        self.path = path
        self._want_fts = use_fts
        self.fts_enabled = False
        self._conn: Optional[aiosqlite.Connection] = None

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
            await self._repair_tables()
            await self._conn.executescript(SCHEMA)
            stored_version = await self._read_version()
            await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_alive ON messages(person_id, deleted_at)")
            await self._migrate_dup_keys()
        except Exception as exc:
            try:
                await self._verify_schema()
            except Exception as schema_error:
                await self.close()
                raise RuntimeError(str(schema_error)) from exc
            await self.close()
            raise
        if self._want_fts:
            self.fts_enabled = await self._try_fts()
        if stored_version and _version_tuple(stored_version) > _version_tuple(SCHEMA_VERSION):
            log.warning("%s was written by a newer app version (schema %s > %s) — continuing, but consider updating the app", os.path.basename(self.path), stored_version, SCHEMA_VERSION)
        await self.set_meta("schema_version", SCHEMA_VERSION)
        await self.set_meta("fts", "1" if self.fts_enabled else "0")
        await self._conn.commit()
        await self._verify_schema()
        return self

    async def _table_columns(self, table: str):
        from stores._history_db_schema import SchemaMigrator
        return await SchemaMigrator(self)._table_columns(table)

    async def _repair_tables(self) -> None:
        from stores._history_db_schema import SchemaMigrator
        await SchemaMigrator(self)._repair_tables()

    async def _rebuild_legacy_messages(self, columns: list[str]) -> None:
        from stores._history_db_schema import SchemaMigrator
        await SchemaMigrator(self)._rebuild_legacy_messages(columns)

    async def _has_legacy_messages_constraint(self) -> bool:
        from stores._history_db_schema import SchemaMigrator
        return await SchemaMigrator(self)._has_legacy_messages_constraint()

    async def _rebuild_messages_constraint(self) -> None:
        from stores._history_db_schema import SchemaMigrator
        await SchemaMigrator(self)._rebuild_messages_constraint()

    async def _person_for_nick(self, nick: str) -> int:
        from stores._history_db_schema import SchemaMigrator
        return await SchemaMigrator(self)._person_for_nick(nick)

    @staticmethod
    def normalise_nick(nick: str) -> str:
        return " ".join(str(nick or "").split()).strip()

    async def _count_rows(self, table: str) -> int:
        from stores._history_db_schema import SchemaMigrator
        return await SchemaMigrator(self)._count_rows(table)

    async def db_fetch_legacy(self, table: str, columns: list[str]) -> list[dict]:
        wanted = [col for col, _ in TABLE_COLUMNS["messages"] if col in set(columns)]
        wanted += [c for c in ("nick",) if c in set(columns) and c not in wanted]
        rows = await self.fetchdicts(f"SELECT {', '.join(wanted)} FROM {table}")
        return rows

    async def _read_version(self) -> Optional[str]:
        try:
            value = await self.get_meta("schema_version")
            return str(value) if value else None
        except Exception:
            return None

    async def _verify_schema(self) -> None:
        problems = []
        for name in TABLE_ORDER:
            columns = await self._table_columns(name)
            if columns is None:
                problems.append(f"{name}: table missing")
                continue
            have = set(columns)
            for col, _decl in TABLE_COLUMNS[name]:
                if col not in have:
                    problems.append(f"{name}.{col} missing")
        if problems:
            raise RuntimeError(f"database {os.path.basename(self.path)} has an incomplete schema: {', '.join(problems[:6])}")

    @property
    def LATE_COLUMNS(self) -> dict:
        return {name: list(cols) for name, cols in TABLE_COLUMNS.items()}

    async def _add_missing_columns(self) -> None:
        await self._repair_tables()

    async def _migrate_dup_keys(self) -> None:
        from stores._history_db_schema import SchemaMigrator
        await SchemaMigrator(self)._migrate_dup_keys()

    async def _try_fts(self) -> bool:
        try:
            await self.conn.executescript(FTS_SCHEMA)
            await self.conn.commit()
            return True
        except Exception as e:
            log.warning("FTS5 unavailable, falling back to LIKE search: %s", e)
            return False

    async def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                await conn.commit()
            except Exception:
                pass
            await conn.close()

    async def execute(self, sql: str, params: Iterable[Any] = ()):
        return await self.conn.execute(sql, tuple(params))

    async def executemany(self, sql: str, seq):
        return await self.conn.executemany(sql, seq)

    async def commit(self) -> None:
        await self.conn.commit()

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list:
        cur = await self.conn.execute(sql, tuple(params))
        try:
            return [tuple(row) for row in await cur.fetchall()]
        finally:
            await cur.close()

    async def fetchdicts(self, sql: str, params: Iterable[Any] = ()) -> list:
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

    async def get_meta(self, key: str, default: str | None = None):
        row = await self.fetchone("SELECT value FROM schema_meta WHERE key=?", (key,))
        return row[0] if row else default

    async def set_meta(self, key: str, value: str) -> None:
        await self.execute("INSERT INTO schema_meta(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def file_size(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += os.path.getsize(self.path + suffix)
            except OSError:
                continue
        return total
