"""Chrome DevTools Protocol WebSocket client with auto-reconnect.

Round H step H-B6 split the file by *who it talks to*:

* `backend/cdp_client_transport.py` — the wire: the connect/disconnect
  lifecycle, request/response framing, the receive loop, tab discovery and
  the command helpers (script injection, cookies, input, file inputs);
* `backend/cdp_client_events.py` — the event fan-out: the listener table
  and the isolation rule (a failing listener must never kill the loop);
* this file — the `CDPClient` QObject the rest of the application knows,
  plus the priority lease and `TabInfo`.

The facade keeps every historical name and seam: the mutable socket state
(`_ws`, `_cmd_id`, `_pending`, `_connected`, `_receive_task`) stays plain
instance attributes, and every command method calls `self.send`, so the
long-standing test seam (shadowing `cdp.send` with a fake, assigning
`cdp._ws` / `cdp._connected`) works unchanged (tests/test_cdp_events.py,
tests/unit/backend/test_cdp_client_transport.py). `CdpLease` and `TabInfo`
stay defined here because the public API snapshot pins them to this module
(tests/unit/backend/backend_api_snapshot.json).

Imports: the two part modules only (plus PySide6); the parts never import
this file back.
"""

import asyncio
import heapq
import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Signal

from backend import cdp_client_transport as transport
from backend.cdp_client_events import CdpEvents

log = logging.getLogger("chatbot")

HIGH, LOW = 0, 1


@dataclass
class TabInfo:
    id: str; title: str; url: str; ws_url: str


class _LeaseCtx:
    """`async with lease.high(): ...` — an acquired-and-released lease."""

    def __init__(self, lease: "CdpLease", priority: int):
        self._lease, self._priority = lease, priority

    async def __aenter__(self):
        await self._lease.acquire(self._priority)
        return self._lease

    async def __aexit__(self, exc_type, exc, tb):
        self._lease.release()
        return False


class CdpLease:
    """Priority mutex over the single CDP socket.

    The action engine (HIGH) and the passive collector (LOW) share one
    WebSocket. Whoever holds the lease is never interrupted mid-command,
    but a queued HIGH waiter always jumps ahead of queued LOW waiters, so
    a user-triggered run never waits behind background collection.
    """

    def __init__(self) -> None:
        self._locked = False
        self._waiters: list[tuple[int, int, asyncio.Future]] = []
        self._seq = 0

    # ── public api ───────────────────────────────────────────────
    def high(self) -> _LeaseCtx:
        return _LeaseCtx(self, HIGH)

    def low(self) -> _LeaseCtx:
        return _LeaseCtx(self, LOW)

    @property
    def busy(self) -> bool:
        return self._locked

    @property
    def waiting(self) -> int:
        return len(self._waiters)

    @property
    def high_waiting(self) -> bool:
        return any(p == HIGH for p, _s, f in self._waiters if not f.done())

    async def acquire(self, priority: int = LOW) -> None:
        if not self._locked and not self._waiters:
            self._locked = True
            return
        self._seq += 1
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        heapq.heappush(self._waiters, (priority, self._seq, fut))
        try:
            await fut
        except asyncio.CancelledError:
            # we may have been handed ownership just as we were cancelled
            if fut.done() and not fut.cancelled():
                self.release()
            raise

    def release(self) -> None:
        while self._waiters:
            _prio, _seq, fut = heapq.heappop(self._waiters)
            if not fut.done():
                fut.set_result(True)      # hand the lease over, stay locked
                return
        self._locked = False


class CDPClient(QObject):
    """WebSocket client for Chrome DevTools Protocol.

    Method count is one below the ideal fifteen-plus-one only because the
    public command surface (frozen by ~20 importers and by the API
    snapshot) is flat on this class; the bodies of all of them live in the
    two part modules, so the class itself is a thin, fully testable seam.
    """

    connected = Signal()
    disconnected = Signal()
    error = Signal(str)

    def __init__(self, host: str = "127.0.0.1", port: int = 9222,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self._host, self._port = host, port
        self._ws: Any = None
        self._cmd_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._receive_task: Optional[asyncio.Task] = None
        self._connected = False
        self.lease = CdpLease()
        self._events = CdpEvents()

    # ── event fan-out (body in cdp_client_events.py) ──────────────
    def on_event(self, method: str, callback: Callable) -> Callable:
        """Subscribe to a CDP event (e.g. `Runtime.bindingCalled`)."""
        return self._events.on_event(method, callback)

    def off_event(self, method: str, callback: Callable | None = None) -> None:
        """Unsubscribe one callback, or every callback for `method`."""
        self._events.off_event(method, callback)

    def _dispatch_event(self, frame: dict) -> None:
        """Deliver one received event frame to its listeners."""
        self._events.dispatch(frame)

    # ── connection lifecycle (body in cdp_client_transport.py) ────
    async def connect(self, ws_url: str) -> bool:
        """Connect, enable the four domains and start the receive loop."""
        return await transport.open_client(self, ws_url)

    async def disconnect(self) -> None:
        await transport.close_client(self)

    async def send(self, method: str, params: dict | None = None) -> dict:
        return await transport.raw_send(self, method, params)

    async def _receive_loop(self) -> None:
        await transport.receive_loop(self)

    @property
    def is_connected(self) -> bool:
        return bool(self._connected and self._ws is not None)

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    async def fetch_tabs(self) -> list[TabInfo]:
        """List of available page tabs (empty if the endpoint is down)."""
        return [TabInfo(item.get("id", ""), item.get("title", ""),
                        item.get("url", ""),
                        item.get("webSocketDebuggerUrl", ""))
                for item in await transport.fetch_tabs(self)]

    # ── command helpers (bodies in cdp_client_transport.py) ───────
    async def add_binding(self, name: str) -> bool:
        """Expose `window[name](payload)` as a `Runtime.bindingCalled` event."""
        return await transport.add_binding(self, name)

    async def add_script_on_new_document(self, source: str) -> str:
        """Re-inject `source` after every navigation. Returns its identifier."""
        return await transport.add_script_on_new_document(self, source)

    async def remove_script_on_new_document(self, identifier: str) -> bool:
        if not identifier:
            return False
        return await transport.remove_script_on_new_document(self, identifier)

    async def evaluate(self, expression: str) -> Any:
        return await transport.evaluate(self, expression)

    async def get_cookies(self, url: str = "") -> str:
        """A `Cookie` header string for the given origin.

        Used by the media cache's Python download path: the browser tab can
        load `images.virt-chat.com` through an `<img>` tag with the session
        cookies (no CORS), but the in-page `fetch()` needed for the old cache
        can be blocked by CORS. Downloading from Python with the same cookies
        bypasses that while still authenticating like the page.
        """
        return await transport.cookie_header(self, url)

    async def click_at(self, x: float, y: float) -> None:
        await transport.click_at(self, x, y)

    async def mouse_wheel(self, dx: float, dy: float, x: float,
                          y: float) -> None:
        await transport.mouse_wheel(self, dx, dy, x, y)

    async def get_element_rect(self, selector: str) -> Optional[dict]:
        return await transport.get_element_rect(self, selector)

    async def set_file_input_files(self, selector: str,
                                   files: list[str]) -> None:
        await transport.set_file_input_files(self, selector, files)
