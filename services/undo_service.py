"""UndoService — the ONE global undo timeline.

Extracted from the bridge monolith (2026-09-09). Stack edits, grid edits,
people-list edits, label edits, archive deletions and DB-connection
actions all record reversible entries on a single chronological timeline
(capped at MAX_STACK_HISTORY). The timeline is split by ownership:
app-level entries (stack/grid) persist in config/undo.json; world-bound
entries (people/labels/archive/dbconn) persist in the active world's
``undo_history`` table and die with the world.

Qt-free: services and bridges react to UndoHistoryChanged /
UserDbChanged / DbChanged / LabelsChanged / StackLoaded /
GridLayoutChanged / LogMessage events on the EventBus.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from typing import Any, Optional

from backend.config_manager import MAX_STACK_HISTORY
from core.events import (EventBus, DbChanged, GridLayoutChanged,
                         LabelsChanged, LogMessage, PeopleChanged, StackLoaded,
                         UndoHistoryChanged, UserDbChanged)
from core.result import Err, Ok, Result
from services.layout_service import LayoutService  # noqa: F401  API parity
from services.run import normalize_blocks
from services.service_log import emit_log
from services.undo_archive import ArchiveCommands
from services.undo_support import UndoProjection, UndoWorldStore
from services.undo_timeline import TimelineCommit
from services.world_events import announce_world_live

log = logging.getLogger("chatbot")


def _values_equal(a, b) -> bool:
    try:
        return json.dumps(a, sort_keys=True, ensure_ascii=False) == \
               json.dumps(b, sort_keys=True, ensure_ascii=False)
    except Exception:                                   # noqa: BLE001
        return a == b


def _same_entry(a: dict, b: dict) -> bool:
    """Two timeline entries carry the same edit (kind + value).

    ``seq``/timestamps are bookkeeping, not part of the edit identity:
    comparing them made an identical re-push look different (the fresh entry
    has no seq yet) and grew the timeline with duplicates.
    """
    return (isinstance(a, dict) and isinstance(b, dict)
            and a.get("kind") == b.get("kind")
            and _values_equal(a.get("value"), b.get("value")))


def _position_of(history: list, entry: dict) -> int:
    """Where this exact entry sits in the timeline (-1 when it is gone)."""
    for pos, item in enumerate(history):
        if item is entry:
            return pos
    for pos, item in enumerate(history):
        if _same_entry(item, entry):
            return pos
    return -1


def emit_db_change(bus: EventBus, action: str, result) -> None:
    """Format a DbManager result as the db_changed wire payload."""
    payload = dict(result or {})
    payload["action"] = action
    if action in ("create", "load", "delete") and payload.get("ok") \
            and not payload.get("unchanged") and not payload.get("offline"):
        # a different world is live now — every JS window that caches
        # world data must drop it
        payload["switched"] = True
    bus.emit(DbChanged(action=action,
                       payload=json.dumps(payload, ensure_ascii=False)))
    bus.emit(UserDbChanged(payload=json.dumps(
        {"action": "db_" + action, "ok": bool(payload.get("ok"))},
        ensure_ascii=False)))
    if payload.get("error"):
        bus.emit(LogMessage(message="⚠ " + str(payload["error"]),
                            level="warn"))


async def restart_world(memory, archive, labels, undo, bus: EventBus,
                        op: str) -> None:
    """After a world create/load/delete: rebuild every world-bound surface.

    The service already tore the old world down and rebuilt the database
    side (queue connection, labels, radar state, per-world settings);
    here the rest of the app follows via bus events: undo timeline,
    People list, Full User Database, labels and the my-nick readout.
    """
    if archive is None:
        return
    if memory is not None:
        try:
            if os.path.abspath(memory.db_path) != \
                    os.path.abspath(archive.db.path):
                await memory.switch_db(archive.db.path)
        except Exception as exc:                        # noqa: BLE001
            log.warning("queue did not follow the world switch: %s", exc)
    if undo is not None:
        try:
            await undo.sync_world_state()
        except Exception as exc:                        # noqa: BLE001
            log.warning("world undo sync failed: %s", exc)
    announce_world_live(bus, labels, reason="db_switch")
    try:
        bus.emit(LogMessage(message="👤 my nick follows the world", level="debug"))
        from core.events import MyNickChanged
        bus.emit(MyNickChanged(nick=archive.my_nick))
    except Exception:                                   # noqa: BLE001
        pass
    log.info("world %s is live — all world state rebuilt (%s)",
             os.path.basename(archive.db.path), op)


def _apply_people_command(host, value: dict, forward: bool) -> bool:
    """Restore / re-apply the people-list snapshot the entry carries."""
    rows = value.get("after" if forward else "before")
    if rows is None or host._people is None:
        return False
    host._timeline_commit.spawn("people restore", host._people.apply(rows))
    return True


def _apply_labels_command(host, value: dict, forward: bool) -> bool:
    """Restore / re-apply the label snapshot the entry carries."""
    snapshot = value.get("after" if forward else "before")
    if not isinstance(snapshot, dict) or host._labels is None:
        return False
    host._labels.restore(snapshot)
    host._bus.emit(LabelsChanged(
        payload=json.dumps(host._labels.state(), ensure_ascii=False)))
    # labels can hide people from the queue: the # column changes
    host._bus.emit(PeopleChanged(reason="labels"))
    return True


def _log_command(host, entry: dict, forward: bool) -> None:
    """Announce a command entry; archive ones report themselves later,
    with the database state they actually produced."""
    kind = entry.get("kind")
    if kind == "archive":
        return
    host._log(f"{'↪ Redo' if forward else '↩ Undo'} — "
              + host.UNDO_LABELS.get(kind, kind + " restored"), "info")


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

    def _migrated_entry(self, source: dict, kind: str, value) -> dict:
        """Rebuild a stored timeline entry, PRESERVING its seq.

        seq is the identity used to merge the app-level config half with the
        active world's ``undo_history`` table on startup. Dropping it (as a
        plain rebuild did) pushed every app entry ahead of the world entries
        in the merged timeline and could issue duplicate seqs — the global
        undo order was wrong after a restart.
        """
        entry = self._history_entry(kind, value)
        seq = source.get("seq")
        if isinstance(seq, int) and seq > 0:
            entry["seq"] = seq
        return entry

    # ── seq ──────────────────────────────────────────────────────
    def _next_seq(self) -> int:
        next_seq = self._seq_next
        self._seq_next = next_seq + 1
        return next_seq

    # ── legacy migration ─────────────────────────────────────────
    def migrate_global_history(self) -> tuple[list, int]:
        """Build the global timeline from pre-global-history config once."""
        raw = self._config.get_state("undo_history", None)
        if isinstance(raw, list) and raw:
            return self._projection.from_raw_history(self._config, raw)
        history, index, canonical = self._projection.from_legacy_config(
            self._config)
        if canonical is not None:
            self._config.set_state(grid_layout=canonical)
        self._config.set_state(undo_history=copy.deepcopy(history),
                               undo_history_index=index)
        return history, index

    # ── timeline access ──────────────────────────────────────────
    def history(self) -> tuple[list, int]:
        """The timeline (stack snapshots cleaned) and its pointer."""
        timeline = self._timeline
        if timeline is None:
            history, index = self.migrate_global_history()
            history = copy.deepcopy(history)
        else:
            history, index = copy.deepcopy(timeline), self._h_index
        return self._projection.clean(history), index

    def set_history(self, history: list, index: int) -> None:
        self._timeline_commit.commit(list(history), index)

    def _schedule_world_undo_save(self, entries: list) -> None:
        """Persist the world half, tracking the task for a later
        `sync_world_state` can wait for it."""
        self._world_store.schedule_save(entries)

    async def sync_world_state(self) -> Result[None]:
        """Rebuild the unified timeline from both stores after a world
        change (startup or switch): config's app-level half + the active
        world's `undo_history` table, merged by `seq`."""
        await self._world_store.settle()
        world_entries: list[dict] = await self._world_store.load()
        service = self._archive
        app_entries: list[dict] = []
        raw = self._config.get_state("undo_history", None)
        if isinstance(raw, list):
            for entry in raw:
                if not (isinstance(entry, dict)
                        and isinstance(entry.get("kind"), str)):
                    continue
                if service is not None and \
                        entry.get("kind") in self.WORLD_UNDO_KINDS:
                    continue             # the world table is the truth
                app_entries.append(copy.deepcopy(entry))
        merged = app_entries + world_entries
        merged.sort(key=lambda e: (isinstance(e.get("seq"), int)
                                   and e["seq"] > 0,
                                   e.get("seq") if isinstance(e.get("seq"),
                                                              int) else 0))
        self._timeline_commit.commit(merged, len(merged) - 1,
                                      purge_dropped=False)
        self._bus.emit(UndoHistoryChanged())
        return Ok(None)

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

    # ── compat projections (older integrations and tests) ────────
    def stack_projection(self) -> tuple[list, int]:
        """Compatibility projection of stack entries."""
        history, global_index = self.history()
        return self._projection.stack_projection(history, global_index)

    def set_stack_projection(self, history: list, index: int,
                             save: bool = True) -> None:
        entries = [self._history_entry("stack", self._clean_blocks(value))
                   for value in history if isinstance(value, list)]
        self.set_history(entries,
                         max(-1, min(index, len(entries) - 1)))

    def kind_projection(self, kind: str) -> tuple[list, int]:
        history, global_index = self.history()
        return self._projection.kind_projection(history, global_index, kind)

    def push_stack(self, blocks: list) -> tuple[list, int]:
        """Backward-compatible: append the stack to global history."""
        if isinstance(blocks, list):
            self.push("stack", self._clean_blocks(blocks))
        return self.stack_projection()

    # ── command application (undo/redo of COMMAND kinds) ─────────
    def apply_command(self, entry, forward: bool) -> bool:
        """Apply one command entry forward (redo) or backward (undo)."""
        kind = entry.get("kind")
        value = entry.get("value")
        if not isinstance(value, dict):
            return False
        if kind == "people":
            return _apply_people_command(self, value, forward)
        if kind == "labels":
            return _apply_labels_command(self, value, forward)
        if kind == "archive":
            return self._apply_archive_command(value, forward, entry)
        if kind == "dbconn":
            return self._apply_db_command(value, forward)
        return False

    def _apply_archive_command(self, value: dict, forward: bool,
                               entry: Optional[dict] = None) -> bool:
        """Reverse / re-apply a message, chat or person deletion (soft).

        The work is ONE self-verifying task (`services/undo_archive.py`):
        it applies the command, reads the database back, reports what the
        rows now show — and, when it cannot, says so and leaves the entry
        where Ctrl+Z finds it again. Announcing success from the *intent* is
        what let a locked database keep a person deleted while the log said
        “archive restored” (bug 2026-09-11).
        """
        if str(value.get("op") or "") not in ArchiveCommands.OPS:
            return False
        if self._archive is None and self._people is None:
            return False
        return self._timeline_commit.spawn("archive undo",
                           self._archive_commands.run(entry, value, forward))

    def rewind_after_failure(self, entry: Optional[dict],
                             forward: bool) -> None:
        """A command that could not be applied stays where Ctrl+Z finds it.

        A failed undo puts the pointer back ON the entry and a failed redo
        puts it back IN FRONT of it, so the next key press tries the same
        command again instead of skipping a state the database never reached.
        """
        if not isinstance(entry, dict):
            return
        history, index = self.history()
        at = _position_of(history, entry)
        if at < 0:
            return
        target = max(0, min(at - 1 if forward else at, len(history) - 1))
        if target != index:
            self.set_history(history, target)
            self._bus.emit(UndoHistoryChanged())

    def _apply_db_command(self, value: dict, forward: bool) -> bool:
        """Re-apply / reverse a DB Connection action (legacy entries)."""
        op = str(value.get("op") or "")
        path = str(value.get("path") or "")
        before_path = str(value.get("before_path") or "")
        backup = str(value.get("backup") or "")
        manager = self._dbs

        async def work():
            if op == "delete":
                if forward:
                    if os.path.exists(path):
                        result = await manager.delete(path)
                    else:
                        self._log("⚠ Nothing to re-delete — the file is "
                                  "already gone", "warn")
                        return
                else:
                    if os.path.exists(backup):
                        result = await manager.restore_backup(backup, path)
                    else:
                        self._log("⚠ Database deletions are permanent — "
                                  "no backup exists to restore", "warn")
                        return
                if result.get("ok"):
                    await restart_world(self._memory, self._archive,
                                        self._labels, self, self._bus,
                                        "delete")
                emit_db_change(self._bus, "delete", result)
                return
            if forward:
                if op in ("create", "load"):
                    result = await manager.load(path, create=(op == "create"))
                elif op == "clean":
                    result = await manager.clean()
                else:
                    return
            else:
                if op in ("create", "load"):
                    result = await manager.load(before_path)
                elif op == "clean":
                    result = await manager.restore_backup(backup, path)
                else:
                    return
            if op in ("create", "load") and result.get("ok") \
                    and not result.get("unchanged"):
                await restart_world(self._memory, self._archive,
                                    self._labels, self, self._bus, op)
            emit_db_change(self._bus, op, result)
        self._timeline_commit.spawn("db command", work())
        return True

    # ── apply one entry's state (walk onto a snapshot entry) ──────
    def _apply_entry(self, entry) -> None:
        """Apply the state a history entry represents."""
        kind = entry.get("kind")
        if kind in ("labels", "archive", "dbconn"):
            self.apply_command(entry, forward=True)
            return
        if kind == "grid":
            self._config.set_state(grid_layout=entry["value"])
            self._bus.emit(GridLayoutChanged(payload=entry["value"]))
        elif kind == "people":
            value = entry.get("value")
            rows = value.get("after") if isinstance(value, dict) else None
            if rows is not None and self._people is not None:
                self._timeline_commit.spawn(
                    "people restore", self._people.apply(rows))
        else:
            blocks = self._clean_blocks(entry["value"])
            self._config.set_state(last_stack=blocks, last_stack_preset="")
            engine = self._engine
            if engine is not None:
                engine.load_stack(blocks)
            self._bus.emit(StackLoaded(
                name="", payload=json.dumps(blocks, ensure_ascii=False)))
            # Undo/redo of a stack edit can change the enabled Scroll &
            # Parse presence — re-rank the people list's # column.
            self._bus.emit(PeopleChanged(reason="stack"))

    # ── undo / redo ──────────────────────────────────────────────
    def undo(self) -> Result[Optional[dict]]:
        """Undo one step; Ok(entry payload) | Err('nothing_to_undo')."""
        history, index = self.history()
        if not history or index < 0 or index >= len(history):
            return Err("nothing_to_undo", "the timeline is at its start")
        entry = history[index]
        if entry.get("kind") in self.COMMAND_KINDS:
            if not self.apply_command(entry, forward=False):
                return Err("nothing_to_undo",
                           f"cannot reverse {entry.get('kind')}")
            index -= 1
            self.set_history(history, index)
            self._bus.emit(UndoHistoryChanged())
            kind = entry["kind"]
            _log_command(self, entry, forward=False)
            value = entry.get("value") or {}
            payload = (value.get("before")
                       if kind in ("people", "labels") else value)
            return Ok({"kind": kind, "value": payload, "index": index})
        if index <= 0:
            return Err("nothing_to_undo", "nothing before the first entry")
        index -= 1
        self.set_history(history, index)
        self._bus.emit(UndoHistoryChanged())
        entry = history[index]
        self._apply_entry(entry)
        self._log("↩ Undo — restored " + entry["kind"], "info")
        return Ok({"kind": entry["kind"], "value": entry["value"],
                   "index": index})

    def redo(self) -> Result[Optional[dict]]:
        history, index = self.history()
        if not history or index >= len(history) - 1:
            return Err("nothing_to_redo", "the timeline is at its tip")
        index += 1
        entry = history[index]
        if entry.get("kind") in self.COMMAND_KINDS:
            if not self.apply_command(entry, forward=True):
                return Err("nothing_to_redo",
                           f"cannot re-apply {entry.get('kind')}")
            self.set_history(history, index)
            self._bus.emit(UndoHistoryChanged())
            kind = entry["kind"]
            _log_command(self, entry, forward=True)
            value = entry.get("value") or {}
            payload = (value.get("after")
                       if kind in ("people", "labels") else value)
            return Ok({"kind": kind, "value": payload, "index": index})
        self.set_history(history, index)
        self._bus.emit(UndoHistoryChanged())
        self._apply_entry(entry)
        self._log("↪ Redo — restored " + entry["kind"], "info")
        return Ok({"kind": entry["kind"], "value": entry["value"],
                   "index": index})
