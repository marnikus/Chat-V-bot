"""Undo store — one file (undo.json) holding {"history", "index"}."""

from __future__ import annotations

import copy
from typing import Any

from core.result import Result
from stores.jsonio import load_json, save_json

MAX_STACK_HISTORY = 100


class UndoStore:
    def __init__(self, path: str = "undo.json") -> None:
        self._path = path
        self._data: dict[str, Any] = {"history": [], "index": -1}
        self.load()

    # ── lifecycle ──────────────────────────────────────────────
    def load(self) -> None:
        data = load_json(self._path, None)
        if not isinstance(data, dict):
            data = {}
        self._assign(data.get("history", []), data.get("index", -1))

    def reload(self) -> None:
        self.load()

    def save(self) -> Result[None]:
        if save_json(self._path, self._data):
            return Result.ok(None)
        return Result.err(f"undo save failed: {self._path}")

    def flush(self) -> Result[None]:
        return self.save()

    # ── reads ──────────────────────────────────────────────────
    def get(self) -> tuple[list[Any], int]:
        hist = self._data.get("history", [])
        idx = self._data.get("index", -1)
        if not isinstance(hist, list):
            hist = []
        if not isinstance(idx, int):
            idx = len(hist) - 1
        return copy.deepcopy(hist), int(idx)

    def load_state(self) -> tuple[list[Any], int]:
        return self.get()

    def history(self) -> list[Any]:
        hist, _idx = self.get()
        return hist

    def index(self) -> int:
        _hist, idx = self.get()
        return idx

    # ── writes ─────────────────────────────────────────────────
    def _assign(self, history: Any, index: Any) -> None:
        """Normalize + store in memory (no disk write)."""
        if not isinstance(history, list):
            history = []
        if not isinstance(index, int):
            index = len(history) - 1
        if len(history) > MAX_STACK_HISTORY:
            overflow = len(history) - MAX_STACK_HISTORY
            history = history[overflow:]
            index = max(-1, index - overflow)
        # never hold an (history, index) pair no reader can use
        index = max(-1, min(int(index), len(history) - 1))
        self._data = {"history": copy.deepcopy(history),
                      "index": int(index)}

    def set(self, history: list[Any], index: int) -> Result[None]:
        self._assign(history, index)
        return self.save()

    def save_state(self, history: list[Any], index: int,
                   save_now: bool = True) -> Result[None]:
        self._assign(history, index)
        if save_now:
            return self.save()
        return Result.ok(None)

    def push(self, kind: str, value: Any) -> Result[tuple[list[Any], int]]:
        hist, idx = self.get()
        entry = {"kind": kind, "value": copy.deepcopy(value)}
        if idx < len(hist) - 1:
            hist = hist[: idx + 1]
        hist.append(entry)
        idx = len(hist) - 1
        res = self.set(hist, idx)
        if res.is_ok:
            return Result.ok((hist, idx))
        return Result.err(res.error or "save failed")
