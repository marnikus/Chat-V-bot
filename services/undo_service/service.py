"""`UndoService` — the facade over the ONE global undo timeline.

The class owns the vocabulary (which kinds exist, which of them are commands,
which belong to a world, how each is described in the log), the construction
(the dependencies and the four collaborators it delegates to) and the wiring
(`attach`, `_log`). The behaviour lives one responsibility per mixin:

    timeline     entry shape, cleaning, seq, history read/write, migration
    worldsync    the config half + the world table, merged by seq
    recording    `push` — dedupe at the pointer, honour the cap
    projections  the four stack-era compat names (`push_stack` & friends)
    commands     apply a COMMAND kind in either direction, rewind on refusal
    dbconn       the DB Connection ops and the world they announce
    snapshots    `_apply_entry` — walking onto a stack/grid snapshot
    walking      `undo` / `redo` — the pointer moves, the answer is a Result

The mixins are plain classes that own no state and never import this module:
everything they need is on `self` (the dependencies below) or on another mixin
through the MRO, so the facade is the only module that imports them (the
`backend/history_query/` and `bridge/history_bridge/` precedents).

The four collaborators are constructed here and take the service as their
`host`: `UndoProjection` (timeline ⇄ the per-kind views), `UndoWorldStore`
(the world's `undo_history` table), `ArchiveCommands` (the self-verifying
archive task) and `TimelineCommit` (the ONE writer of both halves, and the
spawn point for async work). They call back into `self._config`, `self._bus`,
`self._timeline`, `self._h_index`, `self._seq_next`, `self._next_seq`,
`self._history_entry`, `self.history`, `self._log`, `self._undo_pendings`,
`self._world_store`, `self._archive`, `self._people` and
`self.rewind_after_failure` — all still one object, so that contract is
untouched by the split.

Extracted from `services/undo_service.py` (god-class round, step 7). See
`docs/archive/2026-09-13-god-classes/STEP7_UNDO_SERVICE_DESIGN_2026-09-13.md`.
"""

from __future__ import annotations

from typing import Optional

from core.events import EventBus
from services.service_log import emit_log
from services.undo_archive import ArchiveCommands
from services.undo_support import UndoProjection, UndoWorldStore
from services.undo_timeline import TimelineCommit

from .commands import CommandsMixin
from .dbconn import DbConnMixin
from .projections import ProjectionMixin
from .recording import RecordingMixin
from .snapshots import SnapshotMixin
from .timeline import TimelineMixin
from .walking import UndoRedoMixin
from .worldsync import WorldSyncMixin


class UndoService(TimelineMixin, WorldSyncMixin, RecordingMixin,
                  ProjectionMixin, CommandsMixin, DbConnMixin,
                  SnapshotMixin, UndoRedoMixin):
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

    def __init__(self, config, archive=None, people=None, labels=None,
                 dbs=None, memory=None, engine=None,
                 bus: EventBus | None = None):
        self._config = config
        self._archive = archive
        self._people = people
        self._labels = labels
        self._dbs = dbs
        self._memory = memory
        self._engine = engine
        self._bus = bus or EventBus()
        self._timeline: Optional[list] = None
        self._h_index = -1
        self._seq_next = 1
        self._undo_pendings: list = []
        self._projection = UndoProjection(self._history_entry)
        self._world_store = UndoWorldStore(self)
        self._archive_commands = ArchiveCommands(self)
        self._timeline_commit = TimelineCommit(self)

    # ── wiring (main.py / attach_history) ────────────────────────
    def attach(self, archive=None, people=None, labels=None, dbs=None,
               memory=None, engine=None, bus=None) -> None:
        if archive is not None:
            self._archive = archive
        if people is not None:
            self._people = people
        if labels is not None:
            self._labels = labels
        if dbs is not None:
            self._dbs = dbs
        if memory is not None:
            self._memory = memory
        if engine is not None:
            self._engine = engine
        if bus is not None:
            self._bus = bus

    def _log(self, message: str, level: str = "info") -> None:
        emit_log(self._bus, message, level)
