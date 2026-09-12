"""Collect-phase machinery of the run engine (Scroll & Parse).

Owns the retry-wrapped pipeline call, the fail-open known-messaged set, the
RULE 6 persistence of *kept* people, the one-line outcome summary, and the
post-collect stop tail. Extracted from `error_recovery.py` in the round-3
CC tail work (design: docs/archive/2026-09-11-cc-tail/) so the mixin it
shared with the per-user step runner stays within the method cap.

Leaf mixin: stdlib + logging only; `actions.*` is imported function-locally
so `import services.run` stays light (the round-2 convention).
"""

from __future__ import annotations

import logging
from asyncio import CancelledError

log = logging.getLogger("chatbot")


class CollectPhaseMixin:
    """The Scroll & Parse phase of one cycle, decomposed."""

    async def _known_messaged_set(self) -> set:
        """Nicks already messaged; counting errors fail open (RULE 9)."""
        try:
            return {u.nick for u in await self._memory.get_all() if u.messaged}
        except Exception:
            return set()

    async def _call_pipeline(self, block, known):
        """Run the pipeline under the retry policy; None after _collect_failed."""
        from actions.cancellation import RunStopped
        try:
            return await self._retry.retry_with_backoff(
                lambda: block.run_pipeline(self._cdp, self,
                                           panel_criteria=self._criteria,
                                           known_messaged=known),
                fallback=lambda exc: self._collect_failed(block, exc),
                stop=self)
        except CancelledError:
            self._ctx = {}
            raise
        except RunStopped:
            self._ctx = {}
            self.debug_msg.emit("      ⏹ Collection stopped by user — not "
                                "queueing anyone from this run", "warn")
            # run_end/stopped is noted once at the cycle boundary.
            raise
        except Exception:
            self._ctx = {}
            return None

    async def _collect_failed(self, block, exc: Exception):
        log.exception("Collect phase failed")
        self.debug_msg.emit(f"      ❌ Scroll & Parse raised: {exc}", "error")
        self._tracer.note({"type": "phase_end", "phase": "collect",
                           "status": "exception", "error": str(exc)})
        raise exc

    async def _persist_collected(self, collected) -> None:
        """Upsert everyone the pipeline kept (RULE 6: rejects never persist)."""
        for person in collected:
            try:
                await self._memory.upsert_user(person)
            except Exception as exc:
                log.warning("upsert failed for %s: %s", person.nick, exc)

    def _collect_summary(self, result) -> str:
        """The one-line collect outcome for the log (seeking vs harvest)."""
        if result.seeking and result.found is not None:
            return (f"🎯 Scroll-only: found “{result.found.nick}” on the "
                    "page — no new people were added")
        if result.seeking:
            return ("🔎 Scroll-only: no un-messaged person from the list "
                    "is currently on the page")
        msg = (f"📜 Seen {len(result.all_people)} person(s), "
               f"{len(result.collected)} matched the filter")
        if result.purged:
            msg += f", {len(result.purged)} removed"
        return msg

    def _collect_tail(self, result):
        """Post-collect stop verdict: None ⇒ use the unmessaged collected."""
        from actions.cancellation import RunStopped, is_stop_requested
        if is_stop_requested(self):
            self.debug_msg.emit("      ⏹ Collection stopped by user — not "
                                "queueing anyone from this run", "warn")
            raise RunStopped
        if result.stopped:
            # Pipeline-reported stop without an engine flag (test fakes /
            # direct run_pipeline callers): legacy [] return, no raise, so the
            # pre-existing collect-phase contract stays green. Real engine
            # stops always set the flag (predicate is engine.is_stopping).
            self.debug_msg.emit("      ⏹ Collection stopped by user — not "
                                "queueing anyone from this run", "warn")
            return []
        return None

    async def _run_collect_phase(self, block):
        self.log_msg.emit("📜 Collecting people (Scroll & Parse)…")
        self._tracer.note({"type": "phase", "phase": "collect"})
        self._ctx = {"block_id": block.block_id, "block_name": block.display_name, "phase": "collect"}
        self.step_started.emit(1, block.block_id, "—")
        known = await self._known_messaged_set()
        result = await self._call_pipeline(block, known)
        if result is None:
            return []
        await self._persist_collected(result.collected)
        self.log_msg.emit(self._collect_summary(result))
        self._tracer.note({"type": "phase_end", "phase": "collect", "seen": len(result.all_people), "collected": len(result.collected), "scrolls": result.scrolls, "reached_end": result.reached_end, "stopped_early": result.stopped_early, "stopped": result.stopped, "seeking": result.seeking, "found": getattr(result.found, "nick", None), "purged": len(result.purged)})
        self.step_complete.emit(block.display_name, "—")
        self._ctx = {}
        early = self._collect_tail(result)
        if early is not None:
            return early
        return [person for person in result.collected if not person.messaged]
