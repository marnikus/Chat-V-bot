"""The compatibility projections older integrations and tests still call.

Before the ONE global timeline, the stack had its own undo history, and four
names from that era are still load bearing:

* `stack_projection` / `kind_projection` — the stack-only (or any single
  kind's) view of the global timeline, as `(values, index)`;
* `set_stack_projection` — write a stack-only history back as stack entries,
  clamping the pointer into range (`-1` for an empty timeline);
* `push_stack` — what `bridge/undo_bridge.py` calls on every stack autosave.
  It answers from the STORE (`stack_projection()` re-reads the timeline), not
  from the `push` it just made — which is why, after a no-op re-push, it still
  shows the redo branch `push` truncated locally.

They are thin adapters over `UndoProjection` (`services/undo_support.py`); the
projection logic itself is not duplicated here.

Extracted unchanged from `services/undo_service.py` (god-class round, step 7).
See `docs/archive/2026-09-13-god-classes/STEP7_UNDO_SERVICE_DESIGN_2026-09-13.md`.
"""

from __future__ import annotations


class ProjectionMixin:
    """The four stack-era names, as adapters over the global timeline."""

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
