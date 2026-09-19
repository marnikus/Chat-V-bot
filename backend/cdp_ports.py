"""Browser I/O contracts; framing and event policy remain in the client.

The connection is an async frame stream, not a second CDP implementation.
Adapters own network acquisition; the client still owns request IDs, pending
responses, domain enable order and event dispatch. No Qt or network imports.
"""

from typing import AsyncIterator, Protocol


class CdpConnection(Protocol):
    """The portion of a WebSocket consumed by the CDP receive loop."""

    def __aiter__(self) -> AsyncIterator[str | bytes]: ...

    async def send(self, payload: str) -> None: ...

    async def close(self) -> None: ...


class CdpTransport(Protocol):
    """Acquire a frame stream and discover raw browser targets."""

    async def connect(self, ws_url: str) -> CdpConnection: ...

    async def discover(self, base_url: str) -> list[dict]: ...
