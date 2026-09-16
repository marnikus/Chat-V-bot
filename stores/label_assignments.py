"""LabelAssignments — facade (H-C5 split)

CRUD + read, now ≤80 LOC via read/crud/helpers split.
"""

from __future__ import annotations

from stores.label_assignments_crud import LabelAssignmentsCrud
from stores.label_assignments_read import LabelAssignmentsRead
from stores.label_rules import PALETTE  # frozen shim: pinned by api_baseline


class LabelAssignments(LabelAssignmentsRead, LabelAssignmentsCrud):
    def __init__(self, owner) -> None:
        self._owner = owner


__all__ = ["LabelAssignments", "PALETTE"]
