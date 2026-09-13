"""The Scroll & Parse phase of a run cycle (AREA C, split 2026-09-11).

Extracted from `services/run/error_recovery.py` so `RunExecutionMixin` stays
inside the RULE 16 method cap and this file stays inside the RULE 18 file
band: collecting people is its own responsibility — run the pipeline under
the retry policy, persist who survived the filter, summarise the outcome in
one line, and answer the stop question at the phase boundary.

The mixin is internal (every method is private) and reaches the engine the
same way `RunExecutionMixin` does: through `RunCoordinator`'s bases, so
`engine._run_collect_phase(...)` keeps resolving by MRO.
"""

from __future__ import annotations

import asyncio
import logging

#: The pinned "collection stopped" notice. It appears at three boundaries —
#: the retry policy raising RunStopped, the engine flag set after the phase,
#: and a pipeline-reported stop with no engine flag — and must read the same
#: at all three, so it is stated once.
_COLLECTION_STOPPED = ("      ⏹ Collection stopped by user — not queueing "
                       "anyone from this run")

# Stated before the logger on purpose: `from __future__ … / import asyncio /
# import logging / log = logging.getLogger("chatbot")` is the verbatim header
# of app/lifecycle.py and services/history/export.py, and a third copy is a
# new cross-file clone (tools/metrics/clone_scan.py, ≥6-line statement
# window) — the one smell RULE 16 §16.4 forbids adding. This module's own
# constant between the imports and the logger makes the header its own.
log = logging.getLogger("chatbot")


class CollectPhaseMixin:
    """Run the collect phase and decide what the cycle queues from it."""

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

    async def _known_messaged_set(self) -> set:
        """Nicks already messaged (fail-open: counting errors never stop collect)."""
        try:
            return {u.nick for u in await self._memory.get_all() if u.messaged}
        except Exception:
            return set()

    async def _call_pipeline(self, block, known):
        """Run the pipeline under the retry policy; None after _collect_failed."""
        from actions.cancellation import RunStopped
        try:
            return await self._retry.retry_with_backoff(
                lambda: block.run_pipeline(self._cdp, self, panel_criteria=self._criteria, known_messaged=known),
                fallback=lambda exc: self._collect_failed(block, exc),
                stop=self)
        except asyncio.CancelledError:
            self._ctx = {}
            raise
        except RunStopped:
            self._ctx = {}
            self.debug_msg.emit(_COLLECTION_STOPPED, "warn")
            # run_end/stopped is noted once at the cycle boundary.
            raise
        except Exception:
            self._ctx = {}
            return None

    async def _collect_failed(self, block, exc: Exception):
        log.exception("Collect phase failed")
        self.debug_msg.emit(f"      ❌ Scroll & Parse raised: {exc}", "error")
        self._tracer.note({"type": "phase_end", "phase": "collect", "status": "exception", "error": str(exc)})
        raise exc

    async def _persist_collected(self, collected) -> None:
        """Upsert everyone the pipeline kept (RULE 6: rejects are not persisted)."""
        for person in collected:
            try:
                await self._memory.upsert_user(person)
            except Exception as exc:
                log.warning("upsert failed for %s: %s", person.nick, exc)

    def _collect_summary(self, result) -> str:
        """The one-line collect outcome for the log (seeking vs harvest)."""
        if result.seeking and result.found is not None:
            return f"🎯 Scroll-only: found “{result.found.nick}” on the page — no new people were added"
        if result.seeking:
            return "🔎 Scroll-only: no un-messaged person from the list is currently on the page"
        msg = f"📜 Seen {len(result.all_people)} person(s), {len(result.collected)} matched the filter"
        if result.purged:
            msg += f", {len(result.purged)} removed"
        return msg

    def _collect_tail(self, result) -> list | None:
        """The post-collect stop verdict: None ⇒ use the unmessaged collected."""
        from actions.cancellation import RunStopped, is_stop_requested
        if is_stop_requested(self):
            self.debug_msg.emit(_COLLECTION_STOPPED, "warn")
            raise RunStopped
        if result.stopped:
            # Pipeline-reported stop without an engine flag (test fakes /
            # direct run_pipeline callers): legacy [] return, no raise, so the
            # pre-existing collect-phase contract stays green. Real engine
            # stops always set the flag (predicate is engine.is_stopping).
            self.debug_msg.emit(_COLLECTION_STOPPED, "warn")
            return []
        return None
