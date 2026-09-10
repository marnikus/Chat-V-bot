"""Label definitions — extracted from LabelStore (AREA B)."""

from __future__ import annotations

import re
from datetime import datetime

PALETTE = [
    "#ff3b30", "#ff9500", "#ffcc00", "#a3e635", "#34c759",
    "#14b8a6", "#22d3ee", "#38bdf8", "#0a84ff", "#5856d6",
    "#7c3aed", "#af52de", "#e935c1", "#ff2d95", "#ff375f",
    "#ff7a5c", "#f59e0b", "#7fff00", "#00ff7f", "#00e5ff",
]

DEFAULT_COLOR = PALETTE[0]
MAX_NAME = 40
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

def normalize_color(value, fallback: str = DEFAULT_COLOR) -> str:
    text = str(value or "").strip()
    if not _HEX.match(text):
        return fallback
    text = text.lower()
    if len(text) == 4:
        text = "#" + "".join(ch * 2 for ch in text[1:])
    return text

def normalize_name(value) -> str:
    return " ".join(str(value or "").split())[:MAX_NAME].strip()

def normalize_nick(value) -> str:
    return " ".join(str(value or "").split()).strip()

def normalize_id(value) -> str:
    return str(value or "").strip()

class LabelDefinitions:
    def __init__(self, store):
        self.store = store

    def defs(self):
        return self.store._normalized()["defs"]

    def by_id(self, label_id):
        wanted = normalize_id(label_id)
        return next((d for d in self.defs() if d["id"] == wanted), None)

    def by_name(self, name):
        wanted = normalize_name(name).casefold()
        if not wanted:
            return None
        return next((d for d in self.defs() if d["name"].casefold() == wanted), None)

    def create(self, name, color: str = ""):
        from datetime import datetime as _dt
        clean = normalize_name(name)
        if not clean:
            return None
        data = self.store._normalized()
        if any(d["name"].casefold() == clean.casefold() for d in data["defs"]):
            return None
        next_id = max(data["next_id"], len(data["defs"]))
        used = {d["id"] for d in data["defs"]}
        while True:
            next_id += 1
            cand = f"lbl_{next_id}"
            if cand not in used:
                break
        label = {"id": cand, "name": clean, "color": normalize_color(color, PALETTE[len(data["defs"]) % len(PALETTE)]), "created_at": _dt.now().isoformat(timespec="seconds")}
        data["defs"].append(label)
        data["next_id"] = next_id
        self.store._save(data)
        return label

    def update(self, label_id, name=None, color=None):
        data = self.store._normalized()
        label = next((d for d in data["defs"] if d["id"] == str(label_id)), None)
        if label is None:
            return None
        if name is not None:
            clean = normalize_name(name)
            if clean and not any(d is not label and d["name"].casefold() == clean.casefold() for d in data["defs"]):
                label["name"] = clean
        if color is not None:
            label["color"] = normalize_color(color, label["color"])
        self.store._save(data)
        return dict(label)

    def delete(self, label_id) -> bool:
        wanted = str(label_id or "")
        data = self.store._normalized()
        before = len(data["defs"])
        data["defs"] = [d for d in data["defs"] if d["id"] != wanted]
        if len(data["defs"]) == before:
            return False
        for nick in list(data["assign"]):
            kept = [i for i in data["assign"][nick] if i != wanted]
            if kept:
                data["assign"][nick] = kept
            else:
                data["assign"].pop(nick, None)
        data["filter"]["include"] = [i for i in data["filter"]["include"] if i != wanted]
        data["filter"]["exclude"] = [i for i in data["filter"]["exclude"] if i != wanted]
        self.store._save(data)
        return True
