"""Repeat-loop iteration for the run coordinator (AREA C tail).

This mixin owns the per-cycle machinery that used to live inline in
``RunCoordinator.execute``: the between-cycle stop/pause gates, cycle
announcements, the single ``RunStopped`` → ``"stopped"`` mapping and the
outcome transitions (worked / stopped / empty / empty_stack). The run's
begin/teardown bookkeeping lives in ``run_lifecycle.RunLifecycleMixin``.

Lazy ``actions.cancellation`` imports match the rest of the run package so
that ``import services.run`` never triggers the actions package scan.
"""

from __future__ import annotations


class CycleLoopMixin:
    """Repeat-loop steps; mixed into ``RunCoordinator``."""

    async def _gate_before_cycle(self) -> bool:
        """Stop check, pause wait, stop check. True when the run must end.

        Verbatim from the old inline loop: on stop the debug line and the
        ``run_end/stopped`` trace note are emitted directly (this boundary
        note is intentionally NOT guarded, unlike the inner RunStopped one).
        """
        from actions.cancellation import is_stop_requested
        if is_stop_requested(self):
            self.debug_msg.emit("⏹ Stack stopped by user", "warn")
            self._tracer.note({"type": "run_end", "reason": "stopped"})
            return True
        await self._wait_if_paused()
        if is_stop_requested(self):
            self.debug_msg.emit("⏹ Stack stopped by user", "warn")
            self._tracer.note({"type": "run_end", "reason": "stopped"})
            return True
        return False

    def _announce_cycle_start(self, cycle: int, cycles: int) -> None:
        """Repeat-loop per-cycle banner + trace note (single runs silent)."""
        if cycles > 1:
            self.log_msg.emit(f"🔁 Cycle {cycle}/{cycles} — running…")
            self._tracer.note(
                {"type": "cycle_start", "cycle": cycle, "total": cycles})

    def _cycle_transition(self, outcome: str, cycle: int,
                          cycles: int) -> tuple[str, bool] | None:
        """Map one cycle's outcome to the loop result, or None to continue."""
        if outcome in ("stopped", "empty_stack"):
            return outcome, outcome == "empty_stack"
        if outcome == "empty":
            if cycles > 1:
                self.log_msg.emit(
                    "🔁 No users found — Repeat Loop ends the run "
                    f"after cycle {cycle}")
            return "empty", True
        if cycle >= cycles:
            return "worked", True
        return None

    def _mark_run_done(self, outcome: str, done: bool) -> None:
        """State + terminal trace note after the cycle loop."""
        from actions.cancellation import is_stop_requested
        if done:
            self._state.mark_done()
            self._tracer.note(
                {"type": "run_end", "reason": "completed"})
        elif outcome == "stopped" or is_stop_requested(self):
            self._state.mark_done()
