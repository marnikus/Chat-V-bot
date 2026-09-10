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
        try:
            from actions.cancellation import RunStopped
        except ImportError:  # pragma: no cover - red phase
            RunStopped = None  # type: ignore
        if RunStopped is not None and isinstance(exc, RunStopped):
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
        try:
            from actions.cancellation import RunStopped, sleep_with_stop
        except ImportError:  # pragma: no cover - red phase
            RunStopped = None  # type: ignore
            sleep_with_stop = None  # type: ignore

        def _stopped() -> bool:
            if stop is None:
                return False
            try:
                from actions.cancellation import is_stop_requested
            except ImportError:
                fn = getattr(stop, "is_stopping", None)
                if callable(fn):
                    try:
                        return bool(fn())
                    except Exception:
                        return False
                return bool(getattr(stop, "_stop_requested", False))
            return bool(is_stop_requested(stop))

        attempt = 0
        while True:
            if _stopped():
                if RunStopped is not None:
                    raise RunStopped
            try:
                return await op()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if RunStopped is not None and isinstance(exc, RunStopped):
                    raise
                if not self.should_retry(exc, attempt):
                    return await fallback(exc) if fallback else (_raise(exc))
                if _stopped():
                    if RunStopped is not None:
                        raise RunStopped
                    raise exc
                if sleep_with_stop is not None:
                    await sleep_with_stop(
                        self.base_delay * (2 ** attempt), stop, slice_s=0.02
                    )
                else:  # pragma: no cover - red phase
                    await asyncio.sleep(self.base_delay * (2 ** attempt))
                attempt += 1

    async def fallback(self, exc: Exception):
        raise exc


def _raise(exc: Exception):
    raise exc


def _is_stop_requested(engine) -> bool:
    try:
        from actions.cancellation import is_stop_requested
    except ImportError:  # pragma: no cover - red phase
        fn = getattr(engine, "is_stopping", None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception:
                return False
        return bool(getattr(engine, "_stop_requested", False))
    return bool(is_stop_requested(engine))


class RunExecutionMixin:
    async def _run_collect_phase(self, block):
        self.log_msg.emit("📜 Collecting people (Scroll & Parse)…")
        self._tracer.note({"type": "phase", "phase": "collect"})
        self._ctx = {"block_id": block.block_id, "block_name": block.display_name, "phase": "collect"}
        self.step_started.emit(1, block.block_id, "—")
        try:
            known = {u.nick for u in await self._memory.get_all() if u.messaged}
        except Exception:
            known = set()
        try:
            from actions.cancellation import RunStopped
        except ImportError:  # pragma: no cover - red phase
            RunStopped = None  # type: ignore
        try:
            result = await self._retry.retry_with_backoff(
                lambda: block.run_pipeline(self._cdp, self, panel_criteria=self._criteria, known_messaged=known),
                fallback=lambda exc: self._collect_failed(block, exc),
                stop=self)
        except asyncio.CancelledError:
            self._ctx = {}
            raise
        except Exception as exc:
            if RunStopped is not None and isinstance(exc, RunStopped):
                self._ctx = {}
                self.debug_msg.emit("      ⏹ Collection stopped by user — not queueing anyone from this run", "warn")
                # run_end/stopped is noted once at the cycle boundary.
                raise
            self._ctx = {}
            return []
        for person in result.collected:
            try:
                await self._memory.upsert_user(person)
            except Exception as exc:
                log.warning("upsert failed for %s: %s", person.nick, exc)
        if result.seeking and result.found is not None:
            self.log_msg.emit(f"🎯 Scroll-only: found “{result.found.nick}” on the page — no new people were added")
        elif result.seeking:
            self.log_msg.emit("🔎 Scroll-only: no un-messaged person from the list is currently on the page")
        else:
            msg = f"📜 Seen {len(result.all_people)} person(s), {len(result.collected)} matched the filter"
            if result.purged:
                msg += f", {len(result.purged)} removed"
            self.log_msg.emit(msg)
        self._tracer.note({"type": "phase_end", "phase": "collect", "seen": len(result.all_people), "collected": len(result.collected), "scrolls": result.scrolls, "reached_end": result.reached_end, "stopped_early": result.stopped_early, "stopped": result.stopped, "seeking": result.seeking, "found": getattr(result.found, "nick", None), "purged": len(result.purged)})
        self.step_complete.emit(block.display_name, "—")
        self._ctx = {}
        if _is_stop_requested(self):
            self.debug_msg.emit("      ⏹ Collection stopped by user — not queueing anyone from this run", "warn")
            if RunStopped is not None:
                raise RunStopped
            return []
        if result.stopped:
            # Pipeline-reported stop without an engine flag (test fakes /
            # direct run_pipeline callers): legacy [] return, no raise, so the
            # pre-existing collect-phase contract stays green. Real engine
            # stops always set the flag (predicate is engine.is_stopping).
            self.debug_msg.emit("      ⏹ Collection stopped by user — not queueing anyone from this run", "warn")
            return []
        return [person for person in result.collected if not person.messaged]

    async def _collect_failed(self, block, exc: Exception):
        log.exception("Collect phase failed")
        self.debug_msg.emit(f"      ❌ Scroll & Parse raised: {exc}", "error")
        self._tracer.note({"type": "phase_end", "phase": "collect", "status": "exception", "error": str(exc)})
        raise exc

    async def _execute_for_user(self, user, has_skip: bool) -> str:
        try:
            from actions.cancellation import RunStopped
        except ImportError:  # pragma: no cover - red phase
            RunStopped = None  # type: ignore
        if user.messaged and has_skip:
            self.log_msg.emit(f"⏭ Skipping (already messaged): {user.nick}")
            return "skip"
        total = len(self._stack)
        if not sum(1 for b in self._stack if getattr(b, "enabled", True)):
            # B5 regression guard: reporting "ok" here marks the queue
            # person as messaged although no block ever ran. "skip" tells
            # the coordinator the user was NOT completed.
            self.debug_msg.emit("⚠ All blocks are disabled — nothing to run",
                                "warn")
            self._tracer.note({"type": "run_skip", "reason": "all_disabled"})
            return "skip"
        for idx, block in enumerate(self._stack, start=1):
            if _is_stop_requested(self):
                self.debug_msg.emit("⏹ Stack stopped by user", "warn")
                self._tracer.note({"type": "run_end", "reason": "stopped"})
                return "stop"
            await self._wait_if_paused()
            if _is_stop_requested(self):
                self.debug_msg.emit("⏹ Stack stopped by user", "warn")
                self._tracer.note({"type": "run_end", "reason": "stopped"})
                return "stop"
            if not getattr(block, "enabled", True):
                self.debug_msg.emit(f"      ⏭ Skipped disabled block [{block.block_id}] {block.display_name}", "warn")
                self._tracer.note({"type": "step_skip", "reason": "disabled", "block_id": block.block_id, "block_name": block.display_name, "step": idx})
                continue
            if block.block_id == "CONDITIONAL_SKIP":
                if user.messaged:
                    self.debug_msg.emit(f"      ⏭ Conditional skip: {user.nick} already messaged", "warn")
                    self._tracer.note({"type": "user_skip", "nick": user.nick})
                    return "skip"
                continue
            if block.block_id in {"SCROLL_PARSE", "REPEAT_LOOP", "TAKE_PERSON"}:
                continue
            self._ctx = {"step": idx, "total_steps": total, "block_id": block.block_id, "block_name": block.display_name, "user": user.nick}
            self.step_started.emit(idx, block.block_id, user.nick)
            started = time.monotonic()
            self.debug_msg.emit(f"▶▶ Step {idx}/{total} [{block.icon}] {block.display_name} — user: {user.nick}", "info")
            self._tracer.note({"type": "step_start", **self._ctx})
            originals = self._expand_nick_on_block(block, self.selected_nick or user.nick)
            try:
                try:
                    result = await self._retry.retry_with_backoff(
                        lambda: block.execute(user.nick, self._cdp, self),
                        fallback=lambda exc: self._step_failed(block, user.nick, exc),
                        stop=self)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if RunStopped is not None and isinstance(exc, RunStopped):
                        self._tracer.note({"type": "step_end", "status": "stop", **self._ctx})
                        self.debug_msg.emit(f"      ⏹ {block.display_name} stopped on request", "warn")
                        self.step_complete.emit(block.display_name, user.nick)
                        self._tracer.note({"type": "run_end", "reason": "stopped"})
                        return "stop"
                    return "fail"
                status = self._handle_step_result(block, user.nick, idx, started, result)
                await self._call_action_hook(block, user.nick, status)
                if status != "ok":
                    return status
            finally:
                self._restore_block_attrs(block, originals)
                self._ctx = {}
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
