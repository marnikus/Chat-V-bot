"""`Ctrl+Z` and `Ctrl+Shift+Z`: moving the pointer over ONE global timeline.

Both directions answer a `Result`, and the two shapes they can return are the
contract the bridge and the JS wire depend on:

* a COMMAND entry (`people` / `labels` / `archive` / `dbconn`) — the entry is
  applied in that direction, the pointer moves, and the answer's `value` is the
  half that was applied (`before` for undo, `after` for redo; for the other two
  kinds the whole op description);
* a SNAPSHOT entry (`stack` / `grid`) — the pointer moves first and then the
  entry it landed on is restored, and the answer's `value` is that entry's
  value.

The asymmetry between the two is deliberate and load bearing: undo of a
snapshot has to land ON the previous entry (`index <= 0` is a typed
`Err("nothing_to_undo")`, because there is nothing before the first), while
undo of a command applies the entry the pointer is already on and then steps
back. Redo mirrors it.

A command that REFUSES is an `Err` and the pointer does not move — the entry
stays where the next key press finds it (`commands.rewind_after_failure` is
what the spawned archive/dbconn tasks call when they fail later). Announcing
success for an edit that did not happen is the bug class this file exists to
prevent (I-18/I-19).

Extracted unchanged from `services/undo_service.py` (god-class round, step 7).
See `docs/archive/2026-09-13-god-classes/STEP7_UNDO_SERVICE_DESIGN_2026-09-13.md`.
"""

from __future__ import annotations

from typing import Optional

from core.events import UndoHistoryChanged
from core.result import Err, Ok, Result

from .commands import _log_command


class UndoRedoMixin:
    """The two pointer walks, and what each answers."""

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
