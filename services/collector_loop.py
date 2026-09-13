"""The heartbeat loop, and nothing else.

Owns `run()` (the cancellable loop) and `tick()` (one guarded beat: the
off/paused/disconnected/busy refusals, the error capture and the probe
timing). Built from the aggregate only; `_busy`, `_running` and
`_stop_event` stay on `Collector`. The tick's phase state machine is
already `services/collector_tick.py` and is not touched here.
"""

from __future__ import annotations

import asyncio
import logging

from services.collector_states import CollectorState

log = logging.getLogger("chatbot")


class RunLoop:
    """One responsibility of `Collector`, built from it."""

    def __init__(self, owner):
        self._o = owner

    async def run(self) -> None:
        """The heartbeat loop. Exits promptly when `stop()` is called."""
        self._o._stop_event = asyncio.Event()
        self._o.start()
        while self._o._running:
            try:
                await self._o.tick()
            except Exception as e:                    # noqa: BLE001
                log.warning("collector tick failed: %s", e)
            if not self._o._running:
                break
            try:
                await asyncio.wait_for(
                    self._o._stop_event.wait(),
                    timeout=self._o.next_interval_ms() / 1000.0)
            except asyncio.TimeoutError:
                pass

    # ── the heartbeat ────────────────────────────────────────────
    async def tick(self) -> str:
        if not self._o._running:
            return self._o._set(CollectorState.OFF, "Collector stopped")
        if not self._o.enabled:
            return self._o._set(CollectorState.OFF, "Collector is off")
        if self._o._paused:
            return self._o._set(CollectorState.PAUSED, "Paused")
        if not getattr(self._o.cdp, "is_connected", False):
            return self._o._set(CollectorState.DISCONNECTED, "Not connected")
        if self._o._busy:
            return self._o._state
        self._o._busy = True
        started = self._o.now()
        try:
            return await self._o._tick()
        except Exception as e:                        # noqa: BLE001
            self._o._error = str(e)
            return self._o._set(CollectorState.ERROR, f"Collector error: {e}")
        finally:
            self._o._busy = False
            try:
                self._o.note_probe_duration(
                    (self._o.now() - started).total_seconds())
            except Exception:                         # noqa: BLE001
                pass
