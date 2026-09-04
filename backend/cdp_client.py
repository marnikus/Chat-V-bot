"""Chrome DevTools Protocol WebSocket client with auto-reconnect."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional
import aiohttp
import websockets
from PySide6.QtCore import QObject, Signal

log = logging.getLogger("chatbot")


@dataclass
class TabInfo:
    id: str; title: str; url: str; ws_url: str


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
        self._receive_task: Optional[asyncio.Task] = None
        self._connected = False

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
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass
        except Exception as e:
            log.error("CDP receive error: %s", e)
        finally:
            self._connected = False
            self.disconnected.emit()
