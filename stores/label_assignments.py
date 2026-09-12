"""LabelAssignments — the definitions and the person → label mapping.

Extracted from `stores/label_store.py` by the AREA B2 split (design §2.5):
the CRUD the panels drive (create, rename, recolour, delete a label; assign
it to a person; forget a person) plus the deep `snapshot`/`restore` pair the
global undo timeline stores.

Every write is a whole-payload `_save` — the "apply to memory first, then
schedule the flush" rule the class docstring promises — and the id allocator
never reuses an id, so undoing a delete cannot re-point an old assignment at
a different label.
"""

from __future__ import annotations

import copy
from datetime import datetime

from stores.label_rules import (
    PALETTE,
    normalize_color,
    normalize_id,
    normalize_name,
    normalize_nick,
)


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


class LabelAssignments:
    """Label definitions, per-person assignment and undo snapshots."""

    def __init__(self, owner) -> None:
        self._owner = owner

    def defs(self) -> list[dict]:
        return self._owner._normalized()["defs"]

    def by_id(self, label_id) -> dict | None:
        wanted = normalize_id(label_id)
        return next((d for d in self.defs() if d["id"] == wanted), None)

    def by_name(self, name) -> dict | None:
        wanted = normalize_name(name).casefold()
        if not wanted:
            return None
        return next((d for d in self.defs()
                     if d["name"].casefold() == wanted), None)

    def assignments(self) -> dict:
        return self._owner._normalized()["assign"]

    def ids_for(self, nick) -> list[str]:
        return list(self._owner._normalized()["assign"].get(normalize_nick(nick), []))

    def labels_for(self, nick) -> list[dict]:
        """Full label objects for one person (order = assignment order)."""
        data = self._owner._normalized()
        index = {d["id"]: d for d in data["defs"]}
        return [index[i] for i in data["assign"].get(normalize_nick(nick), [])
                if i in index]

    def labels_map(self, nicks=None) -> dict:
        """`{nick: [label, …]}` for a set of nicks (all of them when None)."""
        data = self._owner._normalized()
        index = {d["id"]: d for d in data["defs"]}
        wanted = None if nicks is None else {normalize_nick(n) for n in nicks}
        out: dict[str, list[dict]] = {}
        for nick, ids in data["assign"].items():
            if wanted is not None and nick not in wanted:
                continue
            out[nick] = [index[i] for i in ids if i in index]
        return out

    def state(self) -> dict:
        """Everything the UI needs in one payload."""
        data = self._owner._normalized()
        return {"defs": data["defs"], "assign": data["assign"],
                "filter": data["filter"], "palette": list(PALETTE)}

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

    def assign(self, nick, label_id) -> bool:
        clean = normalize_nick(nick)
        wanted = normalize_id(label_id)
        data = self._owner._normalized()
        if not clean or not any(d["id"] == wanted for d in data["defs"]):
            return False
        current = data["assign"].get(clean, [])
        if wanted in current:
            return False
        data["assign"][clean] = current + [wanted]
        self._owner._save(data)
        return True

    def unassign(self, nick, label_id) -> bool:
        clean = normalize_nick(nick)
        wanted = normalize_id(label_id)
        data = self._owner._normalized()
        current = data["assign"].get(clean)
        if not current or wanted not in current:
            return False
        kept = [i for i in current if i != wanted]
        if kept:
            data["assign"][clean] = kept
        else:
            data["assign"].pop(clean, None)
        self._owner._save(data)
        return True

    def set_for(self, nick, ids) -> bool:
        """Replace the whole label set of one person (used by 'Assign')."""
        clean = normalize_nick(nick)
        if not clean:
            return False
        data = self._owner._normalized()
        known = {d["id"] for d in data["defs"]}
        kept = list(dict.fromkeys(normalize_id(i) for i in (ids or [])
                                  if normalize_id(i) in known))
        current = data["assign"].get(clean, [])
        if kept == current:
            return False
        if kept:
            data["assign"][clean] = kept
        else:
            data["assign"].pop(clean, None)
        self._owner._save(data)
        return True

    def forget(self, nick) -> bool:
        """Drop every label of a person (used when a person is hard-deleted)."""
        clean = normalize_nick(nick)
        data = self._owner._normalized()
        if clean not in data["assign"]:
            return False
        data["assign"].pop(clean, None)
        self._owner._save(data)
        return True

    def snapshot(self) -> dict:
        """A deep copy of the whole section, for the global undo history."""
        return copy.deepcopy(self._owner._normalized())

    def restore(self, snapshot) -> None:
        if not isinstance(snapshot, dict):
            return
        defs = snapshot.get("defs")
        assign = snapshot.get("assign")
        filt = snapshot.get("filter")
        try:
            next_id = int(snapshot.get("next_id") or 0)
        except (TypeError, ValueError):
            next_id = 0
        # Coerce ill-typed values so garbage can neither brick reads nor be
        # persisted back to the config file verbatim (LBL-17).
        self._owner._save({
            "defs": defs if isinstance(defs, list) else [],
            "assign": assign if isinstance(assign, dict) else {},
            "filter": filt if isinstance(filt, dict)
            else {"include": [], "exclude": []},
            "next_id": next_id,
        })
