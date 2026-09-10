from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from PySide6.QtCore import QObject, Signal
from core.events import EventBus
from actions.base_action import BaseAction, get_action_class
from actions.cancellation import RunStopped, check_stopped, is_stop_requested
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
from .cycle_loop import CycleLoopMixin
from .cycle_plan import choose_cycle_mode, inspect_stack
from .error_recovery import RetryPolicy, RunExecutionMixin
from .hooks import STANDALONE_NICK, RunHooks, RunHooksMixin, RunTracer, maybe_await, normalize_blocks
from .progress import RunProgress, RunQueueMixin
from .run_lifecycle import RunLifecycleMixin
from .state_machine import RunStateMachine
log = logging.getLogger("chatbot")

class RunCoordinator(QObject, RunHooksMixin, RunQueueMixin, RunExecutionMixin,
                     CycleLoopMixin, RunLifecycleMixin):
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
        if self._running:
            self.log_msg.emit("⚠ Already running"); return
        cycles = self._begin_run()
        outcome, done, run_error = "worked", False, None
        try:
            await maybe_await(self._hooks.pre_run(self))
            self._announce_repeat(cycles)
            for cycle in range(1, cycles + 1):
                if await self._gate_before_cycle():
                    outcome = "stopped"; break
                self._announce_cycle_start(cycle, cycles)
                try:
                    outcome = await self._execute_cycle()
                except asyncio.CancelledError:
                    raise
                except RunStopped:
                    self._announce_stopped(); outcome = "stopped"; break
                transition = self._cycle_transition(outcome, cycle, cycles)
                if transition is not None:
                    outcome, done = transition; break
            self._mark_run_done(outcome, done)
        except asyncio.CancelledError as exc:
            run_error = exc; self._note_run_cancelled(); raise
        except Exception as exc:
            run_error = exc; self._note_run_exception(exc)
        finally:
            post_error = await self._run_post_hook(outcome)
            self._finish_signals(); self._resolve_cleanup_failure(run_error, post_error)

    def _announce_stopped(self) -> None:
        """Emit the single stopped announcement (debug + trace)."""
        self.debug_msg.emit("⏹ Stack stopped by user", "warn")
        try:
            self._tracer.note({"type": "run_end", "reason": "stopped"})
        except Exception:
            pass

    async def _prepare_cycle_queue(self) -> tuple[list, bool]:
        """Collect → filter → order → take; raises RunStopped on stop.

        Inspection point A (scroll lookup) lives here, immediately before
        collection. Phase ``RunStopped`` propagates untouched and the three
        between-phase flag checks raise; the cycle boundary owns the single
        ``run_end/stopped`` note. ``CancelledError`` propagates untouched.
        """
        scroll = next((b for b in self._stack if b.block_id == "SCROLL_PARSE" and getattr(b, "enabled", True)), None)
        queue = await self._run_collect_phase(scroll) if scroll is not None else await self._memory.get_queue()
        check_stopped(self)
        queue = self.filter_by_labels(queue, announce=True)
        check_stopped(self)
        queue = await self._order_queue_by_column(queue)
        take_matched = await self._run_take_phase()
        check_stopped(self)
        return queue, take_matched

    def _announce_empty_mode(self, reason: str, needs_user: list[str]) -> str:
        """Emit the take-miss / empty-stack / empty-queue announcements."""
        if reason == "no_take_match":
            self.log_msg.emit("⚠ Pick Person found no one this cycle — nothing left to work (a Repeat Loop ends here, like an empty queue)")
            self.debug_msg.emit("ℹ Memory-driven cycle ended: no person matched Pick Person", "warn")
            self._tracer.note({"type": "run_skip", "reason": "no_take_match"}); return "empty"
        if reason == "no_stack":
            self.log_msg.emit("⚠ The stack is empty — add at least one block"); self.debug_msg.emit("⚠ Nothing to run: the action stack is empty", "warn")
            return "empty_stack"
        self.log_msg.emit("⚠ No users in queue — nothing to run")
        self.debug_msg.emit("⚠ The queue is empty and this stack contains user-dependent block(s): " + ", ".join(sorted(set(needs_user))) + ". Add a Scroll & Parse block (or reset the 'messaged' flags) so there are users to run on.", "warn")
        self._tracer.note({"type": "run_skip", "reason": "empty_queue", "needs_user": sorted(set(needs_user))}); return "empty"

    def _prepare_user_queue(self, queue: list, mode: str) -> tuple[list, bool]:
        """Announce queued/standalone and return (queue, standalone)."""
        if mode == "queued":
            self.progress.extend_total(len(queue)); self.log_msg.emit(f"▶ Running stack on {len(queue)} user(s)")
            return queue, False
        self.progress.extend_total(1)
        self.log_msg.emit("▶ Running stack once (standalone — no user context needed)")
        self.debug_msg.emit("ℹ Standalone run: this stack contains no user-dependent blocks, so it executes once independently of the user queue.", "info")
        self._tracer.note({"type": "run_mode", "mode": "standalone"})
        return [UserRecord(nick=STANDALONE_NICK)], True

    async def _execute_one_queued_user(self, user, has_skip: bool) -> str:
        """Run one user; maps cooperative ``RunStopped`` to ``"stop"``.

        ``CancelledError`` and unexpected errors propagate untouched past
        the narrow handler below.
        """
        try:
            return await self._execute_for_user(user, has_skip)
        except RunStopped:
            return "stop"

    async def _finalize_user_status(self, user, status: str, standalone: bool) -> str | None:
        """Account + mark + emit for one user; returns ``"stopped"`` to end."""
        if status == "stop":
            # Already announced in _execute_for_user; account + return.
            self.progress.note_status("fail")
            if not standalone: self.user_complete.emit(user.nick, False)
            return "stopped"
        if is_stop_requested(self):
            # Stop observed before the automatic-mark boundary.
            self.progress.note_status("fail")
            if not standalone: self.user_complete.emit(user.nick, False)
            self._announce_stopped(); return "stopped"
        self.progress.note_status(status)
        if status == "ok" and not standalone: await self._memory.mark_messaged(user.nick); self.person_marked.emit(user.nick)
        if not standalone: self.user_complete.emit(user.nick, status == "ok")
        return None

    async def _run_user_queue(self, queue: list, has_skip: bool, standalone: bool) -> str:
        """Run the per-user loop with stop/pause/mark gates."""
        for user in queue:
            if is_stop_requested(self):
                self._announce_stopped(); return "stopped"
            await self._wait_if_paused()
            if is_stop_requested(self):
                self._announce_stopped(); return "stopped"
            status = await self._execute_one_queued_user(user, has_skip)
            stopped = await self._finalize_user_status(user, status, standalone)
            if stopped is not None:
                return stopped
        return "worked"

    async def _try_prepare_cycle_queue(self) -> tuple[list, bool] | None:
        """Collect→filter→order→take; None when a cooperative stop won.

        ``CancelledError`` propagates untouched: the handler below is narrow
        (``RunStopped`` derives from ``Exception``), so no explicit re-raise
        is needed. Unexpected exceptions propagate.
        """
        try:
            return await self._prepare_cycle_queue()
        except RunStopped:
            return None

    async def _execute_cycle(self) -> str:
        """One cycle. Owns the Scroll & Parse collect phase via
        _run_collect_phase (through _try_prepare_cycle_queue, which
        delegates to _prepare_cycle_queue)."""
        prepared = await self._try_prepare_cycle_queue()
        if prepared is None:
            self._announce_stopped(); return "stopped"
        queue, take_matched = prepared
        # Inspection point B: single post-take scan, then the mode table.
        facts = inspect_stack(self._stack)
        decision = choose_cycle_mode(facts, has_queue=bool(queue), take_matched=take_matched, stopped=is_stop_requested(self))
        if decision.mode == "stopped":
            self._announce_stopped(); return "stopped"
        if decision.mode == "single_target":
            return await self._run_single_target_cycle(facts.has_conditional_skip, take_matched)
        if decision.mode in ("empty", "empty_stack"):
            return self._announce_empty_mode(decision.reason, list(facts.user_scoped_ids))
        queue, standalone = self._prepare_user_queue(queue, decision.mode)
        return await self._run_user_queue(queue, facts.has_conditional_skip, standalone)

ActionEngine = RunCoordinator
