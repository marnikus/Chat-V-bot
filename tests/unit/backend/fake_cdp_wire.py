"""Scripted Chrome wire reconstructed from the supplied Area A double.

A script returns a reply dict, a raw string frame, or None (peer EOF).
Requests are queued rather than busy-polled; close wakes a parked reader.
No live sockets and no module patching above the production adapter boundary.
"""
from __future__ import annotations

import asyncio
import json
from typing import Callable, Iterable, Optional

from backend.cdp_transport import CdpWire

Script = Callable[[dict], Optional[dict | str]]


def _ok(_request: dict) -> dict:
    return {"result": {}}


class FakeConnection:
    def __init__(self, script: Script | None = None,
                 events: Iterable[dict | str] = ()):
        self.sent: list[dict] = []
        self.closed = False
        self._script = script or _ok
        self._events = [e if isinstance(e, str) else json.dumps(e) for e in events]
        self._requests = asyncio.Queue()

    @property
    def methods(self) -> list[str]:
        return [request.get("method", "") for request in self.sent]

    def __aiter__(self):
        return self._frames()

    async def _frames(self):
        for frame in self._events:
            await asyncio.sleep(0)
            yield frame
        while True:
            request = await self._requests.get()
            if request is None:
                return
            answer = self._script(request)
            if answer is None:
                return
            await asyncio.sleep(0)
            yield (answer if isinstance(answer, str)
                   else json.dumps({"id": request["id"], **answer}))

    async def send(self, payload: str) -> None:
        if self.closed:
            raise ConnectionError("closed")
        request = json.loads(payload)
        self.sent.append(request)
        await self._requests.put(request)

    async def close(self) -> None:
        self.closed = True
        await self._requests.put(None)


class FakeConnector:
    def __init__(self, *connections: FakeConnection, refuse: int = 0):
        self.opened: list[str] = []
        self._connections = list(connections)
        self._refuse = refuse

    async def open(self, ws_url: str) -> FakeConnection:
        self.opened.append(ws_url)
        if self._refuse > 0:
            self._refuse -= 1
            raise OSError("refused")
        if not self._connections:
            raise OSError("no scripted connection left")
        return self._connections.pop(0)


class FakeTabDiscovery:
    def __init__(self, items: Iterable[dict] = (), error: Exception | None = None):
        self.items = list(items)
        self.error = error
        self.asked: list[str] = []

    async def list_tabs(self, base_url: str) -> list[dict]:
        self.asked.append(base_url)
        if self.error is not None:
            raise self.error
        return list(self.items)


def fake_wire(*connections: FakeConnection, tabs: Iterable[dict] = (),
              refuse: int = 0, tab_error: Exception | None = None) -> CdpWire:
    return CdpWire(FakeConnector(*connections, refuse=refuse),
                   FakeTabDiscovery(tabs, tab_error))
