"""LabelState — the one payload shape, read and written in one place.

Extracted from `stores/label_store.py` by the AREA B2 split (design §2.5).
Where the payload currently lives — the config.json `labels` section, the
active world's in-memory copy, or both — is this module's business, and only
its: `_raw` is the single reader, `_write` the single writer. Keeping the two
together is what guarantees that a mutation the UI sees is the mutation that
reaches the file or the database.
    """

from __future__ import annotations

import copy

from stores.label_rules import normalize_color, normalize_name, normalize_nick


class LabelState:
    """The live label payload: config section, world memory, normalisation.

    Nothing here touches the database or the config object directly; it reads
    what the aggregate points at and normalises it.
"""

    def __init__(self, owner) -> None:
        self._owner = owner

    def _initial_state(self) -> dict:
        return {"defs": [], "assign": {},
                "filter": {"include": [], "exclude": []}, "next_id": 0}

    def _memory_state(self) -> dict:
        if self._owner._memory is None:
            raw = self._raw_config()
            if isinstance(raw, dict) and raw:
                self._owner._memory = copy.deepcopy(raw)
            else:
                self._owner._memory = self._initial_state()
        return self._owner._memory

    def _raw_config(self) -> dict:
        data = None
        if self._owner._config is not None:
            data = self._owner._config.get(self._owner.SECTION, default=None)
        return data if isinstance(data, dict) else {}

    def _raw(self) -> dict:
        if self._owner._db is not None:
            return self._memory_state()
        data = self._raw_config()
        if isinstance(data, dict) and data:
            return data
        return self._memory_state()

    def _write(self, data: dict) -> None:
        self._owner._memory = copy.deepcopy(data)
        if self._owner._db is not None:
            self._owner._schedule_flush()
            return
        if self._owner._config is None:
            return
        self._owner._config.set(self._owner.SECTION, copy.deepcopy(data))
        self._owner._config.save()

    def _save(self, data: dict) -> None:
        payload = {
            "defs": data.get("defs") or [],
            "assign": data.get("assign") or {},
            "filter": data.get("filter") or {"include": [], "exclude": []},
            "next_id": int(data.get("next_id") or 0),
        }
        self._write(payload)

    def _normalized(self) -> dict:
        raw = self._raw()
        defs, seen_ids = self._normalize_defs(raw)
        assign = self._normalize_assign(raw, seen_ids)
        include, exclude = self._normalize_filter(raw, seen_ids)
        return {"defs": defs, "assign": assign,
                "filter": {"include": include, "exclude": exclude},
                "next_id": int(raw.get("next_id") or 0)}

    @staticmethod
    def _normalize_defs(raw: dict) -> tuple[list, set]:
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
        return defs, seen_ids

    @staticmethod
    def _normalize_assign(raw: dict, seen_ids: set) -> dict:
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
        return assign

    @staticmethod
    def _normalize_filter(raw: dict, seen_ids: set) -> tuple[list, list]:
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
        return include, exclude
