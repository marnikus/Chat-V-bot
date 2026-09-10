"""One run's begin/teardown bookkeeping for the run coordinator.

Split out of the former 103-line ``RunCoordinator.execute`` (CC 36). This
mixin owns run context setup, repeat-loop banner, cancel/error trace notes,
the post-run hook call, the terminal signals and the precedence rules
between a run error and a post-run cleanup error. The per-cycle loop lives
in ``cycle_loop.CycleLoopMixin``.

The cleanup precedence (pinned by tests/integration/run_safety) is:

* external cancel during the run + post-run failure → warn, original cancel
  propagates;
* post-run cancelled → mark error, raise the post-run cancellation;
* successful run + post-run failure → mark error, raise post-run failure;
* contained run error + post-run failure → log, body error stays reported.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from .hooks import RunTracer, maybe_await

log = logging.getLogger("chatbot")


class RunLifecycleMixin:
    """Begin/teardown steps; mixed into ``RunCoordinator``."""

    def _begin_run(self) -> int:
        """Guard-passed run setup; returns the configured cycle count."""
        self._running, self._stop_requested, self._paused = True, False, False
        self._state.mark_running()
        self.progress.reset()
        self.progress.emit()
        self._run_seq += 1
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") \
            + f"_{self._run_seq}"
        self._tracer = RunTracer(run_id)
        self.selected_nick = ""
        self.log_msg.emit(f"▶▶ Run #{run_id} started")
        self.debug_msg.emit(
            f"📄 Trace file: {self._tracer.path}", "info")
        self._tracer.note({
            "type": "run_start",
            "blocks": [b.block_id for b in self._stack],
        })
        return self._repeat_cycles()

    def _announce_repeat(self, cycles: int) -> None:
        if cycles > 1:
            self.log_msg.emit(
                f"🔁 Repeat Loop: the stack will run {cycles} cycles — "
                "Stop ends it at any time")
            self._tracer.note({"type": "repeat", "cycles": cycles})

    def _mark_error_quiet(self) -> None:
        """mark_error that tolerates an illegal current state transition."""
        try:
            self._state.mark_error()
        except ValueError:
            pass

    def _note_run_cancelled(self) -> None:
        self._mark_error_quiet()
        self.debug_msg.emit("⏹ Run cancelled — cleaning up…", "warn")
        try:
            self._tracer.note(
                {"type": "run_end", "reason": "cancelled"})
        except Exception:  # noqa: BLE001
            pass

    def _note_run_exception(self, exc: Exception) -> None:
        self._state.mark_error()
        log.error("Stack execution error: %s", exc, exc_info=True)
        self.log_msg.emit(f"❌ Error: {exc}")
        self.debug_msg.emit(f"❌ Fatal error: {exc}", "error")
        self._tracer.note({
            "type": "run_end", "reason": "exception",
            "error": str(exc),
        })

    def _note_hook_error(self, exc: BaseException) -> None:
        try:
            self._tracer.note({
                "type": "hook_error", "hook": "post_run",
                "error": str(exc),
            })
        except Exception:  # noqa: BLE001
            pass

    async def _run_post_hook(self, outcome: str):
        """Run post_run exactly once; return its failure (or None)."""
        try:
            await maybe_await(self._hooks.post_run(self, outcome))
            return None
        except asyncio.CancelledError as exc:
            self.debug_msg.emit(
                f"⚠ post_run cancelled: {exc}", "warn")
            self._note_hook_error(exc)
            return exc
        except Exception as exc:  # noqa: BLE001
            self.debug_msg.emit(f"⚠ post_run failed: {exc}", "warn")
            self._note_hook_error(exc)
            return exc

    def _finish_signals(self) -> None:
        """Close the tracer, reset run state, emit completion exactly once."""
        try:
            if self._tracer is not None:
                self._tracer.close()
                self._tracer = None
        finally:
            self._running = False
            self._ctx = {}
            try:
                self.stack_complete.emit()
            finally:
                self.log_msg.emit("✅ Stack execution complete")

    def _resolve_cleanup_failure(self, run_error, post_error) -> None:
        """Apply the cleanup precedence rules (may re-raise post_error)."""
        if isinstance(run_error, asyncio.CancelledError):
            if post_error is not None:
                log.warning(
                    "post_run failed during cancelled-run cleanup: %r",
                    post_error)
            return
        if isinstance(post_error, asyncio.CancelledError):
            self._mark_error_quiet()
            raise post_error
        if run_error is None and post_error is not None:
            self._mark_error_quiet()
            raise post_error
        if run_error is not None and post_error is not None:
            log.warning(
                "post_run failed during error cleanup %r: %r",
                run_error, post_error)
