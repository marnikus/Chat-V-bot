"""services/run/progress — the run's counters and its ETA.

`RunProgress` / `RunProgressChanged` — done / total / skipped / failed and the
derived ETA, published on the event bus. The UI progress bar reads nothing
else.

This module used to own a second, unrelated thing: the work queue. Round G
(G8) moved `RunQueueMixin` to `services/run/queue` on the strength of the
docstring's own admission that there were "two independent things" here. The
counters answer *how far along are we*; the queue answers *who is in scope*.
Nothing passed between them but the coordinator that mixes in both.

Imports point one way: `coordinator` imports this; this imports only `core`.

Three rules here are contractual and must not be "tidied":

* only `ok` / `skip` / `fail` move a counter (AREA C1 wire contract). A
  cooperative stop is accounted as `fail` at the cycle call sites — stop
  identity lives in the outcome, the trace and `user_complete`, never in a new
  counter, because the UI reads these four numbers positionally.
* an unknown status still EMITS, it just does not increment. Silence would
  freeze the progress bar on an unrecognised status; a repeat of the last
  numbers is the honest answer.
* `eta_seconds` distinguishes `None` (cannot know yet — nothing has finished,
  or the total is not trustworthy) from `0.0` (finished). Collapsing the two
  makes a run that has not started look complete.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from core.events import Event, EventBus

log = logging.getLogger("chatbot")




# F7 (ROUND_F_DESIGN_2026-09-12.md §6) names this file for an MI of 27.85 that is
# NOT a size problem: 258 lines sits inside RULE 18's 150–300 band, so no
# `ideal-size:` note applies here — §18.5 is for exceeding an ideal. The density
# is measured, not asserted: RunProgress 40 LOC / 7 methods, RunQueueMixin
# 177 LOC / 14 methods, worst CC 9 (`queue_order`, `_run_single_target_cycle`),
# and `_run_single_target_cycle` at 31 LOC is over §16.1's fail line as legacy
# debt. §6 asks for decomposition of those, not a split; it is still owed, and a
# higher MI from prose is not progress (§16.2 anti-gaming).


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
