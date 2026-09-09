"""Session store — last-session state (state.*)."""

from __future__ import annotations

import copy
from typing import Any

from core.result import Result
from stores.atomic import AtomicJsonStore


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
    def __init__(self, atomic: AtomicJsonStore | None = None, path: str = "config.json") -> None:
        self._atomic = atomic or AtomicJsonStore(path)

    def get(self, key: str, default: Any = None) -> Any:
        state = self._atomic.get("state", default={})
        if not isinstance(state, dict):
            return default
        if key in state:
            return copy.deepcopy(state[key])
        if key in DEFAULT_STATE:
            return copy.deepcopy(DEFAULT_STATE[key])
        return default

    def set(self, save: bool = True, **updates: Any) -> Result[None]:
        state = self._atomic.get("state", default={})
        if not isinstance(state, dict):
            state = {}
        else:
            state = copy.deepcopy(state)
        for k, v in updates.items():
            state[k] = v
        self._atomic.set("state", state)
        if save:
            return self._atomic.save()
        return Result.ok(None)

    def data(self) -> dict[str, Any]:
        raw = self._atomic.get("state", default={})
        return copy.deepcopy(raw) if isinstance(raw, dict) else {}
