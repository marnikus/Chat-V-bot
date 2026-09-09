"""CdpBridge — Chrome tab discovery & connection domain."""

from __future__ import annotations

import asyncio
import json
import logging
from PySide6.QtCore import QObject, Signal, Slot
try:
    from qasync import asyncSlot
except Exception:
    asyncSlot = lambda *a, **kw: (lambda f: f)

from backend.tab_matcher import best_matches

log = logging.getLogger("chatbot")


class CdpBridge(QObject):
    tabs_received = Signal(str)
    connection_status = Signal(str)
    tab_match_result = Signal(str, str)
    log_message = Signal(str, str)

    def __init__(self, ctx: dict, parent=None):
        super().__init__(parent)
        self._cdp = ctx.get("cdp")
        self._engine = ctx.get("engine")
        if self._cdp:
            try:
                self._cdp.connected.connect(lambda: self.connection_status.emit("connected"))
                self._cdp.disconnected.connect(lambda: self.connection_status.emit("disconnected"))
                self._cdp.error.connect(lambda e: self.connection_status.emit("error"))
            except Exception:
                pass

    @Slot(result=str)
    def get_tabs(self):
        asyncio.ensure_future(self._fetch_tabs())
        return "pending"

    async def _fetch_tabs(self):
        try:
            tabs = await self._cdp.fetch_tabs()
            self.tabs_received.emit(json.dumps([{"id": t.id, "title": t.title, "url": t.url, "ws_url": t.ws_url} for t in tabs], ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            log.error("Tab fetch failed: %s", exc)
            self.log_message.emit(f"❌ Tab discovery failed: {exc}", "error")

    @Slot(str)
    def connect_tab(self, ws_url):
        asyncio.ensure_future(self._do_connect(ws_url))

    async def _do_connect(self, ws_url):
        if await self._cdp.connect(ws_url):
            self.log_message.emit("🔗 Connected", "info")

    @Slot(str)
    def find_tab_by_url(self, query):
        asyncio.ensure_future(self._find_tab_by_url(query))

    async def _find_tab_by_url(self, query):
        query = (query or "").strip()
        if not query:
            self.log_message.emit("⚠ URL field is empty", "warn")
            self.tab_match_result.emit(query, "[]")
            return
        try:
            tabs = await self._cdp.fetch_tabs()
        except Exception as exc:  # noqa: BLE001
            self.log_message.emit(f"❌ Tab discovery failed: {exc}", "error")
            self.tab_match_result.emit(query, "[]")
            return
        if not tabs:
            self.log_message.emit("⚠ No Chrome tabs found", "warn")
            self.tab_match_result.emit(query, "[]")
            return
        matches = best_matches(query, [t.__dict__ for t in tabs])
        self.tabs_received.emit(json.dumps([{"id": t.id, "title": t.title, "url": t.url, "ws_url": t.ws_url} for t in tabs], ensure_ascii=False))
        self.tab_match_result.emit(query, json.dumps(matches, ensure_ascii=False))
