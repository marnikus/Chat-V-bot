"""Block store — one file (blocks.json) holding custom blocks.

The file is a bare list of {"name", "block", "updated_at"} entries.
Named stack/template presets live in PresetStore, not here.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from core.result import Result
from stores.jsonio import load_json, save_json


class BlockStore:
    """Custom Find & Click block presets. Autosave-only: every mutation
    persists immediately (the facade never calls load/save on blocks)."""

    def __init__(self, path: str = "blocks.json") -> None:
        self._path = path
        self._data: list[dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        data = load_json(self._path, None)
        self._data = list(data) if isinstance(data, list) else []

    def save(self) -> Result[None]:
        if save_json(self._path, self._data):
            return Result.ok(None)
        return Result.err(f"blocks save failed: {self._path}")

    def all(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._data)

    def save_block(self, name: str, block: dict[str, Any]) -> bool:
        if not isinstance(name, str):
            raise TypeError(f"name must be a str, got {type(name).__name__}")
        if not isinstance(block, dict):
            raise TypeError(
                f"block must be a dict, got {type(block).__name__}")
        name = name.strip()
        if not name:
            return False
        entry = {"name": name, "block": copy.deepcopy(block),
                 "updated_at": datetime.now().isoformat(timespec="seconds")}
        for i, existing in enumerate(self._data):
            if isinstance(existing, dict) and existing.get("name") == name:
                self._data[i] = entry
                break
        else:
            self._data.append(entry)
        save_json(self._path, self._data)
        return True

    def delete(self, name: str) -> bool:
        if not isinstance(name, str):
            raise TypeError(f"name must be a str, got {type(name).__name__}")
        name = name.strip()
        for i, existing in enumerate(self._data):
            if isinstance(existing, dict) and existing.get("name") == name:
                del self._data[i]
                save_json(self._path, self._data)
                return True
        return False

    def set_all(self, blocks: list[dict[str, Any]]) -> bool:
        if not isinstance(blocks, list):
            raise TypeError(
                f"blocks must be a list, got {type(blocks).__name__}")
        self._data = copy.deepcopy(blocks)
        save_json(self._path, self._data)
        return True
