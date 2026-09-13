"""The timeline's contents: how an entry is built, cleaned, read and written.

`TimelineMixin` is the only place that touches the two in-memory fields
(`self._timeline`, `self._h_index`) and the seq counter (`self._seq_next`),
plus the normalization the wire hands over:

* `_clean_blocks` / `_clean_history` — strip retired block keys from stack
  snapshots (the safety net behind `services.run.normalize_blocks`);
* `_history_entry` — the ONE entry shape (`{kind, value}`, deep-copied so a
  caller's later mutation cannot rewrite history);
* `_next_seq` — the identity `sync_world_state` merges the two stores by;
* `migrate_global_history` — the one-shot rebuild from pre-global-history
  config;
* `history` / `set_history` — the read (a cleaned deep copy, so a caller
  cannot mutate the timeline in place) and the write (which delegates to
  `services.undo_timeline.TimelineCommit`, the owner of persisting both
  halves).

Extracted unchanged from `services/undo_service.py` (god-class round, step 7).
See `docs/archive/2026-09-13-god-classes/STEP7_UNDO_SERVICE_DESIGN_2026-09-13.md`.
"""

from __future__ import annotations

import copy

from services.run import normalize_blocks


class TimelineMixin:
    """Entry shape, seq, and the read/write of the in-memory timeline."""

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
