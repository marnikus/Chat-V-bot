"""Single-target cycle — part of RunQueueMixin, extracted by responsibility.

H-C1: single-target execution (Use Person from Memory).
Methods: _wait_if_paused, _announce_stop, _announce_single_target,
_work_single_target, _account_single_target, _run_single_target_cycle,
_single_target_guard, _stopped_single_target.

Design: docs/archive/2026-09-14-round-h/AREA_C_SERVICES_STORES_DESIGN_2026-09-14.md H-C1
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

try:
    from stores.user_memory import UserRecord
except Exception:

    @dataclass
    class UserRecord:
        nick: str
        messaged: bool = False
        _fallback: str = "single_target"


class SingleTargetMixin:
    """Single-target (Use Person from Memory) — one run per cycle against saved nick."""

    async def _wait_if_paused(self) -> None:
        while self._paused and not self._stop_requested:
            await asyncio.sleep(0.2)

    def _announce_stop(self) -> None:
        """The one stop line and its trace entry, which two call sites shared."""
        self.debug_msg.emit("⏹ Stack stopped by user", "warn")
        self._tracer.note({"type": "run_end", "reason": "stopped"})

    def _announce_single_target(self, target: str) -> None:
        """Say once, before the work, that this cycle ignores the user list."""
        self.progress.extend_total(1)
        self.log_msg.emit(
            f"▶ Single-target run — working the person saved in memory: "
            f"“{target}” (the user list is ignored)"
        )
        self.debug_msg.emit(
            "ℹ Click User 'Use Person from Memory' is on: this stack runs once "
            "per cycle against the saved nick, not once per queued person.",
            "info",
        )
        self._tracer.note({"type": "run_mode", "mode": "single_target", "nick": target})

    async def _work_single_target(self, target: str, has_skip: bool) -> str:
        """Run the saved nick once; 'stop' when cancellation caught it."""
        from actions.cancellation import RunStopped

        try:
            return await self._execute_for_user(UserRecord(nick=target), has_skip)
        except RunStopped:
            return "stop"

    async def _account_single_target(self, target: str, status: str) -> str:
        """Account a finished cycle, and mark the person only on 'ok'."""
        self.progress.note_status(status)
        if status == "ok":
            await self._memory.mark_messaged(target)
            self.person_marked.emit(target)
        self.user_complete.emit(target, status == "ok")
        return "worked"

    async def _run_single_target_cycle(self, has_skip: bool, take_matched: bool) -> str:
        from actions.cancellation import is_stop_requested

        take_present = self._enabled_block("TAKE_PERSON") is not None
        verdict = self._single_target_guard(take_present, take_matched)
        if verdict is not None:
            return verdict
        if is_stop_requested(self):
            self._announce_stop()
            return "stopped"
        target = self.selected_nick
        self._announce_single_target(target)
        status = await self._work_single_target(target, has_skip)
        if status == "stop":
            return self._stopped_single_target(target, announce=False)
        if is_stop_requested(self):
            return self._stopped_single_target(target, announce=True)
        return await self._account_single_target(target, status)

    def _single_target_guard(self, take_present: bool, take_matched: bool) -> str | None:
        """The pre-flight verdict of a single-target cycle (None ⇒ proceed)."""
        if take_present and not take_matched:
            self.log_msg.emit(
                "⚠ Use Person from Memory: Pick Person found no one to work — nothing to click this cycle"
            )
            self.debug_msg.emit(
                "ℹ Single-target cycle ended — a Repeat Loop stops here, exactly like an empty queue",
                "warn",
            )
            self._tracer.note({"type": "run_skip", "reason": "no_take_match"})
            return "empty"
        if not self.selected_nick:
            self.log_msg.emit(
                "⚠ Use Person from Memory: no person is saved in memory this run — add a Pick Person block "
                "before the Click User block (or let an earlier Click User click someone first) so {{nick}} has a value"
            )
            self.debug_msg.emit(
                "⚠ Nothing to click: Click User 'Use Person from Memory' needs a nick saved by Pick Person "
                "or an earlier Click User this run",
                "warn",
            )
            self._tracer.note({"type": "run_skip", "reason": "no_memory_nick"})
            return "empty"
        return None

    def _stopped_single_target(self, target: str, *, announce: bool) -> str:
        """Account the stopped single-target cycle (fail per wire contract)."""
        if announce:
            self._announce_stop()
        self.progress.note_status("fail")
        self.user_complete.emit(target, False)
        return "stopped"
