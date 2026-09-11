"""preset_store — named stack presets + message templates
(config/presets.json).

Owns exactly one file. Previously these lived as sections of the single
config.json (and, before that, in SQLite tables): a one-time import keeps
both legacy sources working. The store is cached per file path so that a
`PresetStore(config)` built by a bridge and the ConfigManager's own
instance are the SAME object — two writers can never clobber each other.

AREA B1 (plan P1-3) put this store on the shared `JsonFileStore` lifecycle:
`PresetStore(atomic | path | config)`, `data()`, `load()` / `reload()`,
`save(force=False)` / `flush()`, `dirty`. The per-path identity and the
`config=` spelling of the constructor stay exactly as the bridges use them.
"""

from __future__ import annotations

import copy
import logging
import os
from datetime import datetime
from typing import Any, Optional

from stores.atomic import AtomicJsonStore
from stores.json_store import JsonFileStore

log = logging.getLogger("chatbot")

#: the sections this file owns; other sections are kept verbatim (PRS-03)
SECTIONS = ("stack_presets", "template_presets")


def _config_dir_of(config: Any) -> str:
    """`…/config` derived from a ConfigManager's legacy path (or cwd)."""
    legacy = getattr(config, "_path", None) if config is not None else None
    if not legacy:
        return os.path.join(os.getcwd(), "config")
    return os.path.join(os.path.dirname(os.path.abspath(legacy)), "config")


def _file_for(config: Any, path: Optional[str]) -> str:
    """The one file a `PresetStore(config=…, path=…)` call means.

    Slot one is whichever of the four things a caller can hand a store this
    is — a `ConfigManager`, an `AtomicJsonStore`, another store, or a path —
    because `bridge/router.py` and `backend/config_manager.py` use `config=`
    and every test uses `path=`.
    """
    if isinstance(config, AtomicJsonStore):
        return config.path
    if isinstance(config, JsonFileStore):
        return config.path
    if isinstance(config, (str, os.PathLike)) and str(config):
        return os.fspath(config)
    if path:
        return str(path)
    return os.path.join(_config_dir_of(config), "presets.json")


class PresetStore(JsonFileStore):
    """CRUD for named stack presets and message templates (JSON-backed)."""

    DEFAULT_FILE = os.path.join("config", "presets.json")
    DEFAULTS: dict[str, Any] = {"stack_presets": {}, "template_presets": {}}

    _by_path: dict[str, "PresetStore"] = {}

    def __new__(cls, config: Any = None, path: Optional[str] = None):
        key = os.path.abspath(_file_for(config, path))
        return cls._instance_for(key)

    def __init__(self, config: Any = None, path: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return                # the per-path cache hands back one instance
        from stores.preset_migration import PresetMigration
        self._initialized = True
        self.migration = PresetMigration(self)
        borrowed = config if isinstance(config, AtomicJsonStore) else None
        super().__init__(borrowed, "" if borrowed is not None
                         else _file_for(config, path))

    def _coerce(self, raw: Any) -> dict[str, Any]:
        """Keep unknown sections and guarantee the two known ones are maps.

        `named_set()` lets the ConfigManager facade address ANY section, so
        dropping the unknown ones here would lose committed user data on the
        first restart (PRS-03).
        """
        data = copy.deepcopy(raw) if isinstance(raw, dict) \
            else copy.deepcopy(self.DEFAULTS)
        for key in SECTIONS:
            if not isinstance(data.get(key), dict):
                data[key] = {}
        return data

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
        """Presets from the old SQLite tables (runs at most once).

        The reading itself is `PresetMigration`'s (design §2.6): the two
        legacy tables, the tolerant `blocks` decoding, the "only into an
        empty store" gate. This stays the name `ConfigManager` and the
        migration call.
        """
        return self.migration.import_sqlite(db_path)
