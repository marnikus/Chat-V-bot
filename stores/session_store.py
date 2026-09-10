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

    def __init__(self, path: Any | None = None,
                 data: dict | None = None):
        # Accept AtomicJsonStore or plain path for test compat:
        #   SessionStore(AtomicJsonStore(path))   → use store's _path
        #   SessionStore("/tmp/session.json")     → use string directly
        #   SessionStore(path="/tmp/session.json") → keyword path
        from stores.atomic import AtomicJsonStore as _AJS  # local to avoid cycle
        if isinstance(path, _AJS):
            self._path = path._path
        elif isinstance(path, str) and path:
            self._path = path
        else:
            self._path = "config.json" if not isinstance(path, str) else path
            if not self._path:
                self._path = "config.json"
        # handle legacy positional data when path is actually data dict
        if isinstance(path, dict) and data is None:
            data = path  # type: ignore
            self._path = "config.json"
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

    def set(self, save_now: bool = True, save: bool | None = None, **updates: Any) -> None:
        # alias: tests call set(save=False, ...) while signature is save_now
        if save is not None:
            save_now = save
        # also handle save_now passed as part of updates when called as set(save=False, ...)
        # (Python would have put it in updates if caller used keyword `save`)
        # but we already handled `save` alias above; for `save_now` alias both names work
        if "save_now" in updates:
            save_now = updates.pop("save_now")  # type: ignore
        if "save" in updates:
            save_now = updates.pop("save")  # type: ignore
        for key, value in updates.items():
            self._data[key] = copy.deepcopy(value)
        self._dirty = True
        if save_now:
            self.save()

    def data(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)
