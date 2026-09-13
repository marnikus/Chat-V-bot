"""Walking ONTO a snapshot entry: applying the state it represents.

`undo`/`redo` (`walking.py`) move the pointer and then, for a non-command
entry, restore the state that entry recorded. This is that restore, and its
shape is dictated by what each kind owns:

* `labels` / `archive` / `dbconn` are not snapshots at all — they are commands
  and are handed to `apply_command(forward=True)`;
* `grid` writes the layout and emits `GridLayoutChanged` with the payload
  verbatim. Note the write happens on LANDING, not on `push`: recording a
  layout snapshot must never clobber the live grid;
* `people` re-applies the entry's `after` rows as one spawned task (the queue
  is async);
* anything else is a `stack` snapshot: the blocks are cleaned, written to
  config as the last stack (with the preset name cleared — a restored stack is
  not "the preset you saved"), handed to the engine when one is attached, and
  announced as `StackLoaded`. It also re-ranks the People list's # column,
  because a stack edit can change whether Scroll & Parse is enabled.

Extracted unchanged from `services/undo_service.py` (god-class round, step 7).
See `docs/archive/2026-09-13-god-classes/STEP7_UNDO_SERVICE_DESIGN_2026-09-13.md`.
"""

from __future__ import annotations

import json

from core.events import GridLayoutChanged, PeopleChanged, StackLoaded


class SnapshotMixin:
    """`_apply_entry` — restore the state one timeline entry represents."""

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
