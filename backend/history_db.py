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
from datetime import datetime
from typing import Any, Iterable, Optional

import aiosqlite

log = logging.getLogger("chatbot")

#: v5 (2026-09-08): full schema validation on open — an old file is repaired
#: in place (missing columns are added, a `messages` table without
#: `person_id` is rebuilt with its rows attributed to persons) and the
#: version is stamped + checked. Clearing a history releases the messages'
#: identity (dup_key) so the collector re-collects that chat from scratch.
SCHEMA_VERSION = "5"

# ── the canonical schema ─────────────────────────────────────────
# One source of truth for BOTH paths:
#   * a fresh file is created from TABLE_SQL / INDEX_SQL, and
#   * an existing file is validated against TABLE_COLUMNS, so creation and
#     validation can never drift apart (a parity test pins this).
# `decl` is the exact text used by CREATE TABLE and by ALTER TABLE ADD
# COLUMN, so a repaired column is identical to a created one.

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
        ("owner", "TEXT NOT NULL DEFAULT ''"),    # whose conversation it belongs to
        ("day", "TEXT NOT NULL DEFAULT ''"),      # YYYY-MM-DD used in the filename
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
        # author-agnostic signatures (fingerprint without the nick): the
        # rename check compares these so a partner renaming themselves —
        # which re-renders every line under the new nick — still resolves
        # to the SAME conversation (2026-09-08)
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
}

#: table-level constraints that a plain column list cannot express.
#: Deliberately NONE for `messages`: the old UNIQUE(person_id, fp, day)
#: constraint made hidden (soft-deleted) rows absorb re-collected lines —
#: a cleared conversation could never be re-collected because every fresh
#: row collided with its hidden twin (Bugs 3 & 4, 2026-09-08). Deduping is
#: the partial unique index on (person_id, dup_key), which ignores the
#: identity-released hidden rows.
TABLE_CONSTRAINTS: dict[str, str] = {}

#: the constraint the pre-v5 schema carried on `messages`; files that still
#: have it are rebuilt once on open (same columns, constraint removed)
LEGACY_MESSAGES_CONSTRAINT = "UNIQUE(person_id, fp, day)"

TABLE_ORDER = ("schema_meta", "persons", "media", "messages", "cursors",
               "gaps")


def _create_table_sql(name: str) -> str:
    lines = [f"    {col} {decl}" for col, decl in TABLE_COLUMNS[name]]
    if name in TABLE_CONSTRAINTS:
        lines.append(f"    {TABLE_CONSTRAINTS[name]}")
    return f"CREATE TABLE IF NOT EXISTS {name} (\n" + ",\n".join(lines) + "\n);"


TABLE_SQL: dict[str, str] = {name: _create_table_sql(name)
                             for name in TABLE_ORDER}

INDEX_SQL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_persons_lc ON persons(nick_lc)",
    # NOT unique: two urls may legitimately carry identical bytes; they share
    # one file on disk but keep one row each.
    "CREATE INDEX IF NOT EXISTS idx_media_sha ON media(sha256)",
    "CREATE INDEX IF NOT EXISTS idx_media_state ON media(state)",
    "CREATE INDEX IF NOT EXISTS idx_messages_person_ord ON messages(person_id, ord)",
    "CREATE INDEX IF NOT EXISTS idx_messages_lc ON messages(person_id, text_lc)",
    "CREATE INDEX IF NOT EXISTS idx_gaps_person ON gaps(person_id)",
)

SCHEMA = "\n\n".join([TABLE_SQL[name] for name in TABLE_ORDER] +
                     [stmt + ";" for stmt in INDEX_SQL]) + "\n"

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
    """Numeric compare for schema versions ("10" > "9", unlike str order)."""
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

    async def _rebuild_legacy_messages(self, columns: list[str]) -> None:
        """Rebuild a pre-persons `messages` table into the canonical shape.

        The legacy table is renamed away first (no byte is destroyed), a
        canonical `messages` is created, and every row is copied over —
        attributed to a person derived from the legacy `nick` column when
        there is one. Rows that cannot be attributed stay in the renamed
        table as quarantine and the archive continues empty.
        """
        path = os.path.basename(self.path)
        quarantine = ("messages_legacy_"
                      + datetime.now().strftime("%Y%m%d%H%M%S"))
        have = set(columns)
        # index names are global in SQLite: the legacy table's indexes must
        # go before `CREATE INDEX IF NOT EXISTS` can rebuild them here
        # (auto-indexes from table constraints cannot be dropped — they die
        # with the table itself)
        legacy_indexes = await self.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='messages' AND sql IS NOT NULL")
        for (idx_name,) in legacy_indexes:
            try:
                await self._conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
            except Exception as e:                  # noqa: BLE001
                log.warning("cannot drop legacy index %s: %s", idx_name, e)
        await self._conn.execute(f"ALTER TABLE messages RENAME TO {quarantine}")
        await self._conn.execute(TABLE_SQL["messages"])
        total = await self._count_rows(quarantine)
        if "nick" not in have:
            await self._conn.commit()
            log.warning(
                "%s: legacy messages table has no person_id and no nick — "
                "%d row(s) kept untouched in %s, the archive starts empty",
                path, total, quarantine)
            return
        from backend.history_models import dedupe_key  # local: avoid cycles
        rows = await self.db_fetch_legacy(quarantine, columns)
        shared = [col for col, _decl in TABLE_COLUMNS["messages"]
                  if col in have and col != "person_id"]
        person_cache: dict[str, int] = {}
        copied = 0
        for row in rows:
            nick = self.normalise_nick(row.get("nick") or "")
            if not nick:
                nick = "Unknown"
            person_id = person_cache.get(nick)
            if person_id is None:
                person_id = await self._person_for_nick(nick)
                person_cache[nick] = person_id
            values = [row.get(col) for col in shared]
            try:
                cur = await self._conn.execute(
                    f"INSERT INTO messages(person_id, {', '.join(shared)}) "
                    f"VALUES(?, {', '.join('?' for _ in shared)})",
                    [person_id] + values)
                copied += 1
            except Exception as e:                  # noqa: BLE001
                log.warning("cannot copy legacy message row: %s", e)
                continue
            # recompute the identity this row never had (payload = the media
            # url when the row points at media, the text otherwise)
            payload = row.get("text") or ""
            if row.get("media_id"):
                url = await self.fetchone(
                    "SELECT url FROM media WHERE id=?", (row["media_id"],))
                payload = (url[0] if url else "") or payload
            key = dedupe_key(row.get("direction") or "in", nick,
                             row.get("ts_display") or "",
                             row.get("kind") or "text", payload)
            await self._conn.execute(
                "UPDATE messages SET text_lc=?, dup_key=? WHERE id=?",
                (str(row.get("text") or "").lower(), key, cur.lastrowid))
        await self._conn.commit()
        if copied == total:
            # explicit-id inserts leave AUTOINCREMENT behind; drop the stale
            # counter so the next insert continues from max(id) + 1
            await self._conn.execute(
                "DELETE FROM sqlite_sequence WHERE name='messages'")
            await self._conn.execute(f"DROP TABLE {quarantine}")
            await self._conn.commit()
        log.info("%s: rebuilt the legacy messages table — %d/%d row(s) "
                 "attributed to %d person(s)",
                 path, copied, total, len(person_cache))

    async def _has_legacy_messages_constraint(self) -> bool:
        """Does this file's `messages` still carry UNIQUE(person_id, fp, day)?

        That constraint made a cleared conversation un-collectable: every
        re-collected line collided with its hidden twin and INSERT OR IGNORE
        dropped it silently ("Added 25" next to "In archive 0", Bugs 3 & 4
        of 2026-09-08). Deduping moved to the partial unique index on
        (person_id, dup_key) in v4; the table constraint is redundant since.
        """
        row = await self.fetchone(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='messages'")
        sql = str(row[0] or "").upper().replace(" ", "") if row else ""
        return LEGACY_MESSAGES_CONSTRAINT.upper().replace(" ", "") in sql

    async def _rebuild_messages_constraint(self) -> None:
        """One-time rebuild that drops the legacy UNIQUE(person_id, fp, day).

        Every row is copied as-is (person_id included) — this only changes
        the table shape, never the data.
        """
        path = os.path.basename(self.path)
        quarantine = ("messages_old_"
                      + datetime.now().strftime("%Y%m%d%H%M%S"))
        legacy_indexes = await self.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='messages' AND sql IS NOT NULL")
        for (idx_name,) in legacy_indexes:
            try:
                await self._conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
            except Exception as e:                  # noqa: BLE001
                log.warning("cannot drop index %s before rebuild: %s",
                            idx_name, e)
        await self._conn.execute(f"ALTER TABLE messages RENAME TO {quarantine}")
        await self._conn.execute(TABLE_SQL["messages"])
        # copy the columns the old table actually has (an older file may be
        # missing late columns — they take their defaults), person_id included
        cur = await self._conn.execute(f"PRAGMA table_info({quarantine})")
        old_columns = [row[1] for row in await cur.fetchall()]
        await cur.close()
        canonical = [col for col, _ in TABLE_COLUMNS["messages"]]
        shared = [col for col in canonical if col in set(old_columns)]
        await self._conn.execute(
            f"INSERT INTO messages({', '.join(shared)}) "
            f"SELECT {', '.join(shared)} FROM {quarantine}")
        total = await self._count_rows(quarantine)
        await self._conn.execute(
            "DELETE FROM sqlite_sequence WHERE name='messages'")
        await self._conn.commit()
        await self._conn.execute(f"DROP TABLE {quarantine}")
        await self._conn.commit()
        log.info("%s: rebuilt the messages table without the legacy "
                 "UNIQUE(person_id, fp, day) constraint — %d row(s) kept",
                 path, total)

    async def _person_for_nick(self, nick: str) -> int:
        """The archive person for a nick, created when missing (repair path)."""
        row = await self.fetchone("SELECT id FROM persons WHERE nick=?",
                                  (nick,))
        if row:
            return int(row[0])
        stamp = datetime.now().isoformat(timespec="seconds")
        cur = await self._conn.execute(
            "INSERT INTO persons(nick, nick_lc, first_seen, last_seen, "
            "created_at) VALUES(?,?,?,?,?)",
            (nick, nick.lower(), stamp, stamp, stamp))
        return int(cur.lastrowid)

    @staticmethod
    def normalise_nick(nick: str) -> str:
        return " ".join(str(nick or "").split()).strip()

    async def _count_rows(self, table: str) -> int:
        try:
            row = await self.fetchone(f"SELECT COUNT(*) FROM {table}")
            return int(row[0]) if row else 0
        except Exception:                            # noqa: BLE001
            return 0

    async def db_fetch_legacy(self, table: str, columns: list[str]) -> list[dict]:
        wanted = [col for col, _ in TABLE_COLUMNS["messages"]
                  if col in set(columns)]
        wanted += [c for c in ("nick",) if c in set(columns) and
                   c not in wanted]
        rows = await self.fetchdicts(
            f"SELECT {', '.join(wanted)} FROM {table}")
        return rows

    async def _read_version(self) -> Optional[str]:
        try:
            value = await self.get_meta("schema_version")
            return str(value) if value else None
        except Exception:                            # noqa: BLE001
            return None

    async def _verify_schema(self) -> None:
        """Post-open guarantee: every canonical column really exists.

        Raises one clear error instead of letting every later query fail
        with "no such column: …" (Bug 1, 2026-09-08).
        """
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
            raise RuntimeError(
                f"database {os.path.basename(self.path)} has an incomplete "
                f"schema: {', '.join(problems[:6])}")

    #: columns added after the first release — old files are upgraded in
    #: place. Kept as an alias of the canonical map: every missing column is
    #: now found by comparing against TABLE_COLUMNS (Bug 5, 2026-09-08).
    @property
    def LATE_COLUMNS(self) -> dict:
        return {name: list(cols) for name, cols in TABLE_COLUMNS.items()}

    async def _add_missing_columns(self) -> None:
        """Compatibility shim — the work now happens in `_repair_tables`."""
        await self._repair_tables()

    async def _migrate_dup_keys(self) -> None:
        """Compute `dup_key`, drop pre-existing duplicates and add its index.

        Old databases stored identity as `fingerprint(.., occ) + day`. That is
        why the same physical line was re-inserted when occurrences shifted or
        the day resolution changed. The new key is timestamp + content for the
        person; here we back-fill it for existing rows and keep the earliest
        row for each key, then resequence as a consequence.

        Hidden (soft-deleted) rows whose identity was deliberately released
        by a history clear stay at `dup_key=''` — re-arming them here would
        block the re-collection the clear promised (Bug 3, 2026-09-08).
        """
        from backend.history_models import dedupe_key  # local: avoid cycles
        rows = await self.fetchall(
            "SELECT m.id, m.person_id, m.direction, m.from_nick, m.kind, "
            "m.text, m.ts_display, COALESCE(md.url, '') AS media_url "
            "FROM messages m LEFT JOIN media md ON md.id = m.media_id "
            "WHERE m.dup_key='' AND m.deleted_at=''")
        for row in rows:
            payload = row[7] or row[5]
            key = dedupe_key(row[2], row[3], row[6], row[4], payload)
            # OR IGNORE: another row may already own this identity (a line
            # that was re-collected while its older copy was hidden)
            await self.execute(
                "UPDATE OR IGNORE messages SET dup_key=? WHERE id=?",
                (key, row[0]))
        if rows:
            await self.commit()

        # keep the earliest id for each (person, dup_key)
        before = int(await self.scalar(
            "SELECT COUNT(*) FROM messages WHERE dup_key<>''", (), 0))
        await self.execute(
            "DELETE FROM messages WHERE dup_key<>'' AND id NOT IN ("
            "SELECT MIN(id) FROM messages WHERE dup_key<>'' "
            "GROUP BY person_id, dup_key)")
        await self.commit()
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
            await self.commit()

        # the index must exist even before the first insert (fresh DBs)
        await self.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_dup_key "
            "ON messages(person_id, dup_key) WHERE dup_key <> ''")
        await self.commit()

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
