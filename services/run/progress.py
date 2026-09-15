"""Run-progress accounting, and the queue-order half of a run cycle.

`RunProgress` owns the wire counters (done/total/skipped/failed and the ETA) and
emits `RunProgressChanged`. `RunQueueMixin` now delegates to four focused mixins
extracted by responsibility (H-C1): label filtering, queue ordering,
single-target and take phase — each ≤150 LOC, LCOM drops.

Design: docs/archive/2026-09-14-round-h/AREA_C_SERVICES_STORES_DESIGN_2026-09-14.md H-C1
"""

from __future__ import annotations

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
        _fallback: str = "progress"


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
        return RunProgressChanged(
            done=self.done,
            total=self.total,
            skipped=self.skipped,
            failed=self.failed,
            eta_seconds=self.eta_seconds(),
        )

    def emit(self) -> None:
        self._bus.emit(self.payload())


# ── H-C1: decomposed queue mixin — 4 focused mixins, 1 facade ─────────────
from .label_filter import LabelFilterMixin
from .queue_order import QueueOrderMixin
from .single_target import SingleTargetMixin
from .take_phase import TakePhaseMixin


class RunQueueMixin(LabelFilterMixin, QueueOrderMixin, SingleTargetMixin, TakePhaseMixin):
    """Facade over 4 focused mixins — keeps RunCoordinator's MRO unchanged.

    Old file was 314 LOC, LCOM 0.94, 22 methods mixing 4 concerns.
    New: 4 files × ~60-120 LOC, each LCOM <0.5, plus this 10-line facade.
    """
