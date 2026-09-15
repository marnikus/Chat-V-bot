"""Config manager owners — extracted from config_manager (H-C5 split)

_Owner + 4 subclasses, ≤250 LOC.
"""

from __future__ import annotations

import copy
from typing import Any

from backend.config_manager_helpers import _deep_merge, _set_nested
from stores.settings_store import SETTINGS_DEFAULTS

_UNSET = object()


class _Owner:
    store_name: str = "settings"

    def __init__(self, manager: "ConfigManager", store_name: str = "settings"):
        self._m = manager
        self.store_name = store_name

    def _store(self):
        return getattr(self._m, self.store_name)

    def read(self, section: str, rest, default: Any = None) -> Any:
        raise NotImplementedError

    def write(self, section: str, rest, value: Any) -> None:
        raise NotImplementedError

    def snapshot(self, section: str) -> Any:
        raise NotImplementedError

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
    store_name = "settings"

    def read(self, section: str, rest, default: Any = None) -> Any:
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
                return
            node = node[key]
            if not isinstance(node, dict):
                store.set(*path[: depth + 1], {})
                return

    def snapshot(self, section: str) -> dict:
        return _deep_merge(copy.deepcopy(SETTINGS_DEFAULTS), self._store().data())


class _ListOwner(_Owner):
    def read(self, section: str, rest, default: Any = None) -> Any:
        if rest:
            return default
        return copy.deepcopy(self._store().all())

    def write(self, section: str, rest, value: Any) -> None:
        self._store().set_all(value if isinstance(value, list) else [])

    def snapshot(self, section: str) -> list:
        return self.read(section, (), [])


class _DictOwner(_Owner):
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
    store_name = "presets"

    def read(self, section: str, rest, default: Any = None) -> Any:
        store = self._store()
        if rest:
            return store.named_get(section, rest[0], default)
        return copy.deepcopy(store.named_all(section))

    def write(self, section: str, rest, value: Any) -> None:
        store = self._store()
        if rest:
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

    def named_all(self, section: str) -> dict:
        return self._store().named_all(section)

    def named_get(self, section: str, name: str, default: Any = None) -> Any:
        return self._store().named_get(section, name, default)

    def named_set(self, section: str, name: str, value: Any) -> None:
        self._store().named_set(section, name, value)

    def named_delete(self, section: str, name: str) -> bool:
        return bool(self._store().named_delete(section, name))


_OWNERS: dict[str, type] = {
    "settings": _SettingsOwner,
    "bookmarks": _ListOwner,
    "blocks": _ListOwner,
    "labels_file": _DictOwner,
    "presets": _NamedOwner,
}
