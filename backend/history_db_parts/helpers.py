"""HistoryDB helpers (<150)."""
from __future__ import annotations
import re

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


class HistoryDB:
    """Thin async wrapper around the archive's SQLite file."""


