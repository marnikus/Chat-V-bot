"""Bot worker: QThread with its own asyncio loop (Playwright lives here, R1).

Commands arrive via a thread-safe queue (R2); results leave via the `event`
signal, which the main thread relays to the JS UI (R3). Run orchestration
itself lives in engine/run_task.py (150-line budget).
"""
from __future__ import annotations

import asyncio
import queue
from typing import Any

from PySide6.QtCore import QThread, Signal

from ..core.models import EngineState
from ..engine import state as state_mod
from ..engine import run_task
from ..engine.errors import StopRequested


class Worker(QThread):
    event = Signal(str, object)  # (name, payload) -> main thread

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.s = settings
        self._q: "queue.Queue[tuple[str, dict]]" = queue.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.sm = state_mod.StateMachine(
            on_change=lambda st: self.event.emit("status", {"state": st}))
        self.stop_run = False
        self.pause_evt: asyncio.Event | None = None
        self.ctx = None

    # --- public API (main thread) ------------------------------------------
    def command(self, name: str, payload: dict | None = None) -> None:
        self._q.put((name, payload or {}))

    def run_seq(self, payload: dict) -> None:
        self.command("run", payload)

    def pause(self) -> None:
        self.command("pause")

    def resume(self) -> None:
        self.command("resume")

    def stop(self) -> None:
        self.command("stop")

    def test(self) -> None:
        self.command("test")

    def shutdown(self) -> None:
        self.command("shutdown")

    @property
    def engine_state(self) -> str:
        return self.sm.state.value

    # --- plumbing -------------------------------------------------------------
    def emit_event(self, name: str, payload: Any) -> None:
        self.event.emit(name, payload)

    def log(self, level: str, msg: str, icon: str = "") -> None:
        self.event.emit("log", {"level": level, "msg": msg, "icon": icon})

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._pump())
        finally:
            loop.close()
            self._loop = None

    async def _pump(self) -> None:
        while True:
            name, payload = await self._loop_get()
            if name == "shutdown":
                return
            try:
                if name == "run":
                    await run_task.do_run(self, payload)
                elif name == "test":
                    from ..browser import connect as cdp
                    self.emit_event("test_result", await cdp.test_connection(self.s))
                elif name == "stop":
                    self._on_stop()
                elif name == "pause":
                    self._on_pause()
                elif name == "resume":
                    self._on_resume()
            except Exception as e:  # noqa: BLE001 — worker must never die silently
                self.emit_event("error", {"code": "worker", "msg": str(e)})

    async def _loop_get(self) -> tuple:
        loop = self._loop
        if loop is None:
            return ("shutdown", {})
        return await loop.run_in_executor(None, self._q.get)

    # --- pause / stop -----------------------------------------------------------
    def _on_stop(self) -> None:
        self.stop_run = True
        if self.ctx:
            self.ctx.mark_stopped()
        if self.sm.state in (EngineState.RUNNING, EngineState.PAUSED):
            self.sm.go(EngineState.STOPPING)

    def _on_pause(self) -> None:
        if self.sm.state == EngineState.RUNNING and self.pause_evt:
            self.sm.go(EngineState.PAUSED)
            self.pause_evt.clear()

    def _on_resume(self) -> None:
        if self.sm.state == EngineState.PAUSED and self.pause_evt:
            self.sm.go(EngineState.RUNNING)
            self.pause_evt.set()

    async def gate(self) -> None:
        """Awaited by blocks while paused; raises on stop."""
        while self.pause_evt is not None and not self.pause_evt.is_set():
            if self.stop_run:
                raise StopRequested
            await asyncio.sleep(0.1)
