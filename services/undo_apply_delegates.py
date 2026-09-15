"""Apply command delegators — part of UndoService facade.

H-C2: 6 methods moved out of UndoService to reduce direct method count ≤15.
"""

from __future__ import annotations

from typing import Optional

from core.result import Result


class UndoApplyDelegates:
    def apply_command(self, entry, forward: bool) -> bool:
        return self._apply.apply_command(entry, forward)

    def _apply_archive_command(self, value: dict, forward: bool, entry: Optional[dict] = None) -> bool:
        return self._apply._apply_archive_command(value, forward, entry)

    def _apply_entry(self, entry) -> None:
        return self._apply._apply_entry(entry)

    def rewind_after_failure(self, entry: Optional[dict], forward: bool) -> None:
        return self._apply.rewind_after_failure(entry, forward)

    def undo(self) -> Result[Optional[dict]]:
        return self._apply.undo()

    def redo(self) -> Result[Optional[dict]]:
        return self._apply.redo()
