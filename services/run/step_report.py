"""How one step's outcome is announced.

Every step ends one of four ways — ok, skip, fail, or an exception — and all
four report the same three things: a debug line, a `step_end` trace note and
the `step_complete` signal. `RunExecutionMixin` attempts the step; this mixin
reports it, which is a separate policy (RULE 2 — every step reports through
`engine.report`, and here through the two signals that reach the UI console
and the JSONL trace).

Kept out of `error_recovery.py` so that file stays inside the RULE 18 file
band and neither class crosses the RULE 16 class-LOC cap.

Import direction: `actions.base_action` inside the method, matching the rest
of the run package (a module-level import would make `import services.run`
load the whole block registry).
"""

from __future__ import annotations

import asyncio
import logging
import time

from .requests import StepContext

log = logging.getLogger("chatbot")


class StepReportMixin:
    """The step_end report for one block run; mixed into ``RunCoordinator``."""

    def _handle_step_result(self, block, result, step: StepContext) -> str:
        """Map an ``ActionResult`` to ok/skip/fail and report it."""
        from actions.base_action import ActionResult
        nick, idx = step.nick, step.idx
        elapsed = time.monotonic() - step.started
        if result == ActionResult.OK:
            self.debug_msg.emit(f"      ✓ Step {idx} OK ({elapsed:.2f}s)", "success")
            self._tracer.note({"type": "step_end", "status": "ok", "duration_s": round(elapsed, 3), **self._ctx})
            self.step_complete.emit(block.display_name, nick)
            return "ok"
        if result == ActionResult.SKIP:
            self.debug_msg.emit(f"      ⏭ Step {idx} skipped", "warn")
            self._tracer.note({"type": "step_end", "status": "skip", **self._ctx})
            self.step_complete.emit(block.display_name, nick)
            return "skip"
        self.debug_msg.emit(f"      ✗ Step {idx} FAILED after {elapsed:.2f}s — stopping this user", "error")
        self._tracer.note({"type": "step_end", "status": "fail", "duration_s": round(elapsed, 3), **self._ctx})
        self.step_complete.emit(block.display_name, nick)
        return "fail"

    async def _step_failed(self, block, nick: str, exc: Exception):
        """Report a raising block, then re-raise for the retry policy."""
        log.exception("Block error")
        self._tracer.note({"type": "step_end", "status": "exception", "error": str(exc), **self._ctx})
        self.debug_msg.emit(f"      ❌ {block.display_name} raised: {exc}", "error")
        self.step_complete.emit(block.display_name, nick)
        raise exc

    async def _call_action_hook(self, block, nick: str, status: str) -> None:
        """Run ``on_action_complete`` if the hooks provide it, sync or async."""
        hook = getattr(self._hooks, "on_action_complete", None)
        if hook is not None:
            result = hook(self, block, nick, status)
            if asyncio.iscoroutine(result):
                await result
