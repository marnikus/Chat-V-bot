"""LabelAssignments CRUD — extracted from label_assignments (H-C5 split)

Create/update/delete/assign, ≤150 LOC.
"""

from __future__ import annotations

from datetime import datetime

from stores.label_assignments_helpers import (
    coerce_next_id as _coerce_next_id,
    has_assignments as _has_assignments,
    is_assigned as _is_assigned,
    is_dict_snapshot as _is_dict_snapshot,
    is_known_label as _is_known_label,
    is_same_assignment as _is_same_assignment,
    is_unique_name as _is_unique_name,
    is_valid_id as _is_valid_id,
    is_valid_name as _is_valid_name,
    is_valid_nick as _is_valid_nick,
    next_label_id as _next_label_id,
    unassign as _unassign,
    unfilter as _unfilter,
)
from stores.label_rules import PALETTE, normalize_color, normalize_id, normalize_name, normalize_nick


class LabelAssignmentsCrud:
    def __init__(self, owner) -> None:
        self._owner = owner

    def create(self, name, color: str = "") -> dict | None:
        if not _is_valid_name(name):
            return None
        clean = normalize_name(name)
        data = self._owner._normalized()
        if not _is_unique_name(data["defs"], clean):
            return None
        candidate, next_id = _next_label_id(data["defs"], data["next_id"])
        label = {
            "id": candidate,
            "name": clean,
            "color": normalize_color(color, PALETTE[len(data["defs"]) % len(PALETTE)]),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        data["defs"].append(label)
        data["next_id"] = next_id
        self._owner._save(data)
        return label

    def update(self, label_id, name=None, color=None) -> dict | None:
        data = self._owner._normalized()
        label = next((d for d in data["defs"] if d["id"] == str(label_id)), None)
        if label is None:
            return None
        if name is not None:
            clean = normalize_name(name)
            if clean and _is_unique_name(data["defs"], clean, exclude=label):
                label["name"] = clean
        if color is not None:
            label["color"] = normalize_color(color, label["color"])
        self._owner._save(data)
        return dict(label)

    def delete(self, label_id) -> bool:
        wanted = str(label_id or "")
        data = self._owner._normalized()
        before = len(data["defs"])
        data["defs"] = [d for d in data["defs"] if d["id"] != wanted]
        if len(data["defs"]) == before:
            return False
        _unassign(data, wanted)
        _unfilter(data, wanted)
        self._owner._save(data)
        return True

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
