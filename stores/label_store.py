"""Person labels: custom coloured tags — ONE world's data, per database.

Since the unified single-DB redesign (2026-09-08, docs/
DB_CREATION_DELETION_REDESIGN_DESIGN_2026-09-08.md) labels belong to the
WORLD they were created in: the definitions live in the `labels` table and
the person→label mapping in `label_assigns` inside the active database file,
so deleting a database takes its labels with it and loading another one
shows only that world's tags (no cross-DB leakage).

The class keeps a fully SYNCHRONOUS read API because the run queue and the
engine's label guard call it from non-async code paths:

* `LabelStore(config)` — legacy/offline mode: the config.json `labels`
  section is the store (hand-assembled bridges, unit tests, or a moment
  before the archive service is up).
* `LabelStore(config, db, scheduler)` — world mode: `db` is the open
  `HistoryDB`; every mutation updates the in-memory state immediately and
  schedules an async write-through to the database (`scheduler(coro)`).
  `await store.load_from_db(db)` / `await store.switch_db(db)` move the
  world; `await store.flush_to_db()` empties the dirty queue.

Shape of the in-memory state (same as the old config section, so undo
snapshots keep working unchanged)::

    {
      "defs":   [{"id": "lbl_1", "name": "Rude", "color": "#ff3b30",
                  "created_at": "2026-09-07T18:22:31"}],
      "assign": {"Angelochenek": ["lbl_1", "lbl_2"]},
      "filter": {"include": ["lbl_3"], "exclude": ["lbl_1"]},
      "next_id": 4
    }

The include/exclude filter is a per-world setting: it persists in the
database's `app_settings` table under the key `label_filter`.

Everything is normalised on read: unknown ids, broken colours and duplicate
names can never reach the UI or crash a panel (AGENT_RULES RULE 13).
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
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

#: app_settings key that holds the world's include/exclude label filter.
FILTER_KEY = "label_filter"


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

    def __init__(self, config, db=None, scheduler=None):
        """`db`: an open `HistoryDB` (world mode), else config.json mode.
        `scheduler(coro)`: runs the async write-through (the bridge passes a
        Qt-loop helper). Mutations are always applied to memory first."""
        self._config = config
        self._db = db
        self._scheduler = scheduler
        self._memory: dict | None = None     # live raw state (world mode)
        self._dirty = False

    # ── world binding ────────────────────────────────────────────
    @property
    def db(self):
        return self._db

    @property
    def is_bound(self) -> bool:
        return self._db is not None

    def set_scheduler(self, scheduler) -> None:
        self._scheduler = scheduler

    def _initial_state(self) -> dict:
        return {"defs": [], "assign": {},
                "filter": {"include": [], "exclude": []}, "next_id": 0}

    def _memory_state(self) -> dict:
        if self._memory is None:
            raw = self._raw_config()
            if isinstance(raw, dict) and raw:
                self._memory = copy.deepcopy(raw)
            else:
                self._memory = self._initial_state()
        return self._memory

    async def load_from_db(self, db) -> dict:
        """Read one world's labels out of `db` into memory (the switch path)."""
        self._db = db
        self._dirty = False
        rows = await db.fetchdicts("SELECT id, name, color, created_at "
                                   "FROM labels ORDER BY rowid")
        defs = [{"id": str(r["id"]), "name": str(r["name"] or ""),
                 "color": str(r["color"] or DEFAULT_COLOR),
                 "created_at": str(r["created_at"] or "")} for r in rows]
        assign: dict[str, list[str]] = {}
        known = {d["id"] for d in defs}
        pairs = await db.fetchall("SELECT nick, label_id FROM label_assigns "
                                  "ORDER BY rowid")
        for nick, label_id in pairs:
            if label_id in known:
                assign.setdefault(str(nick), []).append(str(label_id))
        filter_state = {"include": [], "exclude": []}
        raw_filter = await db.scalar(
            "SELECT value FROM app_settings WHERE key=?", (FILTER_KEY,), "")
        if raw_filter:
            try:
                data = json.loads(str(raw_filter))
                if isinstance(data, dict):
                    filter_state = {"include": [str(i) for i in
                                                data.get("include") or []],
                                    "exclude": [str(i) for i in
                                                data.get("exclude") or []]}
            except (TypeError, ValueError):
                pass
        try:
            next_id = int(await db.scalar(
                "SELECT value FROM schema_meta WHERE key='labels_next_id'",
                (), 0))
        except (TypeError, ValueError):
            next_id = 0  # corrupt meta must not brick the world load
        self._memory = {"defs": defs, "assign": assign,
                        "filter": filter_state, "next_id": next_id}
        return self._normalized()

    async def flush_to_db(self) -> None:
        """Write the dirty in-memory state into the bound world's tables."""
        if self._db is None or not self._dirty:
            return
        db = self._db
        data = self._normalized()
        stamp = datetime.now().isoformat(timespec="seconds")
        await db.execute("DELETE FROM labels")
        for label in data["defs"]:
            await db.execute(
                "INSERT INTO labels(id, name, color, created_at) "
                "VALUES(?,?,?,?)",
                (label["id"], label["name"], label["color"],
                 label["created_at"]))
        await db.execute("DELETE FROM label_assigns")
        for nick, ids in data["assign"].items():
            for label_id in ids:
                await db.execute(
                    "INSERT OR IGNORE INTO label_assigns(nick, label_id) "
                    "VALUES(?,?)", (nick, label_id))
        await db.execute(
            "INSERT INTO app_settings(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (FILTER_KEY, json.dumps(data["filter"]), stamp))
        await db.execute(
            "INSERT INTO schema_meta(key, value) VALUES('labels_next_id',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(int(data["next_id"])),))
        await db.commit()
        self._dirty = False

    def _schedule_flush(self) -> None:
        if self._db is None:
            return
        self._dirty = True
        if self._scheduler is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return                          # flushed on switch/close instead
        # the scheduler (the bridge) starts the coroutine on the live loop
        try:
            self._scheduler(self._guarded_flush())
        except Exception as exc:            # noqa: BLE001
            log.warning("cannot schedule label flush: %s", exc)

    async def _guarded_flush(self) -> None:
        try:
            await self.flush_to_db()
        except Exception as exc:            # noqa: BLE001
            log.warning("label write-through failed: %s", exc)

    # ── raw state access ─────────────────────────────────────────
    def _raw_config(self) -> dict:
        data = None
        if self._config is not None:
            data = self._config.get(self.SECTION, default=None)
        return data if isinstance(data, dict) else {}

    def _raw(self) -> dict:
        if self._db is not None:
            return self._memory_state()
        data = self._raw_config()
        if isinstance(data, dict) and data:
            return data
        return self._memory_state()

    def _write(self, data: dict) -> None:
        self._memory = copy.deepcopy(data)
        if self._db is not None:
            self._schedule_flush()
            return
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
        defs = snapshot.get("defs")
        assign = snapshot.get("assign")
        filt = snapshot.get("filter")
        try:
            next_id = int(snapshot.get("next_id") or 0)
        except (TypeError, ValueError):
            next_id = 0
        # Coerce ill-typed values so garbage can neither brick reads nor be
        # persisted back to the config file verbatim (LBL-17).
        self._save({
            "defs": defs if isinstance(defs, list) else [],
            "assign": assign if isinstance(assign, dict) else {},
            "filter": filt if isinstance(filt, dict)
            else {"include": [], "exclude": []},
            "next_id": next_id,
        })
