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

    def _label_reason_for(self, nick) -> str:
        """Why the filter rejected one nick (fail-open to no reason)."""
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

    def queue_order(self, users: list) -> list[str]:
        block = next((b for b in self._stack if b.block_id == "SCROLL_PARSE" and getattr(b, "enabled", True)), None)
        users = self.filter_by_labels([u for u in users if not getattr(u, "messaged", False)])
        if block is not None:
            from backend.person_filter import sort_people
            users = sort_people(users)
        else:
            users = sorted(sorted(users, key=lambda u: str(getattr(u, "nick", "")).casefold()), key=lambda u: str(getattr(u, "first_seen", "") or ""), reverse=True)
        return [getattr(u, "nick", "") for u in users]

    def _repeat_cycles(self) -> int:
        block = next((b for b in self._stack if b.block_id == "REPEAT_LOOP" and getattr(b, "enabled", True)), None)
        try:
            return max(1, int(getattr(block, "repeat_count", 1))) if block else 1
        except (TypeError, ValueError):
            return 1

    def _respect_order_wanted(self) -> bool:
        """True when an enabled CLICK_USER asks for Order (#) column order."""
        return any(b.block_id == "CLICK_USER"
                   and getattr(b, "respect_order", False)
                   and getattr(b, "enabled", True) for b in self._stack)

    def _rank_by_column(self, rows) -> list:
        """The rows re-ordered into the visible Order (#) column order."""
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
        ranked = self._rank_by_column(rows)
        if ranked:
            self.log_msg.emit(f"🔢 Respecting the Order (#) column — running {len(ranked)} person(s) in list order (#1 first)")
            if self._tracer is not None:
                self._tracer.note({"type": "queue_mode", "mode": "respect_order", "count": len(ranked)})
        return ranked or queue

    async def _wait_if_paused(self) -> None:
        while self._paused and not self._stop_requested:
            await asyncio.sleep(0.2)

    def _single_target_guard(self, take_present: bool,
                             take_matched: bool) -> str | None:
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
        """Account the stopped single-target cycle (stop ⇒ fail on the wire)."""
        # "stop" statuses were already announced in _execute_for_user; only
        # the stop observed at the automatic-mark boundary announces itself.
        if announce:
            self.debug_msg.emit("⏹ Stack stopped by user", "warn")
            self._tracer.note({"type": "run_end", "reason": "stopped"})
        self.progress.note_status("fail")
        self.user_complete.emit(target, False)
        return "stopped"

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

        self.progress.extend_total(1)
        self.log_msg.emit(f"▶ Single-target run — working the person saved in memory: “{target}” (the user list is ignored)")
        self.debug_msg.emit("ℹ Click User 'Use Person from Memory' is on: this stack runs once per cycle against the saved nick, not once per queued person.", "info")
        self._tracer.note({"type": "run_mode", "mode": "single_target", "nick": target})
        try:
            status = await self._execute_for_user(UserRecord(nick=target), has_skip)
        except RunStopped:
            # Narrow handler: CancelledError and unexpected errors propagate.
            status = "stop"
        if status == "stop":
            # Already announced in _execute_for_user; account + return.
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
            try:
                nick = block.choose(rows, self)
            except Exception as exc:
                log.warning("Pick Person failed: %s", exc)
                self.debug_msg.emit(f"      ❌ Pick Person raised: {exc}", "error")
                continue
            if nick:
                matched = True
                self.log_msg.emit(f"🎯 Pick Person: remembering “{nick}” — {{nick}} in later fields will resolve to it")
                self.note_selected(nick)
            else:
                self.log_msg.emit("⚠ Pick Person: no " + (getattr(block, "mode_phrase", "") or "matching person") + " in the list — skipped (previous selection kept)")
        return matched
