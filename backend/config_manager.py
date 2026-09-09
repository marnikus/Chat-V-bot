"""Facade over the new stores/ — preserves old ConfigManager API (atomic saves).

New code should import from stores.* directly; this module remains for
backward compatibility until all call-sites are migrated (tests still import it).
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

from stores.atomic import AtomicJsonStore
from stores.migration import migrate

log = logging.getLogger("chatbot")

# Re-export defaults & constant for callers that imported them
from stores.settings_store import DEFAULTS  # noqa: F401
from stores.undo_store import MAX_STACK_HISTORY  # noqa: F401


class ConfigManager:
    """Compatibility façade delegating to a single AtomicJsonStore.

    Internally the new stores (settings/bookmark/block/session/undo) each
    wrap the same AtomicJsonStore instance; this class keeps the old
    method signatures working while the refactor moves call-sites one by one.
    """

    def __init__(self, path: str = "config.json") -> None:
        self._path = path
        # run idempotent migration of legacy file shape
        try:
            migrate(path)
        except Exception as exc:  # noqa: BLE001
            log.debug("migration skipped: %s", exc)
        self._store = AtomicJsonStore(path)
        self._data = self._store._data  # alias for direct access compat

    # persistence (atomic via store)
    def load(self) -> None:
        self._store.load()
        self._data = self._store._data

    def save(self) -> None:
        self._store._data = self._data
        self._store.save()

    # access (mirrors old behaviour including DEFAULTS fallback)
    def get(self, *keys: str, default: Any = None) -> Any:
        node = self._data
        for key in keys:
            if isinstance(node, dict):
                node = node.get(key, _UNSET)
            else:
                return default
            if node is _UNSET:
                node2: Any = DEFAULTS
                for k in keys:
                    node2 = node2.get(k, default) if isinstance(node2, dict) else default
                    if node2 is default:
                        return default
                return copy.deepcopy(node2) if isinstance(node2, (dict, list)) else node2
        return node

    def get_copy(self, *keys: str, default: Any = None) -> Any:
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
        return copy.deepcopy(self._data)

    # named sub-stores
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

    # last-session state
    def get_state(self, key: str, default: Any = None) -> Any:
        state = self.get("state", default={})
        if not isinstance(state, dict):
            return default
        if key in state:
            return copy.deepcopy(state[key])
        defaults_state = DEFAULTS.get("state", {})
        if isinstance(defaults_state, dict) and key in defaults_state:
            return copy.deepcopy(defaults_state[key])
        return default

    def set_state(self, save: bool = True, **updates: Any) -> None:
        state = self.get_copy("state", default={})
        if not isinstance(state, dict):
            state = {}
        for k, v in updates.items():
            state[k] = v
        self.set("state", state)
        if save:
            self.save()

    def validate(self) -> list[str]:
        errors: list[str] = []
        port = self.get("chrome", "port", default=9222)
        try:
            if not (1 <= int(port) <= 65535):
                errors.append(f"chrome.port invalid: {port}")
        except (TypeError, ValueError):
            errors.append(f"chrome.port invalid: {port}")
        return errors


_UNSET = object()
