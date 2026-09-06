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

log = logging.getLogger("chatbot")

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS persons (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nick          TEXT NOT NULL UNIQUE,
    nick_lc       TEXT NOT NULL,
    first_seen    TEXT,
    last_seen     TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    in_count      INTEGER NOT NULL DEFAULT 0,
    out_count     INTEGER NOT NULL DEFAULT 0,
    media_count   INTEGER NOT NULL DEFAULT 0,
    last_ord      INTEGER NOT NULL DEFAULT 0,
    my_nicks      TEXT NOT NULL DEFAULT '[]',
    note          TEXT NOT NULL DEFAULT '',
    created_at    TEXT,
    deleted_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_persons_lc ON persons(nick_lc);

CREATE TABLE IF NOT EXISTS media (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL DEFAULT 'image',
    state       TEXT NOT NULL DEFAULT 'pending',
    sha256      TEXT,
    bytes       INTEGER NOT NULL DEFAULT 0,
    cache_path  TEXT NOT NULL DEFAULT '',
    ref_count   INTEGER NOT NULL DEFAULT 0,
    fail_reason TEXT NOT NULL DEFAULT '',
    created_at  TEXT,
    last_used   TEXT
);
-- NOT unique: two urls may legitimately carry identical bytes; they share
-- one file on disk but keep one row each.
CREATE INDEX IF NOT EXISTS idx_media_sha ON media(sha256);
CREATE INDEX IF NOT EXISTS idx_media_state ON media(state);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id   INTEGER NOT NULL,
    ord         INTEGER NOT NULL,
    fp          TEXT NOT NULL,
    direction   TEXT NOT NULL,
    from_nick   TEXT NOT NULL DEFAULT '',
    my_nick     TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT 'text',
    text        TEXT NOT NULL DEFAULT '',
    text_lc     TEXT NOT NULL DEFAULT '',
    media_id    INTEGER,
    ts_display  TEXT NOT NULL DEFAULT '',
    ts_resolved TEXT NOT NULL DEFAULT '',
    day         TEXT NOT NULL DEFAULT '',
    ts_exact    INTEGER NOT NULL DEFAULT 0,
    occ         INTEGER NOT NULL DEFAULT 0,
    dom_idx     INTEGER NOT NULL DEFAULT 0,
    session_id  TEXT NOT NULL DEFAULT '',
    created_at  TEXT,
    UNIQUE(person_id, fp, day)
);
CREATE INDEX IF NOT EXISTS idx_messages_person_ord ON messages(person_id, ord);
CREATE INDEX IF NOT EXISTS idx_messages_lc ON messages(person_id, text_lc);

CREATE TABLE IF NOT EXISTS cursors (
    person_id    INTEGER PRIMARY KEY,
    last_ord     INTEGER NOT NULL DEFAULT 0,
    dom_count    INTEGER NOT NULL DEFAULT 0,
    head_sig     TEXT NOT NULL DEFAULT '',
    tail_sig     TEXT NOT NULL DEFAULT '',
    tail_fps     TEXT NOT NULL DEFAULT '[]',
    bootstrapped INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS gaps (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id  INTEGER NOT NULL,
    after_ord  INTEGER NOT NULL DEFAULT 0,
    reason     TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT '',
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_gaps_person ON gaps(person_id);
"""

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


class HistoryDB:
    """Thin async wrapper around the archive's SQLite file."""

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
        await self._conn.executescript(SCHEMA)
        if self._want_fts:
            self.fts_enabled = await self._try_fts()
        await self.set_meta("schema_version", SCHEMA_VERSION)
        await self.set_meta("fts", "1" if self.fts_enabled else "0")
        await self._conn.commit()
        return self

    async def _try_fts(self) -> bool:
        try:
            await self.conn.executescript(FTS_SCHEMA)
            await self.conn.commit()
            return True
        except Exception as e:                      # noqa: BLE001
            log.warning("FTS5 unavailable, falling back to LIKE search: %s", e)
            return False

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
        cur = await self.conn.execute(sql, tuple(params))
        try:
            return list(await cur.fetchall())
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
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0
