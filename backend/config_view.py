"""The merged view: whole-tree reads and the last-session state surface.

Part of the `config_*` family (facade: `backend/config_manager.py`, Round J
step J-3). `ConfigView` is the base class the facade inherits, and it holds
exactly the methods that are *about the view* rather than about one section:

* `data()` — every documented section merged over its store, so a fresh
  install is not an empty app;
* `to_dict()` — the same tree as JSON, for `get_app_state` and the log dump;
* `state_data()` / `get_state()` / `set_state()` — the session file over the
  documented `state` defaults, with the undo timeline split out to its own
  store (`UNDO_STATE_KEYS`).

Why a base class and not five more methods on the facade: those five are part
of the public API the snapshot pins to `backend.config_manager` (a method that
moved up into a base is still the same callable with the same signature — the
dumper models that case explicitly), and they are what keeps
`ConfigManager`'s own body to the section-level verbs. The rows of RULE 18.2
count what a class *declares*; this file is where the declared view lives.
"""

from __future__ import annotations

import copy
from typing import Any

from backend.config_defaults import (
    DEFAULTS, SECTION_ROUTES, UNDO_STATE_KEYS, UNSET, deep_merge, json_dumps,
)
from backend import config_owners as owners


def state_default(key: str, default: Any) -> Any:
    """The documented `state.*` default, if there is one."""
    defaults_state = DEFAULTS.get("state", {})
    if isinstance(defaults_state, dict) and key in defaults_state:
        return copy.deepcopy(defaults_state[key])
    return default


class ConfigView:
    """The whole-tree read and the last-session state, over the owners."""

    # ── merged data ──────────────────────────────────────────────
    def data(self) -> dict[str, Any]:
        """Full JSON-serialisable merged data (for get_app_state etc.).

        Every documented settings section is present even when the file holds
        nothing for it: `get()` serves those defaults, so a view built out of
        the stored keys alone would show a fresh install as an empty app.
        """
        merged = self._owners["settings"].snapshot("settings")
        for section in SECTION_ROUTES:
            merged[section] = owners.owner_for(self, section).snapshot(section)
        merged["state"] = self.state_data()
        return merged

    def to_dict(self) -> str:
        """`data()` as JSON."""
        return json_dumps(self.data())

    def state_data(self) -> dict[str, Any]:
        """The session file over the documented `state` defaults.

        `get_state()` promises a default for every key it knows about, so the
        merged view has to agree with it — a fresh install still has a
        `grid_layout` and a `db_recent`, they are just not in the file yet.
        """
        state = deep_merge(copy.deepcopy(DEFAULTS.get("state") or {}),
                           self.session.data())
        state["undo_history"] = self.undo.history()
        state["undo_history_index"] = self.undo.index()
        return state

    # ── last-session state ───────────────────────────────────────
    def get_state(self, key: str, default: Any = None) -> Any:
        """One `state.*` value: the undo keys from their store, the rest from
        the session file, and the documented default when neither has it."""
        if key in UNDO_STATE_KEYS:
            return (self.undo.history() if key == "undo_history"
                    else self.undo.index())
        value = self.session.get(key, UNSET)
        if value is not UNSET:
            return value
        return state_default(key, default)

    def set_state(self, save: bool = True, **updates: Any) -> None:
        """Write `state.*` values, splitting the undo keys off to their store."""
        undo_updates = {k: v for k, v in updates.items()
                        if k in UNDO_STATE_KEYS}
        session_updates = {k: v for k, v in updates.items()
                           if k not in UNDO_STATE_KEYS}
        if undo_updates:
            self.undo.save_state(undo_updates.get("undo_history",
                                                  self.undo.history()),
                                 undo_updates.get("undo_history_index",
                                                  self.undo.index()),
                                 save_now=save)
        if session_updates:
            self.session.set(save_now=save, **session_updates)
        if undo_updates and not session_updates:
            return
        # a save was requested for sections that write through the
        # settings store too (e.g. grid_layout also mirrored) — flush
        # everything for callers that expect a whole-file save
        if save:
            self.settings.save()
            self.labels_file.flush()
