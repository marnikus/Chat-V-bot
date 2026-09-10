"""preset_store — named stack presets + message templates
(config/presets.json).

Owns exactly one file. Previously these lived as sections of the single
config.json (and, before that, in SQLite tables): a one-time import keeps
both legacy sources working. The store is cached per file path so that a
`PresetStore(config)` built by a bridge and the ConfigManager's own
instance are the SAME object — two writers can never clobber each other.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Optional

from stores.jsonio import load_json, save_json

log = logging.getLogger("chatbot")


def _config_dir_of(config) -> str:
    """`…/config` derived from a ConfigManager's legacy path (or cwd)."""
    legacy = getattr(config, "_path", None) if config is not None else None
    if not legacy:
        return os.path.join(os.getcwd(), "config")
    return os.path.join(os.path.dirname(os.path.abspath(legacy)), "config")


class PresetStore:
    """CRUD for named stack presets and message templates (JSON-backed)."""

    _by_path: dict[str, "PresetStore"] = {}

    def __new__(cls, config=None, path: Optional[str] = None):
        # B1 unification: config may be AtomicJsonStore, a path string, or a
        # ConfigManager-like object; path may be AtomicJsonStore or str.
        from stores.atomic import AtomicJsonStore as _AJS
        effective_path: Optional[str] = None
        effective_config = config
        if isinstance(config, _AJS):
            effective_path = config._path
            effective_config = None
        elif isinstance(config, str) and config:
            effective_path = config
            effective_config = None
        elif isinstance(path, _AJS):
            effective_path = path._path
        elif isinstance(path, str) and path:
            effective_path = path
        else:
            effective_path = path
        if effective_path:
            key = os.path.abspath(effective_path)
        else:
            key = os.path.abspath(
                os.path.join(_config_dir_of(effective_config), "presets.json"))
        cached = cls._by_path.get(key)
        if cached is not None:
            return cached
        instance = super().__new__(cls)
        instance._cache_key = key
        cls._by_path[key] = instance
        return instance

    def __init__(self, config=None, path: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._path = self._cache_key
        self._data: dict[str, dict[str, Any]] = {"stack_presets": {},
                                                 "template_presets": {}}
        self._dirty = False
        self.load()

    # ── persistence ──────────────────────────────────────────────
    def load(self) -> None:
        raw = load_json(self._path, default={})
        if isinstance(raw, dict):
            # Unknown sections survive the round-trip: named_set() lets the
            # facade address any section, so dropping them here would lose
            # committed user data on every restart (PRS-03).
            data = dict(raw)
            for key in ("stack_presets", "template_presets"):
                if not isinstance(data.get(key), dict):
                    data[key] = {}
            self._data = data

    def save(self, force: bool = False) -> bool:
        if not (self._dirty or force):
            return True
        ok = save_json(self._path, self._data)
        if ok:
            self._dirty = False
        return ok

    @property
    def path(self) -> str:
        return self._path

    @property
    def dirty(self) -> bool:
        return self._dirty

    # ── timestamp ────────────────────────────────────────────────
    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    # ── stacks (action presets) ──────────────────────────────────
    def save_stack(self, name: str, blocks: list[dict]) -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("Preset name cannot be empty")
        if blocks is not None and not isinstance(blocks, (list, tuple)):
            raise ValueError("blocks must be a list of dicts")
        self._data["stack_presets"][name] = {
            "blocks": list(blocks or []),
            "updated_at": self._now(),
        }
        self._dirty = True
        log.info("Stack preset saved: '%s' (%d blocks)", name,
                 len(blocks or []))

    def load_stack(self, name: str) -> Optional[list[dict]]:
        entry = self._data["stack_presets"].get(name)
        if not isinstance(entry, dict):
            return None
        blocks = entry.get("blocks")
        if not isinstance(blocks, list):
            return None
        return list(blocks)

    def list_stacks(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name, entry in self._data["stack_presets"].items():
            if not isinstance(entry, dict):
                continue
            blocks = entry.get("blocks")
            out.append({
                "name": name,
                "blocks": len(blocks) if isinstance(blocks, list) else 0,
                "updated_at": entry.get("updated_at", ""),
            })
        out.sort(key=lambda r: (r["updated_at"] or "", r["name"]),
                 reverse=True)
        return out

    def delete_stack(self, name: str) -> bool:
        if name not in self._data["stack_presets"]:
            return False
        del self._data["stack_presets"][name]
        self._dirty = True
        return True

    # ── templates (message presets) ──────────────────────────────
    def save_template(self, name: str, body: str) -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("Template name cannot be empty")
        if body is not None and not isinstance(body, str):
            raise ValueError("template body must be a string")
        self._data["template_presets"][name] = {
            "body": body or "",
            "updated_at": self._now(),
        }
        self._dirty = True
        log.info("Template saved: '%s' (%d chars)", name, len(body or ""))

    def load_template(self, name: str) -> Optional[str]:
        entry = self._data["template_presets"].get(name)
        if not isinstance(entry, dict):
            return None
        body = entry.get("body")
        return body if isinstance(body, str) else None

    def list_templates(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name, entry in self._data["template_presets"].items():
            if not isinstance(entry, dict):
                continue
            body = entry.get("body", "")
            out.append({
                "name": name,
                "len": len(body) if isinstance(body, str) else 0,
                "updated_at": entry.get("updated_at", ""),
            })
        out.sort(key=lambda r: (r["updated_at"] or "", r["name"]),
                 reverse=True)
        return out

    def delete_template(self, name: str) -> bool:
        if name not in self._data["template_presets"]:
            return False
        del self._data["template_presets"][name]
        self._dirty = True
        return True

    # ── named_* compatibility surface (used by the ConfigManager
    #    facade so old callers can address presets by section name) ─
    def named_all(self, section: str) -> dict[str, Any]:
        return dict(self._data.get(section) or {})

    def named_get(self, section: str, name: str,
                  default: Any = None) -> Any:
        return self._data.get(section, {}).get(name, default)

    def named_set(self, section: str, name: str, value: Any) -> None:
        self._data.setdefault(section, {})[str(name)] = value
        self._dirty = True

    def named_delete(self, section: str, name: str) -> bool:
        section_data = self._data.get(section)
        if not isinstance(section_data, dict) or \
                str(name) not in section_data:
            return False
        del section_data[str(name)]
        self._dirty = True
        return True

    # ── one-time legacy imports ──────────────────────────────────
    def import_legacy(self, db_path: str = "chatbot.db") -> bool:
        """Presets from the old SQLite tables (runs at most once)."""
        from stores._preset_migrate import import_legacy as _import
        return _import(self, db_path)
