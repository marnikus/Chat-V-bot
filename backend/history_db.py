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
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

import aiosqlite

from backend.archive_lock import ArchiveLock

log = logging.getLogger("chatbot")

SCHEMA_VERSION = "5"
APPLICATION_ID = 0x43564248  # CVBH: Chat-V-bot history, never the People/undo store
INCOMPATIBLE_SCHEMA = "Database schema is incompatible. Cannot load."


class SchemaError(ValueError):
    """A target cannot safely be used as a chat archive."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(INCOMPATIBLE_SCHEMA)

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

CREATE TABLE IF NOT EXISTS media (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL DEFAULT 'image',
    state       TEXT NOT NULL DEFAULT 'pending',
    sha256      TEXT,
    bytes       INTEGER NOT NULL DEFAULT 0,
    cache_path  TEXT NOT NULL DEFAULT '',
    owner       TEXT NOT NULL DEFAULT '',   -- whose conversation it belongs to
    day         TEXT NOT NULL DEFAULT '',   -- YYYY-MM-DD used in the filename
    ref_count   INTEGER NOT NULL DEFAULT 0,
    fail_reason TEXT NOT NULL DEFAULT '',
    created_at  TEXT,
    last_used   TEXT,
    recovered_at   TEXT NOT NULL DEFAULT '',
    recovery_attempts INTEGER NOT NULL DEFAULT 0
);
-- NOT unique: two urls may legitimately carry identical bytes; they share
-- one file on disk but keep one row each.

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id   INTEGER NOT NULL REFERENCES persons(id),
    ord         INTEGER NOT NULL,
    fp          TEXT NOT NULL,
    direction   TEXT NOT NULL,
    from_nick   TEXT NOT NULL DEFAULT '',
    my_nick     TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT 'text',
    text        TEXT NOT NULL DEFAULT '',
    text_lc     TEXT NOT NULL DEFAULT '',
    media_id    INTEGER REFERENCES media(id),
    ts_display  TEXT NOT NULL DEFAULT '',
    ts_resolved TEXT NOT NULL DEFAULT '',
    day         TEXT NOT NULL DEFAULT '',
    ts_exact    INTEGER NOT NULL DEFAULT 0,
    deleted_at  TEXT NOT NULL DEFAULT '',
    occ         INTEGER NOT NULL DEFAULT 0,
    dom_idx     INTEGER NOT NULL DEFAULT 0,
    session_id  TEXT NOT NULL DEFAULT '',
    created_at  TEXT,
    dup_key     TEXT NOT NULL DEFAULT '',
    media_scan_at      TEXT NOT NULL DEFAULT '',
    media_recovered_at TEXT NOT NULL DEFAULT '',
    text_scan_at      TEXT NOT NULL DEFAULT '',
    text_recovered_at TEXT NOT NULL DEFAULT '',
    UNIQUE(person_id, fp, day)
);

CREATE TABLE IF NOT EXISTS cursors (
    person_id    INTEGER PRIMARY KEY REFERENCES persons(id),
    last_ord     INTEGER NOT NULL DEFAULT 0,
    dom_count    INTEGER NOT NULL DEFAULT 0,
    head_sig     TEXT NOT NULL DEFAULT '',
    tail_sig     TEXT NOT NULL DEFAULT '',
    tail_fps     TEXT NOT NULL DEFAULT '[]',
    tail_keys    TEXT NOT NULL DEFAULT '[]',
    bootstrapped INTEGER NOT NULL DEFAULT 0,
    full_scan_complete INTEGER NOT NULL DEFAULT 0,
    full_scan_at TEXT NOT NULL DEFAULT '',
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS gaps (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id  INTEGER NOT NULL REFERENCES persons(id),
    after_ord  INTEGER NOT NULL DEFAULT 0,
    reason     TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT '',
    created_at TEXT
);
"""

INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_persons_lc ON persons(nick_lc);
CREATE INDEX IF NOT EXISTS idx_media_sha ON media(sha256);
CREATE INDEX IF NOT EXISTS idx_media_state ON media(state);
CREATE INDEX IF NOT EXISTS idx_messages_person_ord ON messages(person_id, ord);
CREATE INDEX IF NOT EXISTS idx_messages_lc ON messages(person_id, text_lc);
CREATE INDEX IF NOT EXISTS idx_gaps_person ON gaps(person_id);
CREATE INDEX IF NOT EXISTS idx_messages_alive ON messages(person_id, deleted_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_dup_key
    ON messages(person_id, dup_key) WHERE dup_key <> '';
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
        self.path = str(path)
        self.operation_lock = ArchiveLock()
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

    async def init(self, *, allow_create: bool = True) -> "HistoryDB":
        """Open only a recognized archive; migrate and validate before use.

        Unknown/core-column-deficient schemas are rejected BEFORE any DDL.
        A failed migration rolls back and always closes its worker connection.
        `allow_create=False` also prevents SQLite from creating a missing file.
        """
        if self.is_open:
            return self
        if allow_create:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        uri = Path(os.path.abspath(self.path)).as_uri()
        self._conn = await aiosqlite.connect(
            uri + ("?mode=rwc" if allow_create else "?mode=rw"), uri=True)
        self._conn.row_factory = aiosqlite.Row
        try:
            shape = await self._shape()
            empty = not shape["tables"]
            if empty and not allow_create:
                raise SchemaError("the file has no archive schema")
            if not empty:
                _check_shape(shape, allow_legacy=True)
            await self.conn.execute("PRAGMA journal_mode=WAL")
            await self.conn.execute("PRAGMA synchronous=NORMAL")
            await self.conn.execute("PRAGMA foreign_keys=ON")
            await self.conn.execute("BEGIN IMMEDIATE")
            await self._script(SCHEMA)
            await self._add_missing_columns()
            await self._migrate_dup_keys()
            await self._script(INDEX_SCHEMA)
            if self._want_fts:
                self.fts_enabled = await self._try_fts()
            elif "messages_fts" in shape["tables"]:
                # Existing triggers must stay functional even with search off.
                await self._script(FTS_SCHEMA)
            legacy_refs = (shape["meta"].get("legacy_references") == "1" or
                           (not empty and any(not shape["foreign_keys"][table]
                                              for table, _column, _parent in REFERENCES)))
            await self.set_meta("legacy_references", "1" if legacy_refs else "0")
            await self.set_meta("schema_version", SCHEMA_VERSION)
            await self.set_meta("storage_kind", "chat_archive")
            await self.set_meta("fts", "1" if self.fts_enabled else "0")
            await self.conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
            await self.validate()
            await self.conn.commit()
        except BaseException:
            try:
                await self.conn.rollback()
            finally:
                await self.conn.close()
                self._conn = None
                self.fts_enabled = False
            raise
        return self

    async def _script(self, script: str) -> None:
        # executescript() commits implicitly, making a failed migration partial.
        for statement in _statements(script):
            await self.conn.execute(statement)

    async def _shape(self) -> dict:
        rows = await self.fetchall("SELECT type, name, sql FROM sqlite_master")
        shape = _empty_shape(rows)
        for table in ARCHIVE_TABLES:
            shape["columns"][table] = await self.fetchall(f"PRAGMA table_info({table})")
            indexes = await self.fetchall(f"PRAGMA index_list({table})")
            shape["indexes"][table] = []
            for index in indexes:
                name = index[1].replace('"', '""')
                columns = await self.fetchall(f'PRAGMA index_info("{name}")')
                shape["indexes"][table].append((index[1], bool(index[2]),
                                               tuple(c[2] for c in columns)))
            shape["foreign_keys"][table] = await self.fetchall(
                f"PRAGMA foreign_key_list({table})")
        shape["application_id"] = await self.scalar("PRAGMA application_id")
        if {"key", "value"} <= {c[1] for c in shape["columns"]["schema_meta"]}:
            shape["meta"] = dict(await self.fetchall("SELECT key, value FROM schema_meta"))
        return shape

    async def validate(self) -> None:
        """Verify the complete runtime contract, indexes and stored references."""
        shape = await self._shape()
        _check_shape(shape, allow_legacy=False)
        rows = await self.fetchall("PRAGMA quick_check")
        if rows != [("ok",)]:
            raise SchemaError(f"SQLite integrity check failed: {rows[:3]}")
        if await self.fetchall("PRAGMA foreign_key_check"):
            raise SchemaError("foreign key violations")
        # Pre-FK archives are not destructively rebuilt. Check their references
        # explicitly as well, so an orphan is never marked ready to load.
        for table, column, parent in REFERENCES:
            orphan = await self.scalar(
                f"SELECT 1 FROM {table} c LEFT JOIN {parent} p ON p.id=c.{column} "
                f"WHERE c.{column} IS NOT NULL AND p.id IS NULL LIMIT 1", (), 0)
            if orphan:
                raise SchemaError(f"orphan reference: {table}.{column}")
        if "messages_fts" in shape["tables"]:
            for trigger in ("messages_ai", "messages_ad", "messages_au"):
                if _normal_sql(shape["sql"].get(trigger, "")) != \
                        _normal_sql(_contract()["sql"][trigger]):
                    raise SchemaError(f"missing or incompatible FTS trigger: {trigger}")

    async def backup_to(self, path: str) -> None:
        """Consistent SQLite snapshot, including committed WAL contents."""
        destination = await aiosqlite.connect(path)
        try:
            await self.conn.backup(destination)
        finally:
            await destination.close()

    #: columns added after the first release — old files are upgraded in place
    LATE_COLUMNS = {
        "media": [("owner", "TEXT NOT NULL DEFAULT ''"),
                  ("day", "TEXT NOT NULL DEFAULT ''"),
                  ("recovered_at", "TEXT NOT NULL DEFAULT ''"),
                  ("recovery_attempts", "INTEGER NOT NULL DEFAULT 0")],
        "messages": [("dup_key", "TEXT NOT NULL DEFAULT ''"),
                     ("text_scan_at", "TEXT NOT NULL DEFAULT ''"),
                     ("text_recovered_at", "TEXT NOT NULL DEFAULT ''"),
                     ("media_scan_at", "TEXT NOT NULL DEFAULT ''"),
                     ("media_recovered_at", "TEXT NOT NULL DEFAULT ''"),
                     # Explicit user deletions hide a row instead of erasing
                     # it, so one Ctrl+Z can put it back (RULE 14 stays true:
                     # only an explicit purge ever removes bytes).
                     ("deleted_at", "TEXT NOT NULL DEFAULT ''")],
        "cursors": [("tail_keys", "TEXT NOT NULL DEFAULT '[]'"),
                    ("full_scan_complete", "INTEGER NOT NULL DEFAULT 0"),
                    ("full_scan_at", "TEXT NOT NULL DEFAULT ''")],
    }

    async def _add_missing_columns(self) -> None:
        for table, columns in self.LATE_COLUMNS.items():
            cur = await self._conn.execute(f"PRAGMA table_info({table})")
            have = {row[1] for row in await cur.fetchall()}
            await cur.close()
            for name, decl in columns:
                if name in have:
                    continue
                await self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    async def _migrate_dup_keys(self) -> None:
        """Compute `dup_key`, drop pre-existing duplicates and add its index.

        Old databases stored identity as `fingerprint(.., occ) + day`. That is
        why the same physical line was re-inserted when occurrences shifted or
        the day resolution changed. The new key is timestamp + content for the
        person; here we back-fill it for existing rows and keep the earliest
        row for each key, then resequence as a consequence.
        """
        from backend.history_models import dedupe_key  # local: avoid cycles
        rows = await self.fetchall(
            "SELECT m.id, m.person_id, m.direction, m.from_nick, m.kind, "
            "m.text, m.ts_display, COALESCE(md.url, '') AS media_url "
            "FROM messages m LEFT JOIN media md ON md.id = m.media_id "
            "WHERE m.dup_key=''")
        for row in rows:
            payload = row[7] or row[5]
            key = dedupe_key(row[2], row[3], row[6], row[4], payload)
            await self.execute("UPDATE messages SET dup_key=? WHERE id=?",
                               (key, row[0]))

        # keep the earliest id for each (person, dup_key)
        before = int(await self.scalar(
            "SELECT COUNT(*) FROM messages WHERE dup_key<>''", (), 0))
        await self.execute(
            "DELETE FROM messages WHERE dup_key<>'' AND id NOT IN ("
            "SELECT MIN(id) FROM messages WHERE dup_key<>'' "
            "GROUP BY person_id, dup_key)")
        deleted = before - int(await self.scalar(
            "SELECT COUNT(*) FROM messages WHERE dup_key<>''", (), 0))

        # resequence ord only when duplicate removal left holes
        if deleted:
            res = await self.fetchall(
                "SELECT person_id, id FROM messages "
                "ORDER BY person_id, day, ts_display, ord, id")
            current = None
            position = 0
            for person_id, mid in res:
                if current != person_id:
                    current = person_id
                    position = 0
                position += 1
                await self.execute("UPDATE messages SET ord=? WHERE id=?",
                                   (position, mid))

        # the index must exist even before the first insert (fresh DBs)
        await self.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_dup_key "
            "ON messages(person_id, dup_key) WHERE dup_key <> ''")

    async def _try_fts(self) -> bool:
        try:
            existed = bool(await self.scalar(
                "SELECT 1 FROM sqlite_master WHERE name='messages_fts'", (), 0))
            missing_triggers = await self.scalar(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' "
                "AND name IN ('messages_ai','messages_ad','messages_au')") != 3
            await self._script(FTS_SCHEMA)
            if not existed or missing_triggers:
                await self.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
            return True
        except aiosqlite.OperationalError as exc:
            if "no such module: fts5" not in str(exc).lower():
                raise
            log.warning("FTS5 unavailable, falling back to LIKE search: %s", exc)
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


ARCHIVE_TABLES = ("schema_meta", "persons", "media", "messages", "cursors", "gaps")
REFERENCES = (("messages", "person_id", "persons"),
              ("messages", "media_id", "media"),
              ("cursors", "person_id", "persons"),
              ("gaps", "person_id", "persons"))


def _statements(script):
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            yield statement
            statement = ""
    if statement.strip():
        raise ValueError("incomplete archive schema statement")


def _normal_sql(sql):
    return " ".join(str(sql or "").lower().replace("if not exists", "").split())


def _empty_shape(rows):
    rows = list(rows)
    return {"tables": {r[1] for r in rows if r[0] == "table"
                        and not r[1].startswith("sqlite_")},
            "sql": {r[1]: r[2] for r in rows},
            "columns": {}, "indexes": {}, "foreign_keys": {}, "meta": {},
            "application_id": 0}


def _read_shape(conn):
    shape = _empty_shape(conn.execute("SELECT type, name, sql FROM sqlite_master"))
    for table in ARCHIVE_TABLES:
        shape["columns"][table] = list(conn.execute(f"PRAGMA table_info({table})"))
        shape["indexes"][table] = []
        for index in conn.execute(f"PRAGMA index_list({table})"):
            name = index[1].replace('"', '""')
            columns = tuple(c[2] for c in conn.execute(f'PRAGMA index_info("{name}")'))
            shape["indexes"][table].append((index[1], bool(index[2]), columns))
        shape["foreign_keys"][table] = list(conn.execute(f"PRAGMA foreign_key_list({table})"))
    shape["application_id"] = conn.execute("PRAGMA application_id").fetchone()[0]
    if {"key", "value"} <= {c[1] for c in shape["columns"]["schema_meta"]}:
        shape["meta"] = dict(conn.execute("SELECT key, value FROM schema_meta"))
    return shape


@lru_cache(maxsize=1)
def _contract():
    # Derive the validation contract from the same SQL creation uses, so a new
    # column or index cannot be forgotten in a hand-maintained parallel list.
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(SCHEMA + INDEX_SCHEMA)
        try:
            conn.executescript(FTS_SCHEMA)
        except sqlite3.OperationalError as exc:
            if "no such module: fts5" not in str(exc).lower():
                raise
        shape = _read_shape(conn)
        # Trigger SQL is needed for validation even on a build lacking FTS5.
        for stmt in _statements(FTS_SCHEMA):
            if "CREATE TRIGGER" in stmt:
                name = stmt.split("EXISTS", 1)[1].strip().split()[0]
                shape["sql"].setdefault(name, stmt.strip().rstrip(";"))
        return shape
    finally:
        conn.close()


def _check_shape(shape, *, allow_legacy):
    tables = shape["tables"]
    if shape["application_id"] not in (0, APPLICATION_ID):
        raise SchemaError("another application's database")
    foreign = tables - set(ARCHIVE_TABLES) - {
        "messages_fts", "messages_fts_data", "messages_fts_idx",
        "messages_fts_docsize", "messages_fts_config", "messages_fts_content"}
    if foreign:
        raise SchemaError("non-archive tables: " + ", ".join(sorted(foreign)))
    missing = set(ARCHIVE_TABLES) - tables
    if missing:
        raise SchemaError("missing archive tables: " + ", ".join(sorted(missing)))
    meta = shape["meta"]
    if meta.get("storage_kind", "chat_archive") != "chat_archive":
        raise SchemaError("not a chat archive")
    version = meta.get("schema_version")
    if version is not None:
        try:
            supported = 1 <= int(version) <= int(SCHEMA_VERSION)
        except (TypeError, ValueError):
            supported = False
        if not supported:
            raise SchemaError(f"unsupported schema version: {version}")
    if not allow_legacy and (version != SCHEMA_VERSION or
                             meta.get("storage_kind") != "chat_archive"):
        raise SchemaError("schema migration not completed")

    expected = _contract()
    for table in ARCHIVE_TABLES:
        have = {r[1]: r for r in shape["columns"][table]}
        late = {c[0] for c in HistoryDB.LATE_COLUMNS.get(table, [])} if allow_legacy else set()
        for col in expected["columns"][table]:
            name = col[1]
            if name not in have:
                if name in late:
                    continue
                raise SchemaError(f"missing column: {table}.{name}")
            actual = have[name]
            if (actual[2].upper(), actual[3], actual[4], actual[5]) != \
                    (col[2].upper(), col[3], col[4], col[5]):
                raise SchemaError(f"incompatible column: {table}.{name}")
        indexes = {i[0]: i for i in shape["indexes"][table]}
        uniques = {i[2] for i in indexes.values() if i[1]}
        for name, unique, columns in expected["indexes"][table]:
            if name.startswith("sqlite_autoindex"):
                if columns not in uniques:
                    raise SchemaError(f"missing unique constraint: {table}{columns}")
            elif name in indexes:
                if (indexes[name][1:] != (unique, columns) or
                    _normal_sql(shape["sql"].get(name)) != _normal_sql(expected["sql"][name])):
                    raise SchemaError(f"incompatible index: {name}")
            elif not allow_legacy:
                raise SchemaError(f"missing index: {name}")
        refs = {(r[2], r[3], r[4]) for r in shape["foreign_keys"][table]}
        want_refs = {(r[2], r[3], r[4]) for r in expected["foreign_keys"][table]}
        legacy_refs = (shape["meta"].get("legacy_references") == "1" or
                       (allow_legacy and version != SCHEMA_VERSION))
        if refs != want_refs and (refs or not legacy_refs):
            raise SchemaError(f"incompatible foreign keys: {table}")
    if "messages_fts" in tables:
        if _normal_sql(shape["sql"].get("messages_fts")) != _normal_sql(expected["sql"].get("messages_fts")):
            raise SchemaError("incompatible FTS table")
        for name in ("messages_ai", "messages_ad", "messages_au"):
            if name in shape["sql"] and _normal_sql(shape["sql"][name]) != _normal_sql(expected["sql"][name]):
                raise SchemaError(f"incompatible FTS trigger: {name}")


def inspect_archive_details(path: str, *, full: bool = False) -> dict:
    """Describe loadability without confusing an invalid file with no file.

    No DDL, initialization or migration. SQLite may use WAL sidecars, but
    mode=ro never creates a missing main database. Load still validates again.
    """
    result = {"compatible": False, "status": "incompatible",
              "detail": "", "schema_version": ""}
    if not os.path.isfile(path):
        return dict(result, status="missing", detail="The database file does not exist.")
    conn = None
    try:
        uri = Path(os.path.abspath(path)).as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=0.2)
        shape = _read_shape(conn)
        _check_shape(shape, allow_legacy=True)
        if full:
            checked = list(conn.execute("PRAGMA quick_check"))
            if checked != [("ok",)]:
                raise SchemaError("integrity check failed: " + str(checked[:3]))
            for table, column, parent in REFERENCES:
                if conn.execute(
                        f"SELECT 1 FROM {table} c LEFT JOIN {parent} p ON p.id=c.{column} "
                        f"WHERE c.{column} IS NOT NULL AND p.id IS NULL LIMIT 1").fetchone():
                    raise SchemaError(f"foreign key reference missing: {table}.{column}")
        version = shape["meta"].get("schema_version") or ""
        return dict(result, compatible=True, schema_version=version,
                    status="ready" if version == SCHEMA_VERSION else "legacy",
                    detail="" if version == SCHEMA_VERSION else "Compatible older archive; upgraded only when loaded.")
    except SchemaError as exc:
        return dict(result, detail=exc.detail)
    except sqlite3.Error as exc:
        code = (getattr(exc, "sqlite_errorcode", 0) or 0) & 255
        unavailable = code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED,
                               sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_PERM,
                               sqlite3.SQLITE_READONLY, sqlite3.SQLITE_IOERR}
        return dict(result, status="unavailable" if unavailable else "incompatible",
                    detail=str(exc))
    except OSError as exc:
        return dict(result, status="unavailable", detail=str(exc))
    finally:
        if conn is not None:
            conn.close()


def inspect_archive(path: str, *, full: bool = False) -> bool:
    """Compatibility boolean; diagnostics/discovery use the detailed result."""
    return inspect_archive_details(path, full=full)["compatible"]
