"""The body of one run cycle: prepare the queue, then work it.

`RunCoordinator.execute` owns the repeat loop and the run's begin/teardown
(`cycle_loop.py`, `run_lifecycle.py`). This mixin owns what happens *inside*
one cycle, in the order the ladder already names it:

    _prepare_cycle_queue   collect → label filter → order → Pick Person
    _execute_cycle         inspect the stack, pick the mode, dispatch
    _prepare_user_queue    queued vs standalone announcement + accounting
    _run_user_queue        the per-user loop with its stop/pause gates
    _finalize_user_status  account, auto-mark, emit user_complete

Each phase raises or maps cooperative cancellation the way it always has:
phase `RunStopped` propagates to `_try_prepare_cycle_queue`, which turns it
into the cycle's ``"stopped"`` outcome, and `asyncio.CancelledError`
propagates untouched past every narrow handler here (RULE 7).

Import direction: `actions.cancellation` at module level — this file is only
ever imported by `coordinator.py`, which already loads that module.
"""

from __future__ import annotations

from actions.cancellation import RunStopped, check_stopped, is_stop_requested

from .cycle_plan import choose_cycle_mode, inspect_stack
from .hooks import STANDALONE_NICK
from .requests import UserRecord


class CycleBodyMixin:
    """One cycle's phases; mixed into ``RunCoordinator``."""

    async def _prepare_cycle_queue(self) -> tuple[list, bool]:
        """Collect → filter → order → take; raises RunStopped on stop.

        Inspection point A (scroll lookup) lives here, immediately before
        collection. Phase ``RunStopped`` propagates untouched and the three
        between-phase flag checks raise; the cycle boundary owns the single
        ``run_end/stopped`` note. ``CancelledError`` propagates untouched.
        """
        scroll = self._enabled_block("SCROLL_PARSE")
        queue = await self._run_collect_phase(scroll) if scroll is not None else await self._memory.get_queue()
        check_stopped(self)
        queue = self.filter_by_labels(queue, announce=True)
        check_stopped(self)
        queue = await self._order_queue_by_column(queue)
        take_matched = await self._run_take_phase()
        check_stopped(self)
        return queue, take_matched

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
