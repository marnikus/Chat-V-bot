"""The five section owners the config facade dispatches to.

`ConfigManager` (backend/config_manager.py) keeps the historical public API
and answers "which store owns this section"; this module answers the other
half — "what SHAPE does that store keep its data in". Every store replies to
the same three verbs, so the facade dispatches once through an `_Owner`
instead of re-deriving each store's quirks inside `get()` and `set()`.

These classes are private and never reach back into `ConfigManager`: an owner
receives the manager only to read the already-constructed store attribute off
it, which is why they can live in their own module. Split out in Round H
(step H4), when config_manager.py stood at 509 lines.

`read()`/`write()` take the REST of the key path (the section is already
routed away) and are total: a hostile path degrades to the caller's default
instead of raising, because these values come out of a file a human may have
edited.
"""

from __future__ import annotations

import copy
from typing import Any

from stores.settings_store import SETTINGS_DEFAULTS

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
