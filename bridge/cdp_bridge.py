"""CdpBridge — tab connection, discovery, URL-preset matching + bookmarks.

@Slot methods for the connection domain only. The CdpService does the
work and announces outcomes on the EventBus; this bridge forwards them
to the JS signals. The URL bookmark chips also live here (they feed the
connect workflow).
"""

from __future__ import annotations

import asyncio
import json
import logging

from PySide6.QtCore import QObject, Signal, Slot

from core.events import (ConnectionChanged, LogMessage, PresetsChanged,
                         TabsReceived, TabMatchResult)

log = logging.getLogger("chatbot")


class CdpBridge(QObject):
    tabs_received = Signal(str)
    connection_status = Signal(str)
    tab_match_result = Signal(str, str)
    url_presets_updated = Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._publishing = None          # bookmark self-echo guard
        ctx.bus.subscribe(TabsReceived,
                          lambda e: self.tabs_received.emit(e.payload))
        ctx.bus.subscribe(ConnectionChanged,
                          lambda e: self.connection_status.emit(e.status))
        ctx.bus.subscribe(TabMatchResult,
                          lambda e: self.tab_match_result.emit(
                              e.query, e.matches_json))
        # the bookmarks feed the connect workflow
        ctx.bus.subscribe(PresetsChanged, self._on_presets)

    def _on_presets(self, event) -> None:
        if event.kind == "urls":
            if self._publishing and (event.payload or "[]") == self._publishing:
                return                  # our own echo — already announced
            self.url_presets_updated.emit(event.payload or "[]")

    # ── tab discovery / connection ───────────────────────────────
    @Slot(result=str)
    def get_tabs(self):
        self._schedule(self.ctx.cdp_service.fetch_tabs())
        return "pending"

    @Slot(str)
    def connect_tab(self, ws_url):
        self._schedule(self._do_connect(ws_url))

    async def _do_connect(self, ws_url):
        result = await self.ctx.cdp_service.connect(ws_url)
        if result.is_ok and result.value:
            # a fresh explicit connect refills the people list
            from core.events import PeopleChanged
            self.ctx.bus.emit(PeopleChanged(reason="connected"))

    @Slot(str)
    def find_tab_by_url(self, query):
        self._schedule(self.ctx.cdp_service.find_tab_by_url(query))

    @staticmethod
    def _schedule(coro) -> None:
        try:
            asyncio.ensure_future(coro)
        except RuntimeError:
            coro.close()

    # ── URL bookmarks ────────────────────────────────────────────
    @Slot(result=str)
    def get_url_presets(self):
        return json.dumps(self.ctx.config.bookmarks.all(),
                          ensure_ascii=False)

    @Slot(str)
    def add_url_preset(self, url):
        url = (url or "").strip()
        if not url:
            self.ctx.bus.emit(LogMessage(
                message="⚠ URL field is empty — nothing added", level="warn"))
            return
        if self.ctx.config.bookmarks.add(url):
            self.ctx.bus.emit(LogMessage(
                message=f"💾 URL preset added: {url}", level="success"))
        else:
            self.ctx.bus.emit(LogMessage(
                message=f"ℹ URL preset already exists: {url}", level="info"))
        self._emit_bookmarks()

    @Slot(str)
    def remove_url_preset(self, url):
        if self.ctx.config.bookmarks.remove(url):
            self.ctx.bus.emit(LogMessage(
                message=f"🗑 URL preset removed: {url}", level="warn"))
            self.ctx.config.save()
        self._emit_bookmarks()

    def _emit_bookmarks(self) -> None:
        self.ctx.config.save()
        payload = json.dumps(self.ctx.config.bookmarks.all(),
                             ensure_ascii=False)
        self.url_presets_updated.emit(payload)
        # publish for the other listeners WITHOUT re-consuming our own
        # event (the bus is synchronous — a re-entrancy guard suffices)
        self._publishing = payload or "[]"
        try:
            self.ctx.bus.emit(PresetsChanged(kind="urls", payload=payload))
        finally:
            self._publishing = None

    @Slot(str)
    def set_last_url_preset(self, url):
        """Remember which URL preset/bookmark was selected (persisted)."""
        url = (url or "").strip()
        if not url:
            return
        self.ctx.config.set_state(last_url_preset=url)
        self.ctx.bus.emit(LogMessage(message=f"🔖 Bookmark remembered: {url}",
                                     level="info"))
