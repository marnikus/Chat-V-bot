"""Applying one timeline entry: the undo/redo half of UndoService.

Two kinds of entry live on the ONE timeline and are applied differently:

* **snapshots** (stack, grid) — the entry carries the state to restore, so
  applying it means writing that state back and announcing it;
* **commands** (people, labels, archive, dbconn) — the entry carries
  `{before, after}` or an op description, so applying it means running the
  reverse (or forward) operation, which for archive deletions is a
  self-verifying task rather than a promise.

`undo()` / `redo()` walk the pointer and dispatch on the kind; a command that
cannot be applied leaves the pointer where Ctrl+Z finds it again
(`rewind_after_failure`) instead of skipping a state the database never
reached.

The module-level helpers here are pure (entry identity, position lookup) or
take the owner explicitly, and `services/undo_service.py` re-exports
`_values_equal` because `bridge/router.py` imports it from there.

Imports point one way: this module imports `core` and `services.undo_archive`
only, never `services.undo_service`.
"""

from __future__ import annotations

import json
from typing import Optional

from core.events import (GridLayoutChanged, LabelsChanged, PeopleChanged,
                         StackLoaded, UndoHistoryChanged)
from core.result import Err, Ok, Result
from services.undo_archive import ArchiveCommands


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
    """Announce a command entry — except the two that verify themselves.

    `archive` and `dbconn` report later, from the state the database actually
    ended up in: `services/undo_archive.py::_report` and
    `services/undo_db.py::_announce`. Announcing here instead is the bug of
    2026-09-11 — the timeline moves and the log says "restored" before the work
    has run, so a refusal reads to the user as a success.
    """
    kind = entry.get("kind")
    if kind in ("archive", "dbconn"):
        return
    host._log(f"{'↪ Redo' if forward else '↩ Undo'} — "
              + host.UNDO_LABELS.get(kind, kind + " restored"), "info")


class ApplyCommand:
    """Walk the timeline: undo, redo, and apply the entry landed on."""

    def __init__(self, owner):
        self._o = owner

    # ── command application (undo/redo of COMMAND kinds) ─────────
    def apply_command(self, entry, forward: bool) -> bool:
        """Apply one command entry forward (redo) or backward (undo)."""
        kind, value = entry.get("kind"), entry.get("value")
        if not isinstance(value, dict):
            return False
        if kind == "people":
            return _apply_people_command(self._o, value, forward)
        if kind == "labels":
            return _apply_labels_command(self._o, value, forward)
        if kind == "archive":
            return self._o._apply_archive_command(value, forward, entry)
        if kind == "dbconn":
            return self._o._apply_db_command(value, forward)
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
        if self._o._archive is None and self._o._people is None:
            return False
        return self._o._timeline_commit.spawn(
            "archive undo",
            self._o._archive_commands.run(entry, value, forward))

    def rewind_after_failure(self, entry: Optional[dict],
                             forward: bool) -> None:
        """A command that could not be applied stays where Ctrl+Z finds it.

        A failed undo puts the pointer back ON the entry and a failed redo
        puts it back IN FRONT of it, so the next key press tries the same
        command again instead of skipping a state the database never reached.
        """
        if not isinstance(entry, dict):
            return
        history, index = self._o.history()
        at = _position_of(history, entry)
        if at < 0:
            return
        target = max(0, min(at - 1 if forward else at, len(history) - 1))
        if target != index:
            self._o.set_history(history, target)
            self._o._bus.emit(UndoHistoryChanged())

    # ── apply one entry's state (walk onto a snapshot entry) ──────
    def _apply_entry(self, entry) -> None:
        """Apply the state a history entry represents."""
        kind = entry.get("kind")
        if kind in ("labels", "archive", "dbconn"):
            self._o.apply_command(entry, forward=True)
            return
        if kind == "grid":
            self._o._config.set_state(grid_layout=entry["value"])
            self._o._bus.emit(GridLayoutChanged(payload=entry["value"]))
        elif kind == "people":
            value = entry.get("value")
            rows = value.get("after") if isinstance(value, dict) else None
            if rows is not None and self._o._people is not None:
                self._o._timeline_commit.spawn(
                    "people restore", self._o._people.apply(rows))
        else:
            blocks = self._o._clean_blocks(entry["value"])
            self._o._config.set_state(last_stack=blocks, last_stack_preset="")
            engine = self._o._engine
            if engine is not None:
                engine.load_stack(blocks)
            self._o._bus.emit(StackLoaded(
                name="", payload=json.dumps(blocks, ensure_ascii=False)))
            # Undo/redo of a stack edit can change the enabled Scroll &
            # Parse presence — re-rank the people list's # column.
            self._o._bus.emit(PeopleChanged(reason="stack"))

    # ── undo / redo ──────────────────────────────────────────────
    def undo(self) -> Result[Optional[dict]]:
        """Undo one step; Ok(entry payload) | Err('nothing_to_undo')."""
        history, index = self._o.history()
        if not history or index < 0 or index >= len(history):
            return Err("nothing_to_undo", "the timeline is at its start")
        entry = history[index]
        if entry.get("kind") in self._o.COMMAND_KINDS:
            if not self._o.apply_command(entry, forward=False):
                return Err("nothing_to_undo",
                           f"cannot reverse {entry.get('kind')}")
            index -= 1
            self._o.set_history(history, index)
            self._o._bus.emit(UndoHistoryChanged())
            kind = entry["kind"]
            _log_command(self._o, entry, forward=False)
            value = entry.get("value") or {}
            payload = (value.get("before")
                       if kind in ("people", "labels") else value)
            return Ok({"kind": kind, "value": payload, "index": index})
        if index <= 0:
            return Err("nothing_to_undo", "nothing before the first entry")
        index -= 1
        self._o.set_history(history, index)
        self._o._bus.emit(UndoHistoryChanged())
        entry = history[index]
        self._o._apply_entry(entry)
        self._o._log("↩ Undo — restored " + entry["kind"], "info")
        return Ok({"kind": entry["kind"], "value": entry["value"],
                   "index": index})

    def redo(self) -> Result[Optional[dict]]:
        history, index = self._o.history()
        if not history or index >= len(history) - 1:
            return Err("nothing_to_redo", "the timeline is at its tip")
        index += 1
        entry = history[index]
        if entry.get("kind") in self._o.COMMAND_KINDS:
            if not self._o.apply_command(entry, forward=True):
                return Err("nothing_to_redo",
                           f"cannot re-apply {entry.get('kind')}")
            self._o.set_history(history, index)
            self._o._bus.emit(UndoHistoryChanged())
            kind = entry["kind"]
            _log_command(self._o, entry, forward=True)
            value = entry.get("value") or {}
            payload = (value.get("after")
                       if kind in ("people", "labels") else value)
            return Ok({"kind": kind, "value": payload, "index": index})
        self._o.set_history(history, index)
        self._o._bus.emit(UndoHistoryChanged())
        self._o._apply_entry(entry)
        self._o._log("↪ Redo — restored " + entry["kind"], "info")
        return Ok({"kind": entry["kind"], "value": entry["value"],
                   "index": index})
