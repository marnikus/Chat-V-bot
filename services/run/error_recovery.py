from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger("chatbot")


class RetryPolicy:
    def __init__(self, max_retries: int = 0, base_delay: float = 0.25):
        self.max_retries = max(0, int(max_retries))
        self.base_delay = max(0.0, float(base_delay))

    def should_retry(self, exc: Exception, attempt: int) -> bool:
        # Cooperative stop / external cancel never retry (even for permissive
        # subclasses: retry_with_backoff checks before calling this).
        # Local import: keeps "import services.run" light (actions/__init__
        # scans every block module); same for the other lazy imports below.
        from actions.cancellation import RunStopped
        if isinstance(exc, RunStopped):
            return False
        if isinstance(exc, asyncio.CancelledError):
            return False
        transient = (TimeoutError, ConnectionError, asyncio.TimeoutError)
        return attempt < self.max_retries and isinstance(exc, transient)

    async def retry_with_backoff(self, op, *, fallback=None, stop=None):
        """Run ``op`` with backoff; stop-aware (AREA C1).

        ``stop`` is None, an engine with ``is_stopping``/``_stop_requested``,
        or a bare ``() -> bool`` predicate. Cooperative stop raises
        ``RunStopped`` without retry/fallback; external cancel propagates.
        """
        from actions.cancellation import RunStopped, check_stopped, sleep_with_stop

        attempt = 0
        while True:
            check_stopped(stop)
            try:
                return await op()
            except asyncio.CancelledError:
                raise
            except RunStopped:
                # Cooperative stop: immediate propagate, never retried, no
                # fallback (pinned by test_permissive_retry_still_cannot_retry_stop).
                raise
            except Exception as exc:
                if not self.should_retry(exc, attempt):
                    return await fallback(exc) if fallback else (_raise(exc))
                check_stopped(stop)
                await sleep_with_stop(
                    self.base_delay * (2 ** attempt), stop, slice_s=0.02
                )
                attempt += 1

    async def fallback(self, exc: Exception):
        raise exc


def _raise(exc: Exception):
    raise exc


#: blocks that never run inside the per-user stack walk (engine-level phases)
_PER_USER_SKIP_IDS = {"SCROLL_PARSE", "REPEAT_LOOP", "TAKE_PERSON"}


class RunExecutionMixin:
    """Per-user stack execution: gates, block verdicts, one-block runner."""

    def _stack_stopped_status(self) -> str:
        """The per-user stop verdict, announced + traced on every boundary."""
        self.debug_msg.emit("⏹ Stack stopped by user", "warn")
        self._tracer.note({"type": "run_end", "reason": "stopped"})
        return "stop"

    def _all_disabled_guard(self) -> str | None:
        """The nothing-to-run verdict when every block is disabled."""
        if sum(1 for b in self._stack if getattr(b, "enabled", True)):
            return None
        # B5 regression guard: reporting "ok" here marks the queue
        # person as messaged although no block ever ran. "skip" tells
        # the coordinator the user was NOT completed.
        self.debug_msg.emit("⚠ All blocks are disabled — nothing to run",
                            "warn")
        self._tracer.note({"type": "run_skip", "reason": "all_disabled"})
        return "skip"

    async def _between_blocks_gate(self) -> bool:
        """The between-blocks stop/pause boundary → True when stopped."""
        from actions.cancellation import is_stop_requested
        if is_stop_requested(self):
            return True
        await self._wait_if_paused()
        return is_stop_requested(self)

    def _block_verdict(self, block, idx: int, user) -> str | None:
        """Whether the loop runs this block for this user.

        None ⇒ run it; "continue" ⇒ skip to the next block (announced and
        traced where pinned); "skip" ⇒ abandon the whole user (the
        CONDITIONAL_SKIP rule).
        """
        if not getattr(block, "enabled", True):
            self.debug_msg.emit(f"      ⏭ Skipped disabled block [{block.block_id}] {block.display_name}", "warn")
            self._tracer.note({"type": "step_skip", "reason": "disabled", "block_id": block.block_id, "block_name": block.display_name, "step": idx})
            return "continue"
        if block.block_id == "CONDITIONAL_SKIP":
            if user.messaged:
                self.debug_msg.emit(f"      ⏭ Conditional skip: {user.nick} already messaged", "warn")
                self._tracer.note({"type": "user_skip", "nick": user.nick})
                return "skip"
            return "continue"
        if block.block_id in _PER_USER_SKIP_IDS:
            return "continue"
        return None

    async def _step_status(self, block, user):
        """Run the step → (result, status); CancelledError alone propagates."""
        from actions.cancellation import RunStopped
        try:
            result = await self._retry.retry_with_backoff(
                lambda: block.execute(user.nick, self._cdp, self),
                fallback=lambda exc: self._step_failed(block, user.nick, exc),
                stop=self)
            return result, "ok"
        except asyncio.CancelledError:
            raise
        except RunStopped:
            self._tracer.note({"type": "step_end", "status": "stop", **self._ctx})
            self.debug_msg.emit(f"      ⏹ {block.display_name} stopped on request", "warn")
            self.step_complete.emit(block.display_name, user.nick)
            self._tracer.note({"type": "run_end", "reason": "stopped"})
            return None, "stop"
        except Exception:
            return None, "fail"

    async def _run_one_block(self, block, idx: int, total: int, user) -> str:
        """Execute one enabled block against one user → the step status."""
        self._ctx = {"step": idx, "total_steps": total, "block_id": block.block_id, "block_name": block.display_name, "user": user.nick}
        self.step_started.emit(idx, block.block_id, user.nick)
        started = time.monotonic()
        self.debug_msg.emit(f"▶▶ Step {idx}/{total} [{block.icon}] {block.display_name} — user: {user.nick}", "info")
        self._tracer.note({"type": "step_start", **self._ctx})
        originals = self._expand_nick_on_block(block, self.selected_nick or user.nick)
        try:
            result, status = await self._step_status(block, user)
            if status == "ok":
                status = self._handle_step_result(block, user.nick, idx,
                                                  started, result)
                await self._call_action_hook(block, user.nick, status)
            return status
        finally:
            self._restore_block_attrs(block, originals)
            self._ctx = {}

    async def _execute_for_user(self, user, has_skip: bool) -> str:
        if user.messaged and has_skip:
            self.log_msg.emit(f"⏭ Skipping (already messaged): {user.nick}")
            return "skip"
        guard = self._all_disabled_guard()
        if guard is not None:
            return guard
        total = len(self._stack)
        for idx, block in enumerate(self._stack, start=1):
            if await self._between_blocks_gate():
                return self._stack_stopped_status()
            verdict = self._block_verdict(block, idx, user)
            if verdict == "continue":
                continue
            if verdict == "skip":
                return "skip"
            status = await self._run_one_block(block, idx, total, user)
            if status != "ok":
                return status
        self.debug_msg.emit(f"      ✅ All steps done for {user.nick}", "success")
        return "ok"

    async def _step_failed(self, block, nick: str, exc: Exception):
        log.exception("Block error")
        self._tracer.note({"type": "step_end", "status": "exception", "error": str(exc), **self._ctx})
        self.debug_msg.emit(f"      ❌ {block.display_name} raised: {exc}", "error")
        self.step_complete.emit(block.display_name, nick)
        raise exc

    def _handle_step_result(self, block, nick: str, idx: int, started: float, result) -> str:
        from actions.base_action import ActionResult
        elapsed = time.monotonic() - started
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

    async def _call_action_hook(self, block, nick: str, status: str) -> None:
        hook = getattr(self._hooks, "on_action_complete", None)
        if hook is not None:
            result = hook(self, block, nick, status)
            if asyncio.iscoroutine(result):
                await result

    async def mark_person_messaged(self, nick: str) -> str:
        if not nick:
            return "missing"
        try:
            rows = await self._memory.get_all()
            record = next((r for r in rows if getattr(r, "nick", "") == nick), None)
            if record is None:
                return "missing"
            if getattr(record, "messaged", False):
                return "already"
            await self._memory.mark_messaged(nick)
            self.person_marked.emit(nick)
            return "ok"
        except Exception as exc:
            log.warning("mark_person_messaged(%s) failed: %s", nick, exc)
            return "error"
