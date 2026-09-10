from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from PySide6.QtCore import QObject, Signal
from core.events import EventBus
from actions.base_action import BaseAction, get_action_class
try:
    from stores.user_memory import UserRecord
except Exception:
    @dataclass
    class UserRecord:
        nick: str
        messaged: bool = False
if TYPE_CHECKING:
    from backend.cdp_client import CDPClient
    from backend.criteria_engine import CriteriaEngine
    from backend.scroll_parser import ScrollParser
    from stores.user_memory import UserMemory
from .error_recovery import RetryPolicy, RunExecutionMixin
from .hooks import STANDALONE_NICK, USER_SCOPED_BLOCKS, RunHooks, RunHooksMixin, RunTracer, maybe_await, normalize_blocks
from .progress import RunProgress, RunQueueMixin
from .state_machine import RunStateMachine
log = logging.getLogger("chatbot")

class RunCoordinator(QObject, RunHooksMixin, RunQueueMixin, RunExecutionMixin):
    step_complete = Signal(str, str); user_complete = Signal(str, bool); person_marked = Signal(str)
    stack_complete = Signal(); log_msg = Signal(str); debug_msg = Signal(str, str)
    step_started = Signal(int, str, str); person_found = Signal(str); person_removed = Signal(str)

    def __init__(self, cdp: 'CDPClient', memory: 'UserMemory', criteria: 'CriteriaEngine', bus: EventBus | None = None, hooks: RunHooks | None = None, retry_policy: RetryPolicy | None = None, progress: RunProgress | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._cdp, self._memory, self._criteria = cdp, memory, criteria
        self.criteria = criteria; self._stack: list[BaseAction] = []; self._running = self._paused = self._stop_requested = False
        self._tracer = None; self._ctx: dict = {}; self._run_seq = 0; self._state = RunStateMachine()
        self._hooks = hooks or RunHooks(); self._retry = retry_policy or RetryPolicy(); self.progress = progress or RunProgress(bus)
        self.composer_text = self.selected_nick = ""; self.history = None; self.label_filter = self.label_reason = None

    def load_stack(self, blocks: list[dict]) -> None:
        self._stack.clear()
        for block in normalize_blocks(blocks):
            cls = get_action_class(block.get("block_id", ""))
            if cls: self._stack.append(cls(**{k: v for k, v in block.items() if k != "block_id"}))
        log.info("Stack loaded: %d blocks (%d enabled)", len(self._stack), sum(1 for b in self._stack if getattr(b, "enabled", True)))

    def get_stack(self) -> list[dict]: return [block.to_dict() for block in self._stack]
    @property
    def is_running(self) -> bool: return self._running
    def stop(self) -> None: self._stop_requested = True; self._state.mark_stopping()
    def pause(self) -> None: self._paused = True; self._state.mark_paused()
    def resume(self) -> None: self._paused = False; self._state.mark_resumed()

    async def execute(self, scroll_parser: 'ScrollParser' | None = None) -> None:
        if self._running: self.log_msg.emit("⚠ Already running"); return
        self._running, self._stop_requested, self._paused = True, False, False
        self._state.mark_running(); self.progress.reset(); self.progress.emit(); self._run_seq += 1
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{self._run_seq}"; self._tracer = RunTracer(run_id); self.selected_nick = ""
        self.log_msg.emit(f"▶▶ Run #{run_id} started"); self.debug_msg.emit(f"📄 Trace file: {self._tracer.path}", "info")
        self._tracer.note({"type": "run_start", "blocks": [b.block_id for b in self._stack]})
        cycles = self._repeat_cycles()
        run_cancelled = None
        done, outcome = False, "worked"
        try:
            await maybe_await(self._hooks.pre_run(self))
            if cycles > 1:
                self.log_msg.emit(f"🔁 Repeat Loop: the stack will run {cycles} cycles — Stop ends it at any time")
                self._tracer.note({"type": "repeat", "cycles": cycles})
            for cycle in range(1, cycles + 1):
                if self._stop_requested:
                    self.debug_msg.emit("⏹ Stack stopped by user", "warn"); self._tracer.note({"type": "run_end", "reason": "stopped"}); outcome = "stopped"; break
                await self._wait_if_paused()
                if self._stop_requested:
                    # C1: stop may have landed while parked at the pause
                    # barrier — never start another cycle after it.
                    self.debug_msg.emit("⏹ Stack stopped by user", "warn"); self._tracer.note({"type": "run_end", "reason": "stopped"}); outcome = "stopped"; break
                if cycles > 1:
                    self.log_msg.emit(f"🔁 Cycle {cycle}/{cycles} — running…")
                    self._tracer.note({"type": "cycle_start", "cycle": cycle, "total": cycles})
                outcome = await self._execute_cycle()
                if outcome in {"stopped", "empty_stack"}: done = outcome == "empty_stack"; break
                if outcome == "empty":
                    if cycles > 1: self.log_msg.emit(f"🔁 No users found — Repeat Loop ends the run after cycle {cycle}")
                    done = True; break
                if cycle >= cycles: done = True
            if done:
                self._state.mark_done(); self._tracer.note({"type": "run_end", "reason": "completed"})
            else:
                # C1: a stopped run is terminal too, so a later run restarts
                # from a clean state instead of a stranded RUNNING.
                self._state.mark_done()
        except asyncio.CancelledError as exc:
            # C1: external cancellation notes the run end, then propagates
            # after the finally below has run its cleanup exactly once.
            run_cancelled = exc
            try:
                if self._tracer is not None:
                    self._tracer.note({"type": "run_end", "reason": "cancelled"})
            except Exception:
                pass
            raise
        except Exception as exc:
            self._state.mark_error(); log.error("Stack execution error: %s", exc, exc_info=True)
            self.log_msg.emit(f"❌ Error: {exc}"); self.debug_msg.emit(f"❌ Fatal error: {exc}", "error")
            self._tracer.note({"type": "run_end", "reason": "exception", "error": str(exc)})
        finally:
            # C1: cleanup runs exactly once; the original run
            # cancellation/error keeps precedence over post_run failures.
            post_cancelled = None
            try:
                await maybe_await(self._hooks.post_run(self, outcome))
            except asyncio.CancelledError as exc:
                post_cancelled = exc
            except Exception as exc:
                log.error("post_run hook failed: %s", exc, exc_info=True)
                try:
                    self.debug_msg.emit(f"❌ post_run hook failed: {exc}", "error")
                    if self._tracer is not None:
                        self._tracer.note({"type": "run_hook_error", "hook": "post_run", "error": str(exc)})
                except Exception:
                    pass
            try:
                if run_cancelled is not None:
                    try:
                        self._state.reset()
                    except Exception:
                        pass
                if self._tracer is not None: self._tracer.close(); self._tracer = None
                self._running = False; self._ctx = {}; self.stack_complete.emit(); self.log_msg.emit("✅ Stack execution complete")
            finally:
                if run_cancelled is not None:
                    raise run_cancelled
                if post_cancelled is not None:
                    raise post_cancelled

    async def _execute_cycle(self) -> str:
        from actions.cancellation import RunStopped
        scroll = next((b for b in self._stack if b.block_id == "SCROLL_PARSE" and getattr(b, "enabled", True)), None)
        try:
            queue = await self._run_collect_phase(scroll) if scroll is not None else await self._memory.get_queue()
            queue = self.filter_by_labels(queue, announce=True); queue = await self._order_queue_by_column(queue)
            take_matched = await self._run_take_phase()
        except RunStopped:
            # C1: stop during collect/take/queue preparation ends the cycle
            # as stopped — never an empty-success or a fatal error.
            self.debug_msg.emit("⏹ Stack stopped by user", "warn"); self._tracer.note({"type": "run_end", "reason": "stopped"}); return "stopped"
        has_skip = any(b.block_id == "CONDITIONAL_SKIP" and getattr(b, "enabled", True) for b in self._stack)
        mem_click = next((b for b in self._stack if b.block_id == "CLICK_USER" and getattr(b, "enabled", True) and getattr(b, "use_person_from_memory", False)), None)
        needs_user = [b.block_id for b in self._stack if b.block_id in USER_SCOPED_BLOCKS and getattr(b, "enabled", True)]
        take_present = any(b.block_id == "TAKE_PERSON" and getattr(b, "enabled", True) for b in self._stack)
        if mem_click is not None: return await self._run_single_target_cycle(has_skip, take_matched)
        if take_present and not take_matched and not needs_user and not queue:
            self.log_msg.emit("⚠ Pick Person found no one this cycle — nothing left to work (a Repeat Loop ends here, like an empty queue)")
            self.debug_msg.emit("ℹ Memory-driven cycle ended: no person matched Pick Person", "warn")
            self._tracer.note({"type": "run_skip", "reason": "no_take_match"}); return "empty"
        standalone = False
        if queue:
            self.progress.extend_total(len(queue)); self.log_msg.emit(f"▶ Running stack on {len(queue)} user(s)")
        elif not self._stack:
            self.log_msg.emit("⚠ The stack is empty — add at least one block"); self.debug_msg.emit("⚠ Nothing to run: the action stack is empty", "warn")
            return "empty_stack"
        elif needs_user:
            self.log_msg.emit("⚠ No users in queue — nothing to run")
            self.debug_msg.emit("⚠ The queue is empty and this stack contains user-dependent block(s): " + ", ".join(sorted(set(needs_user))) + ". Add a Scroll & Parse block (or reset the 'messaged' flags) so there are users to run on.", "warn")
            self._tracer.note({"type": "run_skip", "reason": "empty_queue", "needs_user": sorted(set(needs_user))}); return "empty"
        else:
            standalone = True; self.progress.extend_total(1); queue = [UserRecord(nick=STANDALONE_NICK)]
            self.log_msg.emit("▶ Running stack once (standalone — no user context needed)")
            self.debug_msg.emit("ℹ Standalone run: this stack contains no user-dependent blocks, so it executes once independently of the user queue.", "info")
            self._tracer.note({"type": "run_mode", "mode": "standalone"})
        for user in queue:
            if self._stop_requested:
                self.debug_msg.emit("⏹ Stack stopped by user", "warn"); self._tracer.note({"type": "run_end", "reason": "stopped"}); return "stopped"
            await self._wait_if_paused()
            if self._stop_requested:
                # C1: stop may have landed while parked at the pause
                # barrier — never start another block after it.
                self.debug_msg.emit("⏹ Stack stopped by user", "warn"); self._tracer.note({"type": "run_end", "reason": "stopped"}); return "stopped"
            status = await self._execute_for_user(user, has_skip)
            self.progress.note_status("fail" if status == "stop" else status)
            if status == "stop":
                self._tracer.note({"type": "run_end", "reason": "stopped"})
                if not standalone: self.user_complete.emit(user.nick, False)
                return "stopped"
            if status == "ok" and self._stop_requested and not standalone:
                # C1: stop between the final OK and the automatic mark
                # boundary wins — the user is left unmarked for a later run.
                self.debug_msg.emit("⏹ Stack stopped by user", "warn"); self._tracer.note({"type": "run_end", "reason": "stopped"})
                self.user_complete.emit(user.nick, False); return "stopped"
            if status == "ok" and not standalone: await self._memory.mark_messaged(user.nick); self.person_marked.emit(user.nick)
            if not standalone: self.user_complete.emit(user.nick, status == "ok")
        return "worked"

ActionEngine = RunCoordinator
