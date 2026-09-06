"""Chrome DevTools Protocol WebSocket client with auto-reconnect."""

import asyncio
import heapq
import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional
import aiohttp
import websockets
from PySide6.QtCore import QObject, Signal

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
        self._listeners: dict[str, list[Callable]] = {}
        self._receive_task: Optional[asyncio.Task] = None
        self._connected = False
        self.lease = CdpLease()

    # ── event fan-out ────────────────────────────────────────────
    def on_event(self, method: str, callback: Callable) -> Callable:
        """Subscribe to a CDP event (e.g. `Runtime.bindingCalled`)."""
        self._listeners.setdefault(method, []).append(callback)
        return callback

    def off_event(self, method: str, callback: Callable | None = None) -> None:
        """Unsubscribe one callback, or every callback for `method`."""
        if callback is None:
            self._listeners.pop(method, None)
            return
        handlers = self._listeners.get(method)
        if handlers and callback in handlers:
            handlers.remove(callback)

    def _dispatch_event(self, frame: dict) -> None:
        """Deliver one received event frame to its listeners.

        A listener that raises (or an async listener with no running loop)
        must never stop the remaining listeners or the receive loop.
        """
        method = frame.get("method")
        if not method:
            return
        params = frame.get("params") or {}
        for callback in list(self._listeners.get(method, ())):
            try:
                result = callback(params)
                if inspect.isawaitable(result):
                    try:
                        asyncio.get_event_loop().create_task(result)
                    except RuntimeError:      # no loop — drop, do not crash
                        result.close()
            except Exception as e:            # noqa: BLE001 - isolation
                log.warning("CDP listener for %s failed: %s", method, e)

    async def add_binding(self, name: str) -> bool:
        """Expose `window[name](payload)` as a `Runtime.bindingCalled` event."""
        try:
            await self.send("Runtime.addBinding", {"name": name})
            return True
        except Exception as e:                # noqa: BLE001
            log.warning("addBinding(%s) failed: %s", name, e)
            return False

    async def add_script_on_new_document(self, source: str) -> str:
        """Re-inject `source` after every navigation. Returns its identifier."""
        try:
            res = await self.send("Page.addScriptToEvaluateOnNewDocument",
                                  {"source": source})
            return res.get("result", {}).get("identifier", "")
        except Exception as e:                # noqa: BLE001
            log.warning("addScriptToEvaluateOnNewDocument failed: %s", e)
            return ""

    async def remove_script_on_new_document(self, identifier: str) -> bool:
        if not identifier:
            return False
        try:
            await self.send("Page.removeScriptToEvaluateOnNewDocument",
                            {"identifier": identifier})
            return True
        except Exception:                     # noqa: BLE001
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    async def fetch_tabs(self) -> list[TabInfo]:
        tabs: list[TabInfo] = []
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{self.base_url}/json/list",
                                 timeout=aiohttp.ClientTimeout(total=5)) as r:
                    for item in (await r.json() if r.status == 200 else []):
                        if item.get("type") == "page":
                            tabs.append(TabInfo(item.get("id",""), item.get("title",""),
                                                item.get("url",""), item.get("webSocketDebuggerUrl","")))
        except Exception as e:
            log.warning("Tab discovery failed: %s", e)
        return tabs

    async def connect(self, ws_url: str) -> bool:
        await self.disconnect()
        try:
            self._ws = await websockets.connect(ws_url, max_size=50*1024*1024,
                                                 open_timeout=10, close_timeout=5)
            self._connected = True
            self._receive_task = asyncio.create_task(self._receive_loop())
            for dom in ("Page", "DOM", "Runtime", "Network"):
                await self.send(f"{dom}.enable")
            log.info("CDP connected: %s", ws_url[:80])
            self.connected.emit()
            return True
        except Exception as e:
            log.error("CDP connect failed: %s", e)
            self.error.emit(str(e))
            return False

    async def disconnect(self) -> None:
        self._connected = False
        if self._receive_task:
            self._receive_task.cancel()
            self._receive_task = None
        if self._ws:
            try: await self._ws.close()
            except Exception: pass
            self._ws = None
        self._pending.clear()
        self.disconnected.emit()

    async def send(self, method: str, params: dict | None = None) -> dict:
        if not self._ws:
            raise ConnectionError("CDP not connected")
        self._cmd_id += 1
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[self._cmd_id] = fut
        await self._ws.send(json.dumps({"id": self._cmd_id, "method": method,
                                         "params": params or {}}))
        return await asyncio.wait_for(fut, timeout=30)

    async def evaluate(self, expression: str) -> Any:
        r = await self.send("Runtime.evaluate", {"expression": expression,
                                                   "returnByValue": True, "awaitPromise": True})
        return r.get("result", {}).get("result", {}).get("value")

    async def click_at(self, x: float, y: float) -> None:
        for t in ("mousePressed", "mouseReleased"):
            await self.send("Input.dispatchMouseEvent",
                            {"type": t, "x": x, "y": y, "button": "left", "clickCount": 1})

    async def mouse_wheel(self, dx: float, dy: float, x: float, y: float) -> None:
        await self.send("Input.dispatchMouseEvent",
                        {"type": "mouseWheel", "x": x, "y": y, "deltaX": dx, "deltaY": dy})

    async def get_element_rect(self, selector: str) -> Optional[dict]:
        js = (f"(function(){{var e=document.querySelector('{selector}');"
              f"if(!e)return null;var r=e.getBoundingClientRect();"
              f"return{{x:r.x,y:r.y,width:r.width,height:r.height}};}})()")
        return await self.evaluate(js)

    async def set_file_input_files(self, selector: str, files: list[str]) -> None:
        res = await self.send("DOM.getDocument")
        root_id = res.get("result", {}).get("root", {}).get("nodeId", 0)
        res = await self.send("DOM.querySelector", {"nodeId": root_id, "selector": selector})
        node_id = res.get("result", {}).get("nodeId", 0)
        if node_id:
            await self.send("DOM.setFileInputFiles", {"files": files, "nodeId": node_id})

    async def _receive_loop(self) -> None:
        try:
            async for raw in self._ws:
                data = json.loads(raw)
                mid = data.get("id")
                if mid and mid in self._pending:
                    self._pending.pop(mid).set_result(data)
                elif data.get("method"):
                    self._dispatch_event(data)
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass
        except Exception as e:
            log.error("CDP receive error: %s", e)
        finally:
            self._connected = False
            self.disconnected.emit()
