"""Action stack executor: runs blocks sequentially over queued users.

Provides the step-by-step "debugger" contract:
  * `debug_msg(message, level)`  — live detail lines streamed to the UI log
    console (element search results, clickability, per-step status, timing).
  * `step_started(index, block_id, nick)` — lets the UI highlight the running
    block in the stack.
  * every run writes a JSONL trace to logs/run_trace_<run_id>.jsonl so issues
    can be traced after the run.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Callable, Optional
from PySide6.QtCore import QObject, Signal
from backend.cdp_client import CDPClient
from backend.user_memory import UserMemory, UserRecord
from backend.scroll_parser import ScrollParser
from backend.criteria_engine import CriteriaEngine
from actions.base_action import BaseAction, ActionResult, get_action_class

log = logging.getLogger("chatbot")

#: Blocks that only make sense in the context of a concrete queued user.
#: A stack made exclusively of other blocks (tab clicks, waits, DOM checks) is
#: user-independent and must still run exactly once even with an empty queue —
#: otherwise it silently does nothing (see docs/FIND_CLICK_VISUAL_
#: CONFIRMATION_DESIGN_2026-09-05.md).
USER_SCOPED_BLOCKS = frozenset({
    "SCROLL_PARSE", "CONDITIONAL_SKIP", "CLICK_USER",
    "TYPE_MESSAGE", "CLICK_SEND", "ATTACH_IMAGE",
})

#: Nick used for the synthetic user of a standalone (user-independent) run.
STANDALONE_NICK = "—"

#: Block settings that no longer exist for any block. Kept for backward
#: compatibility — old config.json stacks / presets / undo history still
#: carry them — but stripped on the way IN so they are never instantiated,
#: persisted, or sent back to the UI (where the Tune panel renders one row
#: per key). Mirrors RETIRED_KEYS in ui/js/stack-dnd.js and the dead-kwargs
#: list popped by ScrollParse.__init__.
RETIRED_BLOCK_KEYS = frozenset({
    "use_panel_filters",   # duplicate of the four tri-state filter selects
    "skip_if_backlog",     # replaced by the scroll_only seek mode
    "backlog_threshold",
})


def normalize_blocks(blocks) -> list[dict]:
    """Coerce a raw stack payload into clean block dicts.

    Drops non-dict entries, removes retired keys, and ensures ``enabled``
    defaults to True (backward compat). A safety net applied wherever a
    stack enters the backend (run, snapshot, history, preset save/load);
    the JS migration is the primary path that also back-fills missing
    settings — this only guarantees dead keys never survive server-side.
    """
    clean: list[dict] = []
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        nb = {k: v for k, v in b.items()
              if k not in RETIRED_BLOCK_KEYS and not str(k).startswith("_")}
        if "enabled" not in nb or nb["enabled"] is None:
            nb["enabled"] = True
        clean.append(nb)
    return clean


class RunTracer:
    """Appends one JSON line per event to logs/run_trace_<run_id>.jsonl."""

    def __init__(self, run_id: str, log_dir: str = "logs"):
        os.makedirs(log_dir, exist_ok=True)
        self.run_id = run_id
        self.path = os.path.join(log_dir, f"run_trace_{run_id}.jsonl")
        self._fh = open(self.path, "a", encoding="utf-8")

    def note(self, record: dict) -> None:
        try:
            rec = {"ts": datetime.now().isoformat(timespec="milliseconds"),
                   "run_id": self.run_id, **record}
            self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._fh.flush()
        except OSError as exc:
            log.error("Trace write failed: %s", exc)

    def close(self) -> None:
        try:
            self._fh.close()
        except OSError:
            pass


_LEVEL_MAP = {
    "ok": "success", "success": "success", "done": "success",
    "info": "info", "debug": "info",
    "warn": "warn", "warning": "warn",
    "error": "error", "fail": "error",
}


def norm_level(level: str) -> str:
    return _LEVEL_MAP.get((level or "info").lower(), "info")


class ActionEngine(QObject):
    """Execute a stack of action blocks over a user queue."""

    step_complete = Signal(str, str)      # block_name, user_nick
    user_complete = Signal(str, bool)     # user_nick, success
    person_marked = Signal(str)           # user_nick just marked messaged by a run
    stack_complete = Signal()
    log_msg = Signal(str)
    debug_msg = Signal(str, str)          # message, level (info|success|warn|error)
    step_started = Signal(int, str, str)  # step index (1-based), block_id, user_nick
    person_found = Signal(str)            # JSON: one newly collected person
    person_removed = Signal(str)          # JSON: one purged (filtered-out) person

    def __init__(self, cdp: CDPClient, memory: UserMemory,
                 criteria: CriteriaEngine, parent: QObject | None = None):
        super().__init__(parent)
        self._cdp = cdp
        self._memory = memory
        self._criteria = criteria
        #: exposed so blocks can reach the global Filter panel criteria
        self.criteria = criteria
        self._stack: list[BaseAction] = []
        self._running = False
        self._paused = False
        self._stop_requested = False
        self._tracer: Optional[RunTracer] = None
        self._ctx: dict = {}       # current step context for report()
        self._run_seq = 0
        # Live copy of the Message Composer window text. The Bridge mirrors
        # every composer keystroke here so blocks (TYPE_MESSAGE with
        # use_composer) read the CURRENT text at run time.
        self.composer_text = ""

    # ── stack management ─────────────────────────────────────────
    def load_stack(self, blocks: list[dict]) -> None:
        """Build action list from block config dicts."""
        self._stack.clear()
        for b in normalize_blocks(blocks):
            cls = get_action_class(b.get("block_id", ""))
            if cls:
                # enabled is guaranteed True-by-default by normalize_blocks
                data = {k: v for k, v in b.items() if k != "block_id"}
                self._stack.append(cls(**data))
        log.info("Stack loaded: %d blocks (%d enabled)", len(self._stack),
                 sum(1 for a in self._stack if getattr(a, "enabled", True)))

    def get_stack(self) -> list[dict]:
        return [a.to_dict() for a in self._stack]

    # ── execution control ────────────────────────────────────────
    @property
    def is_running(self) -> bool:
        return self._running

    def stop(self) -> None:
        self._stop_requested = True

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    # ── step reporting API (used by action blocks) ───────────────
    def report(self, message: str, level: str = "info") -> None:
        """Stream a detail line about the currently executing step."""
        level = norm_level(level)
        self.debug_msg.emit(f"      {message}", level)
        if self._tracer is not None:
            self._tracer.note({"type": "detail", "level": level,
                               "message": message, **self._ctx})

    # ── live collection hook (used by SCROLL_PARSE) ──────────────
    async def person_collected(self, record, collected: list) -> None:
        """Persist a just-collected person and refresh the UI immediately.

        Called by the Scroll & Parse pipeline the moment a person passes the
        filter, so the list updates in real time instead of only when the
        whole scroll cycle finishes.
        """
        try:
            await self._memory.upsert_user(record)
        except Exception as exc:
            log.warning("Live upsert failed for %s: %s", record.nick, exc)
        payload = {"nick": record.nick, "gender": record.gender,
                   "registered": bool(record.registered),
                   "anonymous": bool(record.anonymous),
                   "guest": bool(record.guest),
                   "messaged": bool(record.messaged),
                   "collected": len(collected)}
        self.person_found.emit(json.dumps(payload, ensure_ascii=False))
        if self._tracer is not None:
            self._tracer.note({"type": "person_collected", **payload})

    async def unmessaged_nicks(self) -> set[str]:
        """Nicks already in the list that have not been messaged yet.

        Used by Scroll & Parse's scroll-only mode. Fails open (empty set →
        normal collection) so a read problem can never leave the block idle.
        """
        try:
            return {u.nick for u in await self._memory.get_all()
                    if not u.messaged}
        except Exception as exc:
            log.warning("Un-messaged read failed (collecting instead): %s", exc)
            return set()

    def is_stopping(self) -> bool:
        """Predicate handed to long-running phases so Stop is honoured."""
        return self._stop_requested

    async def person_rejected(self, record, reason: str) -> bool:
        """Destroy any stored record for a person that FAILED the filter.

        Prevents a filtered-out person from lingering in the list after an
        earlier run (or a run under a laxer filter). Returns True when a stored
        record was actually removed.
        """
        removed = False
        try:
            deleter = getattr(self._memory, "delete_user", None)
            if deleter is not None:
                removed = bool(await deleter(record.nick))
        except Exception as exc:
            log.warning("Purge failed for %s: %s", record.nick, exc)
            return False
        if removed:
            payload = {"nick": record.nick, "reason": reason}
            self.person_removed.emit(json.dumps(payload, ensure_ascii=False))
            self.debug_msg.emit(
                f"      🗑 Removed “{record.nick}” — {reason}", "warn")
            if self._tracer is not None:
                self._tracer.note({"type": "person_purged", **payload})
        return removed

    # ── main execution loop ──────────────────────────────────────
    def queue_order(self, users: list) -> list[str]:
        """The nick order a run would process right now (1st → last).

        Mirrors the two queue-building branches of `_execute_cycle`:
          * an ENABLED SCROLL_PARSE block is present  → the collect phase
            sorts people with sort_people (un-messaged first, A–Z);
          * otherwise                                → UserMemory.get_queue
            (WHERE messaged=0 ORDER BY first_seen DESC).
        Only un-messaged people are ever processed, so messaged users are
        excluded here too.
        """
        scroll_block = next((b for b in self._stack
                             if b.block_id == "SCROLL_PARSE"
                             and getattr(b, "enabled", True)), None)
        unmessaged = [u for u in users if not getattr(u, "messaged", False)]
        if scroll_block is not None:
            from backend.person_filter import sort_people
            ordered = sort_people(unmessaged)
        else:
            # Stable: newest-discovered first, nick A–Z breaks ties so the
            # order never flickers between refreshes.
            ordered = sorted(
                sorted(unmessaged, key=lambda u: str(getattr(u, "nick", ""))
                       .casefold()),
                key=lambda u: str(getattr(u, "first_seen", "") or ""),
                reverse=True)
        return [getattr(u, "nick", "") for u in ordered]

    def _repeat_cycles(self) -> int:
        """How many times the whole stack runs per Run press.

        The first ENABLED Repeat Loop marker decides; with no marker (or it
        is disabled / count ≤ 1) the run plays exactly once, as before.
        """
        marker = next((b for b in self._stack
                       if b.block_id == "REPEAT_LOOP"
                       and getattr(b, "enabled", True)), None)
        if marker is None:
            return 1
        try:
            return max(1, int(getattr(marker, "repeat_count", 1)))
        except (TypeError, ValueError):
            return 1

    async def execute(self, scroll_parser: ScrollParser | None = None) -> None:
        """Run the full stack over the user queue.

        When a Repeat Loop marker is enabled with count N, the whole
        pipeline (collect phase + per-user messaging) runs N cycles so one
        press of Run keeps harvesting without being clicked again.
        """
        if self._running:
            self.log_msg.emit("⚠ Already running")
            return
        self._running = True
        self._stop_requested = False
        self._paused = False
        self._run_seq += 1
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{self._run_seq}"
        self._tracer = RunTracer(run_id)
        self.log_msg.emit(f"▶▶ Run #{run_id} started")
        self.debug_msg.emit(f"📄 Trace file: {self._tracer.path}", "info")
        self._tracer.note({"type": "run_start",
                           "blocks": [b.block_id for b in self._stack]})
        cycles = self._repeat_cycles()
        try:
            if cycles > 1:
                self.log_msg.emit(
                    f"🔁 Repeat Loop: the stack will run {cycles} cycles — "
                    "Stop ends it at any time")
                self._tracer.note({"type": "repeat", "cycles": cycles})
            done = False
            outcome = "worked"
            for cycle in range(1, cycles + 1):
                if self._stop_requested:
                    self.debug_msg.emit("⏹ Stack stopped by user", "warn")
                    self._tracer.note({"type": "run_end", "reason": "stopped"})
                    break
                await self._wait_if_paused()
                if self._stop_requested:
                    self.debug_msg.emit("⏹ Stack stopped by user", "warn")
                    self._tracer.note({"type": "run_end", "reason": "stopped"})
                    break
                if cycles > 1:
                    self.log_msg.emit(f"🔁 Cycle {cycle}/{cycles} — running…")
                    self._tracer.note({"type": "cycle_start", "cycle": cycle,
                                       "total": cycles})
                outcome = await self._execute_cycle()
                if outcome == "stopped":
                    break
                if outcome == "empty_stack":
                    done = True   # nothing to run at all
                    break
                if outcome == "empty":
                    # A user-scoped stack found nobody. Warned inside the
                    # cycle; repeating it would only re-run empty cycles.
                    if cycles > 1:
                        self.log_msg.emit(
                            "🔁 No users found — Repeat Loop ends the run "
                            f"after cycle {cycle}")
                    done = True
                    break
                if cycle >= cycles:
                    done = True
            if done:
                self._tracer.note({"type": "run_end", "reason": "completed"})
        except Exception as exc:
            log.error("Stack execution error: %s", exc, exc_info=True)
            self.log_msg.emit(f"❌ Error: {exc}")
            self.debug_msg.emit(f"❌ Fatal error: {exc}", "error")
            if self._tracer:
                self._tracer.note({"type": "run_end", "reason": "exception",
                                   "error": str(exc)})
        finally:
            if self._tracer:
                self._tracer.close()
                self._tracer = None
            self._running = False
            self._ctx = {}
            self.stack_complete.emit()
            self.log_msg.emit("✅ Stack execution complete")

    async def _execute_cycle(self) -> str:
        """One full run cycle: collect → build queue → per-user execution.

        Returns the outcome for the repeat-loop driver:
          "worked"      — people (or a standalone synthetic user) ran;
          "stopped"     — Stop was requested during the cycle;
          "empty"       — the stack needs users but none are available;
          "empty_stack" — there is nothing to run at all.
        """
        # Phase 1: collect people — the SCROLL_PARSE block owns the whole
        # scroll → filter → collect → order pipeline (STEPS 1-3).
        # Only an ENABLED block runs (enable/disable toggle).
        scroll_block = next((b for b in self._stack
                             if b.block_id == "SCROLL_PARSE"
                             and getattr(b, "enabled", True)), None)
        collected: list[UserRecord] = []
        if scroll_block is not None:
            collected = await self._run_collect_phase(scroll_block)
        # Phase 2: build queue
        queue = collected if scroll_block is not None \
            else await self._memory.get_queue()
        # Phase 2b: Click User "Respect the Order (#) column" override — when
        # an enabled CLICK_USER asks for it, work the People list in Order (#)
        # sequence (#1 first … #N) instead of whatever this run collected.
        queue = await self._order_queue_by_column(queue)
        has_skip = any(b.block_id == "CONDITIONAL_SKIP"
                       and getattr(b, "enabled", True)
                       for b in self._stack)
        needs_user = [b.block_id for b in self._stack
                      if b.block_id in USER_SCOPED_BLOCKS and getattr(b, "enabled", True)]
        standalone = False
        if queue:
            self.log_msg.emit(f"▶ Running stack on {len(queue)} user(s)")
        elif not self._stack:
            self.log_msg.emit("⚠ The stack is empty — add at least one block")
            self.debug_msg.emit("⚠ Nothing to run: the action stack is empty",
                                "warn")
            return "empty_stack"
        elif needs_user:
            # The stack genuinely needs users but there are none. Say so
            # loudly instead of the old misleading "0 user(s)" line.
            self.log_msg.emit("⚠ No users in queue — nothing to run")
            self.debug_msg.emit(
                "⚠ The queue is empty and this stack contains user-dependent "
                "block(s): " + ", ".join(sorted(set(needs_user)))
                + ". Add a Scroll & Parse block (or reset the 'messaged' flags) "
                  "so there are users to run on.", "warn")
            self._tracer.note({"type": "run_skip", "reason": "empty_queue",
                               "needs_user": sorted(set(needs_user))})
            return "empty"
        else:
            # User-independent stack (e.g. a single "Find & Click" tab block):
            # run it exactly once against a synthetic user.
            standalone = True
            queue = [UserRecord(nick=STANDALONE_NICK)]
            self.log_msg.emit("▶ Running stack once (standalone — no user "
                              "context needed)")
            self.debug_msg.emit(
                "ℹ Standalone run: this stack contains no user-dependent "
                "blocks, so it executes once independently of the user queue.",
                "info")
            self._tracer.note({"type": "run_mode", "mode": "standalone"})
        # Phase 3: per-user execution
        for user in queue:
            if self._stop_requested:
                self.debug_msg.emit("⏹ Stack stopped by user", "warn")
                self._tracer.note({"type": "run_end", "reason": "stopped"})
                return "stopped"
            await self._wait_if_paused()
            if self._stop_requested:
                self.debug_msg.emit("⏹ Stack stopped by user", "warn")
                self._tracer.note({"type": "run_end", "reason": "stopped"})
                return "stopped"
            ok = await self._execute_for_user(user, has_skip)
            if ok and not standalone:
                await self._memory.mark_messaged(user.nick)
                # Live status update: the UI re-renders the row (✅ Done) the
                # moment the person is messaged, not only after a restart.
                self.person_marked.emit(user.nick)
            if not standalone:
                self.user_complete.emit(user.nick, ok)
        return "worked"

    async def _order_queue_by_column(self, queue: list[UserRecord]) \
            -> list[UserRecord]:
        """Click User setting: replace the queue with the People-list order.

        When an enabled CLICK_USER block has ``respect_order`` on, the run
        must process every Status-New person strictly in the Order (#) column
        sequence (#1 first, then #2 … N) — the exact order the grid derives
        from :meth:`queue_order` — instead of whichever people the scroll
        phase happened to collect/find this run. An empty queue stays empty:
        if the page had nobody to click, memory-only rows (not currently
        visible) must not turn into a run of failing clicks.
        """
        wants_order = any(
            b.block_id == "CLICK_USER"
            and getattr(b, "respect_order", False)
            and getattr(b, "enabled", True)
            for b in self._stack)
        if not wants_order or not queue:
            return queue
        rows = await self._memory.get_all()
        ordered_nicks = self.queue_order(rows)
        by_nick = {getattr(r, "nick", ""): r for r in rows}
        ranked = [by_nick[n] for n in ordered_nicks if n in by_nick]
        if not ranked:
            return queue
        self.log_msg.emit(
            f"🔢 Respecting the Order (#) column — running {len(ranked)} "
            "person(s) in list order (#1 first)")
        if self._tracer is not None:
            self._tracer.note({"type": "queue_mode", "mode": "respect_order",
                               "count": len(ranked)})
        return ranked

    async def _wait_if_paused(self) -> None:
        while self._paused and not self._stop_requested:
            await asyncio.sleep(0.2)

    async def _run_collect_phase(self, block) -> list[UserRecord]:
        """Run the SCROLL_PARSE block's pipeline and return the ordered queue."""
        self.log_msg.emit("📜 Collecting people (Scroll & Parse)…")
        self._tracer.note({"type": "phase", "phase": "collect"})
        self._ctx = {"block_id": block.block_id, "block_name": block.display_name,
                     "phase": "collect"}
        self.step_started.emit(1, block.block_id, "—")
        try:
            known = {u.nick for u in await self._memory.get_all() if u.messaged}
        except Exception:
            known = set()
        try:
            result = await block.run_pipeline(
                self._cdp, self, panel_criteria=self._criteria,
                known_messaged=known)
        except Exception as exc:
            log.exception("Collect phase failed")
            self.debug_msg.emit(f"      ❌ Scroll & Parse raised: {exc}", "error")
            self._tracer.note({"type": "phase_end", "phase": "collect",
                               "status": "exception", "error": str(exc)})
            self._ctx = {}
            return []
        # Persist ONLY the people that passed the filter. Storing every person
        # we merely *saw* is what used to put filtered-out people (e.g. men
        # under a "female only" filter) into the list, where they survived
        # across runs. Collected people are already upserted live; this pass is
        # an idempotent safety net.
        for person in result.collected:
            try:
                await self._memory.upsert_user(person)
            except Exception as exc:
                log.warning("upsert failed for %s: %s", person.nick, exc)
        if result.seeking:
            if result.found is not None:
                self.log_msg.emit(
                    f"🎯 Scroll-only: found “{result.found.nick}” on the page "
                    "— no new people were added")
            else:
                self.log_msg.emit(
                    "🔎 Scroll-only: no un-messaged person from the list is "
                    "currently on the page")
        else:
            summary = (f"📜 Seen {len(result.all_people)} person(s), "
                       f"{len(result.collected)} matched the filter")
            if result.purged:
                summary += f", {len(result.purged)} removed"
            self.log_msg.emit(summary)
        self._tracer.note({"type": "phase_end", "phase": "collect",
                           "seen": len(result.all_people),
                           "collected": len(result.collected),
                           "scrolls": result.scrolls,
                           "reached_end": result.reached_end,
                           "stopped_early": result.stopped_early,
                           "stopped": result.stopped,
                           "seeking": result.seeking,
                           "found": getattr(result.found, "nick", None),
                           "purged": len(result.purged)})
        self.step_complete.emit(block.display_name, "—")
        self._ctx = {}
        if result.stopped or self._stop_requested:
            self.debug_msg.emit("      ⏹ Collection stopped by user — not "
                                "queueing anyone from this run", "warn")
            return []
        return [p for p in result.collected if not p.messaged]

    async def _execute_for_user(self, user: UserRecord, has_skip: bool) -> bool:
        """Execute all blocks for one user."""
        if user.messaged and has_skip:
            self.log_msg.emit(f"⏭ Skipping (already messaged): {user.nick}")
            return False
        total = len(self._stack)
        enabled_count = sum(1 for b in self._stack if getattr(b, "enabled", True))
        if enabled_count == 0:
            self.debug_msg.emit("⚠ All blocks are disabled — nothing to run", "warn")
            self._tracer.note({"type": "run_skip", "reason": "all_disabled"})
            return True
        for idx, block in enumerate(self._stack, start=1):
            if self._stop_requested:
                return False
            await self._wait_if_paused()
            # Skip disabled blocks
            if not getattr(block, "enabled", True):
                self.debug_msg.emit(
                    f"      ⏭ Skipped disabled block [{block.block_id}] {block.display_name}",
                    "warn")
                self._tracer.note({"type": "step_skip", "reason": "disabled",
                                   "block_id": block.block_id,
                                   "block_name": block.display_name,
                                   "step": idx})
                continue
            if block.block_id == "CONDITIONAL_SKIP":
                if user.messaged:
                    self.debug_msg.emit(
                        f"      ⏭ Conditional skip: {user.nick} already messaged",
                        "warn")
                    self._tracer.note({"type": "user_skip", "nick": user.nick})
                    return False
                continue
            if block.block_id == "SCROLL_PARSE":
                continue  # already handled in the collect phase
            if block.block_id == "REPEAT_LOOP":
                continue  # marker — the engine driver handles the cycle count
            self._ctx = {"step": idx, "total_steps": total,
                         "block_id": block.block_id,
                         "block_name": block.display_name,
                         "user": user.nick}
            self.step_started.emit(idx, block.block_id, user.nick)
            started = time.monotonic()
            self.debug_msg.emit(
                f"▶▶ Step {idx}/{total} [{block.icon}] {block.display_name} "
                f"— user: {user.nick}", "info")
            self._tracer.note({"type": "step_start", **self._ctx})
            try:
                result = await block.execute(user.nick, self._cdp, self)
            except Exception as exc:
                log.exception("Block error")
                self._tracer.note({"type": "step_end", "status": "exception",
                                   "error": str(exc), **self._ctx})
                self.debug_msg.emit(f"      ❌ {block.display_name} raised: {exc}", "error")
                self.step_complete.emit(block.display_name, user.nick)
                self._ctx = {}
                return False
            elapsed = time.monotonic() - started
            if result == ActionResult.OK:
                status = "ok"
                self.debug_msg.emit(f"      ✓ Step {idx} OK ({elapsed:.2f}s)", "success")
                self._tracer.note({"type": "step_end", "status": "ok",
                                   "duration_s": round(elapsed, 3), **self._ctx})
                self.step_complete.emit(block.display_name, user.nick)
            elif result == ActionResult.SKIP:
                self.debug_msg.emit(f"      ⏭ Step {idx} skipped", "warn")
                self._tracer.note({"type": "step_end", "status": "skip", **self._ctx})
                self.step_complete.emit(block.display_name, user.nick)
                self._ctx = {}
                return False
            else:
                self.debug_msg.emit(
                    f"      ✗ Step {idx} FAILED after {elapsed:.2f}s — stopping this user",
                    "error")
                self._tracer.note({"type": "step_end", "status": "fail",
                                   "duration_s": round(elapsed, 3), **self._ctx})
                self.step_complete.emit(block.display_name, user.nick)
                self._ctx = {}
                return False
            self._ctx = {}
        self.debug_msg.emit(f"      ✅ All steps done for {user.nick}", "success")
        return True
