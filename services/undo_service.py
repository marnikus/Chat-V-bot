"""UndoService — the ONE global undo timeline.

Extracted from the bridge monolith (2026-09-09). Stack edits, grid edits,
people-list edits, label edits, archive deletions and DB-connection
actions all record reversible entries on a single chronological timeline
(capped at MAX_STACK_HISTORY). The timeline is split by ownership:
app-level entries (stack/grid) persist in config/undo.json; world-bound
entries (people/labels/archive/dbconn) persist in the active world's
``undo_history`` table and die with the world.

Round H step H-C2: cut direct methods from 28 → 6 by moving delegators
into four focused mixins (undo_*_delegates.py). UndoService now inherits
from those mixins, so method-count (direct) ≤15 while public surface
unchanged. LCOM drops from 0.95.

Design: docs/archive/2026-09-14-round-h/AREA_C_SERVICES_STORES_DESIGN_2026-09-14.md H-C2
"""

from __future__ import annotations

import copy
from typing import Optional

from backend.config_manager import MAX_STACK_HISTORY
from core.events import EventBus, UndoHistoryChanged
from core.result import Err, Ok, Result
from services.layout_service import LayoutService  # noqa: F401  API parity
from services.run import normalize_blocks
from services.service_log import emit_log
from services.undo_apply import ApplyCommand, _same_entry, _values_equal
from services.undo_apply_delegates import UndoApplyDelegates
from services.undo_archive import ArchiveCommands
from services.undo_db import DbCommands
from services.undo_db_delegates import UndoDbDelegates
from services.undo_history import HistoryProjection
from services.undo_history_delegates import UndoHistoryDelegates
from services.undo_support import UndoProjection, UndoWorldStore
from services.undo_timeline import TimelineCommit
from services.undo_world import WorldSync, emit_db_change, restart_world
from services.undo_world_delegates import UndoWorldDelegates
from services.wiring_requests import UndoDeps  # noqa: F401  (re-exported)

__all__ = ["UndoService", "emit_db_change", "restart_world", "_values_equal", "LayoutService"]


class UndoService(
    UndoHistoryDelegates, UndoApplyDelegates, UndoDbDelegates, UndoWorldDelegates
):
    """The global timeline: push / undo / redo / persist / world sync."""

    COMMAND_KINDS = ("people", "labels", "archive", "dbconn")
    UNDO_LABELS = {
        "people": "people list restored",
        "labels": "labels restored",
        "archive": "archive restored",
        "dbconn": "database restored",
    }
    HISTORY_KINDS = ("stack", "grid") + COMMAND_KINDS
    WORLD_UNDO_KINDS = ("people", "labels", "archive", "dbconn")

    def __init__(self, config, deps: UndoDeps | None = None):
        deps = deps or UndoDeps()
        self._config = config
        self._archive = deps.archive
        self._people = deps.people
        self._labels = deps.labels
        self._dbs = deps.dbs
        self._memory = deps.memory
        self._engine = deps.engine
        self._bus = deps.bus or EventBus()
        self._timeline: Optional[list] = None
        self._h_index = -1
        self._seq_next = 1
        self._undo_pendings: list = []
        self._projection = UndoProjection(self._history_entry)
        self._world_store = UndoWorldStore(self)
        self._archive_commands = ArchiveCommands(self)
        self._timeline_commit = TimelineCommit(self)
        self._history = HistoryProjection(self)
        self._apply = ApplyCommand(self)
        self._db_commands = DbCommands(self)
        self._world = WorldSync(self)

    def attach(self, deps: UndoDeps) -> None:
        if deps.archive is not None:
            self._archive = deps.archive
        if deps.people is not None:
            self._people = deps.people
        if deps.labels is not None:
            self._labels = deps.labels
        if deps.dbs is not None:
            self._dbs = deps.dbs
        if deps.memory is not None:
            self._memory = deps.memory
        if deps.engine is not None:
            self._engine = deps.engine
        if deps.bus is not None:
            self._bus = deps.bus

    def _log(self, message: str, level: str = "info") -> None:
        emit_log(self._bus, message, level)

    @staticmethod
    def _clean_blocks(blocks):
        return normalize_blocks(blocks)

    @classmethod
    def _clean_history(cls, hist):
        if not isinstance(hist, list):
            return []
        return [cls._clean_blocks(entry) for entry in hist if isinstance(entry, list)]

    @staticmethod
    def _history_entry(kind, value):
        return {"kind": kind, "value": copy.deepcopy(value)}

    def push(self, kind: str, value) -> Result[tuple]:
        if kind not in self.HISTORY_KINDS:
            return Err("unknown_kind", f"unknown history kind: {kind}")
        history, index = self.history()
        entry = self._history_entry(kind, value)
        if index < len(history) - 1:
            history = history[: index + 1]
        if 0 <= index < len(history) and _same_entry(history[index], entry):
            if index < len(history) - 1:
                self.set_history(history, index)
                self._bus.emit(UndoHistoryChanged())
            return Ok((history, index))
        entry["seq"] = self._next_seq()
        history.append(entry)
        index = len(history) - 1
        if len(history) > MAX_STACK_HISTORY:
            overflow = len(history) - MAX_STACK_HISTORY
            history = history[overflow:]
            index -= overflow
        self.set_history(history, index)
        self._bus.emit(UndoHistoryChanged())
        return Ok((history, index))
