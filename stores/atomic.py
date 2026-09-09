"""Atomic JSON store — base for all stores (write .tmp, rename)."""

from __future__ import annotations

import json
import os
import copy
import logging
from typing import Any

from core.result import Result

log = logging.getLogger("chatbot")


class AtomicJsonStore:
    """Lowest layer: load / atomic save of a JSON file."""

    def __init__(self, path: str = "config.json") -> None:
        self._path = path
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> dict[str, Any]:
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                log.info("Store loaded %s", self._path)
            except (json.JSONDecodeError, OSError) as exc:  # noqa: BLE001
                log.warning("Store load failed (%s), using empty", exc)
                self._data = {}
        else:
            self._data = {}
        return copy.deepcopy(self._data)

    def save(self) -> Result[None]:
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
            log.info("Store saved %s", self._path)
            return Result.ok(None)
        except (OSError, TypeError, ValueError) as exc:  # noqa: BLE001
            # TypeError/ValueError: unserialisable in-memory data. A Result,
            # not a raise — and the previous good file is untouched (the
            # dump failed before os.replace).
            log.error("Store save failed: %s", exc)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return Result.err(str(exc))

    # generic nested access helpers
    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self._data
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return default
        return node

    def get_copy(self, *keys: str, default: Any = None) -> Any:
        return copy.deepcopy(self.get(*keys, default=default))

    def set(self, *keys_and_value: Any) -> None:
        if len(keys_and_value) < 2:
            raise ValueError("set() needs at least a key and a value")
        *keys, value = keys_and_value
        node = self._data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value

    def data(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)
