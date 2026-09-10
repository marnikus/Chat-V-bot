"""Undo store — global undo history (config/undo.json).

Owns exactly one file whose shape is ``{"history": [...], "index": N}`` —
the app-level half of the ONE global undo timeline. (The world-bound half
— people/labels/archive/dbconn — lives in the active world's
``undo_history`` table, not here.) ``migration.py`` writes this same flat
shape when it splits a legacy single-file install, so a migrated install
and a fresh install agree on disk.

Every write clamps the pointer into ``[-1, len-1]`` and caps the timeline
at ``MAX_STACK_HISTORY`` (oldest entries dropped first) so an inconsistent
``(history, index)`` pair can never reach disk. The persistence cycle —
``path`` / ``dirty`` / ``load`` / ``reload`` / ``save`` / ``flush`` /
``data`` — is ``JsonFileStore``'s; this file owns the timeline and its
invariants (``history()`` / ``index()`` / ``get()`` are the same payload the
file holds, projected for ``ConfigManager``).
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from core.result import Result, err, ok
from stores.json_store import JsonFileStore

log = logging.getLogger("chatbot")

MAX_STACK_HISTORY = 100

#: the on-disk shape, and the payload of a store whose file does not exist
UNDO_DEFAULTS: dict[str, Any] = {"history": [], "index": -1}


class UndoStore(JsonFileStore):
    """Global undo timeline persistence (config/undo.json)."""

    DEFAULT_FILE = "config.json"
    DEFAULTS: dict[str, Any] = UNDO_DEFAULTS

    # ── normalisation ────────────────────────────────────────────
    def _coerce(self, raw: Any) -> dict[str, Any]:
        """Keep only the two documented keys, in a shape that cannot lie."""
        if not isinstance(raw, dict):
            data = copy.deepcopy(UNDO_DEFAULTS)
        else:
            history = raw.get("history")
            index = raw.get("index")
            data = {
                "history": copy.deepcopy(history)
                if isinstance(history, list) else [],
                "index": int(index) if isinstance(index, int) else -1,
            }
        self._clamp(data)
        return data

    @staticmethod
    def _clamp(data: dict[str, Any]) -> None:
        """In-place: cap the timeline, then pull the pointer inside it."""
        history = data.get("history")
        if not isinstance(history, list):
            history = []
        if len(history) > MAX_STACK_HISTORY:
            overflow = len(history) - MAX_STACK_HISTORY
            history = history[overflow:]
            if isinstance(data.get("index"), int):
                data["index"] -= overflow
        data["history"] = history
        index = data.get("index")
        if not history:
            index = -1
        elif not isinstance(index, int):
            index = len(history) - 1
        elif index >= len(history):
            index = len(history) - 1
        elif index < 0:
            index = -1
        data["index"] = max(-1, int(index))

    # ── reads (ConfigManager convenience surface) ────────────────
    def history(self) -> list[Any]:
        hist = self._data.get("history")
        return copy.deepcopy(hist) if isinstance(hist, list) else []

    def index(self) -> int:
        idx = self._data.get("index")
        return idx if isinstance(idx, int) else -1

    def get(self) -> tuple[list[Any], int]:
        """The ``(history, index)`` pair, the way `ConfigManager` reads it."""
        return self.history(), self.index()

    # ── writes ───────────────────────────────────────────────────
    def set(self, history: list[Any], index: int) -> Result[None]:
        """Replace the timeline and persist it at once (the facade's `set`)."""
        self._write(history, index)
        return ok(None) if self.save() else err("save failed")

    def save_state(self, history: list[Any], index: int,
                   save_now: bool = True) -> Result[None]:
        """Replace the timeline; persist it unless the caller is batching."""
        self._write(history, index)
        if save_now:
            return ok(None) if self.save() else err("save failed")
        return ok(None)

    def push(self, kind: str, value: Any) -> Result[tuple[list[Any], int]]:
        """Append one entry (dropping the redo tail) and persist it."""
        hist, idx = self.history(), self.index()
        entry: dict[str, Any] = {"kind": kind, "value": copy.deepcopy(value)}
        if idx < len(hist) - 1:
            hist = hist[:idx + 1]          # undo then act: drop the redo tail
        hist.append(entry)
        idx = len(hist) - 1
        res = self.set(hist, idx)
        if res.is_ok:
            return ok((hist, idx))
        return err(res.detail or res.code or "save failed")

    def _write(self, history: list[Any], index: int) -> None:
        """Store a clamped timeline in memory and mark it unsaved."""
        data = {
            "history": copy.deepcopy(history) if isinstance(history, list)
            else [],
            "index": index if isinstance(index, int) else -1,
        }
        self._clamp(data)
        self._data = data
        self._dirty = True
