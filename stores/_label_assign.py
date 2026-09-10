"""Label assignments — extracted from LabelStore (AREA B)."""

from __future__ import annotations

from stores._label_defs import normalize_id, normalize_nick

class LabelAssignments:
    def __init__(self, store):
        self.store = store

    def assignments(self) -> dict:
        return self.store._normalized()["assign"]

    def ids_for(self, nick) -> list[str]:
        return list(self.store._normalized()["assign"].get(normalize_nick(nick), []))

    def labels_for(self, nick) -> list[dict]:
        data = self.store._normalized()
        index = {d["id"]: d for d in data["defs"]}
        return [index[i] for i in data["assign"].get(normalize_nick(nick), []) if i in index]

    def labels_map(self, nicks=None) -> dict:
        data = self.store._normalized()
        index = {d["id"]: d for d in data["defs"]}
        wanted = None if nicks is None else {normalize_nick(n) for n in nicks}
        out: dict[str, list[dict]] = {}
        for nick, ids in data["assign"].items():
            if wanted is not None and nick not in wanted:
                continue
            out[nick] = [index[i] for i in ids if i in index]
        return out

    def assign(self, nick, label_id) -> bool:
        clean = normalize_nick(nick)
        wanted = normalize_id(label_id)
        data = self.store._normalized()
        if not clean or not any(d["id"] == wanted for d in data["defs"]):
            return False
        current = data["assign"].get(clean, [])
        if wanted in current:
            return False
        data["assign"][clean] = current + [wanted]
        self.store._save(data)
        return True

    def unassign(self, nick, label_id) -> bool:
        clean = normalize_nick(nick)
        wanted = normalize_id(label_id)
        data = self.store._normalized()
        current = data["assign"].get(clean)
        if not current or wanted not in current:
            return False
        kept = [i for i in current if i != wanted]
        if kept:
            data["assign"][clean] = kept
        else:
            data["assign"].pop(clean, None)
        self.store._save(data)
        return True

    def set_for(self, nick, ids) -> bool:
        clean = normalize_nick(nick)
        if not clean:
            return False
        data = self.store._normalized()
        known = {d["id"] for d in data["defs"]}
        kept = list(dict.fromkeys(normalize_id(i) for i in (ids or []) if normalize_id(i) in known))
        current = data["assign"].get(clean, [])
        if kept == current:
            return False
        if kept:
            data["assign"][clean] = kept
        else:
            data["assign"].pop(clean, None)
        self.store._save(data)
        return True

    def forget(self, nick) -> bool:
        clean = normalize_nick(nick)
        data = self.store._normalized()
        if clean not in data["assign"]:
            return False
        data["assign"].pop(clean, None)
        self.store._save(data)
        return True
