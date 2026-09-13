"""The archive's schema — one source of truth for creation and validation.

Extracted from `stores/history_db.py` by the AREA B2 split (design §2.4): the
table definitions, the index list, the FTS mirror and the version stamp are
pure data, and the DB class is a connection. Keeping them apart is what lets
`_verify_schema()` validate against the SAME text `init()` creates, instead of
both living in a 600-line file.

`stores/history_db.py` re-exports every name here: `backend/history_db.py` and
the other areas import `SCHEMA_VERSION` / `TABLE_COLUMNS` from the module they
have always used, and an internal split must not force an import edit.

The comments below are load-bearing — they record *why* v5/v6 look like this —
so they moved with the constants rather than being rewritten.
"""

from __future__ import annotations

#: v6 (2026-09-08): ONE DB = ONE WORLD. The file now also carries the
#: People queue (`users` — moved in from `chatbot.db`), person labels
#: (`labels` / `label_assigns` — moved in from config.json), the world-bound
#: half of the undo timeline (`undo_history`), the radar/observation session
#: state (`gaze_data`) and the per-world settings (`app_settings`).
#: v5 (2026-09-08): full schema validation on open — an old file is repaired
#: in place (missing columns are added, a `messages` table without
#: `person_id` is rebuilt with its rows attributed to persons) and the
#: version is stamped + checked. Clearing a history releases the messages'
#: identity (dup_key) so the collector re-collects that chat from scratch.
SCHEMA_VERSION = "6"

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
    # ── v6: the world tables (one DB = one complete world) ─────────
    # People queue — moved in from chatbot.db so the queue follows the
    # world it belongs to. Same shape as the standalone file, so
    # UserMemory keeps working unchanged when it points at this file.
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
    # Label definitions — moved in from config.json ("labels" section).
    "labels": (
        ("id", "TEXT PRIMARY KEY"),
        ("name", "TEXT NOT NULL UNIQUE COLLATE NOCASE"),
        ("color", "TEXT NOT NULL DEFAULT '#ff3b30'"),
        ("created_at", "TEXT NOT NULL DEFAULT ''"),
    ),
    # person → label assignments (one row per pair; display order is
    # re-read from the world on every load, not stored as a list)
    "label_assigns": (
        ("nick", "TEXT NOT NULL"),
        ("label_id", "TEXT NOT NULL"),
    ),
    # World-bound half of the ONE undo timeline (kinds people / labels /
    # archive / dbconn). `seq` is a global monotonic order shared with the
    # app-level entries kept in config.json, so the interleaving survives a
    # restart or a round-trip through another world.
    "undo_history": (
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("seq", "INTEGER NOT NULL UNIQUE"),
        ("kind", "TEXT NOT NULL"),
        ("value", "TEXT NOT NULL"),
        ("created_at", "TEXT"),
    ),
    # Radar / observation session state (partner nick, counters). The
    # verified private-chat gate is deliberately NOT stored here: RULE 15
    # fails closed, so every fresh open re-verifies from scratch.
    "gaze_data": (
        ("key", "TEXT PRIMARY KEY"),
        ("value", "TEXT NOT NULL"),
        ("updated_at", "TEXT"),
    ),
    # Per-world settings (my nick, media caps, preview…). Values are JSON.
    # config.json stays the app-level template that seeds a new world.
    "app_settings": (
        ("key", "TEXT PRIMARY KEY"),
        ("value", "TEXT NOT NULL"),
        ("updated_at", "TEXT"),
    ),
}

#: table-level constraints that a plain column list cannot express.
#: Deliberately NONE for `messages`: the old UNIQUE(person_id, fp, day)
#: constraint made hidden (soft-deleted) rows absorb re-collected lines —
#: a cleared conversation could never be re-collected because every fresh
#: row collided with its hidden twin (Bugs 3 & 4, 2026-09-08). Deduping is
#: the partial unique index on (person_id, dup_key), which ignores the
#: identity-released hidden rows.
TABLE_CONSTRAINTS: dict[str, str] = {
    "label_assigns": "PRIMARY KEY (nick, label_id)",
}

#: the constraint the pre-v5 schema carried on `messages`; files that still
#: have it are rebuilt once on open (same columns, constraint removed)
LEGACY_MESSAGES_CONSTRAINT = "UNIQUE(person_id, fp, day)"

TABLE_ORDER = ("schema_meta", "persons", "media", "messages", "cursors",
               "gaps", "users", "labels", "label_assigns", "undo_history",
               "gaze_data", "app_settings")

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
    # v6 world tables
    "CREATE INDEX IF NOT EXISTS idx_users_messaged ON users(messaged)",
    "CREATE INDEX IF NOT EXISTS idx_label_assigns_nick ON label_assigns(nick)",
    "CREATE INDEX IF NOT EXISTS idx_label_assigns_id ON label_assigns(label_id)",
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
