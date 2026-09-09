"""Configuration facade over the split stores (config/*.json).

The 2026-09-09 refactor split the single config.json into seven
purpose-named files, each owned by exactly one store (stores/ package)
with atomic saves. This class keeps the historical ConfigManager API —
`get/set/get_copy/save/get_state/set_state/named_*/validate`, `DEFAULTS`,
`MAX_STACK_HISTORY`, `_path` — and routes every access to the owning
store, so the six backend consumers and every existing test keep working
unchanged. New code receives the specific store it needs via DI instead.

File map (see stores/migration.py):
    config/settings.json    chrome/scroll/delays/ui/history/collector
    config/presets.json     stack_presets, template_presets
    config/bookmarks.json   url_presets
    config/blocks.json      custom_blocks
    config/labels.json      the legacy labels section (offline fallback)
    config/session.json     state.* (except the undo timeline)
    config/undo.json        state.undo_history + undo_history_index
"""

from __future__ import annotations

import copy
import logging
import os
from typing import Any

from stores.jsonio import config_dir_for
from stores.migration import migrate_legacy_config
from stores.settings_store import SettingsStore, SETTINGS_DEFAULTS
from stores.bookmark_store import BookmarkStore, DEFAULT_BOOKMARKS
from stores.block_store import BlockStore
from stores.session_store import SessionStore
from stores.undo_store import UndoStore
from stores.labels_file_store import LabelsFileStore, LABELS_DEFAULT
from stores.preset_store import PresetStore

log = logging.getLogger("chatbot")

#: History limits (unchanged)
MAX_STACK_HISTORY = 100

#: Compatibility default tree — the merged view of all store defaults.
#: Kept because bridge code and tests import DEFAULTS to reason about
#: fallbacks; writes never go here.
DEFAULTS: dict[str, Any] = dict(SETTINGS_DEFAULTS)
DEFAULTS.update({
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
})

#: state keys owned by the undo store rather than the session store
_UNDO_STATE_KEYS = ("undo_history", "undo_history_index")

#: top-level keys routed away from the settings store
_SECTION_ROUTES = {
    "url_presets": "bookmarks",
    "custom_blocks": "blocks",
    "labels": "labels",
    "stack_presets": "presets",
    "template_presets": "presets",
}

_UNSET = object()


class ConfigManager:
    """Load, access, and persist configuration across the split stores."""

    def __init__(self, path: str = "config.json"):
        self._path = path
        self._dir = config_dir_for(path)
        # one-time split of a legacy single-file install
        try:
            migrate_legacy_config(os.path.abspath(path), self._dir)
        except Exception as exc:                      # noqa: BLE001
            log.warning("config migration skipped: %s", exc)
        os.makedirs(self._dir, exist_ok=True)
        self.settings = SettingsStore(os.path.join(self._dir,
                                                   "settings.json"))
        self.bookmarks = BookmarkStore(os.path.join(self._dir,
                                                    "bookmarks.json"))
        self.blocks = BlockStore(os.path.join(self._dir, "blocks.json"))
        self.session = SessionStore(os.path.join(self._dir,
                                                 "session.json"))
        self.undo = UndoStore(os.path.join(self._dir, "undo.json"))
        self.labels_file = LabelsFileStore(os.path.join(self._dir,
                                                        "labels.json"))
        # PresetStore caches per path, so this is the same instance the
        # bridge constructs with PresetStore(config=self)
        self.presets = PresetStore(config=self)
        log.info("Config loaded from %s", self._dir)

    # ── persistence ──────────────────────────────────────────────
    def load(self) -> None:
        """Re-read every store file from disk."""
        self.settings.load()
        self.bookmarks.load()
        self.blocks.load()
        self.session.load()
        self.undo.reload()
        self.labels_file.reload()
        self.presets.load()

    def save(self) -> None:
        """Flush every dirty store (each save is atomic per file)."""
        self.settings.save()
        self.bookmarks.save()
        self.blocks.save()
        self.session.save()
        self.undo.flush()
        self.labels_file.flush()
        self.presets.save()

    # ── internal routing ─────────────────────────────────────────
    def _store_for(self, section: str):
        route = _SECTION_ROUTES.get(section)
        if route == "bookmarks":
            return self.bookmarks
        if route == "blocks":
            return self.blocks
        if route == "labels":
            return self.labels_file
        if route == "presets":
            return self.presets
        return self.settings

    # ── access ───────────────────────────────────────────────────
    def get(self, *keys: str, default: Any = None) -> Any:
        if not keys:
            return default
        section, rest = keys[0], keys[1:]
        store = self._store_for(section)
        if store is self.bookmarks:
            value = store.all()
        elif store is self.labels_file:
            value = store.data()
        elif store is self.presets:
            if rest:
                return self._named_get(section, rest[0], default)
            value = store.named_all(section)
        elif store is self.blocks:
            value = store.all()
        else:
            return self.settings.get(*keys, default=default)
        if not rest:
            return copy.deepcopy(value)
        # a nested key under a routed section (e.g. get("labels","filter"))
        node = value
        for key in rest:
            if isinstance(node, dict):
                node = node.get(key, _UNSET)
            else:
                return default
            if node is _UNSET:
                return default
        return node

    def get_copy(self, *keys: str, default: Any = None) -> Any:
        """Deep copy of the value so callers can mutate it safely."""
        return copy.deepcopy(self.get(*keys, default=default))

    def set(self, *keys_and_value: Any) -> None:
        *keys, value = keys_and_value
        if not keys:
            return
        section, rest = keys[0], keys[1:]
        store = self._store_for(section)
        if store is self.bookmarks:
            store.set_all(value if isinstance(value, list) else [])
        elif store is self.blocks:
            store.set_all(value if isinstance(value, list) else [])
        elif store is self.labels_file:
            store.set_data(value)
        elif store is self.presets:
            if rest:
                if len(rest) == 2:                 # set(sec, name, value)
                    store.named_set(section, rest[0], rest[1])
                else:                              # set(sec, whole-map)
                    if isinstance(value, dict):
                        for name in list(store.named_all(section)):
                            store.named_delete(section, name)
                        for name, item in value.items():
                            store.named_set(section, name, item)
            elif isinstance(value, dict):
                for name in list(store.named_all(section)):
                    store.named_delete(section, name)
                for name, item in value.items():
                    store.named_set(section, name, item)
        elif rest:
            self.settings.set(section, *rest, value)
        else:
            self.settings.set(section, value)

    def to_dict(self) -> str:
        return json_dumps(self.data())

    def data(self) -> dict[str, Any]:
        """Full JSON-serialisable merged data (for get_app_state etc.)."""
        # underlay the defaults so a fresh install (no settings.json yet)
        # still reports the whole documented tree, not just the routed
        # sections — "merged" must mean the same thing `get()` serves.
        merged = copy.deepcopy(SETTINGS_DEFAULTS)
        merged.update(self.settings.data())
        merged["url_presets"] = self.bookmarks.all()
        merged["custom_blocks"] = self.blocks.all()
        merged["labels"] = self.labels_file.data()
        merged["stack_presets"] = self.presets.named_all("stack_presets")
        merged["template_presets"] = self.presets.named_all(
            "template_presets")
        merged["state"] = self.state_data()
        return merged

    def state_data(self) -> dict[str, Any]:
        state = self.session.data()
        state["undo_history"] = self.undo.history()
        state["undo_history_index"] = self.undo.index()
        return state

    # ── named sub-stores (presets keyed by name) ─────────────────
    def named_all(self, section: str) -> dict[str, Any]:
        if self._store_for(section) is self.presets:
            return self.presets.named_all(section)
        raw = self.get_copy(section, default={})
        return raw if isinstance(raw, dict) else {}

    def named_get(self, section: str, name: str, default: Any = None) -> Any:
        if self._store_for(section) is self.presets:
            return self.presets.named_get(section, name, default)
        return self.named_all(section).get(name, default)

    def named_set(self, section: str, name: str, value: Any,
                  save: bool = True) -> None:
        if self._store_for(section) is self.presets:
            self.presets.named_set(section, name, value)
        else:
            all_items = self.named_all(section)
            all_items[str(name)] = value
            self.set(section, all_items)
        if save:
            self.save()

    def named_delete(self, section: str, name: str,
                     save: bool = True) -> bool:
        if self._store_for(section) is self.presets:
            if not self.presets.named_delete(section, name):
                return False
        else:
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
        if key in _UNDO_STATE_KEYS:
            if key == "undo_history":
                return self.undo.history()
            return self.undo.index()
        value = self.session.get(key, _UNSET)
        if value is not _UNSET:
            return value
        # fallback to DEFAULTS state if present
        defaults_state = DEFAULTS.get("state", {})
        if isinstance(defaults_state, dict) and key in defaults_state:
            return copy.deepcopy(defaults_state[key])
        return default

    def set_state(self, save: bool = True, **updates: Any) -> None:
        undo_updates = {k: v for k, v in updates.items()
                        if k in _UNDO_STATE_KEYS}
        session_updates = {k: v for k, v in updates.items()
                           if k not in _UNDO_STATE_KEYS}
        if undo_updates:
            history = undo_updates.get("undo_history",
                                       self.undo.history())
            index = undo_updates.get("undo_history_index",
                                     self.undo.index())
            self.undo.save_state(history, index, save_now=save)
        if session_updates:
            self.session.set(save_now=save, **session_updates)
        if undo_updates and not session_updates:
            return
        # a save was requested for sections that write through the
        # settings store too (e.g. grid_layout also mirrored) — flush
        # everything for callers that expect a whole-file save
        if save:
            self.settings.save()
            self.labels_file.flush()

    # ── validation ───────────────────────────────────────────────
    def validate(self) -> list[str]:
        return self.settings.validate()


def json_dumps(data: Any) -> str:
    import json
    return json.dumps(data, ensure_ascii=False)
