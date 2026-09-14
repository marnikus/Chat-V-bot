"""The run coordinator: stack loading, run control and the cycle loop.

`RunCoordinator` (exported as `ActionEngine`) is the composition root of the
run ladder — it declares the signals, holds the collaborators `RunDeps`
carries, and runs `execute`. Everything a cycle *does* is contributed by the
mixins, one responsibility each:

    queue_select.LabelGateMixin / QueueOrderMixin / TakePhaseMixin
        who this cycle works, and in what order
    single_target.SingleTargetMixin   the one-saved-nick cycle
    collect_phase.CollectPhaseMixin   the Scroll & Parse phase
    error_recovery.RunExecutionMixin  one user against the whole stack
    step_report.StepReportMixin       how one step's outcome is announced
    cycle_body.CycleBodyMixin         one cycle: prepare the queue, work it
    cycle_loop.CycleLoopMixin         the repeat loop around the cycles
    run_lifecycle.RunLifecycleMixin   begin/teardown, trace notes, signals

Import direction: `actions.*` at module level (this file is the ladder's only
eager consumer of the block registry); `stores.user_memory` only for typing.
"""
from __future__ import annotations
import asyncio
import logging
from typing import TYPE_CHECKING
from PySide6.QtCore import QObject, Signal
from actions.base_action import BaseAction, get_action_class
from actions.cancellation import RunStopped
if TYPE_CHECKING:
    from backend.cdp_client import CDPClient
    from backend.criteria_engine import CriteriaEngine
    from backend.scroll_parser import ScrollParser
    from stores.user_memory import UserMemory
from .cycle_body import CycleBodyMixin
from .cycle_loop import CycleLoopMixin
from .collect_phase import CollectPhaseMixin
from .error_recovery import RetryPolicy, RunExecutionMixin
from .hooks import RunHooks, RunHooksMixin, maybe_await, normalize_blocks
from .progress import RunProgress
from .queue_select import LabelGateMixin, QueueOrderMixin, TakePhaseMixin
from .run_lifecycle import RunLifecycleMixin
from .requests import RunDeps
from .single_target import SingleTargetMixin
from .step_report import StepReportMixin
from .state_machine import RunStateMachine
log = logging.getLogger("chatbot")

class RunCoordinator(QObject, RunHooksMixin, LabelGateMixin, QueueOrderMixin,
                     TakePhaseMixin, SingleTargetMixin, CollectPhaseMixin,
                     RunExecutionMixin, StepReportMixin, CycleLoopMixin,
                     CycleBodyMixin, RunLifecycleMixin):
    step_complete = Signal(str, str); user_complete = Signal(str, bool); person_marked = Signal(str)
    stack_complete = Signal(); log_msg = Signal(str); debug_msg = Signal(str, str)
    step_started = Signal(int, str, str); person_found = Signal(str); person_removed = Signal(str)

    def __init__(self, deps: RunDeps, parent: QObject | None = None):
        super().__init__(parent)
        self._cdp, self._memory, self._criteria = deps.cdp, deps.memory, deps.criteria
        self.criteria = deps.criteria; self._stack: list[BaseAction] = []; self._running = self._paused = self._stop_requested = False
        self._tracer = None; self._ctx: dict = {}; self._run_seq = 0; self._state = RunStateMachine()
        self._hooks = deps.hooks or RunHooks(); self._retry = deps.retry_policy or RetryPolicy(); self.progress = deps.progress or RunProgress(deps.bus)
        self.composer_text = self.selected_nick = ""; self.history = None; self.label_filter = self.label_reason = None
        self.speed_multiplier = 1.0  #: global wait-speed rate, resolved per run (SPEED_MULTIPLIER)

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

ActionEngine = RunCoordinator
