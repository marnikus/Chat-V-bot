"""Run-progress accounting: the wire counters of a run.

`RunProgress` owns done/total/skipped/failed and the ETA, and emits
`RunProgressChanged` whenever one of them moves. Nothing else lives here: the
queue-selection half of a cycle (label filter, ordering, Pick Person) is in
`queue_select.py`, the single-target cycle in `single_target.py`, and the
cycle body in `cycle_body.py`.

Import direction: `core.events` at module level only. `requests.py` supplies
the shared `UserRecord` binding, so this file imports no stores module.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from core.events import Event, EventBus

# P0-2 pin: `services.run.progress` must expose the real stores dataclass at
# runtime, not only under TYPE_CHECKING — see
# tests/integration/services/test_run_engine_p0_pins.py::TestProgressUserRecordPin.
# It is re-exported, not re-defined, so the identity assertion holds.
from .requests import UserRecord  # noqa: F401  (re-export, pinned by P0-2)

__all__ = ["RunProgress", "RunProgressChanged", "UserRecord"]


@dataclass(frozen=True, slots=True)
class RunProgressChanged(Event):
    done: int = 0
    total: int = 0
    skipped: int = 0
    failed: int = 0
    eta_seconds: float | None = None


class RunProgress:
    """The counters the progress bar reads, and the event carrying them."""

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
