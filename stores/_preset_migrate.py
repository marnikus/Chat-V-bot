"""Preset migration — extracted from PresetStore (AREA B)."""

from __future__ import annotations

import json
import logging
import os
import sqlite3

log = logging.getLogger("chatbot")

def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")

def import_legacy(store, db_path: str = "chatbot.db") -> bool:
    if store._data["stack_presets"] or store._data["template_presets"]:
        return False
    if not os.path.exists(db_path):
        return False
    imported = False
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute("SELECT name, blocks FROM stacks")
            for row in cur.fetchall():
                try:
                    blocks = json.loads(row["blocks"])
                    if isinstance(blocks, list):
                        store._data["stack_presets"][row["name"]] = {"blocks": blocks, "updated_at": _now()}
                        imported = True
                except (json.JSONDecodeError, TypeError):
                    continue
            cur = conn.execute("SELECT name, body FROM templates")
            for row in cur.fetchall():
                store._data["template_presets"][row["name"]] = {"body": row["body"], "updated_at": _now()}
                imported = True
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("Legacy preset import failed: %s", exc)
        return False
    if imported:
        store._dirty = True
        store.save()
        log.info("Legacy presets imported into %s", store._path)
    return imported
