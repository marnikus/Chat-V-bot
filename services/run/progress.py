"""Run-progress accounting, and the queue-order half of a run cycle.

`RunProgress` owns the wire counters (done/total/skipped/failed and the ETA) and
emits `RunProgressChanged`. `RunQueueMixin` contributes label filtering, queue
ordering and the single-target cycle to `RunCoordinator`, which owns everything
the mixin reads through `self`. Imports run one way: core.events and
stores.user_memory at module level, backend.person_filter and
actions.cancellation inside methods to keep `import services.run` light.
"""

# ideal-size: 314 lines reason=§6 of ROUND_F_DESIGN_2026-09-12.md rules out
# splitting this file, and F7's decomposition — _run_single_target_cycle was 31
# LOC, over §16.1's fail line — needs more room than §18.2's band leaves. RULE 19
# puts complexity before size, so the functions come inside §18.1's ideal and the
# file carries this note. Measured in §12: max function 19 LOC, worst CC 8.

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from core.events import Event, EventBus

try:
    from stores.user_memory import UserRecord
except Exception:
    @dataclass
    class UserRecord:
        nick: str
        messaged: bool = False

log = logging.getLogger("chatbot")


@dataclass(frozen=True, slots=True)
class RunProgressChanged(Event):
    done: int = 0
    total: int = 0
    skipped: int = 0
    failed: int = 0
    eta_seconds: float | None = None


class RunProgress:
    def __init__(self, bus: EventBus | None = None):
        self._bus = bus or EventBus()
        self.reset()

    def reset(self) -> None:
        self.done = self.total = self.skipped = self.failed = 0
        self._started_at = time.monotonic()

    def extend_total(self, count: int) -> None:
        self.total += max(0, int(count or 0))
        self.emit()

    def note_status(self, status: str) -> None:
        # Wire contract (AREA C1, preserved): only ok/skip/fail increment.
        # Cooperative "stop" is accounted as "fail" by the cycle call sites;
        # stop identity lives in the outcome/trace/user_complete, never in a
        # new wire counter. Unknown statuses emit without incrementing.
        if status == "ok":
            self.done += 1
        elif status == "skip":
            self.skipped += 1
        elif status == "fail":
            self.failed += 1
        self.emit()

    def eta_seconds(self) -> float | None:
        finished = self.done + self.skipped + self.failed
        if finished <= 0 or self.total <= finished:
            return 0.0 if self.total and self.total == finished else None
        elapsed = max(0.001, time.monotonic() - self._started_at)
        return round((elapsed / finished) * (self.total - finished), 3)

    def payload(self) -> RunProgressChanged:
        return RunProgressChanged(done=self.done, total=self.total,
                                  skipped=self.skipped, failed=self.failed,
                                  eta_seconds=self.eta_seconds())

    def emit(self) -> None:
        self._bus.emit(self.payload())


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
        """The enabled block with this id, or None — one shape, three callers."""
        return next((b for b in self._stack if b.block_id == block_id
                     and getattr(b, "enabled", True)), None)

    def _unmessaged(self, users: list) -> list:
        """The people not yet messaged, after the label filter."""
        return self.filter_by_labels(
            [u for u in users if not getattr(u, "messaged", False)])

    def _order_by_recency(self, users: list) -> list:
        """Newest `first_seen` first; stable, so nick stays the tie-break."""
        by_nick = sorted(users,
                         key=lambda u: str(getattr(u, "nick", "")).casefold())
        return sorted(by_nick, reverse=True,
                      key=lambda u: str(getattr(u, "first_seen", "") or ""))

    def queue_order(self, users: list) -> list[str]:
        """The nicks this cycle works, in the order it works them."""
        users = self._unmessaged(users)
        if self._enabled_block("SCROLL_PARSE") is not None:
            from backend.person_filter import sort_people
            users = sort_people(users)
        else:
            users = self._order_by_recency(users)
        return [getattr(u, "nick", "") for u in users]

    def _repeat_cycles(self) -> int:
        block = self._enabled_block("REPEAT_LOOP")
        try:
            return max(1, int(getattr(block, "repeat_count", 1))) if block else 1
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

    def _announce_stop(self) -> None:
        """The one stop line and its trace entry, which two call sites shared."""
        self.debug_msg.emit("⏹ Stack stopped by user", "warn")
        self._tracer.note({"type": "run_end", "reason": "stopped"})

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
            self._announce_stop()
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
            self._announce_stop()
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
            if self._take_one_block(block, rows):
                matched = True
        return matched

    def _take_one_block(self, block, rows) -> bool:
        """One Pick Person block's choice; True when it remembered someone."""
        try:
            nick = block.choose(rows, self)
        except Exception as exc:
            log.warning("Pick Person failed: %s", exc)
            self.debug_msg.emit(f"      ❌ Pick Person raised: {exc}", "error")
            return False
        if nick:
            self.log_msg.emit(
                f"🎯 Pick Person: remembering “{nick}” — {{nick}} in later "
                "fields will resolve to it")
            self.note_selected(nick)
            return True
        self.log_msg.emit(
            "⚠ Pick Person: no "
            + (getattr(block, "mode_phrase", "") or "matching person")
            + " in the list — skipped (previous selection kept)")
        return False
