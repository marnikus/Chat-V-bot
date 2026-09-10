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

#: Top-level keys routed away from the settings store, to the STORE that owns
#: them (the attribute name on `ConfigManager`, which is also the key of
#: `_OWNERS` below). An unlisted section belongs to `settings.json`.
_SECTION_ROUTES = {
    "url_presets": "bookmarks",
    "custom_blocks": "blocks",
    "labels": "labels_file",
    "stack_presets": "presets",
    "template_presets": "presets",
}

_UNSET = object()


# ── section owners ───────────────────────────────────────────────
#
# Every store answers the same three verbs, so the facade dispatches once
# instead of re-deriving "which store is this, and what shape does it keep
# data in" inside `get()` and `set()`. That dispatch used to be a five-branch
# `if/elif` chain in each of them (nesting 14 in `set()`), which is exactly
# where the "a section is a string now" class of bug lived: the chain had to
# know each store's quirks, and adding a section meant editing both.
#
# `read()`/`write()` take the REST of the key path (the section is already
# routed away) and are total: a hostile path degrades to the caller's
# default instead of raising, because these values come out of a file a human
# may have edited.

def _deep_merge(base: dict, overlay: Any) -> dict:
    """`overlay` on top of `base`, dict by dict.

    A non-dict in the overlay wins wholesale — that is how a section that a
    malformed `set()` flattened into a scalar stays visible instead of
    crashing the merge.
    """
    if not isinstance(overlay, dict):
        return overlay
    out = dict(base)
    for key, value in overlay.items():
        current = out.get(key)
        out[key] = (_deep_merge(current, value)
                    if isinstance(current, dict) and isinstance(value, dict)
                    else value)
    return out


def _set_nested(tree: Any, path, value) -> bool:
    """Write `value` at `path` inside `tree`, creating the dicts on the way."""
    node = tree
    for key in path[:-1]:
        if not isinstance(node, dict):
            return False
        if not isinstance(node.get(key), dict):
            node[key] = {}
        node = node[key]
    if not isinstance(node, dict):
        return False
    node[path[-1]] = value
    return True


class _Owner:
    """One store's side of the façade. Subclasses say how their store keeps data."""

    #: the `ConfigManager` attribute holding the store this owner drives
    store_name: str = "settings"

    def __init__(self, manager: "ConfigManager", store_name: str = "settings"):
        self._m = manager
        self.store_name = store_name

    def _store(self):
        return getattr(self._m, self.store_name)

    # ── the three verbs ──────────────────────────────────────────
    def read(self, section: str, rest, default: Any = None) -> Any:
        raise NotImplementedError

    def write(self, section: str, rest, value: Any) -> None:
        raise NotImplementedError

    def snapshot(self, section: str) -> Any:
        raise NotImplementedError

    # ── named access (presets, labels): the generic whole-map form ──
    def named_all(self, section: str) -> dict:
        raw = self.read(section, (), {})
        raw = copy.deepcopy(raw) if isinstance(raw, dict) else {}
        return raw

    def named_get(self, section: str, name: str, default: Any = None) -> Any:
        return self.named_all(section).get(str(name), default)

    def named_set(self, section: str, name: str, value: Any) -> None:
        items = self.named_all(section)
        items[str(name)] = value
        self.write(section, (), items)

    def named_delete(self, section: str, name: str) -> bool:
        items = self.named_all(section)
        if str(name) not in items:
            return False
        del items[str(name)]
        self.write(section, (), items)
        return True


class _SettingsOwner(_Owner):
    """`config/settings.json` — a nested tree with documented defaults.

    Reads go to the store, which walks its own data and falls back to
    `SETTINGS_DEFAULTS` per key; writes must first make sure the path the
    store is about to `setdefault` through is walkable (a scalar standing
    where a dict belongs used to raise `AttributeError` from inside
    `dict.setdefault` and left the section half-written).
    """

    store_name = "settings"

    def read(self, section: str, rest, default: Any = None) -> Any:
        # deliberately NOT copied: `get()` hands out the live node for
        # settings sections, and callers that want a copy use `get_copy()`.
        # (Pinned by test_config_manager_contract's ledger #4 detector.)
        return self._store().get(section, *rest, default=default)

    def write(self, section: str, rest, value: Any) -> None:
        store = self._store()
        self._repair_path(store, (section, *rest))
        store.set(section, *rest, value)

    @staticmethod
    def _repair_path(store, path) -> None:
        node = store.data()
        for depth, key in enumerate(path[:-1]):
            if not isinstance(node, dict) or key not in node:
                return                      # `setdefault` will create it
            node = node[key]
            if not isinstance(node, dict):
                store.set(*path[:depth + 1], {})     # flatten the garbage away
                return

    def snapshot(self, section: str) -> dict:
        """The whole settings tree: every documented section, file wins."""
        return _deep_merge(copy.deepcopy(SETTINGS_DEFAULTS),
                           self._store().data())


class _ListOwner(_Owner):
    """`bookmarks.json` / `blocks.json` — one list per section, nothing inside it."""

    def read(self, section: str, rest, default: Any = None) -> Any:
        if rest:
            return default                    # a list has no keys to walk
        return copy.deepcopy(self._store().all())

    def write(self, section: str, rest, value: Any) -> None:
        # the section IS the list: anything that is not a list is the caller
        # handing us a mistake, and writing `null` into the file is worse
        self._store().set_all(value if isinstance(value, list) else [])

    def snapshot(self, section: str) -> list:
        return self.read(section, (), [])


class _DictOwner(_Owner):
    """`labels.json` — one dict, keyed by the caller."""

    store_name = "labels_file"

    def read(self, section: str, rest, default: Any = None) -> Any:
        node = self._store().data()
        if not rest:
            return copy.deepcopy(node)
        for key in rest:
            if not isinstance(node, dict):
                return default
            node = node.get(key, _UNSET)
            if node is _UNSET:
                return default
        return node

    def write(self, section: str, rest, value: Any) -> None:
        store = self._store()
        if not rest:
            store.set_data(value)
            return
        data = copy.deepcopy(store.data())
        if _set_nested(data, tuple(rest), value):
            store.set_data(data)

    def snapshot(self, section: str) -> dict:
        return self.read(section, (), {})


class _NamedOwner(_Owner):
    """`presets.json` — sections of `{name: payload}`, owned by PresetStore."""

    store_name = "presets"

    def read(self, section: str, rest, default: Any = None) -> Any:
        store = self._store()
        if rest:
            return store.named_get(section, rest[0], default)
        return copy.deepcopy(store.named_all(section))

    def write(self, section: str, rest, value: Any) -> None:
        store = self._store()
        if rest:
            # set(section, name, value) — the name is the first key after the
            # section. (The old chain only accepted a name at `len(rest) == 2`
            # and silently dropped the real value; nothing called it that way.)
            store.named_set(section, rest[0], value)
            return
        if isinstance(value, dict):
            self._replace_all(section, value)

    def _replace_all(self, section: str, value: dict) -> None:
        store = self._store()
        for name in list(store.named_all(section)):
            store.named_delete(section, name)
        for name, item in value.items():
            store.named_set(section, name, item)

    def snapshot(self, section: str) -> dict:
        return self._store().named_all(section)

    # the store keeps named maps itself: use it, do not rebuild them
    def named_all(self, section: str) -> dict:
        return self._store().named_all(section)

    def named_get(self, section: str, name: str, default: Any = None) -> Any:
        return self._store().named_get(section, name, default)

    def named_set(self, section: str, name: str, value: Any) -> None:
        self._store().named_set(section, name, value)

    def named_delete(self, section: str, name: str) -> bool:
        return bool(self._store().named_delete(section, name))


#: route name (a `_SECTION_ROUTES` value) → the owner class that speaks it
_OWNERS: dict[str, type] = {
    "settings": _SettingsOwner,
    "bookmarks": _ListOwner,
    "blocks": _ListOwner,
    "labels_file": _DictOwner,
    "presets": _NamedOwner,
}


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
        self._owners = {name: owner(self, name)
                        for name, owner in _OWNERS.items()}
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
    def _owner_for(self, section: str) -> _Owner:
        """The one place that decides who owns a section."""
        return self._owners[_SECTION_ROUTES.get(section, "settings")]

    def _route_of(self, section: str) -> str:
        return _SECTION_ROUTES.get(section, "settings")

    def _store_for(self, section: str):
        """Legacy name for the routing question: kept because tests and the
        bridge reason about it. It answers with the OWNER now, not the raw
        store, because that is what knows how to read the section."""
        owner = self._owner_for(section)
        return owner._store()

    # ── access ───────────────────────────────────────────────────
    def get(self, *keys: str, default: Any = None) -> Any:
        if not keys:
            return default
        section, rest = keys[0], keys[1:]
        return self._owner_for(section).read(section, rest, default)

    def get_copy(self, *keys: str, default: Any = None) -> Any:
        """Deep copy of the value so callers can mutate it safely."""
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
        """Full JSON-serialisable merged data (for get_app_state etc.).

        Every documented settings section is present even when the file holds
        nothing for it: `get()` serves those defaults, so a view built out of
        the stored keys alone would show a fresh install as an empty app.
        """
        merged = self._owners["settings"].snapshot("settings")
        for section in _SECTION_ROUTES:
            merged[section] = self._owner_for(section).snapshot(section)
        merged["state"] = self.state_data()
        return merged

    def state_data(self) -> dict[str, Any]:
        """The session file over the documented `state` defaults.

        `get_state()` promises a default for every key it knows about, so the
        merged view has to agree with it — a fresh install still has a
        `grid_layout` and a `db_recent`, they are just not in the file yet.
        """
        state = _deep_merge(copy.deepcopy(DEFAULTS.get("state") or {}),
                            self.session.data())
        state["undo_history"] = self.undo.history()
        state["undo_history_index"] = self.undo.index()
        return state

    # ── named sub-stores (presets keyed by name) ─────────────────
    def named_all(self, section: str) -> dict[str, Any]:
        return self._owner_for(section).named_all(section)

    def named_get(self, section: str, name: str, default: Any = None) -> Any:
        return self._owner_for(section).named_get(section, name, default)

    def named_set(self, section: str, name: str, value: Any,
                  save: bool = True) -> None:
        self._owner_for(section).named_set(section, name, value)
        if save:
            self.save()

    def named_delete(self, section: str, name: str,
                     save: bool = True) -> bool:
        ok = self._owner_for(section).named_delete(section, name)
        if ok and save:
            self.save()
        return ok

    # ── last-session state ───────────────────────────────────────
    def get_state(self, key: str, default: Any = None) -> Any:
        if key in _UNDO_STATE_KEYS:
            return (self.undo.history() if key == "undo_history"
                    else self.undo.index())
        value = self.session.get(key, _UNSET)
        if value is not _UNSET:
            return value
        return self._state_default(key, default)

    def _state_default(self, key: str, default: Any) -> Any:
        """The documented `state.*` default, if there is one."""
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
            self.undo.save_state(undo_updates.get("undo_history",
                                                  self.undo.history()),
                                 undo_updates.get("undo_history_index",
                                                  self.undo.index()),
                                 save_now=save)
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
