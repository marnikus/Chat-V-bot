"""Person labels — facade (AREA B).

Definitions, assignments and filter are delegated to helpers; IO to DB is in
``_label_io``.  Public API is byte-identical to the pre-split version.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from datetime import datetime

log = logging.getLogger("chatbot")

from stores._label_defs import PALETTE, DEFAULT_COLOR, MAX_NAME, normalize_color, normalize_name, normalize_nick, normalize_id, LabelDefinitions
from stores._label_assign import LabelAssignments
from stores._label_filter import LabelFilter
from stores._label_io import LabelStoreIO, FILTER_KEY

# re-export for callers that import from label_store
__all__ = ["LabelStore", "PALETTE", "DEFAULT_COLOR", "normalize_color", "normalize_name", "normalize_nick", "normalize_id", "FILTER_KEY"]

class LabelStore:
    """Definitions, per-person assignment and the include/exclude filter."""

    SECTION = "labels"

    def __init__(self, config, db=None, scheduler=None):
        self._config = config
        self._db = db
        self._scheduler = scheduler
        self._memory: dict | None = None
        self._dirty = False
        self._defs = LabelDefinitions(self)
        self._assigns = LabelAssignments(self)
        self._filter = LabelFilter(self)
        self._io = LabelStoreIO(self)

    @property
    def db(self):
        return self._db

    @property
    def is_bound(self) -> bool:
        return self._db is not None

    def set_scheduler(self, scheduler) -> None:
        self._scheduler = scheduler

    def _initial_state(self) -> dict:
        return {"defs": [], "assign": {}, "filter": {"include": [], "exclude": []}, "next_id": 0}

    def _memory_state(self) -> dict:
        if self._memory is None:
            raw = self._raw_config()
            if isinstance(raw, dict) and raw:
                self._memory = copy.deepcopy(raw)
            else:
                self._memory = self._initial_state()
        return self._memory

    async def load_from_db(self, db) -> dict:
        return await self._io.load_from_db(db)

    async def flush_to_db(self) -> None:
        return await self._io.flush_to_db()

    def _schedule_flush(self) -> None:
        return self._io._schedule_flush()

    async def _guarded_flush(self) -> None:
        return await self._io._guarded_flush()

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
            defs.append({"id": label_id, "name": name, "color": normalize_color(item.get("color")), "created_at": str(item.get("created_at") or "")})
        assign: dict[str, list[str]] = {}
        raw_assign = raw.get("assign")
        if isinstance(raw_assign, dict):
            for nick, ids in raw_assign.items():
                clean_nick = normalize_nick(nick)
                if not clean_nick or not isinstance(ids, list):
                    continue
                kept = [str(i) for i in ids if str(i) in seen_ids]
                kept = list(dict.fromkeys(kept))
                if kept:
                    assign[clean_nick] = kept
        raw_filter = raw.get("filter") if isinstance(raw.get("filter"), dict) else {}
        include = [str(i) for i in (raw_filter.get("include") or []) if str(i) in seen_ids]
        exclude = [str(i) for i in (raw_filter.get("exclude") or []) if str(i) in seen_ids]
        include = list(dict.fromkeys(include))
        exclude = [i for i in dict.fromkeys(exclude)]
        include = [i for i in include if i not in exclude]
        return {"defs": defs, "assign": assign, "filter": {"include": include, "exclude": exclude}, "next_id": int(raw.get("next_id") or 0)}

    def _save(self, data: dict) -> None:
        payload = {"defs": data.get("defs") or [], "assign": data.get("assign") or {}, "filter": data.get("filter") or {"include": [], "exclude": []}, "next_id": int(data.get("next_id") or 0)}
        self._write(payload)

    def defs(self) -> list[dict]:
        return self._defs.defs()

    def by_id(self, label_id) -> dict | None:
        return self._defs.by_id(label_id)

    def by_name(self, name) -> dict | None:
        return self._defs.by_name(name)

    def assignments(self) -> dict:
        return self._assigns.assignments()

    def ids_for(self, nick) -> list[str]:
        return self._assigns.ids_for(nick)

    def labels_for(self, nick) -> list[dict]:
        return self._assigns.labels_for(nick)

    def labels_map(self, nicks=None) -> dict:
        return self._assigns.labels_map(nicks)

    def state(self) -> dict:
        data = self._normalized()
        return {"defs": data["defs"], "assign": data["assign"], "filter": data["filter"], "palette": list(PALETTE)}

    def create(self, name, color: str = "") -> dict | None:
        return self._defs.create(name, color)

    def update(self, label_id, name=None, color=None) -> dict | None:
        return self._defs.update(label_id, name, color)

    def delete(self, label_id) -> bool:
        return self._defs.delete(label_id)

    def assign(self, nick, label_id) -> bool:
        return self._assigns.assign(nick, label_id)

    def unassign(self, nick, label_id) -> bool:
        return self._assigns.unassign(nick, label_id)

    def set_for(self, nick, ids) -> bool:
        return self._assigns.set_for(nick, ids)

    def forget(self, nick) -> bool:
        return self._assigns.forget(nick)

    def filter(self) -> dict:
        return self._filter.filter()

    def set_filter(self, include=None, exclude=None) -> dict:
        return self._filter.set_filter(include, exclude)

    def clear_filter(self) -> dict:
        return self._filter.clear_filter()

    @property
    def filter_active(self) -> bool:
        return self._filter.filter_active

    def allows(self, nick) -> bool:
        return self._filter.allows(nick)

    def reject_reason(self, nick) -> str:
        return self._filter.reject_reason(nick)

    def snapshot(self) -> dict:
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
        self._save({"defs": defs if isinstance(defs, list) else [], "assign": assign if isinstance(assign, dict) else {}, "filter": filt if isinstance(filt, dict) else {"include": [], "exclude": []}, "next_id": next_id})
