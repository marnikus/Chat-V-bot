"""Label assignments base CRUD — extracted from label_assignments_crud (H-C5 split)

Create/update/delete, ≤80 LOC.
"""

from __future__ import annotations

from datetime import datetime

from stores.label_assignments_helpers import is_unique_name as _is_unique_name, is_valid_name as _is_valid_name, next_label_id as _next_label_id, unassign as _unassign, unfilter as _unfilter
from stores.label_rules import PALETTE, normalize_color, normalize_name


class LabelAssignmentsCrudBase:
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
