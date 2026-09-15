"""UndoService — the ONE global undo timeline.

Extracted from the bridge monolith (2026-09-09). Stack edits, grid edits,
people-list edits, label edits, archive deletions and DB-connection
actions all record reversible entries on a single chronological timeline
(capped at MAX_STACK_HISTORY). The timeline is split by ownership:
app-level entries (stack/grid) persist in config/undo.json; world-bound
entries (people/labels/archive/dbconn) persist in the active world's
``undo_history`` table and die with the world.

Round F step F3 split the 418-LOC class into a facade plus four
collaborators, following the convention ``tests/unit/stores/
test_stores_structure.py`` pins for ``stores/``: a part takes ``owner`` and
nothing else, and every attribute stays on the aggregate.

    services/undo_history.py  HistoryProjection  the timeline and its projections
    services/undo_apply.py    ApplyCommand       undo / redo / apply one entry
    services/undo_db.py       DbCommands         reversing a DB-connection entry
    services/undo_world.py    WorldSync          rebuilding after a world change

This file keeps what must stay here: ``push`` (its only consumer of
``MAX_STACK_HISTORY``, which ``tests/test_world_write_gate.py`` monkeypatches
as ``undo_service.MAX_STACK_HISTORY``), the normalization helpers, and the
re-exports ``bridge/db_bridge.py``, ``bridge/router.py`` and the tests import
from this module — ``emit_db_change``, ``restart_world`` and ``_values_equal``.
Every other name is still on the class as a one-line delegator, so no caller
and no instance-level patch is affected.

Qt-free: services and bridges react to UndoHistoryChanged /
UserDbChanged / DbChanged / LabelsChanged / StackLoaded /
GridLayoutChanged / LogMessage events on the EventBus.
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
# `_same_entry` is used by push below; `_values_equal` is re-exported because
# bridge/router.py imports it from here (a boundary smell recorded as F3b).
from services.undo_apply import (ApplyCommand, _same_entry, _values_equal)
from services.undo_archive import ArchiveCommands
from services.undo_db import DbCommands
from services.undo_history import HistoryProjection
from services.undo_support import UndoProjection, UndoWorldStore
from services.undo_timeline import TimelineCommit
# WorldSync is used in __init__; emit_db_change and restart_world moved to
# services/undo_world.py and are re-exported for bridge/db_bridge.py,
# tests/unit/services/test_world_events.py and test_bridge_results.py, which
# patch `restart_world` on the db_bridge module namespace.
from services.undo_world import WorldSync, emit_db_change, restart_world
from services.wiring_requests import UndoDeps  # noqa: F401  (re-exported)

__all__ = ["UndoService", "emit_db_change", "restart_world", "_values_equal",
           "LayoutService"]


class UndoService:
    """The global timeline: push / undo / redo / persist / world sync."""

    #: Entries that are reversible COMMANDS ({before, after} or an op
    #: description) rather than full state snapshots.
    COMMAND_KINDS = ("people", "labels", "archive", "dbconn")
    #: how each command kind is described in the log line
    UNDO_LABELS = {"people": "people list restored",
                   "labels": "labels restored",
                   "archive": "archive restored",
                   "dbconn": "database restored"}
    HISTORY_KINDS = ("stack", "grid") + COMMAND_KINDS
    #: undo kinds whose data belongs to a WORLD (a database file)
    WORLD_UNDO_KINDS = ("people", "labels", "archive", "dbconn")

    def __init__(self, config, deps: UndoDeps | None = None):
        deps = deps or UndoDeps()   # world collaborators as one value (G4)
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
        # Built last: nothing above calls a delegated method.
        self._history = HistoryProjection(self)
        self._apply = ApplyCommand(self)
        self._db_commands = DbCommands(self)
        self._world = WorldSync(self)

    # ── wiring (main.py / attach_history) ────────────────────────
    def attach(self, deps: UndoDeps) -> None:
        """Re-wire: only the deps fields that are set replace the current."""
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

    # ── normalization ────────────────────────────────────────────
    @staticmethod
    def _clean_blocks(blocks):
        """Strip retired block keys from stack snapshots (safety net)."""
        return normalize_blocks(blocks)

    @classmethod
    def _clean_history(cls, hist):
        if not isinstance(hist, list):
            return []
        return [cls._clean_blocks(entry) for entry in hist
                if isinstance(entry, list)]

    @staticmethod
    def _history_entry(kind, value):
        return {"kind": kind, "value": copy.deepcopy(value)}

    # ── push ─────────────────────────────────────────────────────
    def push(self, kind: str, value) -> Result[tuple]:
        """Append one entry; returns (history, index) on success.

        Re-committing the value already at the pointer is a no-op (grid /
        stack autosaves must not grow the timeline), and committing anything
        after an undo first truncates the redo branch — including the
        same-value case, so a stale tail cannot survive a re-commit.
        """
        if kind not in self.HISTORY_KINDS:
            return Err("unknown_kind", f"unknown history kind: {kind}")
        history, index = self.history()
        entry = self._history_entry(kind, value)
        if index < len(history) - 1:
            history = history[:index + 1]
        if 0 <= index < len(history) and \
                _same_entry(history[index], entry):
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

    # ── delegators: services/undo_history.py ─────────────────────
    def history(self) -> tuple[list, int]:
        return self._history.history()

    def set_history(self, history: list, index: int) -> None:
        return self._history.set_history(history, index)

    def migrate_global_history(self) -> tuple[list, int]:
        return self._history.migrate_global_history()

    def _migrated_entry(self, source: dict, kind: str, value) -> dict:
        return self._history._migrated_entry(source, kind, value)

    def _next_seq(self) -> int:
        return self._history._next_seq()

    def stack_projection(self) -> tuple[list, int]:
        return self._history.stack_projection()

    def set_stack_projection(self, history: list, index: int,
                             save: bool = True) -> None:
        return self._history.set_stack_projection(history, index, save)

    def kind_projection(self, kind: str) -> tuple[list, int]:
        return self._history.kind_projection(kind)

    def push_stack(self, blocks: list) -> tuple[list, int]:
        return self._history.push_stack(blocks)

    # ── delegators: services/undo_apply.py ───────────────────────
    def apply_command(self, entry, forward: bool) -> bool:
        return self._apply.apply_command(entry, forward)

    def _apply_archive_command(self, value: dict, forward: bool,
                               entry: Optional[dict] = None) -> bool:
        return self._apply._apply_archive_command(value, forward, entry)

    def _apply_entry(self, entry) -> None:
        return self._apply._apply_entry(entry)

    def rewind_after_failure(self, entry: Optional[dict],
                             forward: bool) -> None:
        return self._apply.rewind_after_failure(entry, forward)

    def undo(self) -> Result[Optional[dict]]:
        return self._apply.undo()

    def redo(self) -> Result[Optional[dict]]:
        return self._apply.redo()

    # ── delegators: services/undo_db.py ──────────────────────────
    async def _db_delete_op(self, value: dict, forward: bool) -> dict | None:
        return await self._db_commands._db_delete_op(value, forward)

    async def _db_op_forward(self, op: str, path: str) -> dict | None:
        return await self._db_commands._db_op_forward(op, path)

    async def _db_switch_op(self, value: dict, forward: bool) -> dict | None:
        return await self._db_commands._db_switch_op(value, forward)

    def _apply_db_command(self, value: dict, forward: bool) -> bool:
        return self._db_commands._apply_db_command(value, forward)

    # ── delegators: services/undo_world.py ───────────────────────
    def _schedule_world_undo_save(self, entries: list) -> None:
        return self._world._schedule_world_undo_save(entries)

    async def sync_world_state(self) -> Result[None]:
        return await self._world.sync_world_state()
