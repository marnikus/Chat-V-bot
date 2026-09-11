from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger("chatbot")

#: Verdicts a step hands back instead of raising (see _execute_with_backoff).
_STOPPED = object()
_FAILED = object()


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


#: Blocks that only decide who to work on; they never run per user.
_COLLECT_ONLY_BLOCKS = frozenset({"SCROLL_PARSE", "REPEAT_LOOP", "TAKE_PERSON"})
#: The one wording for "collect ended early", used by both stop paths.
COLLECT_STOP_NOTE = "      ⏹ Collection stopped by user — not queueing anyone from this run"


def _collect_stats(result) -> dict:
    """What the phase trace records about a finished collect."""
    return {
        "seen": len(result.all_people), "collected": len(result.collected),
        "scrolls": result.scrolls, "reached_end": result.reached_end,
        "stopped_early": result.stopped_early, "stopped": result.stopped,
        "seeking": result.seeking, "found": getattr(result.found, "nick", None),
        "purged": len(result.purged),
    }


class CollectPhaseMixin:
    """The scroll-and-parse half of a run: one phase, its reports, its answer."""

    async def _run_collect_phase(self, block):
        """Collect this cycle's people, then report and filter them.

        The phase owns three answers only: the collected list, [] when the
        pipeline reported a stop of its own, and RunStopped when the engine did.
        """
        from actions.cancellation import RunStopped
        self.log_msg.emit("📜 Collecting people (Scroll & Parse)…")
        self._tracer.note({"type": "phase", "phase": "collect"})
        self._ctx = {"block_id": block.block_id, "block_name": block.display_name,
                     "phase": "collect"}
        self.step_started.emit(1, block.block_id, "—")
        try:
            result = await self._collect_with_retry(block)
        except asyncio.CancelledError:
            self._ctx = {}
            raise
        except RunStopped:
            self._ctx = {}
            self.debug_msg.emit(COLLECT_STOP_NOTE, "warn")
            # run_end/stopped is noted once at the cycle boundary.
            raise
        except Exception:
            self._ctx = {}
            return []
        return await self._finish_collect(block, result)

    async def _collect_with_retry(self, block):
        """The pipeline call under the retry policy; reporting is the caller's."""
        try:
            known = {u.nick for u in await self._memory.get_all() if u.messaged}
        except Exception:
            known = set()
        return await self._retry.retry_with_backoff(
            lambda: block.run_pipeline(self._cdp, self, panel_criteria=self._criteria,
                                       known_messaged=known),
            fallback=lambda exc: self._collect_failed(block, exc),
            stop=self)

    async def _finish_collect(self, block, result):
        """Remember, announce and hand back the people this collect found."""
        from actions.cancellation import RunStopped, is_stop_requested
        await self._remember_collected(result)
        self._announce_collect(result)
        self._tracer.note({"type": "phase_end", "phase": "collect",
                           **_collect_stats(result)})
        self.step_complete.emit(block.display_name, "—")
        self._ctx = {}
        if is_stop_requested(self):
            self.debug_msg.emit(COLLECT_STOP_NOTE, "warn")
            raise RunStopped
        if result.stopped:
            # Pipeline-reported stop without an engine flag (test fakes /
            # direct run_pipeline callers): legacy [] return, no raise, so the
            # pre-existing collect-phase contract stays green. Real engine
            # stops always set the flag (predicate is engine.is_stopping).
            self.debug_msg.emit(COLLECT_STOP_NOTE, "warn")
            return []
        return [person for person in result.collected if not person.messaged]

    async def _remember_collected(self, result) -> None:
        """One bad record must not cost the operator the rest of the page."""
        for person in result.collected:
            try:
                await self._memory.upsert_user(person)
            except Exception as exc:
                log.warning("upsert failed for %s: %s", person.nick, exc)

    def _announce_collect(self, result) -> None:
        """The single summary line an operator reads after a collect."""
        if result.seeking and result.found is not None:
            self.log_msg.emit(f"🎯 Scroll-only: found “{result.found.nick}” on the "
                              f"page — no new people were added")
        elif result.seeking:
            self.log_msg.emit("🔎 Scroll-only: no un-messaged person from the list "
                              "is currently on the page")
        else:
            msg = (f"📜 Seen {len(result.all_people)} person(s), "
                   f"{len(result.collected)} matched the filter")
            if result.purged:
                msg += f", {len(result.purged)} removed"
            self.log_msg.emit(msg)

    async def _collect_failed(self, block, exc: Exception):
        log.exception("Collect phase failed")
        self.debug_msg.emit(f"      ❌ Scroll & Parse raised: {exc}", "error")
        self._tracer.note({"type": "phase_end", "phase": "collect", "status": "exception", "error": str(exc)})
        raise exc

class StepExecutionMixin:
    """One queue person at a time, walked through the stack of blocks."""

    async def _execute_for_user(self, user, has_skip: bool) -> str:
        """Walk one person through the stack; return the coordinator's verdict.

        "ok" ran, "skip" was not for us, "stop" the operator asked us to stop,
        "fail" something broke. "skip" on an all-disabled stack is a B5 guard:
        "ok" there would mark a person messaged although no block ever ran.
        """
        if user.messaged and has_skip:
            self.log_msg.emit(f"⏭ Skipping (already messaged): {user.nick}")
            return "skip"
        if self._all_blocks_disabled():
            return "skip"
        total = len(self._stack)
        for idx, block in enumerate(self._stack, start=1):
            verdict = await self._run_stack_entry(block, idx, total, user)
            if verdict is not None:
                return verdict
        self.debug_msg.emit(f"      ✅ All steps done for {user.nick}", "success")
        return "ok"

    def _all_blocks_disabled(self) -> bool:
        """Report the useless stack once, so the reason lands in the trace."""
        if any(getattr(b, "enabled", True) for b in self._stack):
            return False
        self.debug_msg.emit("⚠ All blocks are disabled — nothing to run", "warn")
        self._tracer.note({"type": "run_skip", "reason": "all_disabled"})
        return True

    async def _run_stack_entry(self, block, idx: int, total: int, user) -> str | None:
        """One stack entry: its stop boundaries, its skips, or one real step.

        None means "continue with the next entry"; any other value ends this
        person's turn with that verdict.
        """
        stop = self._stop_verdict()
        if stop is not None:
            return stop
        await self._wait_if_paused()
        stop = self._stop_verdict()
        if stop is not None:
            return stop
        if not getattr(block, "enabled", True):
            self._note_disabled_block(block, idx)
            return None
        if block.block_id == "CONDITIONAL_SKIP":
            if not user.messaged:
                return None
            self.debug_msg.emit(f"      ⏭ Conditional skip: {user.nick} already "
                                f"messaged", "warn")
            self._tracer.note({"type": "user_skip", "nick": user.nick})
            return "skip"
        if block.block_id in _COLLECT_ONLY_BLOCKS:
            return None
        status = await self._run_one_step(block, idx, total, user)
        return None if status == "ok" else status

    def _stop_verdict(self) -> str | None:
        """Stop boundary inside the stack: note it, and say the run stopped."""
        from actions.cancellation import is_stop_requested
        if not is_stop_requested(self):
            return None
        self.debug_msg.emit("⏹ Stack stopped by user", "warn")
        self._tracer.note({"type": "run_end", "reason": "stopped"})
        return "stop"

    def _note_disabled_block(self, block, idx: int) -> None:
        """A disabled block is reported as skipped, never silently passed."""
        self.debug_msg.emit(f"      ⏭ Skipped disabled block [{block.block_id}] "
                            f"{block.display_name}", "warn")
        self._tracer.note({"type": "step_skip", "reason": "disabled",
                           "block_id": block.block_id, "block_name": block.display_name,
                           "step": idx})

    async def _run_one_step(self, block, idx: int, total: int, user) -> str:
        """Announce, run and report one block, always restoring what it changed."""
        self._ctx = {"step": idx, "total_steps": total, "block_id": block.block_id,
                     "block_name": block.display_name, "user": user.nick}
        self.step_started.emit(idx, block.block_id, user.nick)
        started = time.monotonic()
        self.debug_msg.emit(f"▶▶ Step {idx}/{total} [{block.icon}] "
                            f"{block.display_name} — user: {user.nick}", "info")
        self._tracer.note({"type": "step_start", **self._ctx})
        originals = self._expand_nick_on_block(block, self.selected_nick or user.nick)
        try:
            result = await self._execute_with_backoff(block, user.nick)
            if result is _STOPPED:
                return "stop"
            if result is _FAILED:
                return "fail"
            status = self._handle_step_result(block, user.nick, idx, started, result)
            await self._call_action_hook(block, user.nick, status)
            return status
        finally:
            self._restore_block_attrs(block, originals)
            self._ctx = {}

    async def _execute_with_backoff(self, block, nick: str):
        """One block under the retry policy; _STOPPED/_FAILED instead of raise."""
        from actions.cancellation import RunStopped
        try:
            return await self._retry.retry_with_backoff(
                lambda: block.execute(nick, self._cdp, self),
                fallback=lambda exc: self._step_failed(block, nick, exc),
                stop=self)
        except RunStopped:
            self._tracer.note({"type": "step_end", "status": "stop", **self._ctx})
            self.debug_msg.emit(f"      ⏹ {block.display_name} stopped on request",
                                "warn")
            self.step_complete.emit(block.display_name, nick)
            self._tracer.note({"type": "run_end", "reason": "stopped"})
            return _STOPPED
        except Exception:
            return _FAILED

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

class RunExecutionMixin(CollectPhaseMixin, StepExecutionMixin):
    """The engine's execution surface: collect the people, then one at a time.

    Two mixins, one name, because that is what `services.run.coordinator` mixes
    in: the halves are separate to read and to grow, the MRO is what it was.
    """
