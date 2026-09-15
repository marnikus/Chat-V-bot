"""History projection delegators — part of UndoService facade, extracted for method-count.

H-C2: UndoService had 28 methods, 86% delegations. This file owns the history
projection delegators (9 methods) so UndoService can stay ≤15 direct methods
while keeping the same public surface via inheritance.

Design: docs/archive/2026-09-14-round-h/AREA_C_SERVICES_STORES_DESIGN_2026-09-14.md H-C2
"""

from __future__ import annotations

from typing import Optional


class UndoHistoryDelegates:
    """Delegators to HistoryProjection — history() etc."""

    def history(self) -> tuple[list, int]:
        return self._history.history()

    def set_history(self, history: list, index: int) -> None:
        return self._history.set_history(history, index)

    def migrate_global_history(self) -> tuple[list, int]:
        return self._history.migrate_global_history()

    def _migrated_entry(self, source: dict, kind: str, value) -> dict:
        return self._history._migrated_entry(source, kind, value)

    def _next_seq(self) -> int:
        return self._history._next_seq()

    def stack_projection(self) -> tuple[list, int]:
        return self._history.stack_projection()

    def set_stack_projection(self, history: list, index: int, save: bool = True) -> None:
        return self._history.set_stack_projection(history, index, save)

    def kind_projection(self, kind: str) -> tuple[list, int]:
        return self._history.kind_projection(kind)

    def push_stack(self, blocks: list) -> tuple[list, int]:
        return self._history.push_stack(blocks)
