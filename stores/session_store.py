"""session_store — last-session state restored on startup
(config/session.json).

Keys: last_url_preset, last_stack, last_stack_preset,
block_config_pinned, window_states, window_geometry, db_recent,
my_nick_recent, grid_layout. The legacy read-only keys
(stack_history, grid_layout_history, …) keep their defaults so old
config files load without inventing a second active history.
"""

from __future__ import annotations

import copy
import logging
import os
from typing import Any

from stores.jsonio import load_json, save_json

log = logging.getLogger("chatbot")

#: keys that used to live in the single config.json's "state" section and
#: are deliberately NOT migrated into fresh session files (read-only legacy)
LEGACY_KEYS = ("stack_history", "stack_history_index",
               "grid_layout_history", "grid_layout_history_index")

SESSION_DEFAULTS: dict[str, Any] = {
    "undo_history": [],          # legacy defaults, kept for compat reads
    "undo_history_index": -1,
    "grid_layout_history": [],
    "grid_layout_history_index": -1,
}


class SessionStore:
    """Flat key/value session state. One file, atomic saves."""

    def __init__(self, path: str, data: dict | None = None):
        self._path = path
        self._data: dict[str, Any] = {}
        self._dirty = False
        if data is not None:
            self._data = dict(data)
        else:
            self.load()

    def load(self) -> None:
        raw = load_json(self._path, default={})
        self._data = raw if isinstance(raw, dict) else {}

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
    def get(self, key: str, default: Any = None) -> Any:
        if key in self._data:
            return copy.deepcopy(self._data[key])
        if key in SESSION_DEFAULTS:
            return copy.deepcopy(SESSION_DEFAULTS[key])
        return default

    def set(self, save_now: bool = True, **updates: Any) -> None:
        for key, value in updates.items():
            self._data[key] = copy.deepcopy(value)
        self._dirty = True
        if save_now:
            self.save()

    def data(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)
