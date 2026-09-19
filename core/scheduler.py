"""Clock seam for deterministic world-open polling; no Qt dependency."""
from __future__ import annotations

import asyncio
from typing import Callable, Protocol

WAIT_S = 15.0
POLL_STEP_S = 0.05


class Scheduler(Protocol):
    def now(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...

    async def until(self, predicate: Callable[[], bool], timeout: float,
                    step: float = POLL_STEP_S) -> bool: ...


async def poll(scheduler: Scheduler, predicate: Callable[[], bool],
               timeout: float, step: float) -> bool:
    """Poll with historical deadline semantics, rejecting a stalled clock."""
    if not step > 0:
        raise ValueError("poll step must be positive")
    deadline = scheduler.now() + max(0.0, timeout)
    while not predicate():
        if scheduler.now() >= deadline:
            return False
        await scheduler.sleep(step)
    return True


class ManualScheduler:
    """Advance logical time, yielding to other tasks without wall-clock delay."""

    def __init__(self, start: float = 0.0):
        self._time = start
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self._time

    async def sleep(self, seconds: float) -> None:
        delay = max(0.0, seconds)
        self.sleeps.append(delay)
        self._time += delay
        await asyncio.sleep(0)

    async def until(self, predicate: Callable[[], bool], timeout: float,
                    step: float = POLL_STEP_S) -> bool:
        return await poll(self, predicate, timeout, step)
