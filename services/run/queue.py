"""services/run/queue — which people this run will actually work on.

Split out of `services/run/progress` in round G (G8). That module had said
in its own docstring that it "owns two independent things"; this is the
second one. The counters answer *how far along are we*, this answers *who
is in scope*, and nothing passes between them except the coordinator that
mixes both in.

Imports point one way: `coordinator` imports this; this imports only
`core` and `actions.cancellation` (locally, to avoid a cycle).

The contract that must not be "tidied": a label filter that raises is
logged and treated as ALLOW. A broken filter must never silently empty the
queue -- the user would see a run that did nothing and no reason why. The
same reasoning governs a Pick Person block that raises or matches nobody:
it is reported and skipped, and the previous selection is kept, because a
miss must narrow nothing.
"""

from __future__ import annotations

import asyncio
import logging

from dataclasses import dataclass

# `stores.user_memory` is optional at import time: the run package must stay
# importable when the memory store is absent (a fresh checkout, or a test that
# stubs stores/). This package's copy of the fallback lives HERE, and
# `coordinator` imports it from this module rather than repeating the shim —
# two copies could drift into two different UserRecord shapes in one process.
try:
    from stores.user_memory import UserRecord
except Exception:                                    # noqa: BLE001
    @dataclass
    class UserRecord:
        nick: str
        messaged: bool = False

log = logging.getLogger("chatbot")


def _newest_first(users: list) -> list:
    """Newest `first_seen` first, ties broken A–Z by nick.

    Two passes rather than one tuple key because the two fields sort in
    OPPOSITE directions: the stable inner sort establishes the alphabetical
    tie-break, the outer reverse sort puts the newest on top without
    disturbing it. A single `key=` with `reverse=True` would also reverse the
    alphabetical order within each timestamp.
    """
    by_nick = sorted(users,
                     key=lambda u: str(getattr(u, "nick", "")).casefold())
    return sorted(by_nick,
                  key=lambda u: str(getattr(u, "first_seen", "") or ""),
                  reverse=True)


class RunQueueMixin:
    def label_allows(self, nick) -> bool:
        if not callable(self.label_filter):
            return True
        try:
            return bool(self.label_filter(nick))
        except Exception as exc:
            log.warning("label filter failed for %r: %s", nick, exc)
            return True

    def filter_by_labels(self, users: list, announce: bool = False) -> list:
        if not callable(self.label_filter):
            return list(users or [])
        kept, skipped = [], []
        for user in users or []:
            nick = getattr(user, "nick", user)
            if self.label_allows(nick):
                kept.append(user)
            else:
                skipped.append(str(nick))
        if skipped and announce:
            self._announce_label_skips(skipped)
        return kept

    def _label_reason_for(self, nick) -> str:
        """Why the label filter rejected one nick (fail-open to no reason)."""
        if not callable(self.label_reason):
            return ""
        try:
            return str(self.label_reason(nick) or "")
        except Exception:
            return ""

    def _announce_label_skips(self, skipped: list) -> None:
        """One info line naming the first few rejected people (+N more)."""
        samples = []
        for nick in skipped[:5]:
            why = self._label_reason_for(nick)
            samples.append(f"{nick}{f' ({why})' if why else ''}")
        more = (f" +{len(skipped) - len(samples)} more"
                if len(skipped) > len(samples) else "")
        self.debug_msg.emit(f"🏷 Label filter skipped {len(skipped)} person(s): "
                            + ", ".join(samples) + more, "info")

    def _enabled_block(self, block_id: str):
        """The first enabled block with this id, or None. A DISABLED block must
        read as absent everywhere — that is what the checkbox means."""
        return next((b for b in self._stack
                     if b.block_id == block_id and getattr(b, "enabled", True)),
                    None)

    def queue_order(self, users: list) -> list[str]:
        """The nicks to work, in the order they will be worked.

        Already-messaged people are dropped first, then the label filter, then
        the ordering — which depends on whether the stack collects:

        * with SCROLL_PARSE, `sort_people` owns the order (it interleaves
          newly-found people the way the collector expects);
        * without it, newest-first by `first_seen`, ties broken A-Z by nick.
        """
        users = self.filter_by_labels(
            [u for u in users if not getattr(u, "messaged", False)])
        if self._enabled_block("SCROLL_PARSE") is not None:
            from backend.person_filter import sort_people
            users = sort_people(users)
        else:
            users = _newest_first(users)
        return [getattr(u, "nick", "") for u in users]

    def _repeat_cycles(self) -> int:
        """How many times REPEAT_LOOP asks for the queue; always at least 1.

        A missing, disabled or unparsable count means one pass — never zero,
        which would look to the user like the run silently did nothing.
        """
        block = self._enabled_block("REPEAT_LOOP")
        if block is None:
            return 1
        try:
            return max(1, int(getattr(block, "repeat_count", 1)))
        except (TypeError, ValueError):
            return 1

    def _respect_order_wanted(self) -> bool:
        """CLICK_USER wants the queue in the visible Order (#) column order."""
        return any(b.block_id == "CLICK_USER" and getattr(b, "respect_order", False)
                   and getattr(b, "enabled", True) for b in self._stack)

    def _rank_queue(self, rows) -> list:
        """The queue in Order (#) column order, from the memory rows."""
        order = self.queue_order(rows)
        by_nick = {getattr(row, "nick", ""): row for row in rows}
        return [by_nick[nick] for nick in order if nick in by_nick]

    async def _order_queue_by_column(self, queue: list[UserRecord]) -> list[UserRecord]:
        # Local import: keeps "import services.run" light (actions/__init__
        # scans every block module); same for the other lazy imports below.
        from actions.cancellation import check_stopped
        check_stopped(self)
        if not self._respect_order_wanted() or not queue:
            return queue
        rows = await self._memory.get_all()
        check_stopped(self)
        ranked = self._rank_queue(rows)
        if ranked:
            self.log_msg.emit(f"🔢 Respecting the Order (#) column — running {len(ranked)} person(s) in list order (#1 first)")
            if self._tracer is not None:
                self._tracer.note({"type": "queue_mode", "mode": "respect_order", "count": len(ranked)})
        return ranked or queue

    async def _wait_if_paused(self) -> None:
        while self._paused and not self._stop_requested:
            await asyncio.sleep(0.2)

    async def _run_single_target_cycle(self, has_skip: bool, take_matched: bool) -> str:
        from actions.cancellation import RunStopped, is_stop_requested
        take_present = any(b.block_id == "TAKE_PERSON" and getattr(b, "enabled", True) for b in self._stack)
        verdict = self._single_target_guard(take_present, take_matched)
        if verdict is not None:
            return verdict
        if is_stop_requested(self):
            self.debug_msg.emit("⏹ Stack stopped by user", "warn")
            self._tracer.note({"type": "run_end", "reason": "stopped"})
            return "stopped"
        target = self.selected_nick
        self._announce_single_target(target)
        try:
            status = await self._execute_for_user(UserRecord(nick=target), has_skip)
        except RunStopped:
            # Narrow handler: CancelledError and unexpected errors propagate.
            status = "stop"
        if status == "stop":
            return self._stopped_single_target(target, announce=False)
        if is_stop_requested(self):
            # Stop observed before the automatic-mark boundary.
            return self._stopped_single_target(target, announce=True)
        self.progress.note_status(status)
        if status == "ok":
            await self._memory.mark_messaged(target)
            self.person_marked.emit(target)
        self.user_complete.emit(target, status == "ok")
        return "worked"

    def _announce_single_target(self, target: str) -> None:
        """Open a single-target cycle: one more unit of work, and say why.

        The total is extended here rather than up front because a
        single-target run does not know its length in advance -- it adds one
        unit per cycle it actually commits to, so the progress bar never
        promises work that a guard might refuse.
        """
        self.progress.extend_total(1)
        self.log_msg.emit(f"▶ Single-target run — working the person saved in memory: “{target}” (the user list is ignored)")
        self.debug_msg.emit("ℹ Click User 'Use Person from Memory' is on: this stack runs once per cycle against the saved nick, not once per queued person.", "info")
        self._tracer.note({"type": "run_mode", "mode": "single_target", "nick": target})

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
            self.debug_msg.emit("⏹ Stack stopped by user", "warn")
            self._tracer.note({"type": "run_end", "reason": "stopped"})
        self.progress.note_status("fail")
        self.user_complete.emit(target, False)
        return "stopped"

    async def _run_take_phase(self) -> bool:
        from actions.cancellation import check_stopped
        check_stopped(self)
        try:
            rows = await self._memory.get_all()
        except Exception as exc:
            log.warning("Pick Person phase could not read the list: %s", exc)
            self.debug_msg.emit(f"      ❌ Pick Person: cannot read the People list ({exc})", "error")
            return False
        check_stopped(self)
        matched = False
        for block in self._stack:
            check_stopped(self)
            if block.block_id != "TAKE_PERSON" or not getattr(block, "enabled", True):
                continue
            matched = self._apply_take_block(block, rows) or matched
        return matched

    def _apply_take_block(self, block, rows) -> bool:
        """Run one Pick Person block; True when it selected somebody.

        A block that raises, or that matches nobody, is reported and skipped
        rather than ending the phase: later blocks in the stack are separate
        user intentions, and the previous selection is deliberately kept so a
        miss narrows nothing.
        """
        try:
            nick = block.choose(rows, self)
        except Exception as exc:
            log.warning("Pick Person failed: %s", exc)
            self.debug_msg.emit(f"      ❌ Pick Person raised: {exc}", "error")
            return False
        if not nick:
            self.log_msg.emit("⚠ Pick Person: no " + (getattr(block, "mode_phrase", "") or "matching person") + " in the list — skipped (previous selection kept)")
            return False
        self.log_msg.emit(f"🎯 Pick Person: remembering “{nick}” — {{nick}} in later fields will resolve to it")
        self.note_selected(nick)
        return True
