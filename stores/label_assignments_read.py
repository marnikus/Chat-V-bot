"""LabelAssignments read — extracted from label_assignments (H-C5 split)

Read-only projections, ≤150 LOC.
"""

from __future__ import annotations

import copy

from stores.label_rules import PALETTE, normalize_id, normalize_name, normalize_nick


class LabelAssignmentsRead:
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
        return next((d for d in self.defs() if d["name"].casefold() == wanted), None)

    def assignments(self) -> dict:
        return self._owner._normalized()["assign"]

    def ids_for(self, nick) -> list[str]:
        return list(self._owner._normalized()["assign"].get(normalize_nick(nick), []))

    def labels_for(self, nick) -> list[dict]:
        data = self._owner._normalized()
        index = {d["id"]: d for d in data["defs"]}
        return [index[i] for i in data["assign"].get(normalize_nick(nick), []) if i in index]

    def labels_map(self, nicks=None) -> dict:
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
        data = self._owner._normalized()
        return {"defs": data["defs"], "assign": data["assign"], "filter": data["filter"], "palette": list(PALETTE)}

    def snapshot(self) -> dict:
        return copy.deepcopy(self._owner._normalized())
