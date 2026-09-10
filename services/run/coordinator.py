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
except Exception:  # pragma: no cover - defensive fallback for isolated import
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
from .hooks import STANDALONE_NICK, RunHooks, RunHooksMixin, RunTracer, maybe_await, normalize_blocks
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
        """Run the stack. Drives each run cycle itself via _execute_cycle
        (through _run_all_cycles/_execute_cycle_guarded helpers)."""
        if self._running:
            self.log_msg.emit("⚠ Already running")
            return
        self._running, self._stop_requested, self._paused = True, False, False
        self._state.mark_running(); self.progress.reset(); self.progress.emit(); self._run_seq += 1
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{self._run_seq}"; self._tracer = RunTracer(run_id); self.selected_nick = ""
        self.log_msg.emit(f"▶▶ Run #{run_id} started"); self.debug_msg.emit(f"📄 Trace file: {self._tracer.path}", "info")
        self._tracer.note({"type": "run_start", "blocks": [b.block_id for b in self._stack]})
        cycles = self._repeat_cycles()
        run_cancelled = None
        done, outcome = False, "worked"
        try:
            done, outcome = await self._run_all_cycles(cycles)
            if done:
                self._state.mark_done(); self._tracer.note({"type": "run_end", "reason": "completed"})
            else:
                # Not done ⟺ outcome == "stopped" (only _note_cycle_outcome
                # False-return and _pre_cycle_gate early-out).
                self._state.mark_done()
        except asyncio.CancelledError as exc:
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
            await self._finalize_run(outcome, run_cancelled)

    async def _run_all_cycles(self, cycles: int) -> tuple[bool, str]:
        await maybe_await(self._hooks.pre_run(self))
        if cycles > 1:
            self.log_msg.emit(f"🔁 Repeat Loop: the stack will run {cycles} cycles — Stop ends it at any time")
            self._tracer.note({"type": "repeat", "cycles": cycles})
        outcome = "worked"
        for cycle in range(1, cycles + 1):
            pre = await self._pre_cycle_gate(cycle, cycles)
            if pre is not None:
                return False, pre
            outcome = await self._execute_cycle_guarded()
            finished = self._note_cycle_outcome(outcome, cycle, cycles)
            if finished is not None:
                return finished, outcome
        return True, outcome  # pragma: no cover - loop always returns above

    async def _execute_cycle_guarded(self) -> str:
        from actions.cancellation import RunStopped
        try:
            return await self._execute_cycle()
        except asyncio.CancelledError:
            raise
        except RunStopped:
            return self._note_stopped()

    async def _pre_cycle_gate(self, cycle: int, cycles: int) -> str | None:
        if self._stop_requested:
            return self._note_stopped()
        await self._wait_if_paused()
        if self._stop_requested:
            return self._note_stopped()
        if cycles > 1:
            self.log_msg.emit(f"🔁 Cycle {cycle}/{cycles} — running…")
            self._tracer.note({"type": "cycle_start", "cycle": cycle, "total": cycles})
        return None

    def _note_cycle_outcome(self, outcome: str, cycle: int, cycles: int) -> bool | None:
        if outcome in {"stopped", "empty_stack"}:
            return outcome == "empty_stack"
        if outcome == "empty":
            if cycles > 1:
                self.log_msg.emit(f"🔁 No users found — Repeat Loop ends the run after cycle {cycle}")
            return True
        if cycle >= cycles:
            return True
        return None

    async def _finalize_run(self, outcome: str, run_cancelled) -> None:
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

    def _note_stopped(self) -> str:
        self.debug_msg.emit("⏹ Stack stopped by user", "warn")
        try:
            if self._tracer is not None:
                self._tracer.note({"type": "run_end", "reason": "stopped"})
        except Exception:
            pass
        return "stopped"

    async def _execute_cycle(self) -> str:
        """One cycle. Owns the Scroll & Parse collect phase via
        _run_collect_phase (through _prepare_cycle_queue helper)."""
        from actions.cancellation import RunStopped
        from .cycle_plan import choose_cycle_mode, inspect_stack
        try:
            queue, take_matched = await self._prepare_cycle_queue()
        except RunStopped:
            return self._note_stopped()
        facts = inspect_stack(self._stack)
        decision = choose_cycle_mode(facts, has_queue=bool(queue),
                                     take_matched=take_matched)
        if decision.mode == "single_target":
            try:
                return await self._run_single_target_cycle(
                    facts.has_conditional_skip, take_matched)
            except RunStopped:
                return self._note_stopped()
        if decision.mode == "empty" and decision.reason == "no_take_match":
            return self._note_no_take_match()
        if decision.mode == "queued":
            return await self._run_queued_users(
                queue, facts.has_conditional_skip)
        if decision.mode == "empty_stack":
            return self._note_empty_stack()
        if decision.mode == "empty":
            return self._note_empty_queue(facts.user_scoped_ids)
        return await self._run_standalone_user(facts.has_conditional_skip)

    async def _prepare_cycle_queue(self) -> tuple[list, bool]:
        from actions.cancellation import RunStopped, raise_if_stopped
        scroll = next((b for b in self._stack
                       if b.block_id == "SCROLL_PARSE"
                       and getattr(b, "enabled", True)), None)
        if scroll is not None:
            queue = await self._run_collect_phase(scroll)
        else:
            queue = await self._memory.get_queue()
        raise_if_stopped(self)
        queue = self.filter_by_labels(queue, announce=True)
        queue = await self._order_queue_by_column(queue)
        raise_if_stopped(self)
        take_matched = await self._run_take_phase()
        raise_if_stopped(self)
        return queue, take_matched

    def _note_no_take_match(self) -> str:
        self.log_msg.emit("⚠ Pick Person found no one this cycle — nothing left to work (a Repeat Loop ends here, like an empty queue)")
        self.debug_msg.emit("ℹ Memory-driven cycle ended: no person matched Pick Person", "warn")
        self._tracer.note({"type": "run_skip", "reason": "no_take_match"})
        return "empty"

    def _note_empty_stack(self) -> str:
        self.log_msg.emit("⚠ The stack is empty — add at least one block")
        self.debug_msg.emit("⚠ Nothing to run: the action stack is empty", "warn")
        return "empty_stack"

    def _note_empty_queue(self, needs_user) -> str:
        self.log_msg.emit("⚠ No users in queue — nothing to run")
        self.debug_msg.emit("⚠ The queue is empty and this stack contains user-dependent block(s): " + ", ".join(sorted(set(needs_user))) + ". Add a Scroll & Parse block (or reset the 'messaged' flags) so there are users to run on.", "warn")
        self._tracer.note({"type": "run_skip", "reason": "empty_queue", "needs_user": sorted(set(needs_user))})
        return "empty"

    async def _run_queued_users(self, queue: list, has_skip: bool) -> str:
        self.progress.extend_total(len(queue))
        self.log_msg.emit(f"▶ Running stack on {len(queue)} user(s)")
        return await self._run_user_list(queue, has_skip, standalone=False)

    async def _run_standalone_user(self, has_skip: bool) -> str:
        self.progress.extend_total(1)
        queue = [UserRecord(nick=STANDALONE_NICK)]
        self.log_msg.emit("▶ Running stack once (standalone — no user context needed)")
        self.debug_msg.emit("ℹ Standalone run: this stack contains no user-dependent blocks, so it executes once independently of the user queue.", "info")
        self._tracer.note({"type": "run_mode", "mode": "standalone"})
        return await self._run_user_list(queue, has_skip, standalone=True)

    async def _run_user_list(self, queue: list, has_skip: bool,
                             standalone: bool) -> str:
        from actions.cancellation import RunStopped
        for user in queue:
            if self._stop_requested:
                return self._note_stopped()
            await self._wait_if_paused()
            if self._stop_requested:
                return self._note_stopped()
            try:
                status = await self._execute_for_user(user, has_skip)
            except RunStopped:
                return self._note_stopped()
            terminal = await self._finish_single_user(user, status, standalone)
            if terminal is not None:
                return terminal
        return "worked"

    async def _finish_single_user(self, user, status: str,
                                  standalone: bool) -> str | None:
        self.progress.note_status("fail" if status == "stop" else status)
        if status == "ok" and self._stop_requested:
            if not standalone:
                self.user_complete.emit(user.nick, False)
            return self._note_stopped()
        if status == "ok" and not standalone:
            await self._memory.mark_messaged(user.nick)
            self.person_marked.emit(user.nick)
        if not standalone:
            self.user_complete.emit(user.nick, status == "ok")
        if status == "stop":
            try:
                self._tracer.note({"type": "run_end", "reason": "stopped"})
            except Exception:
                pass
            return "stopped"
        return None

ActionEngine = RunCoordinator
