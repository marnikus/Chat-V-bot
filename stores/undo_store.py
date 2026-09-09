"""Undo store — global undo history (config/undo.json).

Owns exactly one file whose shape is ``{"history": [...], "index": N}`` —
the app-level half of the ONE global undo timeline. (The world-bound half
— people/labels/archive/dbconn — lives in the active world's
``undo_history`` table, not here.) ``migration.py`` writes this same flat
shape when it splits a legacy single-file install, so a migrated install
and a fresh install agree on disk.

`ConfigManager` is the facade that routes every undo read/write to this
store. Beyond the small-store API pinned in docs/STORES_TEST_DESIGN
(get/set/push), it therefore exposes the convenience surface the facade
relies on: ``history()`` / ``index()`` (last-read list + pointer),
``save_state(history, index, save_now)`` (atomic write of both), plus
``reload()`` / ``flush()`` / ``save()`` for the shared load/save cycle.

Every write clamps the pointer into ``[-1, len-1]`` and caps the timeline
at ``MAX_STACK_HISTORY`` (oldest entries dropped first) so an inconsistent
``(history, index)`` pair can never reach disk.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from core.result import Result, ok, err
from stores.atomic import AtomicJsonStore
from stores.jsonio import load_json, save_json

log = logging.getLogger("chatbot")

MAX_STACK_HISTORY = 100


class UndoStore:
    """Global undo timeline persistence (config/undo.json)."""

    def __init__(self, atomic: AtomicJsonStore | None = None,
                 path: str = "config.json") -> None:
        # ConfigManager passes a *path* positionally; the small-store tests
        # pass an *AtomicJsonStore*. Accept either.
        if isinstance(atomic, AtomicJsonStore):
            self._path = atomic._path
        else:
            self._path = atomic if isinstance(atomic, str) and atomic \
                else path
        self._data: dict[str, Any] = {"history": [], "index": -1}
        self._dirty = False
        self.reload()

    @property
    def path(self) -> str:
        return self._path

    @property
    def dirty(self) -> bool:
        return self._dirty

    # ── persistence ──────────────────────────────────────────────
    def reload(self) -> None:
        raw = load_json(self._path, default=None)
        if not isinstance(raw, dict):
            self._data = {"history": [], "index": -1}
        else:
            history = raw.get("history")
            index = raw.get("index")
            self._data = {
                "history": copy.deepcopy(history)
                if isinstance(history, list) else [],
                "index": int(index) if isinstance(index, int) else -1,
            }
            self._clamp()
        self._dirty = False

    def flush(self) -> bool:
        if not self._dirty:
            return True
        return self.save()

    def save(self) -> bool:
        self._clamp()
        ok_written = save_json(self._path, copy.deepcopy(self._data))
        if ok_written:
            self._dirty = False
        return ok_written

    # ── normalisation ────────────────────────────────────────────
    def _clamp(self) -> None:
        history = self._data.get("history")
        if not isinstance(history, list):
            history = []
        if len(history) > MAX_STACK_HISTORY:
            overflow = len(history) - MAX_STACK_HISTORY
            history = history[overflow:]
            if isinstance(self._data.get("index"), int):
                self._data["index"] -= overflow
        self._data["history"] = history
        index = self._data.get("index")
        if not history:
            index = -1
        elif not isinstance(index, int):
            index = len(history) - 1
        elif index >= len(history):
            index = len(history) - 1
        elif index < 0:
            index = -1
        self._data["index"] = max(-1, int(index))

    # ── reads (ConfigManager convenience surface) ────────────────
    def history(self) -> list[Any]:
        hist = self._data.get("history")
        return copy.deepcopy(hist) if isinstance(hist, list) else []

    def index(self) -> int:
        idx = self._data.get("index")
        return idx if isinstance(idx, int) else -1

    def get(self) -> tuple[list[Any], int]:
        return self.history(), self.index()

    # ── writes ───────────────────────────────────────────────────
    def set(self, history: list[Any], index: int) -> Result[None]:
        self._data["history"] = copy.deepcopy(
            history) if isinstance(history, list) else []
        self._data["index"] = index if isinstance(index, int) else -1
        if self.save():
            return ok(None)
        return err("save failed")

    def save_state(self, history: list[Any], index: int,
                   save_now: bool = True) -> Result[None]:
        self._data["history"] = copy.deepcopy(
            history) if isinstance(history, list) else []
        self._data["index"] = index if isinstance(index, int) else -1
        self._dirty = True
        if save_now:
            if self.save():
                return ok(None)
            return err("save failed")
        return ok(None)

    def push(self, kind: str, value: Any) -> Result[tuple[list[Any], int]]:
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
