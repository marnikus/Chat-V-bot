"""session_store — last-session state restored on startup
(config/session.json).

Keys: last_url_preset, last_stack, last_stack_preset,
block_config_pinned, window_states, window_geometry, db_recent,
my_nick_recent, grid_layout. The legacy read-only keys
(stack_history, grid_layout_history, …) keep their defaults so old
config files load without inventing a second active history.

The lifecycle (`path`/`dirty`/`load`/`reload`/`save`/`flush`/`data`) is
`JsonFileStore`'s; this file owns only the flat key/value view.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from stores.json_store import JsonFileStore

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


class SessionStore(JsonFileStore):
    """Flat key/value session state. One file, atomic saves."""

    DEFAULT_FILE = "config.json"
    DEFAULTS: dict[str, Any] = {}

    # ── reads ────────────────────────────────────────────────────
    def get(self, key: str, default: Any = None) -> Any:
        if key in self._data:
            return copy.deepcopy(self._data[key])
        if key in SESSION_DEFAULTS:
            return copy.deepcopy(SESSION_DEFAULTS[key])
        return default

    # ── writes ───────────────────────────────────────────────────
    def set(self, save: "bool | None" = None, save_now: "bool | None" = None,
            **updates: Any) -> None:
        """Merge `updates` into the session, then persist unless told not to.

        `save` is the spelling `core/interfaces.py:SessionStoreProto`
        documents; `save_now` is the one `ConfigManager.set_state` has always
        used. They are the same switch — `save` wins when both are given — and
        neither is ever stored as a session key.
        """
        for key, value in updates.items():
            self._data[key] = copy.deepcopy(value)
        self._touch()
        if self._wants_save(save, save_now):
            self.save()
