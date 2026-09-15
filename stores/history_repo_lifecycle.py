"""What happens to a whole conversation, not to one row.

H-C5: split into cursor/trash/person parts, facade ≤50 LOC.
"""

from __future__ import annotations

from stores.history_repo_lifecycle_cursor import LifecycleCursor
from stores.history_repo_lifecycle_person import LifecyclePerson
from stores.history_repo_lifecycle_trash import LifecycleTrash, _hidden_row_key


class PersonLifecycle(LifecycleCursor, LifecycleTrash, LifecyclePerson):
    def __init__(self, owner):
        self._owner = owner
        # init sub-ladders that were in cursor/person
        super().__init__(owner)
        # restore ladder is inside person part, but cursor also needs its own
        # ensure both are initialized (cursor's _cursor, person's _restore)
        from stores.history_repo_cursor import CursorLadder
        from stores.history_repo_restore import RestoreLadder

        self._cursor = CursorLadder(owner)
        self._restore = RestoreLadder(owner)


__all__ = ["PersonLifecycle", "_hidden_row_key"]
