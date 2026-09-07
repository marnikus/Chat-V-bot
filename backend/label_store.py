"""Person labels: custom coloured tags stored in the ONE settings file.

Labels describe a *person*, and two different windows show them: the People
list (`chatbot.db` → User Memory) and the Full User Database (`history.db` →
the archive). Putting the tags in either database would duplicate them, or
break RULE 14 ("the two stores are joined by nick at read time only"), so
they live in `config.json` next to every other user-authored setting and are
merged into each row when it is read.

Shape of the stored section::

    "labels": {
      "defs":   [{"id": "lbl_1", "name": "Rude", "color": "#ff3b30",
                  "created_at": "2026-09-07T18:22:31"}],
      "assign": {"Angelochenek": ["lbl_1", "lbl_2"]},
      "filter": {"include": ["lbl_3"], "exclude": ["lbl_1"]}
    }

Everything is normalised on read: unknown ids, broken colours and duplicate
names can never reach the UI or crash a panel (AGENT_RULES RULE 13).
"""

from __future__ import annotations

import copy
import logging
import re
from datetime import datetime

log = logging.getLogger("chatbot")

#: The 20 bright presets the Color Picker offers (5 × 4 grid, row major).
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
    """Return a safe `#rrggbb` string (never anything a stylesheet chokes on)."""
    text = str(value or "").strip()
    if not _HEX.match(text):
        return fallback
    text = text.lower()
    if len(text) == 4:                      # #abc → #aabbcc
        text = "#" + "".join(ch * 2 for ch in text[1:])
    return text


def normalize_name(value) -> str:
    """Trim/collapse whitespace and cap the length; '' means 'not a label'."""
    return " ".join(str(value or "").split())[:MAX_NAME].strip()


def normalize_nick(value) -> str:
    return " ".join(str(value or "").split()).strip()


def normalize_id(value) -> str:
    """Label ids never contain spaces — trim whatever the UI sent."""
    return str(value or "").strip()


class LabelStore:
    """Definitions, per-person assignment and the include/exclude filter."""

    SECTION = "labels"

    def __init__(self, config):
        self._config = config

    # ── raw section access ───────────────────────────────────────
    def _raw(self) -> dict:
        data = None
        if self._config is not None:
            data = self._config.get(self.SECTION, default=None)
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        if self._config is None:
            return
        self._config.set(self.SECTION, copy.deepcopy(data))
        self._config.save()

    # ── normalisation ────────────────────────────────────────────
    def _normalized(self) -> dict:
        raw = self._raw()
        defs, seen_ids, seen_names = [], set(), set()
        for item in raw.get("defs") or []:
            if not isinstance(item, dict):
                continue
            name = normalize_name(item.get("name"))
            label_id = str(item.get("id") or "").strip()
            if not name or not label_id or label_id in seen_ids:
                continue
            key = name.casefold()
            if key in seen_names:
                continue
            seen_ids.add(label_id)
            seen_names.add(key)
            defs.append({
                "id": label_id,
                "name": name,
                "color": normalize_color(item.get("color")),
                "created_at": str(item.get("created_at") or ""),
            })

        assign: dict[str, list[str]] = {}
        raw_assign = raw.get("assign")
        if isinstance(raw_assign, dict):
            for nick, ids in raw_assign.items():
                clean_nick = normalize_nick(nick)
                if not clean_nick or not isinstance(ids, list):
                    continue
                kept = [str(i) for i in ids
                        if str(i) in seen_ids]
                kept = list(dict.fromkeys(kept))
                if kept:
                    assign[clean_nick] = kept

        raw_filter = raw.get("filter") if isinstance(raw.get("filter"), dict) else {}
        include = [str(i) for i in (raw_filter.get("include") or [])
                   if str(i) in seen_ids]
        exclude = [str(i) for i in (raw_filter.get("exclude") or [])
                   if str(i) in seen_ids]
        include = list(dict.fromkeys(include))
        # A label cannot be included and excluded at once: exclusion wins,
        # because "never message the rude ones" must not be overridable by a
        # stale include tick.
        exclude = [i for i in dict.fromkeys(exclude)]
        include = [i for i in include if i not in exclude]

        return {"defs": defs, "assign": assign,
                "filter": {"include": include, "exclude": exclude},
                "next_id": int(raw.get("next_id") or 0)}

    def _save(self, data: dict) -> None:
        payload = {
            "defs": data.get("defs") or [],
            "assign": data.get("assign") or {},
            "filter": data.get("filter") or {"include": [], "exclude": []},
            "next_id": int(data.get("next_id") or 0),
        }
        self._write(payload)

    # ── reads ────────────────────────────────────────────────────
    def defs(self) -> list[dict]:
        return self._normalized()["defs"]

    def by_id(self, label_id: str) -> dict | None:
        wanted = normalize_id(label_id)
        return next((d for d in self.defs() if d["id"] == wanted), None)

    def by_name(self, name: str) -> dict | None:
        wanted = normalize_name(name).casefold()
        if not wanted:
            return None
        return next((d for d in self.defs()
                     if d["name"].casefold() == wanted), None)

    def assignments(self) -> dict:
        return self._normalized()["assign"]

    def ids_for(self, nick) -> list[str]:
        return list(self._normalized()["assign"].get(normalize_nick(nick), []))

    def labels_for(self, nick) -> list[dict]:
        """Full label objects for one person (order = assignment order)."""
        data = self._normalized()
        index = {d["id"]: d for d in data["defs"]}
        return [index[i] for i in data["assign"].get(normalize_nick(nick), [])
                if i in index]

    def labels_map(self, nicks=None) -> dict:
        """`{nick: [label, …]}` for a set of nicks (all of them when None)."""
        data = self._normalized()
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
        data = self._normalized()
        return {"defs": data["defs"], "assign": data["assign"],
                "filter": data["filter"], "palette": list(PALETTE)}

    # ── definitions ──────────────────────────────────────────────
    def create(self, name, color: str = "") -> dict | None:
        clean = normalize_name(name)
        if not clean:
            return None
        data = self._normalized()
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
        self._save(data)
        return label

    def update(self, label_id, name=None, color=None) -> dict | None:
        data = self._normalized()
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
        self._save(data)
        return dict(label)

    def delete(self, label_id) -> bool:
        """Remove a label from the system: definition, every person, filters."""
        wanted = str(label_id or "")
        data = self._normalized()
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
        data["filter"]["include"] = [i for i in data["filter"]["include"]
                                     if i != wanted]
        data["filter"]["exclude"] = [i for i in data["filter"]["exclude"]
                                     if i != wanted]
        self._save(data)
        return True

    # ── assignment ───────────────────────────────────────────────
    def assign(self, nick, label_id) -> bool:
        clean = normalize_nick(nick)
        wanted = normalize_id(label_id)
        data = self._normalized()
        if not clean or not any(d["id"] == wanted for d in data["defs"]):
            return False
        current = data["assign"].get(clean, [])
        if wanted in current:
            return False
        data["assign"][clean] = current + [wanted]
        self._save(data)
        return True

    def unassign(self, nick, label_id) -> bool:
        clean = normalize_nick(nick)
        wanted = normalize_id(label_id)
        data = self._normalized()
        current = data["assign"].get(clean)
        if not current or wanted not in current:
            return False
        kept = [i for i in current if i != wanted]
        if kept:
            data["assign"][clean] = kept
        else:
            data["assign"].pop(clean, None)
        self._save(data)
        return True

    def set_for(self, nick, ids) -> bool:
        """Replace the whole label set of one person (used by 'Assign')."""
        clean = normalize_nick(nick)
        if not clean:
            return False
        data = self._normalized()
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
        self._save(data)
        return True

    def forget(self, nick) -> bool:
        """Drop every label of a person (used when a person is hard-deleted)."""
        clean = normalize_nick(nick)
        data = self._normalized()
        if clean not in data["assign"]:
            return False
        data["assign"].pop(clean, None)
        self._save(data)
        return True

    # ── filtering ────────────────────────────────────────────────
    def filter(self) -> dict:
        return self._normalized()["filter"]

    def set_filter(self, include=None, exclude=None) -> dict:
        data = self._normalized()
        known = {d["id"] for d in data["defs"]}
        inc = list(dict.fromkeys(str(i) for i in (include or []) if str(i) in known))
        exc = list(dict.fromkeys(str(i) for i in (exclude or []) if str(i) in known))
        inc = [i for i in inc if i not in exc]
        data["filter"] = {"include": inc, "exclude": exc}
        self._save(data)
        return dict(data["filter"])

    def clear_filter(self) -> dict:
        return self.set_filter([], [])

    @property
    def filter_active(self) -> bool:
        current = self.filter()
        return bool(current["include"] or current["exclude"])

    def allows(self, nick) -> bool:
        """Does this person pass the label filter?

        Exclusion always wins; a non-empty include set behaves as a
        whitelist. With no filter configured everyone passes, so the guard
        can never become a silent off-switch (AGENT_RULES RULE 9).
        """
        data = self._normalized()
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
        """Why `allows()` said no (for the log line), or ''."""
        data = self._normalized()
        rule = data["filter"]
        index = {d["id"]: d["name"] for d in data["defs"]}
        mine = set(data["assign"].get(normalize_nick(nick), []))
        hit = mine & set(rule["exclude"])
        if hit:
            return "labelled " + ", ".join(sorted(index.get(i, i) for i in hit))
        if rule["include"] and not (mine & set(rule["include"])):
            return ("missing label " +
                    ", ".join(sorted(index.get(i, i) for i in rule["include"])))
        return ""

    # ── undo support ─────────────────────────────────────────────
    def snapshot(self) -> dict:
        """A deep copy of the whole section, for the global undo history."""
        return copy.deepcopy(self._normalized())

    def restore(self, snapshot) -> None:
        if not isinstance(snapshot, dict):
            return
        self._save({
            "defs": snapshot.get("defs") or [],
            "assign": snapshot.get("assign") or {},
            "filter": snapshot.get("filter") or {"include": [], "exclude": []},
            "next_id": int(snapshot.get("next_id") or 0),
        })
