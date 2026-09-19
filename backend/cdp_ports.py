"""Browser I/O contracts; framing and event policy remain in the client.

The connection is an async frame stream, not a second CDP implementation.
Adapters own network acquisition; the client still owns request IDs, pending
responses, domain enable order and event dispatch. No Qt or network imports.
"""

from typing import Protocol

from backend.cdp_transport import CdpConnection  # noqa: F401 (public re-export)


class CdpTransport(Protocol):
    """Acquire a frame stream and discover raw browser targets."""

    async def connect(self, ws_url: str) -> CdpConnection: ...

    async def discover(self, base_url: str) -> list[dict]: ...


class CombinedTransportAdapter:
    """Keep Round I's combined transport usable with the split CdpWire."""

    def __init__(self, browser: CdpTransport):
        self.browser = browser

    async def open(self, ws_url: str) -> CdpConnection:
        return await self.browser.connect(ws_url)

    async def list_tabs(self, base_url: str) -> list[dict]:
        return await self.browser.discover(base_url)
