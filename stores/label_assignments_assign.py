"""Label assignments assign — extracted from label_assignments_crud (H-C5 split)

Assign/unassign/set_for/forget/restore, ≤120 LOC.
"""

from __future__ import annotations

from stores.label_assignments_crud_base import LabelAssignmentsCrudBase
from stores.label_assignments_helpers import (
    coerce_next_id as _coerce_next_id,
    has_assignments as _has_assignments,
    is_assigned as _is_assigned,
    is_dict_snapshot as _is_dict_snapshot,
    is_known_label as _is_known_label,
    is_same_assignment as _is_same_assignment,
    is_valid_id as _is_valid_id,
    is_valid_nick as _is_valid_nick,
)
from stores.label_rules import normalize_id, normalize_nick


class LabelAssignmentsAssign(LabelAssignmentsCrudBase):
    def assign(self, nick, label_id) -> bool:
        clean = normalize_nick(nick)
        wanted = normalize_id(label_id)
        data = self._owner._normalized()
        if not _is_valid_nick(clean):
            return False
        if not _is_valid_id(wanted):
            return False
        if not _is_known_label(data["defs"], wanted):
            return False
        current = data["assign"].get(clean, [])
        if _is_assigned(current, wanted):
            return False
        data["assign"][clean] = current + [wanted]
        self._owner._save(data)
        return True

    def unassign(self, nick, label_id) -> bool:
        clean = normalize_nick(nick)
        wanted = normalize_id(label_id)
        data = self._owner._normalized()
        current = data["assign"].get(clean)
        if not current or not _is_assigned(current, wanted):
            return False
        kept = [i for i in current if i != wanted]
        if kept:
            data["assign"][clean] = kept
        else:
            data["assign"].pop(clean, None)
        self._owner._save(data)
        return True

    def set_for(self, nick, ids) -> bool:
        clean = normalize_nick(nick)
        if not _is_valid_nick(clean):
            return False
        data = self._owner._normalized()
        known = {d["id"] for d in data["defs"]}
        kept = list(dict.fromkeys(normalize_id(i) for i in (ids or []) if normalize_id(i) in known))
        current = data["assign"].get(clean, [])
        if _is_same_assignment(current, kept):
            return False
        if kept:
            data["assign"][clean] = kept
        else:
            data["assign"].pop(clean, None)
        self._owner._save(data)
        return True

    def forget(self, nick) -> bool:
        clean = normalize_nick(nick)
        data = self._owner._normalized()
        if not _has_assignments(data["assign"], clean):
            return False
        data["assign"].pop(clean, None)
        self._owner._save(data)
        return True

    def restore(self, snapshot) -> None:
        if not _is_dict_snapshot(snapshot):
            return
        defs = snapshot.get("defs")
        assign = snapshot.get("assign")
        filt = snapshot.get("filter")
        next_id = _coerce_next_id(snapshot)
        self._owner._save(
            {
                "defs": defs if isinstance(defs, list) else [],
                "assign": assign if isinstance(assign, dict) else {},
                "filter": filt if isinstance(filt, dict) else {"include": [], "exclude": []},
                "next_id": next_id,
            }
        )
