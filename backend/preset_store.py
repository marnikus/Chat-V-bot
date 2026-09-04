"""Persistent preset store (SQLite) for action stacks and message templates.

Deliberately synchronous: the data volumes are tiny (a few KB) and the
bridge/QWebChannel API is synchronous, so save/load/list must return
immediately without async race conditions. WAL mode + busy timeout keep
it safe alongside UserMemory's aiosqlite connection on the same file.
"""

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Optional

log = logging.getLogger("chatbot")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS stacks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT UNIQUE NOT NULL,
    blocks     TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS templates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT UNIQUE NOT NULL,
    body       TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


class PresetStore:
    """CRUD for stack presets and message templates."""

    def __init__(self, db_path: str = "chatbot.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._ensure_schema()

    # ── connection helpers ───────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=8000")
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            try:
                conn = self._connect()
                try:
                    conn.executescript(_SCHEMA)
                    conn.commit()
                finally:
                    conn.close()
            except sqlite3.Error as exc:
                log.error("PresetStore schema init failed: %s", exc)

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    # ── stacks (action presets) ──────────────────────────────────
    def save_stack(self, name: str, blocks: list[dict]) -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("Preset name cannot be empty")
        payload = json.dumps(list(blocks or []), ensure_ascii=False)
        now = self._now()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO stacks(name, blocks, created_at, updated_at) "
                    "VALUES(?,?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET "
                    "blocks=excluded.blocks, updated_at=excluded.updated_at",
                    (name, payload, now, now))
                conn.commit()
            finally:
                conn.close()
        log.info("Stack preset saved: '%s' (%d blocks)", name, len(blocks or []))

    def load_stack(self, name: str) -> Optional[list[dict]]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("SELECT blocks FROM stacks WHERE name=?", (name,))
                row = cur.fetchone()
            finally:
                conn.close()
        if not row:
            return None
        try:
            data = json.loads(row["blocks"])
            return data if isinstance(data, list) else None
        except (json.JSONDecodeError, TypeError):
            log.error("Stack preset '%s' has corrupt JSON", name)
            return None

    def list_stacks(self) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT name, blocks, updated_at FROM stacks "
                    "ORDER BY updated_at DESC, name COLLATE NOCASE")
                rows = cur.fetchall()
            finally:
                conn.close()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                count = len(json.loads(r["blocks"]))
            except (json.JSONDecodeError, TypeError):
                count = 0
            out.append({"name": r["name"], "blocks": count,
                        "updated_at": r["updated_at"] or ""})
        return out

    def delete_stack(self, name: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("DELETE FROM stacks WHERE name=?", (name,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    # ── templates (message presets) ──────────────────────────────
    def save_template(self, name: str, body: str) -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("Template name cannot be empty")
        now = self._now()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO templates(name, body, created_at, updated_at) "
                    "VALUES(?,?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET "
                    "body=excluded.body, updated_at=excluded.updated_at",
                    (name, body or "", now, now))
                conn.commit()
            finally:
                conn.close()
        log.info("Template saved: '%s' (%d chars)", name, len(body or ""))

    def load_template(self, name: str) -> Optional[str]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("SELECT body FROM templates WHERE name=?", (name,))
                row = cur.fetchone()
            finally:
                conn.close()
        return row["body"] if row else None

    def list_templates(self) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT name, body, updated_at FROM templates "
                    "ORDER BY updated_at DESC, name COLLATE NOCASE")
                rows = cur.fetchall()
            finally:
                conn.close()
        return [{"name": r["name"], "len": len(r["body"] or ""),
                 "updated_at": r["updated_at"] or ""} for r in rows]

    def delete_template(self, name: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("DELETE FROM templates WHERE name=?", (name,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def db_file(self) -> str:
        return os.path.abspath(self._db_path)
