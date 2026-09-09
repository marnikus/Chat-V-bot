"""Settings store — chrome, scroll, delays, ui, history, collector slices."""

from __future__ import annotations

import copy
from typing import Any

from core.result import Result
from stores.atomic import AtomicJsonStore


DEFAULTS: dict[str, Any] = {
    "chrome": {"host": "127.0.0.1", "port": 9222, "reconnect_interval_s": 5, "connection_timeout_s": 10, "auto_reconnect": True},
    "scroll": {"scroll_delta_y": 300, "scroll_pause_ms": 800, "stall_threshold": 3, "max_scrolls": 50, "viewport_selector": "cdk-virtual-scroll-viewport.users-list-viewport"},
    "delays": {"global_pre_action_ms": 500, "global_post_action_ms": 200, "page_load_timeout_ms": 5000},
    "ui": {"theme": "dark", "language": "ru"},
    "history": {
        "enabled": True, "db_path": "history.db", "use_fts": True,
        "media": {"enabled": True, "download": True, "cache_dir": "saved_media", "max_file_mb": 2, "max_cache_mb": 200},
        "preview": {"preload_rows": 40, "page_size": 50, "max_rows": 400, "show_images": True},
    },
    "collector": {"enabled": True, "my_nick": "", "heartbeat_ms": 1500, "idle_ms": 3000, "throttle_factor": 3, "require_private": True, "download_media": True, "chunk_size": 80, "chunk_pause_ms": 40, "bootstrap_max": 2000},
    "labels": {"defs": [], "assign": {}, "filter": {"include": [], "exclude": []}, "next_id": 0},
    "stack_presets": {}, "template_presets": {}, "custom_blocks": [],
    "url_presets": ["https://ru.virt-chat.com/chat", "https://ru.virt-chat.com/"],
    "state": {
        "undo_history": [], "db_recent": [], "my_nick_recent": [], "undo_history_index": -1,
        "grid_layout": None, "block_config_pinned": False, "window_states": {"closed": [], "minimized": []},
        "window_geometry": None, "grid_layout_history": [], "grid_layout_history_index": -1,
    },
}


class SettingsStore:
    """Pure I/O for global settings (no presets, no session)."""

    def __init__(self, atomic: AtomicJsonStore | None = None, path: str = "config.json") -> None:
        self._atomic = atomic or AtomicJsonStore(path)

    def get(self, *keys: str, default: Any = None) -> Any:
        val = self._atomic.get(*keys, default=None)
        if val is not None:
            return val
        # fallback to defaults
        node: Any = DEFAULTS
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return default
        return copy.deepcopy(node)

    def get_copy(self, *keys: str, default: Any = None) -> Any:
        return copy.deepcopy(self.get(*keys, default=default))

    def set(self, *keys_and_value: Any) -> Result[None]:
        self._atomic.set(*keys_and_value)
        return self._atomic.save()

    def data(self) -> dict[str, Any]:
        return self._atomic.data()

    def validate(self) -> list[str]:
        errors: list[str] = []
        port = self.get("chrome", "port", default=9222)
        try:
            if not (1 <= int(port) <= 65535):
                errors.append(f"chrome.port invalid: {port}")
        except (TypeError, ValueError):
            errors.append(f"chrome.port invalid: {port}")
        return errors
