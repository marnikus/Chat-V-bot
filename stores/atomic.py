"""Atomic JSON store — the file handle under every config store.

One file, one writer: `load()` reads from disk, `save()` writes a `.tmp`,
fsyncs it and renames, so a crash can never leave a half-written config.

AREA B1 (docs/REFACTOR_2026-09-09_AREA_B_DESIGN.md §1.1) added the two
things every caller kept re-implementing:

  * it accepts **a path or another `AtomicJsonStore`** — the same coercion a
    store does, so `AtomicJsonStore(store.path)` and `AtomicJsonStore(store)`
    address one file (a passed-in store is re-read from disk on purpose:
    the file, not the object, is the contract);
  * `dirty` / `replace()` — "is there unsaved work?" and "take over the whole
    payload", which `JsonFileStore` needs to write through a borrowed handle.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from typing import Any

from core.result import Result, err, ok

log = logging.getLogger("chatbot")


def _coerce_path(value: Any, default: str = "config.json") -> str:
    """The path behind `value`: a path, a store, an atomic or nothing.

    Every `stores/` constructor takes "an `AtomicJsonStore` **or** a path", and
    this is the single place that turns the first into the second.
    """
    if value is None or value == "":
        return default
    for attribute in ("path", "_path"):            # atomic or store instance
        found = getattr(value, attribute, None)
        if isinstance(found, str) and found:
            return found
    if isinstance(value, (str, os.PathLike)):
        return os.fspath(value)
    raise TypeError(
        f"expected a path or an AtomicJsonStore, got {type(value).__name__}")


class AtomicJsonStore:
    """Lowest layer: load / atomic save of one JSON file."""

    def __init__(self, path: "str | os.PathLike | AtomicJsonStore"
                 = "config.json") -> None:
        self._path = _coerce_path(path)
        self._data: dict[str, Any] = {}
        self._dirty = False
        self.load()

    # ── what it points at, and whether it holds unsaved work ─────
    @property
    def path(self) -> str:
        return self._path

    @property
    def dirty(self) -> bool:
        """True once something changed in memory that the file has not seen."""
        return self._dirty

    # ── lifecycle ────────────────────────────────────────────────
    def load(self) -> dict[str, Any]:
        """Read the file. A missing or corrupt file is an empty payload."""
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                self._data = data if isinstance(data, dict) else {}
                log.info("Store loaded %s", self._path)
            except (json.JSONDecodeError, OSError) as exc:  # noqa: BLE001
                log.warning("Store load failed (%s), using empty", exc)
                self._data = {}
        else:
            self._data = {}
        self._dirty = False
        return copy.deepcopy(self._data)

    def save(self) -> Result[None]:
        """Write the payload atomically. A failure never touches the old file.

        Returns a `Result` (not a bool): this layer reports *why* a write
        failed, and the stores above it decide what that means for their
        caller.
        """
        tmp = self._path + ".tmp"
        try:
            parent = os.path.dirname(os.path.abspath(self._path))
            if parent:
                os.makedirs(parent, exist_ok=True)      # same try on purpose:
                # a config dir the app has not made yet is a write that should
                # simply work (ATM-08), and a failure must still come back as
                # an `err`, not as an exception through `ConfigManager.save()`
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
            self._dirty = False
            log.info("Store saved %s", self._path)
            return ok(None)
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
            return err(str(exc))

    # ── reads ────────────────────────────────────────────────────
    def data(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    def get(self, *keys: str, default: Any = None) -> Any:
        """Walk nested keys without copying anything."""
        node: Any = self._data
        for key in keys:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                return default
        return node

    def get_copy(self, *keys: str, default: Any = None) -> Any:
        return copy.deepcopy(self.get(*keys, default=default))

    # ── writes (memory only; `save()` persists) ──────────────────
    def set(self, *keys_and_value: Any) -> None:
        if len(keys_and_value) < 2:
            raise ValueError("set() needs at least a key and a value")
        *keys, value = keys_and_value
        node = self._data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value
        self._dirty = True

    def replace(self, data: Any) -> None:
        """Take over the whole payload (the store's `save()` uses this)."""
        self._data = copy.deepcopy(data) if isinstance(data, dict) else {}
        self._dirty = True
