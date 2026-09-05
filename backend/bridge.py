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
    template_loaded = Signal(str, str)       # name, body

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

    def _on_person_found(self, payload: str) -> None:
        """Live update: a person just passed the filter during Scroll & Parse."""
        self.person_found.emit(payload)
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

    # ── history helpers (Feature #1 Undo/Redo) ───────────────────
    def _get_history(self) -> tuple[list, int]:
        """Return (history list, current index) with defaults."""
        hist = self._config.get_state("stack_history", [])
        idx = self._config.get_state("stack_history_index", -1)
        if not isinstance(hist, list):
            hist = []
        if not isinstance(idx, int):
            idx = -1
        # Normalize: ensure each entry is a list
        clean_hist = []
        for entry in hist:
            if isinstance(entry, list):
                clean_hist.append(entry)
        return clean_hist, idx

    def _set_history(self, history: list, index: int, save: bool = True) -> None:
        """Persist history and index."""
        # Ensure deep copy and enforce max limit already done by caller
        self._config.set_state(save=save,
                               stack_history=history,
                               stack_history_index=index)

    @staticmethod
    def _stacks_equal(a: list, b: list) -> bool:
        try:
            return json.dumps(a, sort_keys=True, ensure_ascii=False) == \
                   json.dumps(b, sort_keys=True, ensure_ascii=False)
        except Exception:
            return a == b

    # ── generic history engine ───────────────────────────────────
    # Both the action stack and the grid layout need identical semantics
    # (dedup, truncate-on-branch, 100-step cap). They keep SEPARATE
    # histories: undoing a window drag must never revert a block edit.
    def _hist_keys(self, kind: str) -> tuple[str, str]:
        base = "stack_history" if kind == "stack" else "grid_layout_history"
        return base, base + "_index"

    def _get_hist(self, kind: str) -> tuple[list, int]:
        hk, ik = self._hist_keys(kind)
        hist = self._config.get_state(hk, []) or []
        idx = self._config.get_state(ik, -1)
        if not isinstance(hist, list):
            hist, idx = [], -1
        if not isinstance(idx, int):
            idx = len(hist) - 1
        return hist, max(-1, min(idx, len(hist) - 1))

    def _set_hist(self, kind: str, hist: list, idx: int) -> None:
        hk, ik = self._hist_keys(kind)
        self._config.set_state(**{hk: hist, ik: idx})

    def _push_hist(self, kind: str, value) -> tuple[list, int]:
        """Append a snapshot, deduping and capping. Returns (history, index)."""
        hist, idx = self._get_hist(kind)
        if not hist:
            hist = [copy.deepcopy(value)]
            self._set_hist(kind, hist, 0)
            return hist, 0
        if 0 <= idx < len(hist) and self._stacks_equal(hist[idx], value):
            return hist, idx            # no-op edit
        if idx < len(hist) - 1:
            hist = hist[:idx + 1]       # branching discards the redo tail
        hist.append(copy.deepcopy(value))
        idx = len(hist) - 1
        if len(hist) > MAX_STACK_HISTORY:
            overflow = len(hist) - MAX_STACK_HISTORY
            hist = hist[overflow:]
            idx = max(0, idx - overflow)
        self._set_hist(kind, hist, idx)
        return hist, idx

    # ── grid layout (flexible grid / sash layout) ────────────────
    WINDOW_IDS = {"stats", "filters", "stack", "config", "composer",
                  "people", "log"}

    @classmethod
    def _validate_grid_tree(cls, node, depth: int = 0):
        """Mirror of SashCore.validate — never store a tree we cannot read back."""
        if depth > 12:
            return "tree too deep"
        if not isinstance(node, dict):
            return "node must be an object"
        if node.get("type") == "leaf":
            return None if node.get("id") else "leaf without id"
        if node.get("type") != "split":
            return "unknown node type"
        if node.get("dir") not in ("row", "col"):
            return "bad dir"
        kids, sizes = node.get("children"), node.get("sizes")
        if not isinstance(kids, list) or len(kids) < 2:
            return "split needs >=2 children"
        if not isinstance(sizes, list) or len(sizes) != len(kids):
            return "sizes must match children"
        for size in sizes:
            if not isinstance(size, (int, float)) or size <= 0:
                return "bad size value"
        if not 99.5 <= sum(sizes) <= 100.5:
            return "sizes must sum to 100"
        for kid in kids:
            err = cls._validate_grid_tree(kid, depth + 1)
            if err:
                return err
        return None

    @classmethod
    def _leaf_ids(cls, node, out=None):
        out = [] if out is None else out
        if isinstance(node, dict):
            if node.get("type") == "leaf":
                out.append(node.get("id"))
            else:
                for kid in node.get("children") or []:
                    cls._leaf_ids(kid, out)
        return out

    @classmethod
    def _parse_grid_payload(cls, raw: str):
        """Return (tree, None) or (None, error)."""
        try:
            data = json.loads(raw)
        except Exception as exc:
            return None, f"bad JSON ({exc})"
        if not isinstance(data, dict):
            return None, "payload must be an object"
        if data.get("v") != 1:
            return None, f"unsupported version {data.get('v')!r}"
        tree = data.get("tree")
        err = cls._validate_grid_tree(tree)
        if err:
            return None, err
        got = sorted(i for i in cls._leaf_ids(tree) if i)
        if got != sorted(cls.WINDOW_IDS):
            return None, "window set mismatch (every window must appear once)"
        return tree, None

    @Slot(result=str)
    def get_grid_layout(self):
        """Serialized grid tree, or "" when the user has never customised it."""
        raw = self._config.get_state("grid_layout", None)
        return raw if isinstance(raw, str) and raw else ""

    @Slot(str, result=bool)
    def save_grid_layout(self, layout_json):
        """Validate and persist the grid, pushing an undo step."""
        tree, err = self._parse_grid_payload(layout_json or "")
        if err:
            # Reject rather than store: a bad tree would brick every start.
            log.warning("Grid layout rejected: %s", err)
            self.log_message.emit(f"⚠ Grid layout not saved: {err}", "warn")
            return False
        payload = json.dumps({"v": 1, "tree": tree}, ensure_ascii=False)
        self._config.set_state(grid_layout=payload)
        self._push_hist("grid", payload)
        return True

    @Slot(result=str)
    def reset_grid_layout(self):
        """Restore the default grid with EVERY window visible."""
        payload = json.dumps({"v": 1, "tree": self._default_grid_tree()},
                             ensure_ascii=False)
        self._config.set_state(grid_layout=payload)
        self._push_hist("grid", payload)
        self.log_message.emit("↺ Grid layout reset to default "
                              "(all windows visible)", "info")
        return payload

    @Slot(result=str)
    def undo_grid_layout(self):
        hist, idx = self._get_hist("grid")
        if idx <= 0 or not hist:
            self.log_message.emit("⚠ Nothing to undo in the grid layout", "warn")
            return "null"
        idx -= 1
        self._set_hist("grid", hist, idx)
        self._config.set_state(grid_layout=hist[idx])
        self.log_message.emit("↩ Grid layout undo", "info")
        return hist[idx]

    @Slot(result=str)
    def redo_grid_layout(self):
        hist, idx = self._get_hist("grid")
        if idx < 0 or idx >= len(hist) - 1:
            self.log_message.emit("⚠ Nothing to redo in the grid layout", "warn")
            return "null"
        idx += 1
        self._set_hist("grid", hist, idx)
        self._config.set_state(grid_layout=hist[idx])
        self.log_message.emit("↪ Grid layout redo", "info")
        return hist[idx]

    @staticmethod
    def _default_grid_tree() -> dict:
        """Mirror of SashCore.defaultTree(): all seven windows, classic order."""
        def leaf(i):
            return {"type": "leaf", "id": i}

        def split(d, kids, sizes):
            return {"type": "split", "dir": d, "children": kids, "sizes": sizes}

        return split("col", [
            split("row", [
                split("col", [leaf("stats"), leaf("filters")], [35, 65]),
                split("col", [leaf("stack"), leaf("config")], [72, 28]),
            ], [17, 83]),
            leaf("composer"),
            split("row", [leaf("people"), leaf("log")], [70, 30]),
        ], [46, 24, 30])

    def _push_history(self, blocks: list[dict]) -> tuple[list, int]:
        """Push a stack snapshot to history, handling dedup, truncation, max limit.
        Returns (new_history, new_index).
        """
        if not isinstance(blocks, list):
            return self._get_history()
        # Normalize enabled field for backward compat
        norm_blocks = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            nb = dict(b)
            if "enabled" not in nb:
                nb["enabled"] = True
            norm_blocks.append(nb)

        history, idx = self._get_history()

        # If history empty, init
        if not history:
            history = [copy.deepcopy(norm_blocks)]
            idx = 0
            self._set_history(history, idx)
            return history, idx

        # If current index points to same stack, don't push duplicate
        if 0 <= idx < len(history):
            if self._stacks_equal(history[idx], norm_blocks):
                return history, idx

        # Truncate future if we are not at tip (undo then new edit)
        if idx < len(history) - 1:
            history = history[:idx + 1]

        # Append new
        history.append(copy.deepcopy(norm_blocks))
        idx = len(history) - 1

        # Enforce max limit
        if len(history) > MAX_STACK_HISTORY:
            overflow = len(history) - MAX_STACK_HISTORY
            history = history[overflow:]
            idx = max(0, idx - overflow)

        self._set_history(history, idx)
        log.info("History pushed: %d entries, index %d", len(history), idx)
        return history, idx

    # ── unified app state (BUG #2 restore / single store) ────────
    @Slot(result=str)
    def get_app_state(self):
        """Everything the UI needs to restore the last session: ONE payload."""
        history, h_idx = self._get_history()
        payload = {
            "url_presets": list(self._config.get("url_presets", default=[])),
            "custom_blocks": self._custom_blocks_raw(),
            "stack_presets": self._presets.list_stacks(),
            "template_presets": self._presets.list_templates(),
            "state": {
                "last_url_preset": self._config.get_state("last_url_preset", ""),
                "last_stack_preset": self._config.get_state("last_stack_preset", ""),
                "last_stack": self._config.get_state("last_stack", None),
                "stack_history": history,
                "stack_history_index": h_idx,
                "grid_layout": self._config.get_state("grid_layout", None),
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
        blocks = self._clean_blocks(blocks)
        # Save last_stack
        self._config.set_state(last_stack=blocks, last_stack_preset="")
        # Push to history (auto-save history)
        self._push_history(blocks)

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
        """Undo to previous stack, return its JSON or null if not possible."""
        hist, idx = self._get_history()
        if idx <= 0 or not hist:
            self.log_message.emit("⚠ Nothing to undo", "warn")
            return "null"
        idx -= 1
        blocks = self._clean_blocks(hist[idx])
        self._set_history(hist, idx)
        self._config.set_state(last_stack=blocks, last_stack_preset="")
        self._engine.load_stack(blocks)
        payload = json.dumps(blocks, ensure_ascii=False)
        self.stack_loaded.emit("", payload)
        self.log_message.emit(f"↩ Undo — restored {len(blocks)} block(s)", "info")
        return payload

    @Slot(result=str)
    def redo_stack(self):
        """Redo to next stack, return its JSON or null if not possible."""
        hist, idx = self._get_history()
        if idx < 0 or idx >= len(hist) - 1:
            self.log_message.emit("⚠ Nothing to redo", "warn")
            return "null"
        idx += 1
        blocks = self._clean_blocks(hist[idx])
        self._set_history(hist, idx)
        self._config.set_state(last_stack=blocks, last_stack_preset="")
        self._engine.load_stack(blocks)
        payload = json.dumps(blocks, ensure_ascii=False)
        self.stack_loaded.emit("", payload)
        self.log_message.emit(f"↪ Redo — restored {len(blocks)} block(s)", "info")
        return payload

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
        c = await self._memory.reset_messaged()
        self.log_message.emit(f"🔄 Reset {c} users", "info")
        await self._refresh_users()

    async def _do_clear(self):
        c = await self._memory.clear_all()
        self.log_message.emit(f"🗑 Cleared {c} users", "warn")
        self.users_deleted.emit("[]", c)
        await self._refresh_users()

    async def _do_delete_one(self, nick):
        nick = (nick or "").strip()
        if not nick:
            self.log_message.emit("⚠ No nick given — nothing deleted", "warn")
            return
        try:
            ok = await self._memory.delete_user(nick)
        except Exception as exc:
            self.log_message.emit(f"❌ Delete failed for “{nick}”: {exc}", "error")
            return
        if ok:
            self.log_message.emit(f"🗑 Deleted user “{nick}”", "warn")
            self.users_deleted.emit(json.dumps([nick], ensure_ascii=False), 1)
        else:
            self.log_message.emit(f"⚠ User “{nick}” not found", "warn")
        await self._refresh_users()

    async def _do_delete_many(self, nicks):
        if not nicks:
            self.log_message.emit("⚠ Nothing selected — nothing deleted", "warn")
            return
        try:
            count = await self._memory.delete_users(nicks)
        except Exception as exc:
            self.log_message.emit(f"❌ Delete failed: {exc}", "error")
            return
        self.log_message.emit(
            f"🗑 Deleted {count} selected user(s)"
            + (f": {', '.join(nicks[:5])}" + ("…" if len(nicks) > 5 else "")
               if count else ""), "warn")
        self.users_deleted.emit(json.dumps(nicks, ensure_ascii=False), count)
        await self._refresh_users()

    async def _do_set_messaged(self, nick, messaged):
        try:
            ok = await self._memory.set_messaged(nick, messaged)
        except Exception as exc:
            self.log_message.emit(f"❌ Update failed for “{nick}”: {exc}", "error")
            return
        if ok:
            self.log_message.emit(
                f"{'✅' if messaged else '↩'} “{nick}” marked as "
                f"{'messaged' if messaged else 'new'}", "info")
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
        self.users_updated.emit(json.dumps(
            [{"nick": u.nick, "gender": u.gender, "registered": u.registered,
              "anonymous": u.anonymous, "guest": u.guest, "messaged": u.messaged,
              "first_seen": u.first_seen, "last_messaged": u.last_messaged}
             for u in users], ensure_ascii=False))
        self.stats_updated.emit(json.dumps(await self._memory.get_stats()))
