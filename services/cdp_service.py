"""CdpService — tab discovery, connection and URL matching.

Extracted from the bridge monolith (2026-09-09). Wraps the CDP protocol
client (backend/cdp_client.py — infrastructure) with the app's connection
rules. Returns ``Result``; outcomes are announced on the EventBus
(TabsReceived, ConnectionChanged, LogMessage) for the CdpBridge to
forward to JS signals.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from core.events import (EventBus, ConnectionChanged,
                         TabsReceived, TabMatchResult)
from core.result import Err, Ok, Result
from services.service_log import emit_log

from backend.tab_matcher import best_matches

log = logging.getLogger("chatbot")

KIND_NAMES = {"url_exact": "exact URL", "url_path": "URL path",
              "host": "host", "keyword": "keyword"}


def _no_match_line(query: str, tabs) -> str:
    """The "nothing matched" log line, listing the first five open tabs.

    The list is what makes the failure actionable -- the user needs to see
    what WAS open to understand why their preset missed -- and it is capped
    at five with an ellipsis so a browser with thirty tabs cannot flood the
    run panel.
    """
    shown = "; ".join(f"{t.title} — {t.url}" for t in tabs[:5])
    more = "…" if len(tabs) > 5 else ""
    return f"❌ No open tab matches “{query}”. Available: {shown}{more}"


class CdpService:
    """Tab fetch / connect / URL-preset matching."""

    def __init__(self, cdp, bus: EventBus | None = None):
        self._cdp = cdp
        self._bus = bus or EventBus()

    def attach(self, cdp=None, bus=None) -> None:
        if cdp is not None:
            self._cdp = cdp
        if bus is not None:
            self._bus = bus

    def _log(self, message: str, level: str = "info") -> None:
        emit_log(self._bus, message, level)

    def install_status_forwarding(self) -> None:
        """Re-emit the client's Qt connection signals as bus events."""
        cdp = self._cdp
        if cdp is None:
            return
        try:
            cdp.connected.connect(
                lambda: self._bus.emit(ConnectionChanged(status="connected")))
            cdp.disconnected.connect(
                lambda: self._bus.emit(ConnectionChanged(status="disconnected")))
            cdp.error.connect(
                lambda _e: self._bus.emit(ConnectionChanged(status="error")))
        except Exception as exc:                        # noqa: BLE001
            log.debug("cdp status forwarding not installed: %s", exc)

    # ── tabs ─────────────────────────────────────────────────────
    async def fetch_tabs(self) -> Result[list]:
        try:
            tabs = await self._cdp.fetch_tabs()
            payload = json.dumps(
                [{"id": t.id, "title": t.title, "url": t.url,
                  "ws_url": t.ws_url} for t in tabs], ensure_ascii=False)
        except Exception as exc:                        # noqa: BLE001
            log.error("Tab fetch failed: %s", exc)
            self._log(f"❌ Tab discovery failed: {exc}", "error")
            return Err("tab_fetch_failed", str(exc))
        self._bus.emit(TabsReceived(payload=payload))
        return Ok(tabs)

    async def connect(self, ws_url: str) -> Result[bool]:
        try:
            ok = await self._cdp.connect(ws_url)
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Connect failed: {exc}", "error")
            return Err("connect_failed", str(exc))
        if ok:
            self._log("🔗 Connected", "info")
        return Ok(ok)

    async def find_tab_by_url(self, query: str) -> Result[list]:
        """Match a URL/keyword against the open tabs (URL presets)."""
        query = (query or "").strip()
        if not query:
            self._log("⚠ URL field is empty — enter a URL or keyword", "warn")
            self._bus.emit(TabMatchResult(query=query, matches_json="[]"))
            return Err("empty_query", "the URL field is empty")
        self._log(f"🔍 URL preset: parsing “{query}” against open tabs…",
                  "info")
        tabs_result = await self.fetch_tabs()
        if tabs_result.is_err:
            self._bus.emit(TabMatchResult(query=query, matches_json="[]"))
            return tabs_result
        tabs = tabs_result.value
        if not tabs:
            self._log(
                "⚠ No Chrome tabs found — start Chrome with "
                "--remote-debugging-port=9222 "
                "--user-data-dir=\"C:\\chatflow-chrome\" (see README §2)",
                "warn")
            self._bus.emit(TabMatchResult(query=query, matches_json="[]"))
            return Ok([])
        matches = best_matches(query, [t.__dict__ for t in tabs])
        if not matches:
            self._log(_no_match_line(query, tabs), "error")
            self._bus.emit(TabMatchResult(query=query, matches_json="[]"))
            return Ok([])
        for m in matches[:3]:
            self._log(
                f"  · match ({KIND_NAMES.get(m['kind'], m['kind'])}): "
                f"{m['title']} — {m['url']}", "success")
        self._bus.emit(TabMatchResult(
            query=query,
            matches_json=json.dumps(matches, ensure_ascii=False)))
        return Ok(matches)
