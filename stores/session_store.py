"""Session store — one file (session.json) holding last-session state.

The file is a flat dict (no "state" wrapper); missing keys fall back to
DEFAULT_STATE below.
"""

from __future__ import annotations

import copy
from typing import Any

from core.result import Result
from stores.jsonio import load_json, save_json


DEFAULT_STATE: dict[str, Any] = {
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
}


class SessionStore:
    def __init__(self, path: str = "session.json") -> None:
        self._path = path
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        data = load_json(self._path, {})
        self._data = data if isinstance(data, dict) else {}

    def save(self) -> Result[None]:
        if save_json(self._path, self._data):
            return Result.ok(None)
        return Result.err(f"session save failed: {self._path}")

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._data:
            return copy.deepcopy(self._data[key])
        if key in DEFAULT_STATE:
            return copy.deepcopy(DEFAULT_STATE[key])
        return default

    def set(self, save_now: bool = True, **updates: Any) -> None:
        for k, v in updates.items():
            self._data[k] = v
        if save_now:
            self.save()

    def data(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)
