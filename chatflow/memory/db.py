"""SQLite connection, schema and key/value settings store (main thread)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  nickname      TEXT NOT NULL UNIQUE COLLATE NOCASE,
  gender        TEXT NOT NULL DEFAULT 'UNKNOWN',
  registered    INTEGER NOT NULL DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'NEW',
  skip_reason   TEXT,
  first_seen    TEXT NOT NULL,
  last_seen     TEXT NOT NULL,
  messaged_at   TEXT,
  message_count INTEGER NOT NULL DEFAULT 0,
  notes         TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
CREATE INDEX IF NOT EXISTS idx_users_lastseen ON users(last_seen);

CREATE TABLE IF NOT EXISTS presets (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL UNIQUE,
  description TEXT DEFAULT '',
  blocks_json TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS filter_rules (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_id  TEXT NOT NULL UNIQUE,
  type     TEXT NOT NULL,
  selector TEXT NOT NULL,
  value    TEXT NOT NULL,
  enabled  INTEGER NOT NULL DEFAULT 1,
  position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


class Database:
    """Single SQLite connection; never share across threads."""

    def __init__(self, path: str | Path):
        p = Path(path)
        if p.parent and not p.parent.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(p)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchall()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        cur = self._conn.execute(sql, params)
        self._conn.commit()
        return cur

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass


class SettingsRepo:
    """Key/value JSON store inside the DB (app settings snapshot)."""

    def __init__(self, db: Database):
        self._db = db

    def get(self, key: str, default=None):
        row = self._db.query("SELECT value FROM settings WHERE key=?", (key,))
        if not row:
            return default
        try:
            return json.loads(row[0]["value"])
        except json.JSONDecodeError:
            return default

    def set(self, key: str, value) -> None:
        self._db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)))
