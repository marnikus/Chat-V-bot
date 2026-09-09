"""Undo store — global undo history (state.undo_history + index)."""

from __future__ import annotations

import copy
from typing import Any

from core.result import Result, ok, err
from stores.atomic import AtomicJsonStore

MAX_STACK_HISTORY = 100


class UndoStore:
    def __init__(self, atomic: AtomicJsonStore | None = None, path: str = "config.json") -> None:
        self._atomic = atomic or AtomicJsonStore(path)

    def get(self) -> tuple[list[Any], int]:
        hist = self._atomic.get("state", "undo_history", default=[])
        idx = self._atomic.get("state", "undo_history_index", default=-1)
        if not isinstance(hist, list):
            hist = []
        if not isinstance(idx, int):
            idx = len(hist) - 1
        hist = copy.deepcopy(hist)
        return hist, int(idx)

    def set(self, history: list[Any], index: int) -> Result[None]:
        # enforce cap
        if len(history) > MAX_STACK_HISTORY:
            overflow = len(history) - MAX_STACK_HISTORY
            history = history[overflow:]
            index = max(-1, index - overflow)
        # never persist an (history, index) pair no reader can use
        index = max(-1, min(int(index), len(history) - 1))
        # atomic set of both keys in one save
        state = self._atomic.get("state", default={})
        if not isinstance(state, dict):
            state = {}
        else:
            state = copy.deepcopy(state)
        state["undo_history"] = copy.deepcopy(history)
        state["undo_history_index"] = int(index)
        self._atomic.set("state", state)
        return self._atomic.save()

    def push(self, kind: str, value: Any) -> Result[tuple[list[Any], int]]:
        hist, idx = self.get()
        entry = {"kind": kind, "value": copy.deepcopy(value)}
        if idx < len(hist) - 1:
            hist = hist[: idx + 1]
        hist.append(entry)
        idx = len(hist) - 1
        res = self.set(hist, idx)
        if res.is_ok:
            return ok((hist, idx))
        return err(res.detail or res.code or "save failed")
