"""Collector mixin 3a (<150)."""
import asyncio, json, logging
from datetime import datetime
from typing import Optional

class CollectorMixin3a:
    def note_probe_duration(self, seconds: float) -> None:
        """Back off when the page answers slowly (a busy or huge chat)."""
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return
        self._probe_penalty = max(1.0, min(MAX_PROBE_PENALTY, value / 0.1))

    def next_interval_ms(self) -> int:
        base = int(self._settings["idle_heartbeat_ms" if self._state in
                                  IDLE_STATES else "heartbeat_ms"])
        interval = base * self._probe_penalty
        if self._throttled:
            interval *= max(1, int(self._settings["throttle_factor"]))
        return int(interval)

    async def run(self) -> None:
        """The heartbeat loop. Exits promptly when `stop()` is called."""
        self._stop_event = asyncio.Event()
        self.start()
        while self._running:
            try:
                await self.tick()
            except Exception as e:                    # noqa: BLE001
                log.warning("collector tick failed: %s", e)
            if not self._running:
                break
            try:
                await asyncio.wait_for(self._stop_event.wait(),
                                       timeout=self.next_interval_ms() / 1000.0)
            except asyncio.TimeoutError:
                pass

    # ── the heartbeat ────────────────────────────────────────────
    async def tick(self) -> str:
        if not self._running:
            return self._set(CollectorState.OFF, "Collector stopped")
        if not self.enabled:
            return self._set(CollectorState.OFF, "Collector is off")
        if self._paused:
            return self._set(CollectorState.PAUSED, "Paused")
        if not getattr(self.cdp, "is_connected", False):
            return self._set(CollectorState.DISCONNECTED, "Not connected")
        if self._busy:
            return self._state
        self._busy = True
        started = self.now()
        try:
            return await self._tick()
        except Exception as e:                        # noqa: BLE001
            self._error = str(e)
            return self._set(CollectorState.ERROR, f"Collector error: {e}")
        finally:
            self._busy = False
            try:
                self.note_probe_duration(
                    (self.now() - started).total_seconds())
            except Exception:                         # noqa: BLE001
                pass

