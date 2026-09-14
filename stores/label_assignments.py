"""LabelAssignments — the definitions and the person → label mapping.

Extracted from `stores/label_store.py` by the AREA B2 split (design §2.5):
the CRUD the panels drive (create, rename, recolour, delete a label; assign
it to a person; forget a person) plus the deep `snapshot`/`restore` pair the
global undo timeline stores.

Round H step H-C5 split the writes out by responsibility, leaving here the
whole-section *views* (`defs`, `labels_for`, `labels_map`, `state`) and the
undo pair, which both operate on the section as a whole:

    label_defs.py     LabelDefsMixin    create / update / delete a definition
    label_people.py   LabelPeopleMixin  assign / unassign / set_for / forget

Both are inherited, not delegated to, so `LabelStore`'s eighteen one-line
delegators and every `store.assignments.<method>(...)` call site resolve
exactly as before.

Every write is a whole-payload `_save` — the "apply to memory first, then
schedule the flush" rule the class docstring promises — and the id allocator
never reuses an id, so undoing a delete cannot re-point an old assignment at
a different label.

Import direction: `stores.label_rules` for the normalizers and the palette;
nothing imports back.
"""

from __future__ import annotations

import copy

from stores.label_defs import LabelDefsMixin
from stores.label_people import LabelPeopleMixin
from stores.label_rules import PALETTE, normalize_id, normalize_name, normalize_nick


class LabelAssignments(LabelDefsMixin, LabelPeopleMixin):
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
