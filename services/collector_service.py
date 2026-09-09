"""CollectorService — no direct repo calls, mediates via HistoryService.

All methods return Result[T]; bridges await them with @asyncSlot.
"""

from __future__ import annotations

import logging
from typing import Any

from core.result import Result

log = logging.getLogger("chatbot")


class CollectorService:
    """Collector orchestrated through HistoryService (no repo direct)."""

    def __init__(self, history_service) -> None:
        self._hs = history_service
        self._collector = getattr(history_service, "collector", None)
        self._repo = getattr(history_service, "repo", None)

    async def tick(self) -> Result[dict[str, Any]]:
        try:
            if self._collector:
                await self._collector.tick()
                return Result.ok({"ok": True, "state": self._collector.state_payload()})
            return Result.err("collector not available")
        except Exception as exc:  # noqa: BLE001
            log.warning("collector tick failed: %s", exc)
            return Result.err(str(exc))

    async def backfill(self) -> Result[dict[str, Any]]:
        try:
            if self._collector:
                await self._collector.backfill_older()
                return Result.ok({"ok": True})
            return Result.err("collector not available")
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    def state(self) -> Result[dict[str, Any]]:
        try:
            if self._collector:
                return Result.ok(self._collector.state_payload())
            return Result.ok({"state": "off"})
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    async def set_my_nick(self, nick: str) -> Result[str]:
        try:
            clean = self._hs.set_my_nick(nick) if hasattr(self._hs, "set_my_nick") else nick
            return Result.ok(clean)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))
