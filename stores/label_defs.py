"""Label definition CRUD — create, rename/recolour, delete (H-C5 split).

Split out of `stores/label_assignments.py` by Round H step H-C5: that file had
MI 35.5 in 229 lines and an 18-method class, over RULE 16's 15-method cap.
The three definition operations are one responsibility — they are the only
methods that change `defs`, and `delete` is the only one that must also scrub
the id out of every person's assignment list and both filter verdicts.

Mixed into `stores.label_assignments.LabelAssignments`, so `LabelStore`'s
delegators and every `store.assignments.create(...)` call site are unchanged.

Import direction: `stores.label_rules` for the normalizers and the palette;
nothing imports back.
"""

from __future__ import annotations

from datetime import datetime

from stores.label_rules import PALETTE, normalize_color, normalize_id, normalize_name


def _unassign(data: dict, wanted: str) -> None:
    """Drop a label id from every person's assignment list."""
    for nick in list(data["assign"]):
        kept = [i for i in data["assign"][nick] if i != wanted]
        if kept:
            data["assign"][nick] = kept
        else:
            data["assign"].pop(nick, None)


def _unfilter(data: dict, wanted: str) -> None:
    """Drop a label id from both the include and the exclude verdicts."""
    data["filter"]["include"] = [i for i in data["filter"]["include"]
                                 if i != wanted]
    data["filter"]["exclude"] = [i for i in data["filter"]["exclude"]
                                 if i != wanted]


class LabelDefsMixin:
    """Create / update / delete a label definition; on ``LabelAssignments``."""

    def create(self, name, color: str = "") -> dict | None:
        clean = normalize_name(name)
        if not clean:
            return None
        data = self._owner._normalized()
        if any(d["name"].casefold() == clean.casefold() for d in data["defs"]):
            return None                       # names are unique, case-insensitive
        next_id = max(data["next_id"], len(data["defs"]))
        # never reuse an id, even after deletions
        used = {d["id"] for d in data["defs"]}
        while True:
            next_id += 1
            candidate = f"lbl_{next_id}"
            if candidate not in used:
                break
        label = {"id": candidate, "name": clean,
                 "color": normalize_color(color,
                                          PALETTE[len(data["defs"]) % len(PALETTE)]),
                 "created_at": datetime.now().isoformat(timespec="seconds")}
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
            if clean and not any(d is not label and
                                 d["name"].casefold() == clean.casefold()
                                 for d in data["defs"]):
                label["name"] = clean
        if color is not None:
            label["color"] = normalize_color(color, label["color"])
        self._owner._save(data)
        return dict(label)

    def delete(self, label_id) -> bool:
        """Remove a label from the system: definition, every person, filters."""
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
