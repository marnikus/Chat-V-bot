"""CDP wire ports and production browser adapters (Area A transfer).

Only this backend module imports websockets/aiohttp. Imports are deferred so
fake-backed transport tests need neither those libraries nor Qt. Other layers
use HTTP for non-browser work; this is not a repository-wide network port.
Design: docs/archive/2026-09-19-area-a-integration/AREA_A_TRANSFER_2026-09-19.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable

WS_MAX_SIZE = 50 * 1024 * 1024
WS_OPEN_TIMEOUT_S = 10
WS_CLOSE_TIMEOUT_S = 5
TAB_LIST_TIMEOUT_S = 5


@runtime_checkable
class CdpConnection(Protocol):
    """An open socket; peer closure ends the asynchronous frame stream."""

    def __aiter__(self) -> AsyncIterator[str | bytes]: ...

    async def send(self, payload: str) -> None: ...

    async def close(self) -> None: ...


@runtime_checkable
class CdpConnector(Protocol):
    """Open one tab's webSocketDebuggerUrl."""

    async def open(self, ws_url: str) -> CdpConnection: ...


@runtime_checkable
class TabDiscovery(Protocol):
    """Raw /json/list payload; failures are handled by the client."""

    async def list_tabs(self, base_url: str) -> list[dict]: ...


@dataclass(frozen=True)
class CdpWire:
    """The two browser acquisition collaborators, as one value."""

    connector: CdpConnector
    discovery: TabDiscovery


class WebSocketConnection:
    """Normalize library-specific peer closure to stream exhaustion."""

    def __init__(self, socket, closed_exc: type[BaseException]):
        self._socket = socket
        self._closed_exc = closed_exc

    def __aiter__(self) -> AsyncIterator[str | bytes]:
        return self._frames()

    async def _frames(self) -> AsyncIterator[str | bytes]:
        try:
            async for raw in self._socket:
                yield raw
        except self._closed_exc:
            return

    async def send(self, payload: str) -> None:
        await self._socket.send(payload)

    async def close(self) -> None:
        await self._socket.close()


class WebSocketConnector:
    """Production socket acquisition with the existing size/time limits."""

    async def open(self, ws_url: str) -> CdpConnection:
        import websockets
        socket = await websockets.connect(ws_url, max_size=WS_MAX_SIZE,
                                          open_timeout=WS_OPEN_TIMEOUT_S,
                                          close_timeout=WS_CLOSE_TIMEOUT_S)
        return WebSocketConnection(socket, websockets.ConnectionClosed)


class HttpTabDiscovery:
    """Production /json/list discovery with the existing HTTP policy."""

    async def list_tabs(self, base_url: str) -> list[dict]:
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=TAB_LIST_TIMEOUT_S)
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base_url}/json/list",
                                   timeout=timeout) as response:
                return await response.json() if response.status == 200 else []


def default_wire() -> CdpWire:
    """Bind production adapters without opening any sockets."""
    return CdpWire(WebSocketConnector(), HttpTabDiscovery())
