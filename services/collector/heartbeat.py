"""The heartbeat loop and its per-tick gate.

`HeartbeatMixin` owns the supervisor loop (`run`) and the tick gate (`tick`),
which delegates the real state machine to `services.collector_tick` and
reports the terminal status. This is the only collector module that imports
`backend` — the parser helpers are injected into `CollectorTick` so
`collector_tick` itself stays backend-free.
"""

import asyncio
import logging

from backend import chat_agent_js
from backend.chat_parser import _signature, verify_private

from .constants import CollectorState

log = logging.getLogger("chatbot")


class HeartbeatMixin:
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

    async def _tick(self) -> str:
        # The 212-LOC heartbeat coroutine is now the AREA C tick state
        # machine (`services/collector_tick.py`): PROBE → GATE → NICK →
        # VERIFY → ARCHIVE, each phase a CC ≤ 10 collaborator. The parser
        # helpers are injected so `collector_tick` adds no backend import;
        # the import is function-local to avoid a module cycle.
        from services.collector_tick import CollectorTick
        state, text = await CollectorTick(
            self,
            signature=_signature,
            verify_private=verify_private,
            agent_version=chat_agent_js.AGENT_VERSION,
        ).run()
        return self._set(state, text)
