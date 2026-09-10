"""Shared fakes and small utilities for the bridge_safety test package.

Design notes (Area B, B2):
- The fake engine is a REAL QObject so ``StackBridge._connect_engine`` can
  install its signal relays exactly as it does in production.
- The fake CDP service is a plain object (the service seam the bridge reads
  is a coroutine-returning surface, not Qt).
- ``drain`` advances a running loop a bounded number of ticks; tests always
  run inside ``asyncio.run`` / a controlled loop, never in the bare thread.
"""

from __future__ import annotations

import asyncio

from PySide6.QtCore import QObject, Signal

from core.events import LogMessage
from core.result import Ok


class FakeEngine(QObject):
    """Minimal run engine exposing exactly the public surface StackBridge reads."""

    step_complete = Signal(str, str)
    step_started = Signal(int, str, str)
    stack_complete = Signal()
    log_msg = Signal(str)
    debug_msg = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.is_running = False
        self.loaded = None
        self.stop_calls = 0
        self.pause_calls = 0
        self.resume_calls = 0
        self.executions = 0
        self.composer_text = ""
        self._stack = []

    def load_stack(self, blocks):
        self.loaded = list(blocks)

    def get_stack(self):
        return list(self._stack)

    def stop(self):
        self.stop_calls += 1

    def pause(self):
        self.pause_calls += 1

    def resume(self):
        self.resume_calls += 1

    async def execute(self):
        self.executions += 1


class FakeCdpService:
    """Configurable fake CdpService: records calls, returns pluggable Results.

    ``connect_error``, when set, is raised by ``connect`` (the "service
    raises" boundary case). ``fetch_payload`` is emitted back as a
    TabsReceived bus event to prove event-to-signal forwarding.
    """

    def __init__(self, bus=None):
        self.bus = bus
        self.connect_result = Ok(True)
        self.connect_error = None
        self.connect_calls = []
        self.fetch_calls = 0
        self.fetch_payload = None
        self.find_calls = []
        self.find_matches = None

    async def fetch_tabs(self):
        self.fetch_calls += 1
        if self.fetch_payload is not None and self.bus is not None:
            from core.events import TabsReceived
            self.bus.emit(TabsReceived(payload=self.fetch_payload))
        return Ok([])

    async def connect(self, ws_url):
        self.connect_calls.append(ws_url)
        if self.connect_error is not None:
            raise self.connect_error
        return self.connect_result

    async def find_tab_by_url(self, query):
        self.find_calls.append(query)
        if self.bus is not None:
            from core.events import TabMatchResult
            self.bus.emit(TabMatchResult(
                query=query,
                matches_json=self.find_matches or "[]"))
        return Ok([])


class LogCapture:
    """Collects LogMessage events off an EventBus."""

    def __init__(self, bus):
        self.messages = []
        bus.subscribe(LogMessage, self._on)

    def _on(self, event):
        self.messages.append((event.message, event.level))

    def levels(self):
        return [level for _message, level in self.messages]

    def text(self):
        return " ".join(message for message, _level in self.messages)

    def any(self, fragment, level=None):
        return any(fragment in message and (level is None or lvl == level)
                   for message, lvl in self.messages)


async def drain(ticks: int = 16) -> None:
    """Advance the running loop so scheduled bridge tasks get a chance to run."""
    for _ in range(ticks):
        await asyncio.sleep(0.001)


def run(coro_factory):
    """Run an async scenario on a fresh event loop; return its result."""
    return asyncio.run(coro_factory())
