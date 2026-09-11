"""Atomic CRUD store for named portable window-grid presets."""

from __future__ import annotations

import copy
import os
from typing import Any, Optional

from stores.atomic import AtomicJsonStore
from stores.json_store import JsonFileStore


class WindowPresetStore(JsonFileStore):
    """Own ``config/window_presets.json`` and nothing else."""

    DEFAULT_FILE = os.path.join("config", "window_presets.json")
    DEFAULTS: dict[str, Any] = {"window_presets": {}}
    _by_path: dict[str, "WindowPresetStore"] = {}

    def __new__(cls, config: Any = None, path: Optional[str] = None):
        if path:
            raw_path = path
        elif isinstance(config, (str, os.PathLike)):
            raw_path = os.fspath(config)
        elif getattr(config, "path", None):
            raw_path = config.path
        elif getattr(config, "_path", None):
            raw_path = os.path.join(os.path.dirname(os.path.abspath(config._path)),
                                    "config", "window_presets.json")
        else:
            raw_path = cls.DEFAULT_FILE
        key = os.path.abspath(raw_path)
        cached = cls._by_path.get(key)
        if cached is not None:
            return cached
        instance = super().__new__(cls)
        instance._cache_key = key
        cls._by_path[key] = instance
        return instance

    def __init__(self, config: Any = None, path: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        if isinstance(config, (AtomicJsonStore, JsonFileStore)) and path is None:
            super().__init__(config)
            return
        target = path or config or self.DEFAULT_FILE
        if getattr(target, "path", None):
            target = target.path
        elif not isinstance(target, (str, os.PathLike)):
            target = os.path.join(os.path.dirname(os.fspath(config._path)),
                                  "config", "window_presets.json")
        super().__init__(None, os.fspath(target))

    def _coerce(self, raw: Any) -> dict[str, Any]:
        data = copy.deepcopy(raw) if isinstance(raw, dict) else {}
        entries = data.get("window_presets")
        data["window_presets"] = entries if isinstance(entries, dict) else {}
        return data

    def save_preset(self, name: str, document: dict) -> None:
        self._data["window_presets"][str(name)] = copy.deepcopy(document)
        self._touch()

    def load_preset(self, name: str) -> Optional[dict]:
        document = self._data["window_presets"].get(str(name))
        return copy.deepcopy(document) if isinstance(document, dict) else None

    def list_presets(self) -> list[dict[str, Any]]:
        result = []
        for name, document in self._data["window_presets"].items():
            if not isinstance(document, dict):
                continue
            grid = document.get("grid")
            result.append({
                "name": name,
                "window_count": grid.get("window_count", 0)
                if isinstance(grid, dict) else 0,
                "updated_at": document.get("updated_at", ""),
                "app_version": document.get("app_version", ""),
            })
        result.sort(key=lambda item: (item["updated_at"], item["name"]),
                   reverse=True)
        return result

    def delete_preset(self, name: str) -> bool:
        key = str(name)
        if key not in self._data["window_presets"]:
            return False
        del self._data["window_presets"][key]
        self._touch()
        return True
