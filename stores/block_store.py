"""block_store — reusable custom Find & Click block presets
(config/blocks.json). Each item: {name, block, updated_at}."""

from __future__ import annotations

import copy
import logging
import os
from datetime import datetime

from stores.jsonio import load_json, save_json

log = logging.getLogger("chatbot")


class BlockStore:
    """One file, atomic saves, name-keyed list."""

    def __init__(self, path: str, data: list | None = None):
        self._path = path
        self._dirty = False
        if data is not None:
            self._data = list(data)
        else:
            self.load()

    def load(self) -> None:
        raw = load_json(self._path, default=[])
        self._data = ([item for item in raw if isinstance(item, dict)]
                      if isinstance(raw, list) else [])

    def save(self, force: bool = False) -> bool:
        if not (self._dirty or force):
            return True
        ok = save_json(self._path, self._data)
        if ok:
            self._dirty = False
        return ok

    @property
    def dirty(self) -> bool:
        return self._dirty

    # ── API ──────────────────────────────────────────────────────
    def all(self) -> list[dict]:
        return copy.deepcopy(self._data)

    def by_name(self, name: str) -> dict | None:
        for item in self._data:
            if item.get("name") == name:
                return copy.deepcopy(item)
        return None

    def save_block(self, name: str, block: dict) -> bool:
        """Insert or update by name. False on an empty name."""
        name = str(name or "").strip()
        if not name or not isinstance(block, dict):
            return False
        kept = [item for item in self._data if item.get("name") != name]
        kept.append({"name": name, "block": copy.deepcopy(block),
                     "updated_at": datetime.now().isoformat(
                         timespec="seconds")})
        self._data = kept
        self._dirty = True
        return True

    # (the bridge's historical method names)
    set = save_block

    def delete(self, name: str) -> bool:
        before = len(self._data)
        self._data = [item for item in self._data if item.get("name") != name]
        if len(self._data) == before:
            return False
        self._dirty = True
        return True

    def set_all(self, items: list) -> None:
        self._data = [item for item in items or []
                      if isinstance(item, dict)]
        self._dirty = True
