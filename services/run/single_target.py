"""The single-target cycle: one saved nick instead of the whole queue.

Click User's "Use Person from Memory" makes a stack run once per cycle against
the nick Pick Person saved, not once per queued person. That path has its own
pre-flight verdicts (no Pick Person match, no nick in memory), its own
announcement, its own accounting and its own stop boundaries — all of which
are separate from the per-user loop in `cycle_body.py`.

The stop announcement itself is not repeated here: `_announce_stopped` lives
once, on `run_lifecycle.RunLifecycleMixin`, and every stop boundary in the run
ladder calls it (five copies of the same two lines collapsed into one named
helper — RULE 16 §16.4).

Import direction: the shared `UserRecord` at module level;
`actions.cancellation` inside methods, so `import services.run` stays light.
"""

from __future__ import annotations

from .requests import UserRecord


class SingleTargetMixin:
    """One cycle against the saved nick; mixed into ``RunCoordinator``."""

    def _announce_single_target(self, target: str) -> None:
        """Say once, before the work, that this cycle ignores the user list."""
        self.progress.extend_total(1)
        self.log_msg.emit(
            f"▶ Single-target run — working the person saved in memory: "
            f"“{target}” (the user list is ignored)")
        self.debug_msg.emit(
            "ℹ Click User 'Use Person from Memory' is on: this stack runs once "
            "per cycle against the saved nick, not once per queued person.",
            "info")
        self._tracer.note({"type": "run_mode", "mode": "single_target",
                           "nick": target})

    async def _work_single_target(self, target: str, has_skip: bool) -> str:
        """Run the saved nick once; "stop" when cancellation caught it."""
        from actions.cancellation import RunStopped
        try:
            return await self._execute_for_user(UserRecord(nick=target),
                                                has_skip)
        except RunStopped:
            # Narrow handler: CancelledError and unexpected errors propagate.
            return "stop"

    async def _account_single_target(self, target: str, status: str) -> str:
        """Account a finished cycle, and mark the person only on "ok"."""
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
            self._announce_stopped()
            return "stopped"
        target = self.selected_nick
        self._announce_single_target(target)
        status = await self._work_single_target(target, has_skip)
        if status == "stop":
            return self._stopped_single_target(target, announce=False)
        if is_stop_requested(self):
            # Stop observed before the automatic-mark boundary.
            return self._stopped_single_target(target, announce=True)
        return await self._account_single_target(target, status)

    def _single_target_guard(self, take_present: bool, take_matched: bool) -> str | None:
        """The pre-flight verdict of a single-target cycle (None ⇒ proceed)."""
        if take_present and not take_matched:
            self.log_msg.emit("⚠ Use Person from Memory: Pick Person found no one to work — nothing to click this cycle")
            self.debug_msg.emit("ℹ Single-target cycle ended — a Repeat Loop stops here, exactly like an empty queue", "warn")
            self._tracer.note({"type": "run_skip", "reason": "no_take_match"})
            return "empty"
        if not self.selected_nick:
            self.log_msg.emit("⚠ Use Person from Memory: no person is saved in memory this run — add a Pick Person block before the Click User block (or let an earlier Click User click someone first) so {{nick}} has a value")
            self.debug_msg.emit("⚠ Nothing to click: Click User 'Use Person from Memory' needs a nick saved by Pick Person or an earlier Click User this run", "warn")
            self._tracer.note({"type": "run_skip", "reason": "no_memory_nick"})
            return "empty"
        return None

    def _stopped_single_target(self, target: str, *, announce: bool) -> str:
        """Account the stopped single-target cycle (fail per the wire contract)."""
        # Already announced in _execute_for_user when the status came back as
        # "stop"; announce only the stop observed at the mark boundary.
        if announce:
            self._announce_stopped()
        self.progress.note_status("fail")
        self.user_complete.emit(target, False)
        return "stopped"
