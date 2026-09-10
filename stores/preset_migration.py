"""PresetMigration — the one-time import from the pre-JSON preset sources.

Named stack presets and message templates lived in two places before this
store: as sections of the single `config.json` (handled by
`stores/migration.py`) and, before that, in the SQLite tables `stacks` and
`templates` of `chatbot.db`. `PresetStore.import_legacy` is the entry point
callers use; the reading, the tolerant JSON decoding of a `blocks` column and
the "at most once" gate live here so the store itself stays CRUD.

The collaborator writes through the aggregate (`owner._data`, `owner.save()`),
never to a file of its own — one payload, one writer.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:                                  # only for the annotation
    from stores.preset_store import PresetStore

log = logging.getLogger("chatbot")

class PresetMigration:
    """Legacy `chatbot.db` preset tables → the JSON payload."""

    def __init__(self, owner: "PresetStore") -> None:
        self._owner = owner

    def import_sqlite(self, db_path: str = "chatbot.db") -> bool:
        """Presets from the old SQLite tables (runs at most once)."""
        owner = self._owner
        if owner._data["stack_presets"] or owner._data["template_presets"]:
            return False
        if not os.path.exists(db_path):
            return False
        imported = False
        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                imported = bool(self._read_stacks(conn)
                                + self._read_templates(conn))
            except sqlite3.OperationalError:
                pass                       # tables absent in this build
            finally:
                conn.close()
        except sqlite3.Error as exc:
            log.warning("Legacy preset import failed: %s", exc)
            return False
        if imported:
            owner._touch()
            owner.save()
            log.info("Legacy presets imported into %s", owner.path)
        return bool(imported)

    # ── the two tables ───────────────────────────────────────────
    def _read_stacks(self, conn: sqlite3.Connection) -> int:
        """`stacks(name, blocks)` — a garbage row is skipped, never fatal."""
        count = 0
        cur = conn.execute("SELECT name, blocks FROM stacks")  # may not exist
        for row in cur.fetchall():
            try:
                blocks = json.loads(row["blocks"])
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(blocks, list):
                self._owner._data["stack_presets"][row["name"]] = {
                    "blocks": blocks,
                    "updated_at": self._owner._now()}
                count += 1
        return count

    def _read_templates(self, conn: sqlite3.Connection) -> int:
        count = 0
        cur = conn.execute("SELECT name, body FROM templates")
        for row in cur.fetchall():
            self._owner._data["template_presets"][row["name"]] = {
                "body": row["body"], "updated_at": self._owner._now()}
            count += 1
        return count
