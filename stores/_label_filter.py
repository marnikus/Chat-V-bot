"""Label filter — extracted from LabelStore (AREA B)."""

from __future__ import annotations

from stores._label_defs import normalize_nick

class LabelFilter:
    def __init__(self, store):
        self.store = store

    def filter(self) -> dict:
        return self.store._normalized()["filter"]

    def set_filter(self, include=None, exclude=None) -> dict:
        data = self.store._normalized()
        known = {d["id"] for d in data["defs"]}
        inc = list(dict.fromkeys(str(i) for i in (include or []) if str(i) in known))
        exc = list(dict.fromkeys(str(i) for i in (exclude or []) if str(i) in known))
        inc = [i for i in inc if i not in exc]
        data["filter"] = {"include": inc, "exclude": exc}
        self.store._save(data)
        return dict(data["filter"])

    def clear_filter(self) -> dict:
        return self.set_filter([], [])

    @property
    def filter_active(self) -> bool:
        current = self.filter()
        return bool(current["include"] or current["exclude"])

    def allows(self, nick) -> bool:
        data = self.store._normalized()
        rule = data["filter"]
        if not rule["include"] and not rule["exclude"]:
            return True
        mine = set(data["assign"].get(normalize_nick(nick), []))
        if mine & set(rule["exclude"]):
            return False
        if rule["include"]:
            return bool(mine & set(rule["include"]))
        return True

    def reject_reason(self, nick) -> str:
        data = self.store._normalized()
        rule = data["filter"]
        index = {d["id"]: d["name"] for d in data["defs"]}
        mine = set(data["assign"].get(normalize_nick(nick), []))
        hit = mine & set(rule["exclude"])
        if hit:
            return "labelled " + ", ".join(sorted(index.get(i, i) for i in hit))
        if rule["include"] and not (mine & set(rule["include"])):
            return "missing label " + ", ".join(sorted(index.get(i, i) for i in rule["include"]))
        return ""
