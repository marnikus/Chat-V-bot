"""The Filter panel's criteria JSON.

`CriteriaMixin` owns the two slots that read and write the criteria
engine — the only place the stack editor touches the filter rules.
"""

from __future__ import annotations

from PySide6.QtCore import Slot


class CriteriaMixin:
    # ── criteria ─────────────────────────────────────────────────
    @Slot(str)
    def save_criteria(self, j):
        self.ctx.criteria.load_json(j)
        self._log("💾 Criteria saved", "info")

    @Slot(result=str)
    def get_criteria(self):
        return self.ctx.criteria.to_json()
