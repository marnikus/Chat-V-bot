"""settings_store — app settings (config/settings.json).

Owns the settings tree: chrome / scroll / delays / ui / history / collector
and any unknown section no other store claims. Reads fall back to the
defaults below so a fresh install (or a fresh clone) is fully functional
with no file present.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from stores.json_store import JsonFileStore

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


class SettingsStore(JsonFileStore):
    """One JSON file, one settings tree, atomic saves.

    `data()` is the *overlay* the user actually wrote — never the merged view
    (SET-04): reads fall back to `SETTINGS_DEFAULTS`, the file does not grow a
    copy of every default. The lifecycle itself is `JsonFileStore`'s.
    """

    DEFAULT_FILE = "config.json"
    DEFAULTS: dict[str, Any] = {}

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

    # ── writes ───────────────────────────────────────────────────
    def set(self, *keys_and_value: Any, save: "bool | None" = None,
            save_now: "bool | None" = None) -> None:
        """`set("chrome", "port", 9333)` — nested write, dirty until saved.

        `save_now` is the spelling the ConfigManager facade has always used,
        `save` the one this store documents after P1-3; they are the same
        switch and `save` wins, and neither is ever read as a settings key.
        The default is unchanged from before the split — memory first,
        `save()` (or `save=True`) puts it on disk — because a settings write
        is batched by `ConfigManager` and the store must not decide to
        persist halfway through one of its calls.
        """
        *keys, value = keys_and_value
        if not keys:
            raise ValueError("set() needs at least a key and a value")
        node = self._data
        for key in keys[:-1]:
            if not isinstance(node, dict):
                raise TypeError(f"cannot write into {type(node).__name__}")
            node = node.setdefault(key, {})
        node[keys[-1]] = value
        self._touch()
        if self._wants_save(save, save_now, default=False):
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
