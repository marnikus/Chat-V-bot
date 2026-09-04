"""Preset store backed by the SINGLE config.json file.

All presets (action stacks, message templates) are stored together with
the rest of the settings/state in one place (ConfigManager → config.json),
per the "single preset storage" requirement. A one-time import from the
legacy SQLite tables keeps previously saved presets from older builds.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Optional

from backend.config_manager import ConfigManager

log = logging.getLogger("chatbot")


class PresetStore:
    """CRUD for named stack presets and message templates (JSON-backed)."""

    def __init__(self, config: Optional[ConfigManager] = None):
        self._config = config or ConfigManager()

    # ── timestamp ────────────────────────────────────────────────
    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    # ── stacks (action presets) ──────────────────────────────────
    def save_stack(self, name: str, blocks: list[dict]) -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("Preset name cannot be empty")
        entry = {"blocks": list(blocks or []),
                 "updated_at": self._now()}
        self._config.named_set("stack_presets", name, entry)
        log.info("Stack preset saved: '%s' (%d blocks)", name, len(blocks or []))

    def load_stack(self, name: str) -> Optional[list[dict]]:
        entry = self._config.named_get("stack_presets", name)
        if not isinstance(entry, dict):
            return None
        blocks = entry.get("blocks")
        if not isinstance(blocks, list):
            return None
        return list(blocks)

    def list_stacks(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name, entry in self._config.named_all("stack_presets").items():
            if not isinstance(entry, dict):
                continue
            blocks = entry.get("blocks")
            out.append({
                "name": name,
                "blocks": len(blocks) if isinstance(blocks, list) else 0,
                "updated_at": entry.get("updated_at", ""),
            })
        out.sort(key=lambda r: (r["updated_at"] or "", r["name"]), reverse=True)
        return out

    def delete_stack(self, name: str) -> bool:
        return self._config.named_delete("stack_presets", name)

    # ── templates (message presets) ──────────────────────────────
    def save_template(self, name: str, body: str) -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("Template name cannot be empty")
        entry = {"body": body or "", "updated_at": self._now()}
        self._config.named_set("template_presets", name, entry)
        log.info("Template saved: '%s' (%d chars)", name, len(body or ""))

    def load_template(self, name: str) -> Optional[str]:
        entry = self._config.named_get("template_presets", name)
        if not isinstance(entry, dict):
            return None
        body = entry.get("body")
        return body if isinstance(body, str) else None

    def list_templates(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name, entry in self._config.named_all("template_presets").items():
            if not isinstance(entry, dict):
                continue
            body = entry.get("body", "")
            out.append({
                "name": name,
                "len": len(body) if isinstance(body, str) else 0,
                "updated_at": entry.get("updated_at", ""),
            })
        out.sort(key=lambda r: (r["updated_at"] or "", r["name"]), reverse=True)
        return out

    def delete_template(self, name: str) -> bool:
        return self._config.named_delete("template_presets", name)

    # ── one-time legacy import from the old SQLite tables ────────
    def import_legacy(self, db_path: str = "chatbot.db") -> bool:
        """Migrate presets from the old SQLite store into config.json.

        Runs at most once (only when the JSON store is still empty).
        Returns True when anything was imported.
        """
        if self._config.named_all("stack_presets") or \
                self._config.named_all("template_presets"):
            return False
        if not os.path.exists(db_path):
            return False
        imported = False
        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.execute(
                    "SELECT name, blocks FROM stacks")  # may not exist yet
                for row in cur.fetchall():
                    try:
                        blocks = json.loads(row["blocks"])
                        if isinstance(blocks, list):
                            self._config.named_set("stack_presets",
                                                   row["name"],
                                                   {"blocks": blocks,
                                                    "updated_at": self._now()},
                                                   save=False)
                            imported = True
                    except (json.JSONDecodeError, TypeError):
                        continue
                cur = conn.execute(
                    "SELECT name, body FROM templates")
                for row in cur.fetchall():
                    self._config.named_set("template_presets", row["name"],
                                           {"body": row["body"],
                                            "updated_at": self._now()},
                                           save=False)
                    imported = True
            except sqlite3.OperationalError:
                pass  # tables absent in this build
            finally:
                conn.close()
        except sqlite3.Error as exc:
            log.warning("Legacy preset import failed: %s", exc)
            return False
        if imported:
            self._config.save()
            log.info("Legacy presets imported into %s",
                     getattr(self._config, "_path", "config.json"))
        return imported
