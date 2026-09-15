"""Configuration facade over the split stores (config/*.json).

H-C5 split: owners → config_manager_owners, helpers → config_manager_helpers,
facade now ≤250 LOC.
"""

from __future__ import annotations

import copy
import logging
import os
from typing import Any

from backend.config_manager_helpers import _deep_merge
from backend.config_manager_owners import _OWNERS
from stores.block_store import BlockStore
from stores.bookmark_store import BookmarkStore, DEFAULT_BOOKMARKS
from stores.jsonio import config_dir_for
from stores.labels_file_store import LabelsFileStore, LABELS_DEFAULT
from stores.migration import migrate_legacy_config
from stores.preset_store import PresetStore
from stores.session_store import SessionStore
from stores.settings_store import SETTINGS_DEFAULTS, SettingsStore
from stores.undo_store import UndoStore
from stores.window_preset_store import WindowPresetStore

log = logging.getLogger("chatbot")

MAX_STACK_HISTORY = 100

DEFAULTS: dict[str, Any] = dict(SETTINGS_DEFAULTS)
DEFAULTS.update(
    {
        "url_presets": list(DEFAULT_BOOKMARKS),
        "stack_presets": {},
        "template_presets": {},
        "custom_blocks": [],
        "labels": copy.deepcopy(LABELS_DEFAULT),
        "state": {
            "undo_history": [],
            "db_recent": [],
            "my_nick_recent": [],
            "undo_history_index": -1,
            "grid_layout": None,
            "block_config_pinned": False,
            "window_states": {"closed": [], "minimized": []},
            "window_geometry": None,
            "grid_layout_history": [],
            "grid_layout_history_index": -1,
        },
    }
)

_UNDO_STATE_KEYS = ("undo_history", "undo_history_index")

_SECTION_ROUTES = {
    "url_presets": "bookmarks",
    "custom_blocks": "blocks",
    "labels": "labels_file",
    "stack_presets": "presets",
    "template_presets": "presets",
    "ai_connections": "presets",
    "prompt_presets": "presets",
}

_UNSET = object()


class ConfigManager:
    def __init__(self, path: str = "config.json"):
        self._path = path
        self._dir = config_dir_for(path)
        try:
            migrate_legacy_config(os.path.abspath(path), self._dir)
        except Exception as exc:
            log.warning("config migration skipped: %s", exc)
        os.makedirs(self._dir, exist_ok=True)
        self.settings = SettingsStore(os.path.join(self._dir, "settings.json"))
        self.bookmarks = BookmarkStore(os.path.join(self._dir, "bookmarks.json"))
        self.blocks = BlockStore(os.path.join(self._dir, "blocks.json"))
        self.session = SessionStore(os.path.join(self._dir, "session.json"))
        self.undo = UndoStore(os.path.join(self._dir, "undo.json"))
        self.labels_file = LabelsFileStore(os.path.join(self._dir, "labels.json"))
        self.presets = PresetStore(config=self)
        self.window_presets = WindowPresetStore(config=self)
        self._owners = {name: owner(self, name) for name, owner in _OWNERS.items()}
        log.info("Config loaded from %s", self._dir)

    def load(self) -> None:
        self.settings.load()
        self.bookmarks.load()
        self.blocks.load()
        self.session.load()
        self.undo.reload()
        self.labels_file.reload()
        self.presets.load()
        self.window_presets.load()

    def save(self) -> None:
        self.settings.save()
        self.bookmarks.save()
        self.blocks.save()
        self.session.save()
        self.undo.flush()
        self.labels_file.flush()
        self.presets.save()
        self.window_presets.save()

    def _owner_for(self, section: str):
        return self._owners[_SECTION_ROUTES.get(section, "settings")]

    def _route_of(self, section: str) -> str:
        return _SECTION_ROUTES.get(section, "settings")

    def _store_for(self, section: str):
        owner = self._owner_for(section)
        return owner._store()

    def get(self, *keys: str, default: Any = None) -> Any:
        if not keys:
            return default
        section, rest = keys[0], keys[1:]
        return self._owner_for(section).read(section, rest, default)

    def get_copy(self, *keys: str, default: Any = None) -> Any:
        return copy.deepcopy(self.get(*keys, default=default))

    def set(self, *keys_and_value: Any) -> None:
        *keys, value = keys_and_value
        if not keys:
            return
        section, rest = keys[0], keys[1:]
        self._owner_for(section).write(section, rest, value)

    def to_dict(self) -> str:
        return json_dumps(self.data())

    def data(self) -> dict[str, Any]:
        merged = self._owners["settings"].snapshot("settings")
        for section in _SECTION_ROUTES:
            merged[section] = self._owner_for(section).snapshot(section)
        merged["state"] = self.state_data()
        return merged

    def state_data(self) -> dict[str, Any]:
        state = _deep_merge(copy.deepcopy(DEFAULTS.get("state") or {}), self.session.data())
        state["undo_history"] = self.undo.history()
        state["undo_history_index"] = self.undo.index()
        return state

    def named_all(self, section: str) -> dict[str, Any]:
        return self._owner_for(section).named_all(section)

    def named_get(self, section: str, name: str, default: Any = None) -> Any:
        return self._owner_for(section).named_get(section, name, default)

    def named_set(self, section: str, name: str, value: Any, save: bool = True) -> None:
        self._owner_for(section).named_set(section, name, value)
        if save:
            self.save()

    def named_delete(self, section: str, name: str, save: bool = True) -> bool:
        ok = self._owner_for(section).named_delete(section, name)
        if ok and save:
            self.save()
        return ok

    def get_state(self, key: str, default: Any = None) -> Any:
        if key in _UNDO_STATE_KEYS:
            return self.undo.history() if key == "undo_history" else self.undo.index()
        value = self.session.get(key, _UNSET)
        if value is not _UNSET:
            return value
        return self._state_default(key, default)

    def _state_default(self, key: str, default: Any) -> Any:
        defaults_state = DEFAULTS.get("state", {})
        if isinstance(defaults_state, dict) and key in defaults_state:
            return copy.deepcopy(defaults_state[key])
        return default

    def set_state(self, save: bool = True, **updates: Any) -> None:
        undo_updates = {k: v for k, v in updates.items() if k in _UNDO_STATE_KEYS}
        session_updates = {k: v for k, v in updates.items() if k not in _UNDO_STATE_KEYS}
        if undo_updates:
            self.undo.save_state(undo_updates.get("undo_history", self.undo.history()), undo_updates.get("undo_history_index", self.undo.index()), save_now=save)
        if session_updates:
            self.session.set(save_now=save, **session_updates)
        if undo_updates and not session_updates:
            return
        if save:
            self.settings.save()
            self.labels_file.flush()

    def validate(self) -> list[str]:
        return self.settings.validate()


def json_dumps(data: Any) -> str:
    import json

    return json.dumps(data, ensure_ascii=False)
