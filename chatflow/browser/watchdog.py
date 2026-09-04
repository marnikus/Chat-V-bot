"""Tab-alive watchdog: pings the page, reports connection loss (F-BR-03)."""
from __future__ import annotations

import asyncio

from . import selectors as sel


class TabWatchdog:
    def __init__(self, ops, interval: float = 5.0, on_lost=None):
        self.ops = ops
        self.interval = interval
        self.on_lost = on_lost
        self._task: asyncio.Task | None = None
        self._fail = 0
        self._running = False

    def start(self) -> None:
        self._running = True
        self._fail = 0
        self._task = asyncio.get_event_loop().create_task(self._loop())

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.interval)
            if not self._running:
                return
            alive = False
            try:
                alive = await self.ops.exists(sel.APP_ROOT)
            except Exception:  # noqa: BLE001
                alive = False
            if alive:
                self._fail = 0
            else:
                self._fail += 1
                if self._fail >= 2 and self.on_lost:
                    self._running = False
                    self.on_lost()
                    return
