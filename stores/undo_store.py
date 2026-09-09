"""undo_store — the app-level half of the global undo timeline
(config/undo.json).

The timeline itself (push, truncation, pointer movement, command
application) is service logic and lives in services/undo_service. This
store is pure I/O: it persists {"history": [...], "index": N} atomically,
which also makes it the one file that must never be written non-atomically
— a torn undo.json would lose a user's last edits on a crash.
"""

from __future__ import annotations

import copy
import logging
import os
from typing import Any

from stores.jsonio import load_json, save_json

log = logging.getLogger("chatbot")


class UndoStore:
    """{"history": [...], "index": N} — one file, atomic saves."""

    def __init__(self, path: str, data: dict | None = None):
        self._path = path
        self._data: dict[str, Any] = {"history": [], "index": -1}
        self._dirty = False
        if data is not None:
            self._data = dict(data)
        else:
            self.reload()

    # ── persistence ──────────────────────────────────────────────
    def reload(self) -> None:
        raw = load_json(self._path, default={})
        if isinstance(raw, dict):
            history = raw.get("history")
            index = raw.get("index", -1)
            self._data = {
                "history": history if isinstance(history, list) else [],
                "index": index if isinstance(index, int) else -1,
            }

    def flush(self) -> bool:
        """Write the current state to disk (atomic)."""
        if not self._dirty:
            return True
        ok = save_json(self._path, self._data)
        if ok:
            self._dirty = False
        return ok

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def path(self) -> str:
        return self._path

    # ── API ──────────────────────────────────────────────────────
    def history(self) -> list[dict]:
        return copy.deepcopy(self._data["history"])

    def index(self) -> int:
        return int(self._data["index"])

    def load_state(self) -> tuple[list[dict], int]:
        return self.history(), self.index()

    def save_state(self, history: list, index: int,
                   save_now: bool = True) -> None:
        if not isinstance(history, list):
            history = []
        index = int(index)
        if history:
            index = max(-1, min(index, len(history) - 1))
        else:
            index = -1
        self._data = {"history": copy.deepcopy(history), "index": index}
        self._dirty = True
        if save_now:
            self.flush()
