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
    stack_complete = Signal()
    log_msg = Signal(str)
    debug_msg = Signal(str, str)          # message, level (info|success|warn|error)
    step_started = Signal(int, str, str)  # step index (1-based), block_id, user_nick

    def __init__(self, cdp: CDPClient, memory: UserMemory,
                 criteria: CriteriaEngine, parent: QObject | None = None):
        super().__init__(parent)
        self._cdp = cdp
        self._memory = memory
        self._criteria = criteria
        self._stack: list[BaseAction] = []
        self._running = False
        self._paused = False
        self._stop_requested = False
        self._tracer: Optional[RunTracer] = None
        self._ctx: dict = {}       # current step context for report()
        self._run_seq = 0

    # ── stack management ─────────────────────────────────────────
    def load_stack(self, blocks: list[dict]) -> None:
        """Build action list from block config dicts."""
        self._stack.clear()
        for b in blocks or []:
            cls = get_action_class(b.get("block_id", ""))
            if cls:
                # Ensure enabled defaults to True for backward compat
                data = {k: v for k, v in b.items() if k != "block_id"}
                if "enabled" not in data:
                    data["enabled"] = True
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

    # ── main execution loop ──────────────────────────────────────
    async def execute(self, scroll_parser: ScrollParser | None = None) -> None:
        """Run the full stack over the user queue."""
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
        try:
            # Phase 1: parse users if SCROLL_PARSE block exists (only enabled)
            has_scroll = any(b.block_id == "SCROLL_PARSE" and getattr(b, "enabled", True)
                             for b in self._stack)
            if has_scroll and scroll_parser:
                all_u, filtered = await self._run_parse_phase(scroll_parser)
                for u in all_u:
                    await self._memory.upsert_user(u)
                self.log_msg.emit(
                    f"📜 Parsed {len(all_u)} users, {len(filtered)} passed criteria")
            # Phase 2: build queue (consider only enabled blocks)
            queue = await self._memory.get_queue()
            has_skip = any(b.block_id == "CONDITIONAL_SKIP" and getattr(b, "enabled", True)
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
                    break
                await self._wait_if_paused()
                if self._stop_requested:
                    self._tracer.note({"type": "run_end", "reason": "stopped"})
                    break
                ok = await self._execute_for_user(user, has_skip)
                if ok and not standalone:
                    await self._memory.mark_messaged(user.nick)
                if not standalone:
                    self.user_complete.emit(user.nick, ok)
            else:
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

    async def _wait_if_paused(self) -> None:
        while self._paused and not self._stop_requested:
            await asyncio.sleep(0.2)

    async def _run_parse_phase(self, sp: ScrollParser) -> tuple[list, list]:
        self.log_msg.emit("📜 Starting user parse (SCROLL_PARSE step)...")
        self._tracer.note({"type": "phase", "phase": "parse"})

        def progress(scroll_i: int, total: int, new_count: int) -> None:
            self._tracer.note({"type": "scroll", "scroll": scroll_i,
                               "total_users": total, "new": new_count,
                               "phase": "parse"})

        def parse_log(message: str, level: str = "info") -> None:
            self.debug_msg.emit("      " + message, norm_level(level))
            self._tracer.note({"type": "detail", "level": norm_level(level),
                               "message": message, "phase": "parse"})

        sp.set_log_cb(parse_log)
        all_u, filtered = await sp.parse(progress_cb=progress)
        return all_u, filtered

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
                continue  # already handled in parse phase
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
