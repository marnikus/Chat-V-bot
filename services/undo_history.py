"""Reading and writing the ONE global undo timeline.

`UndoService` owns the timeline state (`_timeline`, `_h_index`, `_seq_next`)
and the projections that reshape it for older callers; this module owns the
operations on them:

* `history()` / `set_history()` — the timeline and its pointer, with stack
  snapshots cleaned on the way out and every write going through
  `TimelineCommit` (which persists the ownership split);
* `migrate_global_history()` — the one-time rebuild from pre-global-history
  config, preserving each entry's `seq`, because `seq` is the identity the
  app-level half and the world's `undo_history` table merge on. Dropping it
  pushed every app entry ahead of the world entries and issued duplicate seqs,
  so the global undo order was wrong after a restart;
* `_next_seq()` — the monotonic counter;
* the compatibility projections (`stack_projection`, `kind_projection`) and
  `push_stack`, which older integrations and tests still call.

`_history_entry` and `_clean_blocks` stay on `UndoService`: `push` (which must
stay there — see that file) calls both, and `UndoProjection` is wired with the
bound `_history_entry` in `__init__`. This module reaches them through the
owner, so a patch on the facade is still seen.

Imports point one way: this module imports nothing from `services/` and never
from `services.undo_service`.
"""

from __future__ import annotations

import copy


class HistoryProjection:
    """The timeline accessor half of UndoService."""

    def __init__(self, owner):
        self._o = owner

    # ── seq ──────────────────────────────────────────────────────
    def _next_seq(self) -> int:
        next_seq = self._o._seq_next
        self._o._seq_next = next_seq + 1
        return next_seq

    def _migrated_entry(self, source: dict, kind: str, value) -> dict:
        """Rebuild a stored timeline entry, PRESERVING its seq.

        seq is the identity used to merge the app-level config half with the
        active world's ``undo_history`` table on startup. Dropping it (as a
        plain rebuild did) pushed every app entry ahead of the world entries
        in the merged timeline and could issue duplicate seqs — the global
        undo order was wrong after a restart.
        """
        entry = self._o._history_entry(kind, value)
        seq = source.get("seq")
        if isinstance(seq, int) and seq > 0:
            entry["seq"] = seq
        return entry

    # ── legacy migration ─────────────────────────────────────────
    def migrate_global_history(self) -> tuple[list, int]:
        """Build the global timeline from pre-global-history config once."""
        raw = self._o._config.get_state("undo_history", None)
        if isinstance(raw, list) and raw:
            return self._o._projection.from_raw_history(self._o._config, raw)
        history, index, canonical = self._o._projection.from_legacy_config(
            self._o._config)
        if canonical is not None:
            self._o._config.set_state(grid_layout=canonical)
        self._o._config.set_state(undo_history=copy.deepcopy(history),
                                  undo_history_index=index)
        return history, index

    # ── timeline access ──────────────────────────────────────────
    def history(self) -> tuple[list, int]:
        """The timeline (stack snapshots cleaned) and its pointer."""
        timeline = self._o._timeline
        if timeline is None:
            history, index = self._o.migrate_global_history()
            history = copy.deepcopy(history)
        else:
            history, index = copy.deepcopy(timeline), self._o._h_index
        return self._o._projection.clean(history), index

    def set_history(self, history: list, index: int) -> None:
        self._o._timeline_commit.commit(list(history), index)

    # ── compat projections (older integrations and tests) ────────
    def stack_projection(self) -> tuple[list, int]:
        """Compatibility projection of stack entries."""
        history, global_index = self._o.history()
        return self._o._projection.stack_projection(history, global_index)

    def set_stack_projection(self, history: list, index: int,
                             save: bool = True) -> None:
        entries = [self._o._history_entry("stack", self._o._clean_blocks(value))
                   for value in history if isinstance(value, list)]
        self._o.set_history(entries,
                            max(-1, min(index, len(entries) - 1)))

    def kind_projection(self, kind: str) -> tuple[list, int]:
        history, global_index = self._o.history()
        return self._o._projection.kind_projection(history, global_index, kind)

    def push_stack(self, blocks: list) -> tuple[list, int]:
        """Backward-compatible: append the stack to global history."""
        if isinstance(blocks, list):
            self._o.push("stack", self._o._clean_blocks(blocks))
        return self._o.stack_projection()
