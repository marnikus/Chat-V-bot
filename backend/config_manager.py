"""JSON configuration management with defaults and validation."""

import json
import os
import logging
from typing import Any

log = logging.getLogger("chatbot")

DEFAULTS: dict[str, Any] = {
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
    # URL presets shown as quick-connect chips in the URL toolbar
    "url_presets": [
        "https://ru.virt-chat.com/chat",
        "https://ru.virt-chat.com/",
    ],
}


class ConfigManager:
    """Load, access, and persist configuration from a JSON file."""

    def __init__(self, path: str = "config.json"):
        self._path = path
        self._data: dict[str, Any] = {}
        self.load()

    # ── persistence ──────────────────────────────────────────────
    def load(self) -> None:
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                log.info("Config loaded from %s", self._path)
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Config load failed (%s), using defaults", exc)
                self._data = {}
        else:
            self._data = {}

    def save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            log.info("Config saved to %s", self._path)
        except OSError as exc:
            log.error("Config save failed: %s", exc)

    # ── access ───────────────────────────────────────────────────
    def get(self, *keys: str, default: Any = None) -> Any:
        node = self._data
        for key in keys:
            if isinstance(node, dict):
                node = node.get(key, _UNSET)
            else:
                return default
            if node is _UNSET:
                # fall back to defaults tree
                node = DEFAULTS
                for k in keys:
                    node = node.get(k, default) if isinstance(node, dict) else default
                    if node is default:
                        return default
                return node
        return node

    def set(self, *keys_and_value: Any) -> None:
        *keys, value = keys_and_value
        node = self._data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value

    def to_dict(self) -> dict[str, Any]:
        return json.dumps(self._data, ensure_ascii=False)

    # ── validation ───────────────────────────────────────────────
    def validate(self) -> list[str]:
        errors: list[str] = []
        port = self.get("chrome", "port", default=9222)
        if not (1 <= int(port) <= 65535):
            errors.append(f"chrome.port invalid: {port}")
        for key in ("scroll_pause_ms", "global_pre_action_ms"):
            sec, k = key.rsplit("_", 1) if "_" in key else ("scroll", key)
            val = self.get("scroll" if "scroll" in key else "delays", key, default=0)
            if val < 0:
                errors.append(f"{key} must be >= 0")
        return errors


_UNSET = object()
