"""Single-file JSON settings + preset store.

All settings AND all presets (URL presets, action-stack presets, message
templates, custom blocks) plus the last-session state live in ONE file
(config.json by default) so nothing is split across multiple stores.
"""

import copy
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
    # named action-stack presets: name -> {"blocks": [...], "updated_at": ...}
    "stack_presets": {},
    # named message templates: name -> {"body": "...", "updated_at": ...}
    "template_presets": {},
    # reusable custom Find & Click blocks: [{name, block, updated_at}]
    "custom_blocks": [],
    # last-session state restored on startup:
    #   last_url_preset   -> last selected/connected URL preset
    #   last_stack_preset -> name of the last loaded/saved stack preset
    #   last_stack        -> live snapshot of the last edited/run stack
    #   undo_history       -> one chronological history for every editable
    #       surface (action stack and sash grid), capped at 100 entries
    #   undo_history_index -> current pointer in that single history
    #   grid_layout        -> serialized sash-layout tree (flexible grid)
    #   block_config_pinned -> whether the Block Config panel is pinned open
    #   window_geometry    -> {x, y, width, height} for the desktop window
    "state": {
        "undo_history": [],
        "undo_history_index": -1,
        "grid_layout": None,
        "block_config_pinned": False,
        "window_geometry": None,
        # Legacy read-only migration keys. They are never updated by the
        # global history implementation, but keeping defaults lets old config
        # files load without inventing a second active history.
        "grid_layout_history": [],
        "grid_layout_history_index": -1,
    },
}

# History limits
MAX_STACK_HISTORY = 100


class ConfigManager:
    """Load, access, and persist configuration from a single JSON file."""

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

    def get_copy(self, *keys: str, default: Any = None) -> Any:
        """Deep copy of the value so callers can mutate it safely."""
        return copy.deepcopy(self.get(*keys, default=default))

    def set(self, *keys_and_value: Any) -> None:
        *keys, value = keys_and_value
        node = self._data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value

    def to_dict(self) -> str:
        return json.dumps(self._data, ensure_ascii=False)

    def data(self) -> dict[str, Any]:
        """Full JSON-serialisable data (for get_app_state etc.)."""
        return copy.deepcopy(self._data)

    # ── named sub-stores (presets keyed by name) ─────────────────
    def named_all(self, section: str) -> dict[str, Any]:
        raw = self.get_copy(section, default={})
        return raw if isinstance(raw, dict) else {}

    def named_get(self, section: str, name: str, default: Any = None) -> Any:
        return self.named_all(section).get(name, default)

    def named_set(self, section: str, name: str, value: Any, save: bool = True) -> None:
        all_items = self.named_all(section)
        all_items[str(name)] = value
        self.set(section, all_items)
        if save:
            self.save()

    def named_delete(self, section: str, name: str, save: bool = True) -> bool:
        all_items = self.named_all(section)
        if str(name) not in all_items:
            return False
        del all_items[str(name)]
        self.set(section, all_items)
        if save:
            self.save()
        return True

    # ── last-session state ───────────────────────────────────────
    def get_state(self, key: str, default: Any = None) -> Any:
        state = self.get("state", default={})
        if not isinstance(state, dict):
            return default
        if key in state:
            return state[key]
        # fallback to DEFAULTS state if present
        defaults_state = DEFAULTS.get("state", {})
        if isinstance(defaults_state, dict) and key in defaults_state:
            return copy.deepcopy(defaults_state[key])
        return default

    def set_state(self, save: bool = True, **updates: Any) -> None:
        state = self.get_copy("state", default={})
        if not isinstance(state, dict):
            state = {}
        for key, value in updates.items():
            state[key] = value
        self.set("state", state)
        if save:
            self.save()

    # ── validation ───────────────────────────────────────────────
    def validate(self) -> list[str]:
        errors: list[str] = []
        port = self.get("chrome", "port", default=9222)
        if not (1 <= int(port) <= 65535):
            errors.append(f"chrome.port invalid: {port}")
        for key in ("scroll_pause_ms", "global_pre_action_ms"):
            val = self.get("scroll" if "scroll" in key else "delays", key, default=0)
            if val < 0:
                errors.append(f"{key} must be >= 0")
        return errors


_UNSET = object()
