"""Committing an edit onto the timeline: `push`.

One responsibility with three rules, all pinned by tests:

1. an unknown kind is a typed `Err`, never a silently dropped edit;
2. re-committing the value already at the pointer is a **no-op** — grid and
   stack autosaves fire on every edit, and the timeline must not grow with
   duplicates (`_same_entry` compares kind + value, not `seq`);
3. committing anything after an undo first truncates the redo branch, and the
   timeline is capped at `MAX_STACK_HISTORY`, with the pointer moving down by
   the overflow so it keeps pointing at the same entry.

The cap is read through the PACKAGE namespace at call time, because
`tests/test_world_write_gate.py` shrinks it by rebinding
`services.undo_service.MAX_STACK_HISTORY` — the two I-19 tests that prove an
evicted step gives up its tombstone. A module-level `from … import
MAX_STACK_HISTORY` here would snapshot the value at import time and those
patches would land on nothing.

Extracted from `services/undo_service.py` (god-class round, step 7): the code
is unchanged, the `push` docstring is not — see "OBSERVED, NOT CHANGED" below.
See `docs/archive/2026-09-13-god-classes/STEP7_UNDO_SERVICE_DESIGN_2026-09-13.md`.
"""

from __future__ import annotations

from core.events import UndoHistoryChanged
from core.result import Err, Ok, Result

from .entries import _same_entry


def _history_cap() -> int:
    """The timeline cap, read when `push` runs (a live patch seam)."""
    from services import undo_service as package        # noqa: PLC0415
    return package.MAX_STACK_HISTORY


class RecordingMixin:
    """`push` — append one entry, dedupe at the pointer, honour the cap."""

    def push(self, kind: str, value) -> Result[tuple]:
        """Append one entry; returns (history, index) on success.

        Re-committing the value already at the pointer is a no-op (grid /
        stack autosaves must not grow the timeline), and committing anything
        after an undo first truncates the redo branch.

        OBSERVED, NOT CHANGED (step 7): in the same-value case the truncation
        above happens in the LOCAL list only — the `set_history` +
        `UndoHistoryChanged` inside that branch are unreachable, because
        reaching it means `index == len(history) - 1` already. So a no-op push
        answers with the truncated branch but writes nothing: the stored
        timeline keeps its redo tail and the bus stays quiet (and
        `push_stack`, which re-reads the store, still shows that tail).
        `tests/integration/services/test_undo_world_commands.py` pins both
        halves. The docstring this replaced promised "a stale tail cannot
        survive a re-commit" — the code never did that, and this step moves
        behaviour rather than changing it.
        """
        if kind not in self.HISTORY_KINDS:
            return Err("unknown_kind", f"unknown history kind: {kind}")
        history, index = self.history()
        entry = self._history_entry(kind, value)
        if index < len(history) - 1:
            history = history[:index + 1]
        if 0 <= index < len(history) and \
                _same_entry(history[index], entry):
            if index < len(history) - 1:      # unreachable: see the docstring
                self.set_history(history, index)
                self._bus.emit(UndoHistoryChanged())
            return Ok((history, index))
        entry["seq"] = self._next_seq()
        history.append(entry)
        index = len(history) - 1
        cap = _history_cap()
        if len(history) > cap:
            overflow = len(history) - cap
            history = history[overflow:]
            index -= overflow
        self.set_history(history, index)
        self._bus.emit(UndoHistoryChanged())
        return Ok((history, index))
