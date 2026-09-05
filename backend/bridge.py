"""QWebChannel bridge: routes calls between JS and Python backend."""

import asyncio
import copy
import json
import logging
from datetime import datetime
from PySide6.QtCore import QObject, Signal, Slot
from backend.cdp_client import CDPClient
from backend.user_memory import UserMemory
from backend.criteria_engine import CriteriaEngine
from backend.action_engine import ActionEngine, normalize_blocks
from backend.config_manager import ConfigManager, MAX_STACK_HISTORY
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

    def __init__(self, cdp, memory, criteria, engine, config,
                 presets: PresetStore | None = None, parent=None):
        super().__init__(parent)
        self._cdp, self._memory = cdp, memory
        self._criteria, self._engine = criteria, engine
        self._config, self._message_text = config, ""
        # Presets live in the SAME single JSON file as everything else.
        self._presets = presets or PresetStore(config=self._config)
        self._presets.import_legacy()
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

    def _push_global(self, kind: str, value) -> tuple[list, int]:
        if kind not in ("stack", "grid", "people"):
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
    WINDOW_IDS = {"stats", "filters", "stack", "config", "composer",
                  "people", "log"}
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
        if data.get("v") != 1:
            return None, f"unsupported version {data.get('v')!r}"
        tree, err = cls._normalize_grid_tree(data.get("tree"))
        if err:
            return None, err
        got = sorted(i for i in cls._leaf_ids(tree) if i)
        if got != sorted(cls.WINDOW_IDS):
            return None, "window set mismatch (every window must appear once)"
        return tree, None

    @classmethod
    def _canonical_grid_payload(cls, raw: str):
        tree, err = cls._parse_grid_payload(raw)
        if err:
            return None, err
        return json.dumps({"v": 1, "tree": tree}, ensure_ascii=False,
                          separators=(",", ":")), None

    @Slot(result=str)
    def get_grid_layout(self):
        """Serialized canonical grid tree, or empty before first customization."""
        raw = self._config.get_state("grid_layout", None)
        if not isinstance(raw, str) or not raw:
            return ""
        payload, err = self._canonical_grid_payload(raw)
        return payload if not err else ""

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
        payload = json.dumps({"v": 1, "tree": self._default_grid_tree()},
                             ensure_ascii=False, separators=(",", ":"))
        self._config.set_state(grid_layout=payload)
        self._push_global("grid", payload)
        self.log_message.emit("↺ Grid layout reset to default "
                              "(all windows visible)", "info")
        return payload

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

    def _apply_global_entry(self, entry):
        """Apply the state represented by a history entry.

        Stack/grid entries carry their after-state snapshot. A people entry
        carries {"before":…, "after":…}; when an undo/redo walk reaches it as
        the state to step ONTO, the after-state is the surface state at that
        point in the timeline (the tip-reversal case is handled separately by
        undo()/redo(), which apply the matching half).
        """
        kind = entry.get("kind")
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
            asyncio.ensure_future(self._refresh_users())

    @Slot(result=str)
    def undo(self):
        history, index = self._get_global_history()
        if not history or index < 0 or index >= len(history):
            self.log_message.emit("⚠ Nothing to undo", "warn")
            return "null"
        entry = history[index]
        # People entries are reversible commands: undoing the TIP entry must
        # restore the pre-edit list in a single step even when stack/grid
        # edits surround it in the timeline — and even when the people edit
        # is the FIRST entry of a fresh timeline (index 0 / nothing before).
        if entry.get("kind") == "people":
            value = entry.get("value")
            before = value.get("before") if isinstance(value, dict) else None
            if before is None:
                self.log_message.emit("⚠ Nothing to undo", "warn")
                return "null"
            self._apply_people(before)
            index -= 1
            self._set_global_history(history, index)
            self.history_changed.emit()
            self.log_message.emit("↩ Undo — people list restored", "info")
            result = {"kind": "people", "value": before}
            if index is not None:
                result["index"] = index
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
        history, index = self._get_global_history()
        if not history or index >= len(history) - 1:
            self.log_message.emit("⚠ Nothing to redo", "warn")
            return "null"
        index += 1
        entry = history[index]
        if entry.get("kind") == "people":
            value = entry.get("value")
            after = value.get("after") if isinstance(value, dict) else None
            if after is None:
                self.log_message.emit("⚠ Nothing to redo", "warn")
                return "null"
            self._apply_people(after)
            self._set_global_history(history, index)
            self.history_changed.emit()
            self.log_message.emit("↪ Redo — people list restored", "info")
            result = {"kind": "people", "value": after}
            if index is not None:
                result["index"] = index
            return json.dumps(result, ensure_ascii=False)
        self._set_global_history(history, index)
        self.history_changed.emit()
        self._apply_global_entry(entry)
        self.log_message.emit("↪ Redo — restored " + entry["kind"], "info")
        return self._global_result(entry, index)

    @staticmethod
    def _default_grid_tree() -> dict:
        """Mirror of SashCore.defaultTree(): all seven windows, classic order."""
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
        ], [46, 24, 30])

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
            self.log_message.emit("⚠ No Chrome tabs found — is Chrome running with "
                                  "--remote-debugging-port=9222?", "warn")
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
    def save_message(self, text): self._message_text = text
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
        self.users_updated.emit(json.dumps(
            [{"nick": u.nick, "gender": u.gender, "registered": u.registered,
              "anonymous": u.anonymous, "guest": u.guest, "messaged": u.messaged,
              "first_seen": u.first_seen, "last_messaged": u.last_messaged,
              "order": ranks.get(u.nick)}
             for u in users], ensure_ascii=False))
        self.stats_updated.emit(json.dumps(await self._memory.get_stats()))
