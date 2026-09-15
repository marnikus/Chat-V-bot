"""LabelAssignments CRUD — facade (H-C5 split)

Now ≤20 LOC via base/assign split.
"""

from __future__ import annotations

from stores.label_assignments_assign import LabelAssignmentsAssign


class LabelAssignmentsCrud(LabelAssignmentsAssign):
    pass
