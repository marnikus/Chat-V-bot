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

import asyncio
import copy
import json
import logging
import os
from typing import Any, Optional

from backend.config_manager import MAX_STACK_HISTORY
from core.events import (EventBus, ArchiveUndoApplied, DbChanged,
                         GridLayoutChanged, LabelsChanged, LogMessage,
                         PeopleChanged, StackLoaded, UndoHistoryChanged,
                         UserDbChanged)
from core.result import Err, Ok, Result
from services.undo.projection import UndoProjection
from services.undo.world_store import UndoWorldStore

from services.status_events import StatusEvents

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
    bus.emit(PeopleChanged(reason="db_switch"))
    bus.emit(UserDbChanged(payload=json.dumps(
        {"action": "db_switch", "ok": True}, ensure_ascii=False)))
    if labels is not None:
        try:
            bus.emit(LabelsChanged(
                payload=json.dumps(labels.state(), ensure_ascii=False)))
        except Exception:                               # noqa: BLE001
            pass
    try:
        bus.emit(LogMessage(message="👤 my nick follows the world", level="debug"))
        from core.events import MyNickChanged
        bus.emit(MyNickChanged(nick=archive.my_nick))
    except Exception:                                   # noqa: BLE001
        pass
    log.info("world %s is live — all world state rebuilt (%s)",
             os.path.basename(archive.db.path), op)

class UndoService(StatusEvents, UndoProjection, UndoWorldStore):
    """The global timeline: push / undo / redo / persist / world sync."""

    HISTORY_LIMIT = MAX_STACK_HISTORY

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

    # ── timeline access ──────────────────────────────────────────
    def history(self) -> tuple[list, int]:
        """The timeline (stack snapshots cleaned) and its pointer."""
        timeline = self._timeline
        if timeline is None:
            history, index = self.migrate_global_history()
            history = copy.deepcopy(history)
        else:
            history, index = copy.deepcopy(timeline), self._h_index
        cleaned = []
        for entry in history:
            if not isinstance(entry, dict):
                continue
            if entry.get("kind") == "stack":
                entry["value"] = self._clean_blocks(entry["value"])
            cleaned.append(entry)
        return cleaned, index

    def set_history(self, history: list, index: int) -> None:
        self._commit_timeline(list(history), index)

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
        branched = index < len(history) - 1
        if branched:
            history = history[:index + 1]
        if 0 <= index < len(history) and \
                _same_entry(history[index], entry):
            if branched:
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
            rows = value.get("after" if forward else "before")
            if rows is None or self._people is None:
                return False
            self._schedule(self._people.apply(rows))
            return True
        if kind == "labels":
            snapshot = value.get("after" if forward else "before")
            if not isinstance(snapshot, dict) or self._labels is None:
                return False
            self._labels.restore(snapshot)
            self._bus.emit(LabelsChanged(
                payload=json.dumps(self._labels.state(),
                                   ensure_ascii=False)))
            # labels can hide people from the queue: the # column changes
            self._bus.emit(PeopleChanged(reason="labels"))
            return True
        if kind == "archive":
            return self._apply_archive_command(value, forward)
        if kind == "dbconn":
            return self._apply_db_command(value, forward)
        return False

    @staticmethod
    def _schedule(coro) -> bool:
        try:
            asyncio.ensure_future(coro)
            return True
        except RuntimeError:
            coro.close()
            return False

    def _apply_archive_command(self, value: dict, forward: bool) -> bool:
        """Re-apply / reverse a message, chat or person deletion (soft)."""
        archive = self._archive
        op = str(value.get("op") or "")
        nick = str(value.get("nick") or "")
        token = str(value.get("token") or "")
        people = value.get("people") if isinstance(value.get("people"),
                                                   dict) else None
        if people is not None and self._people is not None:
            rows = people.get("after" if forward else "before")
            if isinstance(rows, list):
                self._schedule(self._people.apply(rows))
        if archive is None:
            return people is not None

        async def work():
            repo = archive.repo
            if forward:
                if op == "delete_message":
                    await repo.soft_delete_message(
                        nick, int(value.get("message_id") or 0), token=token)
                elif op == "clear_history":
                    await repo.soft_delete_history(nick, token=token)
                elif op == "delete_person":
                    await repo.delete_person(nick, hard=False, token=token)
            else:
                if op == "delete_person":
                    await repo.restore_person(nick, token=token)
                else:
                    await repo.restore_deleted(nick, token)
            self._bus.emit(UserDbChanged(payload=json.dumps(
                {"action": "undo" if not forward else "redo", "op": op,
                 "nick": nick}, ensure_ascii=False)))
            self._bus.emit(ArchiveUndoApplied(forward=forward, op=op,
                                              nick=nick))
        self._schedule(work())
        return True

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
        self._schedule(work())
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
                self._schedule(self._people.apply(rows))
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
            self._log("↩ Undo — " + self.UNDO_LABELS.get(
                kind, kind + " restored"), "info")
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
            self._log("↪ Redo — " + self.UNDO_LABELS.get(
                kind, kind + " restored"), "info")
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
