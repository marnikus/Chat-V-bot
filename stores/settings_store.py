"""settings_store — app settings (config/settings.json).

Owns the settings tree: chrome / scroll / delays / ui / history / collector
and any unknown section no other store claims. Reads fall back to the
defaults below so a fresh install (or a fresh clone) is fully functional
with no file present.
"""

from __future__ import annotations

import copy
import logging
import os
from typing import Any

from stores.jsonio import load_json, save_json

log = logging.getLogger("chatbot")

#: The media per-file cap was 2 MB before 2026-09-07 (it silently skipped
#: every ordinary chat GIF); the migrated default is 25 MB.
SETTINGS_DEFAULTS: dict[str, Any] = {
    "chrome": {
        "host": "127.0.0.1",
        "port": 9222,
        "reconnect_interval_s": 5,
        "connection_timeout_s": 10,
        "auto_reconnect": True,
    },
    "scroll": {
        "scroll_delta_y": 300,
        "scroll_pause_ms": 800,
        "stall_threshold": 3,
        "max_scrolls": 50,
        "viewport_selector": "cdk-virtual-scroll-viewport.users-list-viewport",
    },
    "delays": {
        "global_pre_action_ms": 500,
        "global_post_action_ms": 200,
        "page_load_timeout_ms": 5000,
    },
    "ui": {"theme": "dark", "language": "ru"},
    "history": {
        "enabled": True,
        "db_path": "history.db",
        "use_fts": True,
        "media": {
            "enabled": True,
            "download": True,
            "cache_dir": "saved_media",
            "max_file_mb": 25,
            "max_cache_mb": 200,
        },
        "preview": {
            "preload_rows": 40,
            "page_size": 50,
            "max_rows": 400,
            "show_images": True,
        },
    },
    "collector": {
        "enabled": True,
        "my_nick": "",
        "heartbeat_ms": 1500,
        "idle_ms": 3000,
        "throttle_factor": 3,
        "require_private": True,
        "download_media": True,
        "chunk_size": 80,
        "chunk_pause_ms": 40,
        "bootstrap_max": 2000,
    },
}

_UNSET = object()


class SettingsStore:
    """One JSON file, one settings tree, atomic saves."""

    def __init__(self, path: Any | None = None,
                 data: dict | None = None):
        # Accept AtomicJsonStore or plain path (test compat vs ConfigManager)
        from stores.atomic import AtomicJsonStore as _AJS
        if isinstance(path, _AJS):
            self._path = path._path
        elif isinstance(path, str) and path:
            self._path = path
        else:
            self._path = "config.json" if not isinstance(path, str) else path
            if not self._path:
                self._path = "config.json"
        if isinstance(path, dict) and data is None:
            data = path  # type: ignore
            self._path = "config.json"
        self._data: dict[str, Any] = {}
        self._dirty = False
        if data is not None:
            self._data = dict(data)
        else:
            self.load()

    # ── persistence ──────────────────────────────────────────────
    def load(self) -> None:
        raw = load_json(self._path, default={})
        self._data = raw if isinstance(raw, dict) else {}

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

    # ── reads ────────────────────────────────────────────────────
    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self._data
        for key in keys:
            if isinstance(node, dict):
                node = node.get(key, _UNSET)
            else:
                return default
            if node is _UNSET:
                # fall back to the defaults tree (same walk)
                node = SETTINGS_DEFAULTS
                for k in keys:
                    node = (node.get(k, default)
                            if isinstance(node, dict) else default)
                    if node is default:
                        return default
                return node
        return node

    def get_copy(self, *keys: str, default: Any = None) -> Any:
        return copy.deepcopy(self.get(*keys, default=default))

    def section(self, name: str) -> dict[str, Any]:
        value = self.get(name, default={})
        return copy.deepcopy(value) if isinstance(value, dict) else {}

    def data(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    # ── writes (memory only; `save()` persists) ──────────────────
    def set(self, *keys_and_value: Any, save_now: bool = True, save: bool | None = None) -> None:
        if save is not None:
            save_now = save
        # also handle bare `save` in keys_and_value position? not needed
        *keys, value = keys_and_value
        node = self._data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value
        self._dirty = True
        if save_now:
            self.save()

    # ── validation (unchanged rules from the single-file era) ────
    def validate(self) -> list[str]:
        errors: list[str] = []
        port = self.get("chrome", "port", default=9222)
        try:
            if not (1 <= int(port) <= 65535):
                errors.append(f"chrome.port invalid: {port}")
        except (TypeError, ValueError):
            errors.append(f"chrome.port invalid: {port}")
        for owner, key in (("scroll", "scroll_pause_ms"),
                           ("delays", "global_pre_action_ms")):
            value = self.get(owner, key, default=0)
            try:
                if value < 0:
                    errors.append(f"{key} must be >= 0")
            except TypeError:
                errors.append(f"{key} must be a number")
        return errors
