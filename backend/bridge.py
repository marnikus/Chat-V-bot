"""QWebChannel bridge: routes calls between JS and Python backend."""

import asyncio
import copy
import json
import logging
import os
import uuid
from datetime import datetime
from PySide6.QtCore import QObject, Signal, Slot
from backend.cdp_client import CDPClient
from backend.user_memory import UserMemory
from backend.criteria_engine import CriteriaEngine
from backend.action_engine import ActionEngine, normalize_blocks
from backend.config_manager import ConfigManager, MAX_STACK_HISTORY
from backend.db_manager import DbManager
from backend.db_paths import same_database
from backend.label_store import LabelStore
from backend.preset_store import PresetStore
from backend.tab_matcher import best_matches

log = logging.getLogger("chatbot")


class Bridge(QObject):
    users_updated = Signal(str)
    step_complete = Signal(str, str)
    step_started = Signal(int, str, str)     # index, block_id, user_nick
    stack_complete = Signal()
    log_message = Signal(str, str)           # message, level
    connection_status = Signal(str)
    stats_updated = Signal(str)
    tabs_received = Signal(str)
    preset_list_updated = Signal(str)        # JSON: stack presets
    template_list_updated = Signal(str)      # JSON: template presets
    url_presets_updated = Signal(str)        # JSON: url preset list
    custom_blocks_updated = Signal(str)      # JSON: custom block presets
    tab_match_result = Signal(str, str)      # query, JSON matches
    users_deleted = Signal(str, int)         # JSON nicks, deleted count
    person_found = Signal(str)               # JSON: one newly collected person
    person_removed = Signal(str)             # JSON: one purged (filtered-out) person
    stack_loaded = Signal(str, str)          # name, JSON blocks
    grid_layout_changed = Signal(str)        # JSON canonical grid payload
    grid_layout_persisted = Signal(bool)     # close-time save acknowledgment
    template_loaded = Signal(str, str)       # name, body
    history_changed = Signal()               # global timeline grew / moved
    # ── message archive (Person History / User Database / Collector) ──
    history_page_ready = Signal(str, str)    # req_id, JSON page
    history_search_ready = Signal(str, str)  # req_id, JSON results
    history_stats_ready = Signal(str, str)   # req_id, JSON stats
    userdb_page_ready = Signal(str, str)     # req_id, JSON persons / db stats
    userdb_changed = Signal(str)             # JSON {action, nick}
    media_ready = Signal(str, str)           # req_id, JSON media info
    collector_status = Signal(str)           # JSON collector state payload
    collector_log = Signal(str)              # JSON {ts, level, message, nick}
    history_appended = Signal(str)           # JSON {nick, items, added}
    history_reset = Signal(str)        # reset boundary, no old message data
    my_nick_changed = Signal(str)            # the configured "my nick"
    history_error = Signal(str, str)         # scope, message
    # ── person labels / database management ──
    labels_changed = Signal(str)             # JSON: the whole labels state
    db_info_ready = Signal(str, str)         # req_id, JSON db size info
    db_changed = Signal(str)                 # JSON {action, path, ok}

    def __init__(self, cdp, memory, criteria, engine, config,
                 presets: PresetStore | None = None, parent=None):
        super().__init__(parent)
        self._cdp, self._memory = cdp, memory
        self._criteria, self._engine = criteria, engine
        self._config, self._message_text = config, ""
        # Presets live in the SAME single JSON file as everything else.
        self._history = None                 # set by attach_history()
        self._presets = presets or PresetStore(config=self._config)
        self._presets.import_legacy()
        # Person labels live in the same single settings file; the run queue
        # asks them who may be worked on.
        self._labels = LabelStore(self._config)
        self._dbs = DbManager(config=self._config)
        self._install_label_guard()
        self._cdp.connected.connect(lambda: self.connection_status.emit("connected"))
        self._cdp.disconnected.connect(lambda: self.connection_status.emit("disconnected"))
        self._cdp.error.connect(lambda e: self.connection_status.emit("error"))
        self._engine.step_complete.connect(self.step_complete.emit)
        self._engine.step_started.connect(self.step_started.emit)
        self._engine.stack_complete.connect(self.stack_complete.emit)
        self._engine.log_msg.connect(lambda m: self.log_message.emit(m, "info"))
        self._engine.debug_msg.connect(lambda m, l: self.log_message.emit(m, l))
        # A person was collected mid-scroll: surface it and refresh the table
        # right away rather than at the end of the run.
        self._engine.person_found.connect(self._on_person_found)
        # A person failed the filter and was destroyed: drop them from the table.
        self._engine.person_removed.connect(self._on_person_removed)
        # The engine just marked a person messaged during a run: flip the row
        # (and stats) live instead of waiting for the next explicit refresh.
        self._engine.person_marked.connect(self._on_person_marked)
        # Whatever a run did (marking, purges, seek-only passes), the table
        # must end up in sync with SQLite — restart is not a refresh step.
        self._engine.stack_complete.connect(
            lambda: asyncio.ensure_future(self._refresh_users()))

    def _on_person_found(self, payload: str) -> None:
        """Live update: a person just passed the filter during Scroll & Parse."""
        self.person_found.emit(payload)
        asyncio.ensure_future(self._refresh_users())

    def _on_person_marked(self, nick: str) -> None:
        """Live update: a run just messaged `nick` — refresh the table now."""
        asyncio.ensure_future(self._refresh_users())

    def _on_person_removed(self, payload: str) -> None:
        """Live update: a person failed the filter and was purged."""
        self.person_removed.emit(payload)
        asyncio.ensure_future(self._refresh_users())

    @staticmethod
    def _clean_blocks(blocks):
        """Strip retired block keys (e.g. use_panel_filters) before storing
        or emitting a stack, so dead controls never round-trip back to the
        UI. JS performs the fuller migration (it also back-fills missing
        defaults); this is the server-side safety net."""
        return normalize_blocks(blocks)

    @classmethod
    def _clean_history(cls, hist):
        if not isinstance(hist, list):
            return []
        return [cls._clean_blocks(entry) for entry in hist
                if isinstance(entry, list)]

    # ── people-list snapshots for the global undo history ─────────
    @staticmethod
    def _people_row(u) -> dict:
        """Full serialisable row for one person (every DB column)."""
        return {"nick": u.nick, "gender": u.gender,
                "registered": bool(u.registered),
                "anonymous": bool(u.anonymous), "guest": bool(u.guest),
                "first_seen": u.first_seen or "", "last_seen": u.last_seen or "",
                "messaged": bool(u.messaged),
                "message_count": int(u.message_count or 0),
                "last_messaged": u.last_messaged, "notes": u.notes or ""}

    async def _people_rows(self) -> list[dict]:
        """Full snapshot of the people list (all columns)."""
        users = await self._memory.get_all()
        return [self._people_row(u) for u in users]

    async def _push_people_entry(self, before: list[dict],
                                 after: list[dict]) -> bool:
        """Record one people-list edit in the global history.

        The entry stores BOTH halves so the action can be reversed with a
        single Ctrl+Z no matter what stack/grid edits surround it in the
        timeline. Nothing is pushed for a no-op (identical snapshots).
        """
        if before == after:
            return False
        self._push_global("people", {"before": before, "after": after})
        return True

    def _apply_people(self, rows) -> None:
        """Restore the people list to a snapshot (async, then re-emit)."""
        rows = [dict(r) for r in (rows or [])]
        asyncio.ensure_future(self._do_apply_people(rows))

    async def _do_apply_people(self, rows: list[dict]) -> None:
        try:
            await self._memory.replace_all(rows)
            self.log_message.emit(
                f"↩ People list restored — {len(rows)} person(s)", "info")
        except Exception as exc:
            self.log_message.emit(f"❌ People-list restore failed: {exc}",
                                  "error")
        await self._refresh_users()

    # ── person labels ────────────────────────────────────────────
    @property
    def label_store(self) -> LabelStore:
        """Lazily built so hand-assembled Bridges (tests) work unchanged."""
        store = getattr(self, "_labels", None)
        if store is None:
            store = LabelStore(self._config)
            self._labels = store
        return store

    @property
    def db_manager(self) -> DbManager:
        manager = getattr(self, "_dbs", None)
        if manager is None:
            manager = DbManager(config=self._config)
            self._dbs = manager
        return manager

    def _install_label_guard(self) -> None:
        """Let a run skip people carrying an excluded label."""
        engine = getattr(self, "_engine", None)
        if engine is None:
            return
        try:
            engine.label_filter = self.label_store.allows
            engine.label_reason = self.label_store.reject_reason
        except Exception as exc:                      # noqa: BLE001
            log.debug("label guard not installed: %s", exc)

    def _emit_labels(self) -> None:
        state = self.label_store.state()
        self.labels_changed.emit(json.dumps(state, ensure_ascii=False))

    def _labels_edit(self, mutate, message: str = "") -> bool:
        """Run a labels mutation as ONE reversible entry of the timeline.

        Every label action (create/delete/recolour/assign/unassign/filter)
        stores the section before and after, so a single Ctrl+Z reverses it
        no matter what other panels edited in between (RULE 12).
        """
        store = self.label_store
        before = store.snapshot()
        changed = bool(mutate(store))
        if not changed:
            return False
        after = store.snapshot()
        if self._values_equal(before, after):
            return False
        self._push_global("labels", {"before": before, "after": after})
        self._emit_labels()
        if message:
            self.log_message.emit(message, "info")
        # Labels can hide people from the queue, so the # column changes.
        self._schedule(self._refresh_users())
        return True

    def _labels_for_nicks(self, nicks) -> dict:
        try:
            return self.label_store.labels_map(nicks)
        except Exception as exc:                      # noqa: BLE001
            log.warning("labels unavailable: %s", exc)
            return {}

    @Slot(result=str)
    def get_labels(self):
        """The whole labels state: definitions, assignment map, filter."""
        return json.dumps(self.label_store.state(), ensure_ascii=False)

    @Slot(str, str, result=str)
    def label_create(self, name, color):
        created = {}

        def mutate(store):
            made = store.create(name, color)
            if made:
                created.update(made)
            return bool(made)

        if not self._labels_edit(mutate, ""):
            self.log_message.emit(
                f"⚠ Label “{name}” already exists (or has no name)", "warn")
            return "null"
        self.log_message.emit(f"🏷 Label “{created.get('name')}” created",
                              "success")
        return json.dumps(created, ensure_ascii=False)

    @Slot(str, str, str, result=bool)
    def label_update(self, label_id, name, color):
        return self._labels_edit(
            lambda store: bool(store.update(label_id,
                                            name if name else None,
                                            color if color else None)),
            "🏷 Label updated")

    @Slot(str, result=bool)
    def label_delete(self, label_id):
        label = self.label_store.by_id(label_id)
        title = label["name"] if label else label_id
        return self._labels_edit(lambda store: store.delete(label_id),
                                 f"🗑 Label “{title}” removed everywhere")

    @Slot(str, str, result=bool)
    def label_assign(self, nick, label_id):
        return self._labels_edit(lambda store: store.assign(nick, label_id),
                                 "")

    @Slot(str, str, result=bool)
    def label_unassign(self, nick, label_id):
        return self._labels_edit(lambda store: store.unassign(nick, label_id),
                                 "")

    @Slot(str, str, result=bool)
    def label_set_for(self, nick, ids_json):
        try:
            ids = json.loads(ids_json or "[]")
        except json.JSONDecodeError:
            return False
        if not isinstance(ids, list):
            return False
        return self._labels_edit(lambda store: store.set_for(nick, ids),
                                 f"🏷 Labels of “{nick}” updated")

    @Slot(str, result=bool)
    def label_set_filter(self, rule_json):
        try:
            rule = json.loads(rule_json or "{}")
        except json.JSONDecodeError:
            return False
        if not isinstance(rule, dict):
            return False
        include = rule.get("include") or []
        exclude = rule.get("exclude") or []
        return self._labels_edit(
            lambda store: store.set_filter(include, exclude) is not None,
            "🏷 Label filter updated")

    @Slot(result=bool)
    def label_clear_filter(self):
        return self._labels_edit(
            lambda store: bool(store.filter_active) and
            store.clear_filter() is not None,
            "🏷 Label filter cleared")

    # ── one global undo history ─────────────────────────────────
    # Stack edits and grid edits share this timeline.  The old stack/grid
    # histories are accepted only as a one-time migration source; no new
    # edit writes either legacy key.
    @staticmethod
    def _values_equal(a, b) -> bool:
        try:
            return json.dumps(a, sort_keys=True, ensure_ascii=False) == \
                   json.dumps(b, sort_keys=True, ensure_ascii=False)
        except Exception:
            return a == b

    _stacks_equal = _values_equal

    @staticmethod
    def _history_entry(kind, value):
        return {"kind": kind, "value": copy.deepcopy(value)}

    def _migrate_global_history(self) -> tuple[list, int]:
        """Build the global timeline from pre-global-history config once.

        This keeps existing presets usable after the history model changes.
        The returned list is also written to the new keys so subsequent edits
        never need the legacy per-surface histories.
        """
        raw = self._config.get_state("undo_history", None)
        if isinstance(raw, list) and raw:
            history = []
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                if entry.get("kind") == "stack" and isinstance(entry.get("value"), list):
                    history.append(self._history_entry("stack", entry["value"]))
                elif entry.get("kind") == "grid" and isinstance(entry.get("value"), str):
                    canonical, err = self._canonical_grid_payload(entry["value"])
                    if not err:
                        history.append(self._history_entry("grid", canonical))
                elif entry.get("kind") == "people" and isinstance(entry.get("value"), dict):
                    value = entry["value"]
                    if isinstance(value.get("before"), list) and \
                            isinstance(value.get("after"), list):
                        history.append(self._history_entry("people", value))
                elif (entry.get("kind") in ("labels", "archive", "dbconn")
                        and isinstance(entry.get("value"), dict)):
                    history.append(self._history_entry(entry["kind"],
                                                       entry["value"]))
            index = self._config.get_state("undo_history_index", len(history) - 1)
            index = index if isinstance(index, int) else len(history) - 1
            index = max(-1, min(index, len(history) - 1))
            return history, index

        history = []
        legacy_stacks = self._config.get_state("stack_history", [])
        if isinstance(legacy_stacks, list):
            history.extend(self._history_entry("stack", s)
                           for s in legacy_stacks if isinstance(s, list))
        legacy_grids = self._config.get_state("grid_layout_history", [])
        if isinstance(legacy_grids, list):
            for grid_value in legacy_grids:
                if not isinstance(grid_value, str):
                    continue
                canonical, err = self._canonical_grid_payload(grid_value)
                if not err:
                    history.append(self._history_entry("grid", canonical))
        grid = self._config.get_state("grid_layout", None)
        if isinstance(grid, str) and grid:
            canonical, err = self._canonical_grid_payload(grid)
            if not err:
                # A stored grid is a current application state. Add it after
                # migrated stack entries so it can participate in the next undo.
                current = history[-1]["value"] if history and history[-1]["kind"] == "grid" else None
                if canonical != current:
                    history.append(self._history_entry("grid", canonical))
                self._config.set_state(grid_layout=canonical)
        if len(history) > MAX_STACK_HISTORY:
            history = history[-MAX_STACK_HISTORY:]
        has_grid = bool(history and history[-1].get("kind") == "grid")
        legacy_index = self._config.get_state("stack_history_index", -1)
        if has_grid:
            index = len(history) - 1
        elif isinstance(legacy_index, int):
            index = max(-1, min(legacy_index, len(history) - 1))
        else:
            index = len(history) - 1
        self._config.set_state(undo_history=history,
                               undo_history_index=index)
        return history, index

    def _get_global_history(self) -> tuple[list, int]:
        history, index = self._migrate_global_history()
        history = copy.deepcopy(history)
        # Server-side safety net: scrub retired block keys from every stack
        # snapshot as it is read back (undo/redo, history projections,
        # app-state restore) so dead controls can never reach the UI.
        cleaned = []
        for entry in history:
            if not isinstance(entry, dict):
                continue
            if entry.get("kind") == "stack":
                entry["value"] = self._clean_blocks(entry["value"])
            cleaned.append(entry)
        return cleaned, index

    def _set_global_history(self, history: list, index: int) -> None:
        self._config.set_state(undo_history=copy.deepcopy(history),
                               undo_history_index=index)

    #: Entries that are reversible COMMANDS ({before, after} or an op
    #: description) rather than full state snapshots. Undoing the tip of one
    #: of these reverses it in a single step; stack/grid entries are
    #: snapshots and are undone by stepping back onto the previous one.
    COMMAND_KINDS = ("people", "labels", "archive", "dbconn")
    #: how each command kind is described in the log line
    UNDO_LABELS = {"people": "people list restored",
                   "labels": "labels restored",
                   "archive": "archive restored",
                   "dbconn": "database restored"}
    HISTORY_KINDS = ("stack", "grid") + COMMAND_KINDS

    def _push_global(self, kind: str, value) -> tuple[list, int]:
        if kind not in self.HISTORY_KINDS:
            raise ValueError(f"unknown history kind: {kind}")
        history, index = self._get_global_history()
        entry = self._history_entry(kind, value)
        if (0 <= index < len(history) and
                self._values_equal(history[index], entry)):
            return history, index
        if index < len(history) - 1:
            history = history[:index + 1]
        history.append(entry)
        index = len(history) - 1
        if len(history) > MAX_STACK_HISTORY:
            overflow = len(history) - MAX_STACK_HISTORY
            history = history[overflow:]
            index -= overflow
        self._set_global_history(history, index)
        self.history_changed.emit()
        return history, index

    def _get_history(self) -> tuple[list, int]:
        """Compatibility projection of stack entries from the global history."""
        history, global_index = self._get_global_history()
        stacks = [e["value"] for e in history if e.get("kind") == "stack"]
        stack_index = sum(1 for e in history[:global_index + 1]
                          if e.get("kind") == "stack") - 1
        return stacks, max(-1, min(stack_index, len(stacks) - 1))

    def _set_history(self, history: list, index: int, save: bool = True) -> None:
        """Legacy compatibility; new code must use the global timeline."""
        entries = [self._history_entry("stack", self._clean_blocks(value))
                   for value in history if isinstance(value, list)]
        self._set_global_history(entries, max(-1, min(index, len(entries) - 1)))

    def _get_hist(self, kind: str) -> tuple[list, int]:
        """Compatibility projection used by older integrations and tests."""
        history, global_index = self._get_global_history()
        values = [e["value"] for e in history if e.get("kind") == kind]
        local_index = sum(1 for e in history[:global_index + 1]
                          if e.get("kind") == kind) - 1
        return values, max(-1, min(local_index, len(values) - 1))

    def _set_hist(self, kind: str, hist: list, idx: int) -> None:
        # Deliberately not a separate history.  Preserve the API for old
        # callers by replacing the global timeline with these entries.
        if kind == "stack":
            hist = [self._clean_blocks(value) for value in hist]
        history = [self._history_entry(kind, value) for value in hist]
        self._set_global_history(history, max(-1, min(idx, len(history) - 1)))

    def _push_hist(self, kind: str, value) -> tuple[list, int]:
        """Compatibility name that always pushes to the global timeline."""
        if kind == "stack":
            value = self._clean_blocks(value)
        self._push_global(kind, value)
        return self._get_hist(kind)

    # ── grid layout (flexible grid / sash layout) ────────────────
    #: window sets per layout version — an older payload is UPGRADED, never
    #: rejected, so nobody loses their arrangement on an app update
    V1_WINDOW_IDS = {"stats", "filters", "stack", "config", "composer",
                     "people", "log"}
    V2_WINDOW_IDS = V1_WINDOW_IDS | {"history", "userdb", "collector"}
    V3_WINDOW_IDS = V2_WINDOW_IDS | {"labels", "dbconn"}
    LEGACY_WINDOW_IDS = V1_WINDOW_IDS            # kept for older callers
    NEW_WINDOW_IDS = V3_WINDOW_IDS - V1_WINDOW_IDS
    WINDOW_IDS = V3_WINDOW_IDS
    GRID_VERSION = 3
    MIN_GRID_SIZE = 4

    @classmethod
    def _node_type(cls, node):
        """Read both spellings, with SashCore's `t` as the canonical one."""
        return node.get("t", node.get("type")) if isinstance(node, dict) else None

    @classmethod
    def _normalize_grid_tree(cls, node, depth: int = 0):
        """Return a canonical `t` tree or an explanatory validation error."""
        if depth > 12:
            return None, "tree too deep"
        if not isinstance(node, dict):
            return None, "node must be an object"
        node_type = cls._node_type(node)
        if node_type == "leaf":
            if not isinstance(node.get("id"), str) or not node.get("id"):
                return None, "leaf without id"
            return {"t": "leaf", "id": node["id"]}, None
        if node_type != "split":
            return None, "unknown node type"
        if node.get("dir") not in ("row", "col"):
            return None, "bad dir"
        kids, sizes = node.get("children"), node.get("sizes")
        if not isinstance(kids, list) or len(kids) < 2:
            return None, "split needs >=2 children"
        if not isinstance(sizes, list) or len(sizes) != len(kids):
            return None, "sizes must match children"
        clean_sizes = []
        for size in sizes:
            if (isinstance(size, bool) or not isinstance(size, (int, float)) or
                    size < cls.MIN_GRID_SIZE):
                return None, "bad size value (panel below minimum size)"
            clean_sizes.append(size)
        if not 99.5 <= sum(clean_sizes) <= 100.5:
            return None, "sizes must sum to 100"
        clean_kids = []
        for kid in kids:
            clean, err = cls._normalize_grid_tree(kid, depth + 1)
            if err:
                return None, err
            clean_kids.append(clean)
        return {"t": "split", "dir": node["dir"],
                "children": clean_kids, "sizes": clean_sizes}, None

    @classmethod
    def _validate_grid_tree(cls, node, depth: int = 0):
        """Validate both legacy `type` and current SashCore `t` nodes."""
        _, err = cls._normalize_grid_tree(node, depth)
        return err

    @classmethod
    def _leaf_ids(cls, node, out=None):
        out = [] if out is None else out
        if isinstance(node, dict):
            node_type = cls._node_type(node)
            if node_type == "leaf":
                out.append(node.get("id"))
            elif node_type == "split":
                for kid in node.get("children") or []:
                    cls._leaf_ids(kid, out)
        return out

    @classmethod
    def _parse_grid_payload(cls, raw: str):
        """Return (canonical tree, None) or (None, error)."""
        try:
            data = json.loads(raw)
        except Exception as exc:
            return None, f"bad JSON ({exc})"
        if not isinstance(data, dict):
            return None, "payload must be an object"
        version = data.get("v")
        if not isinstance(version, int) or not 1 <= version <= cls.GRID_VERSION:
            return None, f"unsupported version {version!r}"
        tree, err = cls._normalize_grid_tree(data.get("tree"))
        if err:
            return None, err
        got = sorted(i for i in cls._leaf_ids(tree) if i)
        known = {1: sorted(cls.V1_WINDOW_IDS), 2: sorted(cls.V2_WINDOW_IDS)}
        if version < cls.GRID_VERSION and got == known.get(version):
            # A layout saved before newer windows existed. Rejecting it would
            # throw away the user's arrangement on first start after the
            # update, so it is upgraded instead.
            tree = cls._migrate_grid_tree(tree)
            got = sorted(i for i in cls._leaf_ids(tree) if i)
        if got != sorted(cls.WINDOW_IDS):
            return None, "window set mismatch (every window must appear once)"
        return tree, None

    @classmethod
    def _migrate_grid_tree(cls, tree: dict) -> dict:
        """Keep the stored arrangement and append whatever windows are new.

        Works for any older version: the missing windows become one extra
        row along the bottom (mirrors SashCore.migrate() in the UI).
        """
        present = {i for i in cls._leaf_ids(tree) if i}
        missing = [i for i in sorted(cls.WINDOW_IDS) if i not in present]
        if not missing:
            return tree
        if len(missing) == 1:
            extra = {"t": "leaf", "id": missing[0]}
        else:
            share = round(100 / len(missing), 4)
            sizes = [share] * len(missing)
            sizes[0] = round(100 - share * (len(missing) - 1), 4)
            extra = {"t": "split", "dir": "row",
                     "children": [{"t": "leaf", "id": i} for i in missing],
                     "sizes": sizes}
        room = min(40, max(cls.MIN_GRID_SIZE, len(missing) * 9))
        return {"t": "split", "dir": "col", "children": [tree, extra],
                "sizes": [100 - room, room]}

    @classmethod
    def _canonical_grid_payload(cls, raw: str):
        tree, err = cls._parse_grid_payload(raw)
        if err:
            return None, err
        return json.dumps({"v": cls.GRID_VERSION, "tree": tree},
                          ensure_ascii=False, separators=(",", ":")), None

    @Slot(result=str)
    def get_grid_layout(self):
        """Serialized canonical grid tree, or empty before first customization."""
        raw = self._config.get_state("grid_layout", None)
        if not isinstance(raw, str) or not raw:
            return ""
        payload, err = self._canonical_grid_payload(raw)
        return payload if not err else ""

    @Slot(bool)
    def set_block_config_pinned(self, pinned):
        """Persist the Block Config keep-open pin across app restarts."""
        self._config.set_state(block_config_pinned=bool(pinned))

    @Slot(str, result=bool)
    def save_grid_layout(self, layout_json):
        """Validate and persist a grid as one entry in global undo history."""
        payload, err = self._canonical_grid_payload(layout_json or "")
        if err:
            log.warning("Grid layout rejected: %s", err)
            self.log_message.emit(f"⚠ Grid layout not saved: {err}", "warn")
            self.grid_layout_persisted.emit(False)
            return False
        self._config.set_state(grid_layout=payload)
        self._push_global("grid", payload)
        # Emit only after config.json and the global history have both been
        # updated. MainWindow uses this as the close-time flush acknowledgment.
        self.grid_layout_persisted.emit(True)
        return True

    @Slot(result=str)
    def reset_grid_layout(self):
        """Restore the default grid with every window visible."""
        payload = json.dumps({"v": self.GRID_VERSION,
                              "tree": self._default_grid_tree()},
                             ensure_ascii=False, separators=(",", ":"))
        self._config.set_state(grid_layout=payload,
                               window_states={"closed": [], "minimized": []})
        self._push_global("grid", payload)
        self.log_message.emit("↺ Grid layout reset to default "
                              "(all windows visible)", "info")
        return payload

    # ── window open/close/minimize states ────────────────────────
    @Slot(result=str)
    def get_window_states(self):
        """Return open-window state. The full-grid "maximized" concept was
        removed by design; any legacy stored value is ignored here."""
        raw = self._config.get_state("window_states", None)
        if isinstance(raw, dict):
            closed = raw.get("closed", [])
            minimized = raw.get("minimized", [])
            closed = [i for i in closed if isinstance(i, str) and i in self.WINDOW_IDS]
            minimized = [i for i in minimized if isinstance(i, str) and i in self.WINDOW_IDS and i not in closed]
            return json.dumps({"closed": closed, "minimized": minimized},
                              ensure_ascii=False)
        return ""

    @Slot(str, result=bool)
    def save_window_states(self, states_json):
        try:
            data = json.loads(states_json or "{}")
        except json.JSONDecodeError:
            return False
        if not isinstance(data, dict):
            return False
        closed = data.get("closed", [])
        minimized = data.get("minimized", [])
        if not isinstance(closed, list):
            closed = []
        if not isinstance(minimized, list):
            minimized = []
        closed = [i for i in closed if isinstance(i, str) and i in self.WINDOW_IDS]
        minimized = [i for i in minimized if isinstance(i, str) and i in self.WINDOW_IDS and i not in closed]
        self._config.set_state(window_states={"closed": closed, "minimized": minimized})
        return True

    @classmethod
    def _legacy_grid_payload(cls, raw):
        """Render a canonical payload in the old `type` spelling only for
        callers of the retired compatibility slots. The active UI always uses
        the canonical `t` payload.
        """
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return raw

        def convert(node):
            if not isinstance(node, dict):
                return node
            if cls._node_type(node) == "leaf":
                return {"type": "leaf", "id": node.get("id")}
            return {"type": "split", "dir": node.get("dir"),
                    "children": [convert(k) for k in node.get("children", [])],
                    "sizes": node.get("sizes", [])}

        if isinstance(data, dict) and data.get("v") == 1:
            data["tree"] = convert(data.get("tree"))
        return json.dumps(data, ensure_ascii=False)

    # Kept as a compatibility shim for older pages. It delegates to the same
    # global undo timeline; the page no longer renders grid-specific controls.
    @Slot(result=str)
    def undo_grid_layout(self):
        raw = self.undo()
        try:
            result = json.loads(raw)
            return (self._legacy_grid_payload(result.get("value", "null"))
                    if isinstance(result, dict) and result.get("kind") == "grid" else "null")
        except (TypeError, json.JSONDecodeError):
            return "null"

    @Slot(result=str)
    def redo_grid_layout(self):
        raw = self.redo()
        try:
            result = json.loads(raw)
            return (self._legacy_grid_payload(result.get("value", "null"))
                    if isinstance(result, dict) and result.get("kind") == "grid" else "null")
        except (TypeError, json.JSONDecodeError):
            return "null"

    @Slot(result=str)
    def get_undo_history(self):
        history, index = self._get_global_history()
        return json.dumps({"history": history, "index": index},
                          ensure_ascii=False)

    @Slot(str, str, result=bool)
    def push_global_history(self, kind, value_json):
        """Record a frontend edit in the one global timeline."""
        if kind == "stack":
            try:
                value = json.loads(value_json or "[]")
            except json.JSONDecodeError:
                return False
            if not isinstance(value, list):
                return False
            value = self._clean_blocks(value)
        elif kind == "grid":
            value, err = self._canonical_grid_payload(value_json or "")
            if err:
                return False
        else:
            return False
        self._push_global(kind, value)
        if kind == "grid":
            self._config.set_state(grid_layout=value)
        elif kind == "stack":
            self._config.set_state(last_stack=value, last_stack_preset="")
            # The stack determines the processing order (# column): re-rank
            # the people list when a block is added/removed/toggled.
            asyncio.ensure_future(self._refresh_users())
        return True

    def _global_result(self, entry, index=None):
        result = {"kind": entry["kind"], "value": entry["value"]}
        if index is not None:
            result["index"] = index
        return json.dumps(result, ensure_ascii=False)

    # ── reversible commands (people / labels / archive / dbconn) ─
    def _apply_command(self, entry, forward: bool) -> bool:
        """Apply one command entry forward (redo) or backward (undo)."""
        kind = entry.get("kind")
        value = entry.get("value")
        if not isinstance(value, dict):
            return False
        if kind == "people":
            rows = value.get("after" if forward else "before")
            if rows is None:
                return False
            self._apply_people(rows)
            return True
        if kind == "labels":
            snapshot = value.get("after" if forward else "before")
            if not isinstance(snapshot, dict):
                return False
            self.label_store.restore(snapshot)
            self._emit_labels()
            self._schedule(self._refresh_users())
            return True
        if kind == "archive":
            return self._apply_archive_command(value, forward)
        if kind == "dbconn":
            return self._apply_db_command(value, forward)
        return False

    def _update_archive_command(self, original: dict, patch: dict) -> None:
        history, index = self._get_global_history()
        for entry in history:
            value = entry.get("value") or {}
            matches = (value.get("command_id") == original.get("command_id")
                       if original.get("command_id") else (self._values_equal(value, original) or
                       (original.get("token") and value.get("token") == original["token"] and
                        value.get("nick") == original.get("nick"))))
            if entry.get("kind") == "archive" and matches:
                value.update(patch)
                self._set_global_history(history, index)
                return

    def _emit_archive_change(self, action: str, nick: str, **extra) -> None:
        payload = {"action": action, "nick": nick, "ok": True,
                   "generation": self._archive.generation, **extra}
        if payload.get("reset"):
            self.history_reset.emit(json.dumps(payload, ensure_ascii=False))
        self.userdb_changed.emit(json.dumps(payload, ensure_ascii=False))

    def _apply_archive_command(self, value: dict, forward: bool) -> bool:
        """Explicit undo/redo owns snapshots; ordinary collection cannot read them."""
        archive = self._archive
        if archive is None:
            self.history_error.emit("archive_undo", "the message archive is not running")
            return False
        op, nick = str(value.get("op") or ""), str(value.get("nick") or "")
        if value.get("db_path") and not same_database(value["db_path"], archive.db.path):
            self.history_error.emit("archive_undo", "Load the original database before undoing this archive edit")
            return False
        original = copy.deepcopy(value)
        _, previous_index = self._get_global_history()

        async def work():
            command = dict(value)
            reset = False
            try:
                # Old stored command references are converted only here/startup,
                # never by the collector's already-seen logic.
                if op in ("clear_history", "delete_person") and not command.get("snapshot"):
                    await archive._migrate_bulk_tombstones(archive.db)
                    history, _ = self._get_global_history()
                    for entry in history:
                        candidate = entry.get("value") or {}
                        if (entry.get("kind") == "archive" and candidate.get("nick") == nick
                                and candidate.get("token") == command.get("token") and candidate.get("snapshot")):
                            command = candidate
                            break
                kind = command.get("op")
                if kind in ("reset_history", "reset_person", "clear_history", "delete_person"):
                    deleting = kind in ("reset_person", "delete_person")
                    if forward:
                        result = await archive.reset_conversation(nick, delete_person=deleting)
                        patch = {"op": "reset_person" if deleting else "reset_history", "snapshot": result["snapshot"],
                                 "legacy_token": "", "legacy_person": False, "db_path": archive.db.path}
                        self._update_archive_command(original, patch)
                        if deleting and self._memory is not None:
                            await self._memory.delete_user(nick)
                    else:
                        if not command.get("snapshot"):
                            raise ValueError("This legacy deletion has no recoverable undo snapshot")
                        await archive.undo_conversation_reset(nick, command["snapshot"],
                            legacy_token=command.get("legacy_token") or "",
                            legacy_person=bool(command.get("legacy_person")))
                        queue = command.get("queue_before")
                        if queue and self._memory is not None:
                            await self._memory.restore_user(queue)
                        elif deleting and isinstance(command.get("people"), dict) and self._memory is not None:
                            for row in command["people"].get("before", []):
                                if row.get("nick") == nick:
                                    await self._memory.restore_user(row)
                    reset = True
                elif kind == "restore_cleared":
                    # Compatibility with v12's explicit restoration command.
                    # Its reverse now physically removes those rows and resets
                    # the cursor, rather than restoring an active denylist.
                    if forward:
                        snapshots = command.get("legacy_snapshots") or []
                        if not snapshots:
                            raise ValueError("This old restoration has no isolated snapshot")
                        for item in snapshots:
                            await archive.undo_conversation_reset(nick, item["snapshot"], only_ids=item.get("ids"))
                    else:
                        ids = [rid for group in command.get("groups", []) for rid in group.get("ids", [])]
                        result = await archive.reset_conversation(nick, message_ids=ids)
                        self._update_archive_command(original, {"legacy_snapshots": [{"snapshot": result["snapshot"]}]})
                    reset = True
                elif kind == "delete_message":
                    if forward:
                        await archive.repo.soft_delete_message(nick, int(command.get("message_id") or 0), token=command.get("token") or "")
                    else:
                        await archive.repo.restore_deleted(nick, command.get("token") or "")
                    await archive.collector.archive_edited(nick)
                else:
                    raise ValueError("Unknown archive undo command")
            except Exception:
                history, index = self._get_global_history()
                if index == previous_index + (1 if forward else -1):
                    self._set_global_history(history, previous_index)
                    self.history_changed.emit()
                raise
            if op in ("reset_person", "delete_person"):
                await self._refresh_users()
            self._emit_archive_change("redo" if forward else "undo", nick, op=op, reset=reset)
        self._run_async("archive_undo", work())
        return True

    def _apply_db_command(self, value: dict, forward: bool) -> bool:
        """Reverse the file operation, not an implicit Create→Load switch."""
        if getattr(self, "_db_command_pending", False):
            return False
        self._db_command_pending = True
        op = str(value.get("op") or "")
        path = str(value.get("path") or "")
        before_path = str(value.get("before_path") or "")
        backup = str(value.get("backup") or "")
        manager = self.db_manager
        _history, previous_index = self._get_global_history()

        async def work():
            try:
                try:
                    if forward:
                        if op == "create":
                            result = (await manager.restore_backup(backup, path)
                                      if backup else await manager.create(path))
                        elif op == "load":
                            result = await manager.load(path)
                        elif op == "delete":
                            result = await manager.delete(path)
                        elif op == "clean":
                            result = await manager.clean()
                        else:
                            result = {"ok": False, "error": "Unknown database operation"}
                    elif op == "create":
                        result = await manager.delete(path)
                    elif op == "load":
                        result = await manager.load(before_path)
                    elif op in ("delete", "clean"):
                        result = await manager.restore_backup(
                            backup, path, activate=bool(value.get("was_active", op == "clean")))
                    else:
                        result = {"ok": False, "error": "Unknown database operation"}
                except Exception as exc:
                    log.exception("database undo/redo %s failed", op)
                    result = {"ok": False, "error": str(exc)}
                history, index = self._get_global_history()
                if result.get("ok"):
                    # Redo can make a NEW backup. Keep the matching command's
                    # reference current, so repeated undo/redo never restores
                    # an older snapshot or re-creates an empty file over data.
                    for entry in history:
                        old = entry.get("value") or {}
                        matches = (old.get("command_id") == value.get("command_id")
                                   if value.get("command_id") else self._values_equal(old, value))
                        if entry.get("kind") == "dbconn" and matches:
                            if result.get("backup"):
                                old["backup"] = result["backup"]
                            if op == "delete" and forward:
                                old["was_active"] = result.get("was_active", False)
                            self._set_global_history(history, index)
                            break
                elif index == previous_index + (1 if forward else -1):
                    # A refused last-DB undo is NOT a successful timeline step.
                    self._set_global_history(history, previous_index)
                self.history_changed.emit()
                self._emit_db_change(op, result)
            finally:
                self._db_command_pending = False
        self._run_async("db_undo", work())
        return True

    def _emit_db_change(self, action: str, result) -> None:
        payload = dict(result or {})
        payload["action"] = action
        if "items" not in payload:
            payload.update(self.db_manager.snapshot())
        payload["active_path"] = self.db_manager.active_path()
        self.db_changed.emit(json.dumps(payload, ensure_ascii=False))
        # Independent create/delete and failed loads must not clear the
        # working Person History window or invalidate its pending reads.
        if payload.get("ok") and payload.get("active_changed"):
            if self._archive is not None:
                self.history_reset.emit(json.dumps({"reset": True, "nick": None,
                                                    "generation": self._archive.generation}))
            self.userdb_changed.emit(json.dumps(
                {"action": "db_" + action, "ok": True}, ensure_ascii=False))
        if payload.get("error"):
            self.log_message.emit("⚠ " + str(payload["error"]), "warn")

    def _apply_global_entry(self, entry):
        """Apply the state represented by a history entry.

        Stack/grid entries carry their after-state snapshot. A COMMAND entry
        (people/labels/archive/dbconn) carries {"before":…, "after":…} or an
        op description; when an undo/redo walk reaches it as the state to
        step ONTO, its FORWARD half is the surface state at that point in the
        timeline (the tip-reversal case is handled separately by
        undo()/redo(), which apply the matching half).
        """
        kind = entry.get("kind")
        if kind in ("labels", "archive", "dbconn"):
            self._apply_command(entry, forward=True)
            return
        if kind == "grid":
            self._config.set_state(grid_layout=entry["value"])
            self.grid_layout_changed.emit(entry["value"])
        elif kind == "people":
            value = entry.get("value")
            rows = value.get("after") if isinstance(value, dict) else None
            if rows is not None:
                self._apply_people(rows)
        else:
            blocks = self._clean_blocks(entry["value"])
            self._config.set_state(last_stack=blocks, last_stack_preset="")
            self._engine.load_stack(blocks)
            self.stack_loaded.emit("", json.dumps(blocks, ensure_ascii=False))
            # Undo/redo of a stack edit can change the enabled Scroll & Parse
            # presence — re-rank the people list's # column to match.
            self._schedule(self._refresh_users())

    @Slot(result=str)
    def undo(self):
        if (getattr(self, "_db_command_pending", False) or
                getattr(self, "_db_actions_pending", 0) or
                getattr(self, "_archive_actions_pending", 0)):
            self.log_message.emit("⚠ Wait for the archive operation to finish", "warn")
            return "null"
        history, index = self._get_global_history()
        if not history or index < 0 or index >= len(history):
            self.log_message.emit("⚠ Nothing to undo", "warn")
            return "null"
        entry = history[index]
        # Command entries are reversible: undoing the TIP entry must reverse
        # it in a single step even when stack/grid edits surround it in the
        # timeline — and even when it is the FIRST entry of a fresh timeline
        # (index 0 / nothing before).
        if entry.get("kind") in self.COMMAND_KINDS:
            if not self._apply_command(entry, forward=False):
                self.log_message.emit("⚠ Nothing to undo", "warn")
                return "null"
            index -= 1
            self._set_global_history(history, index)
            self.history_changed.emit()
            kind = entry["kind"]
            self.log_message.emit(
                "↩ Undo — " + self.UNDO_LABELS.get(kind, kind + " restored"),
                "info")
            value = entry.get("value") or {}
            payload = (value.get("before") if kind in ("people", "labels")
                       else value)
            result = {"kind": kind, "value": payload, "index": index}
            return json.dumps(result, ensure_ascii=False)
        if index <= 0:
            self.log_message.emit("⚠ Nothing to undo", "warn")
            return "null"
        index -= 1
        self._set_global_history(history, index)
        self.history_changed.emit()
        entry = history[index]
        self._apply_global_entry(entry)
        self.log_message.emit("↩ Undo — restored " + entry["kind"], "info")
        return self._global_result(entry, index)

    @Slot(result=str)
    def redo(self):
        if (getattr(self, "_db_command_pending", False) or
                getattr(self, "_db_actions_pending", 0) or
                getattr(self, "_archive_actions_pending", 0)):
            self.log_message.emit("⚠ Wait for the archive operation to finish", "warn")
            return "null"
        history, index = self._get_global_history()
        if not history or index >= len(history) - 1:
            self.log_message.emit("⚠ Nothing to redo", "warn")
            return "null"
        index += 1
        entry = history[index]
        if entry.get("kind") in self.COMMAND_KINDS:
            if not self._apply_command(entry, forward=True):
                self.log_message.emit("⚠ Nothing to redo", "warn")
                return "null"
            self._set_global_history(history, index)
            self.history_changed.emit()
            kind = entry["kind"]
            self.log_message.emit(
                "↪ Redo — " + self.UNDO_LABELS.get(kind, kind + " restored"),
                "info")
            value = entry.get("value") or {}
            payload = (value.get("after") if kind in ("people", "labels")
                       else value)
            result = {"kind": kind, "value": payload, "index": index}
            return json.dumps(result, ensure_ascii=False)
        self._set_global_history(history, index)
        self.history_changed.emit()
        self._apply_global_entry(entry)
        self.log_message.emit("↪ Redo — restored " + entry["kind"], "info")
        return self._global_result(entry, index)

    @staticmethod
    def _default_grid_tree() -> dict:
        """Mirror of SashCore.defaultTree(): every window, classic order."""
        def leaf(i):
            return {"t": "leaf", "id": i}

        def split(d, kids, sizes):
            return {"t": "split", "dir": d, "children": kids, "sizes": sizes}

        return split("col", [
            split("row", [
                split("col", [leaf("stats"), leaf("filters")], [35, 65]),
                split("col", [leaf("stack"), leaf("config")], [72, 28]),
            ], [17, 83]),
            leaf("composer"),
            split("row", [leaf("people"), leaf("log")], [70, 30]),
            split("row", [leaf("history"), leaf("userdb"),
                          leaf("collector")], [40, 35, 25]),
            split("row", [leaf("labels"), leaf("dbconn")], [55, 45]),
        ], [30, 15, 21, 20, 14])

    def _push_history(self, blocks: list[dict]) -> tuple[list, int]:
        """Backward-compatible name; append the stack to global history."""
        if not isinstance(blocks, list):
            return self._get_history()
        normalized = self._clean_blocks(blocks)
        self._push_global("stack", normalized)
        return self._get_history()

    # ── unified app state (BUG #2 restore / single store) ────────
    @Slot(result=str)
    def get_app_state(self):
        """Everything the UI needs to restore the last session in one payload."""
        history, h_idx = self._get_global_history()
        stack_history, stack_idx = self._get_history()
        # Cleaned here so a legacy config.json can never hand the UI dead
        # controls (JS also migrates on receipt).
        raw_last_stack = self._config.get_state("last_stack", None)
        last_stack = (self._clean_blocks(raw_last_stack)
                      if isinstance(raw_last_stack, list) else raw_last_stack)
        payload = {
            "url_presets": list(self._config.get("url_presets", default=[])),
            "labels": self.label_store.state(),
            "custom_blocks": self._custom_blocks_raw(),
            "stack_presets": self._presets.list_stacks(),
            "template_presets": self._presets.list_templates(),
            "state": {
                "last_url_preset": self._config.get_state("last_url_preset", ""),
                "last_stack_preset": self._config.get_state("last_stack_preset", ""),
                "last_stack": last_stack,
                # Legacy projection retained so older page bundles can still
                # start; all new edits use the global fields below.
                "stack_history": stack_history,
                "stack_history_index": stack_idx,
                "undo_history": history,
                "undo_history_index": h_idx,
                "grid_layout": self.get_grid_layout() or None,
                "block_config_pinned":
                    self._config.get_state("block_config_pinned", False),
                "window_states": self._config.get_state("window_states", None),
                "window_geometry": self._config.get_state("window_geometry", None),
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    @Slot(str)
    def set_last_url_preset(self, url):
        """Remember which URL preset/bookmark was selected (persisted)."""
        url = (url or "").strip()
        if not url:
            return
        self._config.set_state(last_url_preset=url)
        self.log_message.emit(f"🔖 Bookmark remembered: {url}", "info")

    @Slot(str)
    def snapshot_stack(self, stack_json):
        """Persist the current stack so the next session restores it + push history."""
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            return
        if not isinstance(blocks, list):
            return
        # App.recordGlobal() already recorded the edit. This call is only the
        # debounced last-session snapshot, so it must not create a second
        # history entry after a grid change has interleaved with the edit.
        self._config.set_state(last_stack=self._clean_blocks(blocks),
                               last_stack_preset="")

    def _remember_stack(self, name: str, blocks: list[dict]) -> None:
        self._config.set_state(last_stack=blocks, last_stack_preset=name)
        # Also push to history when preset is loaded/saved
        self._push_history(blocks)

    # ── history slots (Feature #1) ─────────────────────────────────
    @Slot(result=str)
    def get_stack_history(self):
        """Return JSON {history: [...], index: N} for undo/redo."""
        hist, idx = self._get_history()
        return json.dumps({"history": hist, "index": idx}, ensure_ascii=False)

    @Slot(str)
    def push_stack_history(self, stack_json):
        """Push a stack to history from frontend (explicit)."""
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            return
        if isinstance(blocks, list):
            self._push_history(self._clean_blocks(blocks))

    @Slot(str, int)
    def save_stack_history(self, history_json, index):
        """Bulk save history from frontend (sync)."""
        try:
            hist = json.loads(history_json or "[]")
        except json.JSONDecodeError:
            return
        if not isinstance(hist, list):
            return
        if not isinstance(index, int):
            index = -1
        # Strip retired keys from every stored snapshot on the way in.
        hist = self._clean_history(hist)
        # Enforce max
        if len(hist) > MAX_STACK_HISTORY:
            overflow = len(hist) - MAX_STACK_HISTORY
            hist = hist[overflow:]
            index = max(0, index - overflow)
        self._set_history(hist, index)
        log.info("History saved from frontend: %d entries, index %d", len(hist), index)

    @Slot(result=str)
    def undo_stack(self):
        """Compatibility alias for the one global undo operation."""
        raw = self.undo()
        try:
            result = json.loads(raw)
            return json.dumps(result["value"], ensure_ascii=False) \
                if isinstance(result, dict) and result.get("kind") == "stack" else "null"
        except (TypeError, KeyError, json.JSONDecodeError):
            return "null"

    @Slot(result=str)
    def redo_stack(self):
        """Compatibility alias for the one global redo operation."""
        raw = self.redo()
        try:
            result = json.loads(raw)
            return json.dumps(result["value"], ensure_ascii=False) \
                if isinstance(result, dict) and result.get("kind") == "stack" else "null"
        except (TypeError, KeyError, json.JSONDecodeError):
            return "null"

    # ── tab discovery / connection ───────────────────────────────
    @Slot(result=str)
    def get_tabs(self):
        asyncio.ensure_future(self._fetch_tabs()); return "pending"

    async def _fetch_tabs(self):
        try:
            tabs = await self._cdp.fetch_tabs()
            self.tabs_received.emit(json.dumps(
                [{"id": t.id, "title": t.title, "url": t.url, "ws_url": t.ws_url}
                 for t in tabs], ensure_ascii=False))
        except Exception as exc:
            log.error("Tab fetch failed: %s", exc)
            self.log_message.emit(f"❌ Tab discovery failed: {exc}", "error")

    @Slot(str)
    def connect_tab(self, ws_url):
        asyncio.ensure_future(self._do_connect(ws_url))

    async def _do_connect(self, ws_url):
        if await self._cdp.connect(ws_url):
            self.log_message.emit("🔗 Connected", "info")
            await self._refresh_users()

    # ── URL parse preset: match query against open tabs & connect ─
    @Slot(str)
    def find_tab_by_url(self, query):
        asyncio.ensure_future(self._find_tab_by_url(query))

    async def _find_tab_by_url(self, query):
        query = (query or "").strip()
        if not query:
            self.log_message.emit("⚠ URL field is empty — enter a URL or keyword",
                                  "warn")
            self.tab_match_result.emit(query, "[]")
            return
        self.log_message.emit(f"🔍 URL preset: parsing “{query}” against open tabs…",
                              "info")
        try:
            tabs = await self._cdp.fetch_tabs()
        except Exception as exc:
            self.log_message.emit(f"❌ Tab discovery failed: {exc}", "error")
            self.tab_match_result.emit(query, "[]")
            return
        if not tabs:
            self.log_message.emit(
                "⚠ No Chrome tabs found — start Chrome with "
                "--remote-debugging-port=9222 "
                "--user-data-dir=\"C:\\chatflow-chrome\" (see README §2)",
                "warn")
            self.tab_match_result.emit(query, "[]")
            return
        matches = best_matches(query, [t.__dict__ for t in tabs])
        if not matches:
            self.log_message.emit(
                f"❌ No open tab matches “{query}”. Available: "
                + "; ".join(f"{t.title} — {t.url}" for t in tabs[:5])
                + ("…" if len(tabs) > 5 else ""), "error")
            self.tab_match_result.emit(query, "[]")
            return
        kind_names = {"url_exact": "exact URL", "url_path": "URL path",
                      "host": "host", "keyword": "keyword"}
        for m in matches[:3]:
            self.log_message.emit(
                f"  · match ({kind_names.get(m['kind'], m['kind'])}): "
                f"{m['title']} — {m['url']}", "success")
        # feed the full tab list so the select can be re-populated too
        self.tabs_received.emit(json.dumps(
            [{"id": t.id, "title": t.title, "url": t.url, "ws_url": t.ws_url}
             for t in tabs], ensure_ascii=False))
        self.tab_match_result.emit(query, json.dumps(matches, ensure_ascii=False))

    # ── run / pause / stop ───────────────────────────────────────
    @Slot(str)
    def run_stack(self, stack_json):
        if self._engine.is_running:
            self.log_message.emit("⚠ Already running", "warn"); return
        try:
            blocks = json.loads(stack_json)
        except json.JSONDecodeError:
            self.log_message.emit("❌ Bad JSON", "error"); return
        blocks = self._clean_blocks(blocks)
        self._engine.load_stack(blocks)
        # remember what is being run for the next session
        if isinstance(blocks, list):
            self._config.set_state(last_stack=blocks,
                                   last_stack_preset="")
        # The SCROLL_PARSE block now owns the whole scroll/filter/collect
        # pipeline and builds its own parser from its own settings, so the
        # bridge no longer constructs a ScrollParser here. Whether the block
        # is enabled is decided by the engine, which skips disabled blocks.
        asyncio.ensure_future(self._engine.execute())

    @Slot()
    def stop_stack(self): self._engine.stop()
    @Slot()
    def pause_stack(self): self._engine.pause()
    @Slot()
    def resume_stack(self): self._engine.resume()

    # ── message composer ─────────────────────────────────────────
    @Slot(str)
    def save_message(self, text):
        self._message_text = text
        # Mirror onto the engine so a Type Message block with
        # use_composer=True sends the composer's CURRENT text at run time.
        try:
            self._engine.composer_text = text
        except Exception:
            pass

    @Slot(result=str)
    def get_message(self): return self._message_text

    # ── criteria ─────────────────────────────────────────────────
    @Slot(str)
    def save_criteria(self, j):
        self._criteria.load_json(j)
        self.log_message.emit("💾 Criteria saved", "info")

    @Slot(result=str)
    def get_criteria(self): return self._criteria.to_json()

    # ── user memory ──────────────────────────────────────────────
    @Slot()
    def reset_messaged(self): asyncio.ensure_future(self._do_reset())
    @Slot()
    def clear_memory(self): asyncio.ensure_future(self._do_clear())

    @Slot()
    def refresh_users(self):
        """Explicit refresh so the people list is filled on app start too."""
        asyncio.ensure_future(self._refresh_users())

    @Slot(str)
    def delete_user(self, nick):
        """Delete a single nick from user memory."""
        asyncio.ensure_future(self._do_delete_one(nick))

    @Slot(str)
    def delete_users(self, nicks_json):
        """Delete a selection of nicks (JSON array) from user memory."""
        try:
            nicks = json.loads(nicks_json or "[]")
        except json.JSONDecodeError:
            self.log_message.emit("❌ Delete aborted: bad selection payload",
                                  "error")
            return
        if not isinstance(nicks, list):
            self.log_message.emit("❌ Delete aborted: selection is not a list",
                                  "error")
            return
        asyncio.ensure_future(self._do_delete_many([str(n) for n in nicks]))

    @Slot(str, bool)
    def set_user_messaged(self, nick, messaged):
        asyncio.ensure_future(self._do_set_messaged(nick, bool(messaged)))

    async def _do_reset(self):
        before = await self._people_rows()
        c = await self._memory.reset_messaged()
        self.log_message.emit(f"🔄 Reset {c} users", "info")
        if c:
            await self._push_people_entry(before, await self._people_rows())
        await self._refresh_users()

    async def _do_clear(self):
        before = await self._people_rows()
        c = await self._memory.clear_all()
        self.log_message.emit(f"🗑 Cleared {c} users", "warn")
        if c:
            await self._push_people_entry(before, await self._people_rows())
        self.users_deleted.emit("[]", c)
        await self._refresh_users()

    async def _do_delete_one(self, nick):
        nick = (nick or "").strip()
        if not nick:
            self.log_message.emit("⚠ No nick given — nothing deleted", "warn")
            return
        before = await self._people_rows()
        try:
            ok = await self._memory.delete_user(nick)
        except Exception as exc:
            self.log_message.emit(f"❌ Delete failed for “{nick}”: {exc}", "error")
            return
        if ok:
            self.log_message.emit(f"🗑 Deleted user “{nick}”", "warn")
            await self._push_people_entry(before, await self._people_rows())
            self.users_deleted.emit(json.dumps([nick], ensure_ascii=False), 1)
        else:
            self.log_message.emit(f"⚠ User “{nick}” not found", "warn")
        await self._refresh_users()

    async def _do_delete_many(self, nicks):
        if not nicks:
            self.log_message.emit("⚠ Nothing selected — nothing deleted", "warn")
            return
        before = await self._people_rows()
        try:
            count = await self._memory.delete_users(nicks)
        except Exception as exc:
            self.log_message.emit(f"❌ Delete failed: {exc}", "error")
            return
        if count:
            await self._push_people_entry(before, await self._people_rows())
        self.log_message.emit(
            f"🗑 Deleted {count} selected user(s)"
            + (f": {', '.join(nicks[:5])}" + ("…" if len(nicks) > 5 else "")
               if count else ""), "warn")
        self.users_deleted.emit(json.dumps(nicks, ensure_ascii=False), count)
        await self._refresh_users()

    async def _do_set_messaged(self, nick, messaged):
        before = await self._people_rows()
        try:
            ok = await self._memory.set_messaged(nick, messaged)
        except Exception as exc:
            self.log_message.emit(f"❌ Update failed for “{nick}”: {exc}", "error")
            return
        if ok:
            self.log_message.emit(
                f"{'✅' if messaged else '↩'} “{nick}” marked as "
                f"{'messaged' if messaged else 'new'}", "info")
            await self._push_people_entry(before, await self._people_rows())
        await self._refresh_users()

    # ── stack presets ────────────────────────────────────────────
    @Slot(str, str)
    def save_stack_preset(self, name, stack_json):
        """Save the FULL action stack received from the UI."""
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            self.log_message.emit("❌ Preset save aborted: stack is not valid JSON",
                                  "error")
            return
        if not isinstance(blocks, list):
            self.log_message.emit("❌ Preset save aborted: bad stack payload",
                                  "error")
            return
        blocks = self._clean_blocks(blocks)
        try:
            self._presets.save_stack(name, blocks)
        except Exception as exc:
            self.log_message.emit(f"❌ Preset save failed: {exc}", "error")
            return
        self._remember_stack(name, blocks)
        self._emit_presets()
        self.log_message.emit(
            f"💾 Preset “{name}” saved ({len(blocks)} block(s)) — reload anytime "
            f"from the preset chips", "success")

    @Slot(str, result=str)
    def load_stack_preset(self, name):
        """Return the stored stack JSON and load it into the engine."""
        blocks = self._presets.load_stack(name)
        if blocks is None:
            self.log_message.emit(f"❌ Preset “{name}” not found", "error")
            return "null"
        # Legacy presets may still carry retired keys — clean before use.
        blocks = self._clean_blocks(blocks)
        # Preserve current stack in history before overwriting (undo after preset load)
        try:
            current = self._config.get_state("last_stack", None)
            if isinstance(current, list) and current:
                if not self._stacks_equal(current, blocks):
                    self._push_history(current)
        except Exception:
            pass
        self._engine.load_stack(blocks)
        self._remember_stack(name, blocks)
        payload = json.dumps(blocks, ensure_ascii=False)
        self.stack_loaded.emit(name, payload)
        self.log_message.emit(f"📂 Preset “{name}” loaded — {len(blocks)} block(s) "
                              "restored (↩ Undo to return to previous)", "success")
        return payload

    @Slot(result=str)
    def list_stack_presets(self):
        try:
            return json.dumps(self._presets.list_stacks(), ensure_ascii=False)
        except Exception as exc:
            log.error("list presets failed: %s", exc)
            return "[]"

    @Slot(str)
    def delete_stack_preset(self, name):
        try:
            if self._presets.delete_stack(name):
                self._emit_presets()
                self.log_message.emit(f"🗑 Preset “{name}” deleted", "warn")
            else:
                self.log_message.emit(f"⚠ Preset “{name}” not found", "warn")
        except Exception as exc:
            self.log_message.emit(f"❌ Preset delete failed: {exc}", "error")

    def _emit_presets(self):
        self.preset_list_updated.emit(
            json.dumps(self._presets.list_stacks(), ensure_ascii=False))

    # ── message template presets ─────────────────────────────────
    @Slot(str, str)
    def save_template_preset(self, name, body):
        try:
            self._presets.save_template(name, body or "")
        except Exception as exc:
            self.log_message.emit(f"❌ Template save failed: {exc}", "error")
            return
        self._emit_templates()
        self.log_message.emit(f"💾 Template “{name}” saved", "success")

    @Slot(str, result=str)
    def load_template_preset(self, name):
        body = self._presets.load_template(name)
        if body is None:
            self.log_message.emit(f"❌ Template “{name}” not found", "error")
            return ""
        self.template_loaded.emit(name, body)
        self.log_message.emit(f"📂 Template “{name}” loaded", "success")
        return body

    @Slot(result=str)
    def list_template_presets(self):
        try:
            return json.dumps(self._presets.list_templates(), ensure_ascii=False)
        except Exception as exc:
            log.error("list templates failed: %s", exc)
            return "[]"

    @Slot(str)
    def delete_template_preset(self, name):
        try:
            if self._presets.delete_template(name):
                self._emit_templates()
                self.log_message.emit(f"🗑 Template “{name}” deleted", "warn")
        except Exception as exc:
            self.log_message.emit(f"❌ Template delete failed: {exc}", "error")

    def _emit_templates(self):
        self.template_list_updated.emit(
            json.dumps(self._presets.list_templates(), ensure_ascii=False))

    # ── URL presets ──────────────────────────────────────────────
    @Slot(result=str)
    def get_url_presets(self):
        return json.dumps(list(self._config.get("url_presets", default=[])),
                          ensure_ascii=False)

    @Slot(str)
    def add_url_preset(self, url):
        url = (url or "").strip()
        if not url:
            self.log_message.emit("⚠ URL field is empty — nothing added", "warn")
            return
        presets = list(self._config.get("url_presets", default=[]))
        if url not in presets:
            presets.append(url)
            self._config.set("url_presets", presets)
            self._config.save()
            self.log_message.emit(f"💾 URL preset added: {url}", "success")
        else:
            self.log_message.emit(f"ℹ URL preset already exists: {url}", "info")
        self.url_presets_updated.emit(json.dumps(presets, ensure_ascii=False))

    @Slot(str)
    def remove_url_preset(self, url):
        presets = list(self._config.get("url_presets", default=[]))
        if url in presets:
            presets.remove(url)
            self._config.set("url_presets", presets)
            self._config.save()
            self.log_message.emit(f"🗑 URL preset removed: {url}", "warn")
        self.url_presets_updated.emit(json.dumps(presets, ensure_ascii=False))

    # ── custom Find & Click block presets (FEATURE) ──────────────
    def _custom_blocks_raw(self) -> list[dict]:
        raw = self._config.get("custom_blocks", default=[])
        return raw if isinstance(raw, list) else []

    @Slot(result=str)
    def list_custom_blocks(self):
        return json.dumps(self._custom_blocks_raw(), ensure_ascii=False)

    @Slot(str, str)
    def save_custom_block(self, name, block_json):
        name = (name or "").strip()
        try:
            block = json.loads(block_json or "{}")
        except json.JSONDecodeError:
            self.log_message.emit("❌ Block preset save aborted: bad JSON", "error")
            return
        if not isinstance(block, dict) or not name:
            self.log_message.emit("❌ Block preset needs a name and block config",
                                  "error")
            return
        items = [b for b in self._custom_blocks_raw() if isinstance(b, dict)
                 and b.get("name") != name]
        items.append({"name": name, "block": block,
                      "updated_at": datetime.now().isoformat(timespec="seconds")})
        self._config.set("custom_blocks", items)
        self._config.save()
        self.custom_blocks_updated.emit(json.dumps(items, ensure_ascii=False))
        self.log_message.emit(f"💾 Block preset “{name}” saved — reusable from "
                              "the + Add menu and Custom Blocks chips", "success")

    @Slot(str)
    def delete_custom_block(self, name):
        items = [b for b in self._custom_blocks_raw() if isinstance(b, dict)
                 and b.get("name") != name]
        if len(items) != len(self._custom_blocks_raw()):
            self._config.set("custom_blocks", items)
            self._config.save()
            self.custom_blocks_updated.emit(json.dumps(items, ensure_ascii=False))
            self.log_message.emit(f"🗑 Block preset “{name}” removed", "warn")
        else:
            self.log_message.emit(f"⚠ Block preset “{name}” not found", "warn")

    # ── engine current stack (compat helper) ─────────────────────
    @Slot(result=str)
    def get_stack_json(self):
        return json.dumps(self._engine.get_stack(), ensure_ascii=False)

    # ── user list refresh ────────────────────────────────────────
    async def _refresh_users(self):
        if self._memory is None:      # archive-only bridges (tests, headless)
            return
        users = await self._memory.get_all()
        # Processing-order ranks (# column). The engine's queue_order()
        # mirrors the queue the run loop would build (A–Z under an enabled
        # Scroll & Parse block, newest-discovered first otherwise). Only
        # un-messaged people are processed, so only they get a number.
        ranks: dict[str, int] = {}
        try:
            ordered = self._engine.queue_order(users)
            ranks = {nick: i + 1 for i, nick in enumerate(ordered)}
        except Exception:
            queue = await self._memory.get_queue()
            ranks = {u.nick: i + 1 for i, u in enumerate(queue)}
        # Labels are stored per nick in config.json and joined here, at read
        # time — neither database owns them (RULE 14).
        labels = self._labels_for_nicks([u.nick for u in users])
        self.users_updated.emit(json.dumps(
            [{"nick": u.nick, "gender": u.gender, "registered": u.registered,
              "anonymous": u.anonymous, "guest": u.guest, "messaged": u.messaged,
              "first_seen": u.first_seen, "last_messaged": u.last_messaged,
              "order": ranks.get(u.nick),
              "labels": labels.get(u.nick, [])}
             for u in users], ensure_ascii=False))
        self.stats_updated.emit(json.dumps(await self._memory.get_stats()))

    # ═════════════════════════════════════════════════════════════
    # MESSAGE ARCHIVE (Person History / User Database / Collector)
    #
    # Reads hit an async SQLite database, so a @Slot cannot answer inline:
    # JS passes a `req_id` and Python answers on a signal carrying the same
    # id. Two windows can therefore ask for two pages at once without their
    # answers crossing.
    # ═════════════════════════════════════════════════════════════

    def attach_history(self, service) -> None:
        """Wire the archive service (created in main.py) into the UI."""
        self._history = service
        self.db_manager.attach(service)
        if service is None:
            return
        service.media.on_change = lambda info: self._emit_media_info(service, info)
        try:
            service.collector.status_changed.connect(self._on_collector_status)
            service.collector.collector_log.connect(self.collector_log.emit)
            service.collector.history_appended.connect(self._on_history_appended)
            # a private chat with an unknown partner creates a People row:
            # refresh the list as soon as the collector discovers it.
            service.collector.people_changed.connect(
                lambda *_a: self.refresh_users())
        except Exception as exc:                      # noqa: BLE001
            log.warning("collector signals not connected: %s", exc)
        engine = getattr(self, "_engine", None)
        if engine is not None:
            try:
                engine.history = service
            except Exception:                         # noqa: BLE001
                pass

    def _on_collector_status(self, payload: str) -> None:
        data = json.loads(payload)
        data["generation"] = self._archive.generation
        self.collector_status.emit(json.dumps(data, ensure_ascii=False))

    def _on_history_appended(self, payload: str) -> None:
        data = json.loads(payload)
        data["generation"] = self._archive.generation
        self.history_appended.emit(json.dumps(data, ensure_ascii=False))

    @property
    def _archive(self):
        return getattr(self, "_history", None)

    def _run_async(self, scope: str, coro) -> None:
        """Run an archive coroutine, reporting failures on history_error."""
        generation = getattr(self._archive, "generation", None)
        mutation = scope in {"history_clear_person", "history_restore_cleared",
                             "history_delete_message", "history_delete_person", "archive_undo"}
        if mutation:
            self._archive_actions_pending = getattr(self, "_archive_actions_pending", 0) + 1

        async def guarded():
            try:
                archive = self._archive
                lock = getattr(getattr(archive, "db", None), "operation_lock", None)
                # Manager actions acquire their own mutation lock BEFORE the
                # archive lock. Taking them in reverse order would deadlock.
                if lock is not None and not scope.startswith("db_"):
                    async with lock:
                        if generation != getattr(archive, "generation", None):
                            # The old UI may have queued a message/media ID
                            # before Load completed. Those IDs belong to the
                            # old archive; a fresh history request is already
                            # issued by the DB-change event. Never reuse them
                            # against a coincidentally equal new row ID.
                            coro.close()
                            return
                        await coro
                else:
                    await coro
            except Exception as exc:                  # noqa: BLE001
                log.warning("archive %s failed: %s", scope, exc)
                self.history_error.emit(scope, str(exc))
            finally:
                if mutation:
                    self._archive_actions_pending -= 1
        runner = guarded()
        if not self._schedule(runner):
            runner.close()
            coro.close()
            if mutation:
                self._archive_actions_pending -= 1

    @staticmethod
    def _schedule(coro) -> bool:
        """Start a coroutine on the running loop; False when there is none.

        The app always runs one (qasync), but a slot must never explode in a
        loop-less context such as a unit test — the synchronous half of the
        work has already been done by then.
        """
        try:
            asyncio.ensure_future(coro)
            return True
        except RuntimeError:
            log.debug("no event loop — skipping a background refresh")
            return False

    @staticmethod
    def _json_arg(raw, default=None):
        if isinstance(raw, dict):
            return raw
        try:
            data = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return dict(default or {})
        return data if isinstance(data, dict) else dict(default or {})

    def _need_archive(self, scope: str, req_id: str = "") -> bool:
        if self._archive is None:
            self.history_error.emit(scope, "the message archive is not running")
            return False
        return True

    # ── person history ───────────────────────────────────────────
    @Slot(str, str, str)
    def history_open(self, req_id, nick, options_json):
        """First page for a person (newest messages, oldest first on screen)."""
        if not self._need_archive("history_open", req_id):
            return
        opts = self._json_arg(options_json)
        self._run_async("history_open", self._history_page(req_id, nick, opts))

    @Slot(str, str, str)
    def history_page(self, req_id, nick, anchor_json):
        """Another page: `before_ord`, `after_ord` or `around` an ord."""
        if not self._need_archive("history_page", req_id):
            return
        opts = self._json_arg(anchor_json)
        self._run_async("history_page", self._history_page(req_id, nick, opts))

    async def _history_page(self, req_id, nick, opts):
        service = self._archive
        limit = int(opts.get("limit") or
                    service.preview_settings().get("page_size", 50))
        if opts.get("around") is not None:
            payload = await service.query.around(
                nick, int(opts["around"]),
                radius=int(opts.get("radius") or 25))
            payload["stats"] = await service.query.person_stats(nick)
            payload["my_nick"] = service.my_nick
        else:
            payload = await service.page(
                nick,
                before_ord=(int(opts["before_ord"])
                            if opts.get("before_ord") is not None else None),
                after_ord=(int(opts["after_ord"])
                           if opts.get("after_ord") is not None else None),
                limit=limit)
        payload["req_id"] = req_id
        payload["generation"] = service.generation
        payload["preview"] = service.preview_settings()
        self.history_page_ready.emit(req_id, json.dumps(payload,
                                                        ensure_ascii=False))

    @Slot(str, str)
    def history_search(self, req_id, query_json):
        """Search one conversation (`scope='person'`) or the whole archive."""
        if not self._need_archive("history_search", req_id):
            return
        opts = self._json_arg(query_json)
        self._run_async("history_search", self._history_search(req_id, opts))

    async def _history_search(self, req_id, opts):
        service = self._archive
        query = str(opts.get("q") or opts.get("query") or "")
        limit = int(opts.get("limit") or 100)
        if str(opts.get("scope") or "person") == "person":
            payload = await service.query.search_person(
                str(opts.get("nick") or ""), query, limit=limit,
                offset=int(opts.get("offset") or 0))
            payload["scope"] = "person"
        else:
            payload = await service.query.search_global(query, limit=limit)
            payload["scope"] = "global"
        payload["req_id"] = req_id
        payload["generation"] = service.generation
        self.history_search_ready.emit(req_id, json.dumps(payload,
                                                          ensure_ascii=False))

    @Slot(str, str)
    def history_stats(self, req_id, nick):
        if not self._need_archive("history_stats", req_id):
            return

        async def work():
            payload = await self._archive.query.person_stats(nick)
            payload["generation"] = self._archive.generation
            payload["req_id"] = req_id
            self.history_stats_ready.emit(req_id, json.dumps(
                payload, ensure_ascii=False))
        self._run_async("history_stats", work())

    # ── the all-time user database ───────────────────────────────
    @Slot(str, str)
    def userdb_page(self, req_id, query_json):
        if not self._need_archive("userdb_page", req_id):
            return
        opts = self._json_arg(query_json)

        async def work():
            payload = await self._archive.query.list_persons(
                q=str(opts.get("q") or ""),
                limit=int(opts.get("limit") or 50),
                offset=int(opts.get("offset") or 0),
                sort=str(opts.get("sort") or "recent"),
                include_deleted=bool(opts.get("include_deleted")))
            payload["req_id"] = req_id
            payload["my_nick"] = self._archive.my_nick
            labels = self._labels_for_nicks(
                [item.get("nick") for item in payload.get("items") or []])
            for item in payload.get("items") or []:
                item["labels"] = labels.get(item.get("nick"), [])
            self.userdb_page_ready.emit(req_id, json.dumps(
                payload, ensure_ascii=False))
        self._run_async("userdb_page", work())

    @Slot(str)
    def userdb_stats(self, req_id):
        if not self._need_archive("userdb_stats", req_id):
            return

        async def work():
            payload = await self._archive.query.db_stats()
            payload["req_id"] = req_id
            payload.update(await self._archive.media.cache_usage())
            self.userdb_page_ready.emit(req_id, json.dumps(
                payload, ensure_ascii=False))
        self._run_async("userdb_stats", work())

    async def _people_snapshot(self):
        """The People rows, or None when there is no user memory attached."""
        if self._memory is None:
            return None
        try:
            return await self._people_rows()
        except Exception as exc:                      # noqa: BLE001
            log.debug("people snapshot unavailable: %s", exc)
            return None

    # ── deleting from the archive (all reversible, RULE 12) ──────
    @Slot(str, bool, result=bool)
    def history_delete_person(self, nick, hard=False):
        """Remove the person and ALL message knowledge; undo is isolated."""
        clean = " ".join(str(nick or "").split()).strip()
        if not clean or not self._need_archive("history_delete_person"):
            return False

        async def work():
            queue_before = None
            if self._memory is not None:
                user = await self._memory.get_user(clean)
                queue_before = self._people_row(user) if user else None
            result = await self._archive.reset_conversation(clean, delete_person=True, with_undo=not hard)
            if self._memory is not None:
                await self._memory.delete_user(clean)
            if result["changed"] and not hard:
                self._push_global("archive", {"op": "reset_person", "command_id": uuid.uuid4().hex,
                    "nick": clean, "snapshot": result["snapshot"], "db_path": self._archive.db.path,
                    "queue_before": queue_before})
            elif hard:
                self.label_store.forget(clean)
            self.log_message.emit(f"🗑 “{clean}” removed with all message tracking — the next scan starts fresh", "info")
            await self._refresh_users()
            self._emit_archive_change("deleted", clean, reset=True, hard=bool(hard))
        self._run_async("history_delete_person", work())
        return True

    @Slot(str, result=bool)
    def history_clear_person(self, nick):
        """Keep the contact, erase all of its messages and tracking state."""
        clean = " ".join(str(nick or "").split()).strip()
        if not clean or not self._need_archive("history_clear_person"):
            return False

        async def work():
            result = await self._archive.reset_conversation(clean)
            if result["changed"]:
                self._push_global("archive", {"op": "reset_history", "command_id": uuid.uuid4().hex,
                    "nick": clean, "snapshot": result["snapshot"], "db_path": self._archive.db.path})
            self.log_message.emit(f"🧹 History and tracking for “{clean}” erased — visible messages can be collected again", "info")
            self._emit_archive_change("cleared", clean, reset=True)
        self._run_async("history_clear_person", work())
        return True

    @Slot(str, result=bool)
    def history_restore_cleared(self, nick):
        """Old UI compatibility: there is no active cleared-message registry."""
        self.log_message.emit("ℹ Collection now starts fresh after Clear. Use global Undo to restore the old archive immediately.", "info")
        return False

    @Slot(str, str, result=bool)
    def history_delete_message(self, nick, message_id):
        """Remove ONE message from a person's history."""
        clean = " ".join(str(nick or "").split()).strip()
        try:
            mid = int(str(message_id or "0").strip() or 0)
        except (TypeError, ValueError):
            mid = 0
        if not clean or mid <= 0:
            return False
        if self._archive is None:
            self.history_error.emit("history_delete_message",
                                    "the message archive is not running")
            return False

        async def work():
            token = await self._archive.repo.soft_delete_message(clean, mid)
            if not token:
                self.log_message.emit("⚠ That message is already gone", "warn")
                return
            self._push_global("archive", {
                "op": "delete_message", "nick": clean, "token": token,
                "message_id": mid})
            self.log_message.emit(
                f"🗑 One message removed from “{clean}” (Ctrl+Z restores it)",
                "info")
            self.userdb_changed.emit(json.dumps(
                {"action": "message_deleted", "nick": clean, "id": mid},
                ensure_ascii=False))
        self._run_async("history_delete_message", work())
        return True

    @Slot(str, result=bool)
    def history_purge_deleted(self, nick):
        """Erase the hidden rows for good (explicit, not undoable)."""
        if self._archive is None:
            return False

        async def work():
            gone = await self._archive.repo.purge_deleted(
                " ".join(str(nick or "").split()).strip())
            self.log_message.emit(
                f"🔥 {gone} hidden message(s) erased permanently", "warn")
            self.userdb_changed.emit(json.dumps(
                {"action": "purged", "nick": nick, "count": gone},
                ensure_ascii=False))
        self._run_async("history_purge_deleted", work())
        return True

    @Slot(str, result=bool)
    def history_restore_person(self, nick):
        if self._archive is None:
            return False

        async def work():
            ok = await self._archive.repo.restore_person(nick)
            self.userdb_changed.emit(json.dumps(
                {"action": "restored", "nick": nick, "ok": ok},
                ensure_ascii=False))
            await self._refresh_users()
        self._run_async("history_restore_person", work())
        return True

    @Slot(str, str, result=bool)
    def history_merge(self, from_nick, into_nick):
        if self._archive is None:
            return False

        async def work():
            moved = await self._archive.repo.merge_persons(from_nick,
                                                           into_nick)
            self.userdb_changed.emit(json.dumps(
                {"action": "merged", "nick": into_nick, "from": from_nick,
                 "moved": moved}, ensure_ascii=False))
        self._run_async("history_merge", work())
        return True

    # ── media + clipboard ────────────────────────────────────────
    def _emit_media_info(self, service, payload: dict, req_id: str = "") -> None:
        """Cache completions and RPCs share the same generation-guarded channel."""
        if service is not self._archive:
            return
        info = dict(payload, generation=service.generation)
        self.media_ready.emit(req_id, json.dumps(info, ensure_ascii=False))

    @Slot(str, str)
    def media_path(self, req_id, media_ref):
        if not self._need_archive("media_path", req_id):
            return

        async def work():
            payload = await self._archive.media.path_for(media_ref)
            payload["req_id"] = req_id
            payload["id"] = media_ref
            self._emit_media_info(self._archive, payload, req_id)
        self._run_async("media_path", work())

    @Slot(str, str)
    def media_restore(self, req_id, media_ref):
        """Re-download one failed/missing image or GIF on the user's request."""
        if not self._need_archive("media_restore", req_id):
            return

        async def work():
            payload = await self._archive.media.download_one(media_ref)
            payload["req_id"] = req_id
            payload["id"] = media_ref
            self._emit_media_info(self._archive, payload, req_id)
        self._run_async("media_restore", work())

    @Slot(str, result=str)
    def media_folder(self, nick):
        """Where this person's saved images and GIFs live on disk."""
        if self._archive is None:
            return ""
        try:
            return self._archive.media.folder_for(str(nick or ""))
        except Exception as exc:                      # noqa: BLE001
            log.debug("media folder unavailable: %s", exc)
            return ""

    # ═════════════════════════════════════════════════════════════
    # DB CONNECTION — create / load / delete / clean + size info
    #
    # Nothing is ever unlinked: delete and clean move the file into
    # db_trash/ first, so both are reversible with one Ctrl+Z.
    # ═════════════════════════════════════════════════════════════
    @Slot(result=str)
    def db_list(self):
        try:
            return json.dumps({"active": self.db_manager.active_path(),
                               **self.db_manager.snapshot()}, ensure_ascii=False)
        except Exception as exc:                      # noqa: BLE001
            log.warning("db_list failed: %s", exc)
            return json.dumps({"active": "", "items": [], "error": str(exc)})

    @Slot(str)
    def db_info(self, req_id):
        manager = self.db_manager
        manager.attach(self._archive)

        async def work():
            payload = await manager.info()
            payload["req_id"] = req_id
            self.db_info_ready.emit(req_id, json.dumps(payload,
                                                       ensure_ascii=False))
        self._run_async("db_info", work())

    @Slot(str, result=str)
    def db_reveal(self, path):
        """Filename click: select a real inventory file, without Load or Undo."""
        from backend.file_reveal import reveal_file
        manager = self.db_manager
        manager.attach(self._archive)
        try:
            result = manager.reveal_target(path)
            if result.get("ok"):
                result.update(reveal_file(result["reveal_path"]))
        except Exception as exc:
            result = {"ok": False, "error": f"Cannot reveal the database file: {exc}"}
        if result.get("error"):
            self.log_message.emit("⚠ " + result["error"], "warn")
        else:
            self.log_message.emit("📂 File location: " + result["reveal_path"], "info")
        return json.dumps(result, ensure_ascii=False)

    def _db_action(self, op: str, runner, success: str):
        """Run one DB action and record it as a single undo entry."""
        manager = self.db_manager
        manager.attach(self._archive)
        self._db_actions_pending = getattr(self, "_db_actions_pending", 0) + 1

        async def work():
            try:
                try:
                    result = await runner(manager)
                except Exception as exc:
                    log.exception("database action %s failed", op)
                    result = {"ok": False, "error": str(exc)}
                result = dict(result or {})
                result["op"] = result.get("op", op)
                if result.get("ok") and not result.get("unchanged"):
                    self._push_global("dbconn", {
                        "op": result["op"],
                        "command_id": uuid.uuid4().hex,
                        "was_active": bool(result.get("was_active", op == "clean")),
                        "path": result.get("path", ""),
                        "before_path": result.get("before_path", ""),
                        "backup": result.get("backup", ""),
                    })
                    self.log_message.emit(success.format(**{
                        "path": result.get("path", ""),
                        "name": os.path.basename(result.get("path", "")),
                    }), "success")
                elif result.get("error"):
                    self.log_message.emit("⚠ " + str(result["error"]), "warn")
                self._emit_db_change(op, result)
            finally:
                self._db_actions_pending -= 1
        self._run_async("db_" + op, work())
        return True

    @Slot(str, result=bool)
    def db_create(self, name):
        return self._db_action(
            "create", lambda m: m.create(name),
            "🆕 New database {name} created. Click Load to connect; the active archive is unchanged.")

    @Slot(str, result=bool)
    def db_load(self, path):
        return self._db_action(
            "load", lambda m: m.load(path),
            "🔌 Connected to {name}")

    @Slot(str, result=bool)
    def db_delete(self, path):
        return self._db_action(
            "delete", lambda m: m.delete(path),
            "🗑 {name} moved to db_trash — Ctrl+Z puts it back")

    @Slot(result=bool)
    def db_clean(self):
        return self._db_action(
            "clean", lambda m: m.clean(),
            "🧹 Database emptied (a backup went to db_trash — Ctrl+Z restores it)")

    @Slot(str, result=bool)
    def open_media_folder(self, nick):
        """Open that folder in Explorer/Finder/the file manager."""
        folder = self.media_folder(nick)
        if not folder:
            return False
        try:
            os.makedirs(folder, exist_ok=True)
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            ok = bool(QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
        except Exception as exc:                      # noqa: BLE001
            self.log_message.emit(f"⚠ Cannot open {folder}: {exc}", "warn")
            return False
        self.log_message.emit(f"📂 {folder}", "info")
        return ok

    @Slot(str)
    def copy_media(self, media_ref):
        """Left click on an image/GIF: put it on the system clipboard."""
        if self._archive is None:
            return

        async def work():
            payload = await self._archive.media.clipboard_payload(media_ref)
            if payload.get("ok"):
                placed = self._to_clipboard(payload)
                payload["copied"] = placed
                if placed:
                    self.log_message.emit(
                        "📋 Copied " + (payload.get("path") or
                                        payload.get("text") or "media"),
                        "success")
            self._emit_media_info(self._archive, payload, str(media_ref))
        self._run_async("copy_media", work())

    @Slot(str, result=bool)
    def copy_text(self, text):
        """Copy selected history text through Qt (works without a browser)."""
        return self._to_clipboard({"mode": "text", "text": str(text or "")})

    @staticmethod
    def _to_clipboard(payload: dict) -> bool:
        try:
            from PySide6.QtGui import QGuiApplication, QImage
            app = QGuiApplication.instance()
            if app is None:
                return False
            clipboard = app.clipboard()
            if clipboard is None:
                return False
            mode = payload.get("mode")
            path = payload.get("path") or ""
            if path and os.path.exists(path):
                # Carry the FILE itself (so a chat can attach it), the path
                # as text, and — for still images — the pixels as well.
                from PySide6.QtCore import QMimeData, QUrl
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(path)])
                mime.setText(path)
                if mode == "image":
                    image = QImage(path)
                    if not image.isNull():
                        mime.setImageData(image)
                clipboard.setMimeData(mime)
                return True
            if path:
                clipboard.setText(path)
                return True
            clipboard.setText(str(payload.get("text") or ""))
            return True
        except Exception as exc:                      # noqa: BLE001
            log.debug("clipboard unavailable: %s", exc)
            return False

    # ── the collector window ─────────────────────────────────────
    @Slot(result=str)
    def collector_state(self):
        if self._archive is None:
            return json.dumps({"state": "off", "text": "Archive not running",
                               "settings": {}, "paused": False})
        return json.dumps(self._archive.collector.state_payload(),
                          ensure_ascii=False)

    @Slot(str)
    def collector_set(self, settings_json):
        """Apply and persist collector settings from the panel."""
        if self._archive is None:
            return
        patch = self._json_arg(settings_json)
        applied = self._archive.collector.configure(**patch)
        stored = self._config.get_copy("collector", default={})
        if not isinstance(stored, dict):
            stored = {}
        stored.update({k: v for k, v in applied.items()})
        self._config.set("collector", stored)
        self._config.save()
        self.collector_status.emit(json.dumps(
            self._archive.collector.state_payload(), ensure_ascii=False))

    @Slot(str)
    def collector_command(self, command):
        """pause / resume / start / stop / tick — anything else is ignored."""
        if self._archive is None:
            return
        collector = self._archive.collector
        action = str(command or "").strip().lower()
        if action == "pause":
            collector.pause()
        elif action == "resume":
            collector.resume()
        elif action == "start":
            collector.start()
            self._archive.start()
        elif action == "stop":
            collector.stop()
        elif action == "tick":
            self._run_async("collector_tick", collector.tick())
        elif action in ("backfill_older", "backfill"):
            self._run_async("collector_backfill", collector.backfill_older())
        else:
            return
        self.collector_status.emit(json.dumps(collector.state_payload(),
                                              ensure_ascii=False))

    # ── My Nick (pinned header) ──────────────────────────────────
    @Slot(result=str)
    def get_my_nick(self):
        value = self._config.get("collector", "my_nick", default="")
        return str(value or "")

    @Slot(str)
    def set_my_nick(self, nick):
        clean = " ".join(str(nick or "").split()).strip()
        stored = self._config.get_copy("collector", default={})
        if not isinstance(stored, dict):
            stored = {}
        stored["my_nick"] = clean
        self._config.set("collector", stored)
        recent = [n for n in (self._config.get_state("my_nick_recent", []) or [])
                  if isinstance(n, str) and n and n != clean]
        if clean:
            recent.insert(0, clean)
        self._config.set_state(my_nick_recent=recent[:10])
        if self._archive is not None:
            self._archive.set_my_nick(clean)
        self.my_nick_changed.emit(clean)
        self.log_message.emit(f"👤 My Nick set to “{clean}”" if clean else
                              "👤 My Nick cleared", "info")

    @Slot(str)
    def detect_my_nick(self, req_id):
        """Read the bold nick from the page's user list as a suggestion."""
        if not self._need_archive("detect_my_nick", req_id):
            return

        async def work():
            state = await self._archive.parser.state()
            self.history_stats_ready.emit(req_id, json.dumps(
                {"req_id": req_id, "detected": state.get("me") or "",
                 "partner": state.get("partner") or ""}, ensure_ascii=False))
        self._run_async("detect_my_nick", work())

    # ── archive settings ─────────────────────────────────────────
    @Slot(result=str)
    def get_history_settings(self):
        if self._archive is None:
            return json.dumps(self._config.get_copy("history", default={}))
        return json.dumps(self._archive.settings(), ensure_ascii=False)

    @Slot(str)
    def save_history_settings(self, settings_json):
        patch = self._json_arg(settings_json)
        if self._archive is None:
            stored = self._config.get_copy("history", default={})
            stored.update(patch)
            self._config.set("history", stored)
            self._config.save()
            return
        self._archive.apply_settings(patch)
        self.log_message.emit("💾 Archive settings saved", "info")
