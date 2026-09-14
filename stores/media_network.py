"""Network-body finisher — extracted from MediaFetcher (H-C4).

One named responsibility: the CDP network-body capture path
(_fetch_via_network, _finish_network_body, _NetworkWatch, _cache_disabled).
Keeps download orchestration in MediaFetcher, moves network capture here.

Design: AREA_C H-C4 — helper named by responsibility, ≤200 LOC.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Optional

log = logging.getLogger("chatbot")


def _response_mime(response: dict) -> str:
    return response.get("mimeType") or (response.get("headers") or {}).get("Content-Type", "")


class _NetworkWatch:
    """CDP network events for one <img> request."""

    EVENTS = (
        ("Network.requestWillBeSent", "on_request"),
        ("Network.responseReceived", "on_response"),
        ("Network.loadingFinished", "on_finished"),
        ("Network.loadingFailed", "on_failed"),
    )

    def __init__(self, fetcher, url: str):
        self.fetcher = fetcher
        self.url = url
        self.fut = asyncio.get_running_loop().create_future()
        self.info: dict = {"request_id": None, "mime": ""}

    @staticmethod
    def clean(value: Optional[str]) -> str:
        return str(value or "").split("#", 1)[0].split("?", 1)[0]

    def matches(self, value: Optional[str]) -> bool:
        return self.clean(value) == self.clean(self.url)

    def attach(self) -> dict:
        cdp = self.fetcher._owner.cdp
        return {event: cdp.on_event(event, getattr(self, handler)) for event, handler in self.EVENTS}

    def detach(self, handles: dict) -> None:
        cdp = self.fetcher._owner.cdp
        for event, handle in handles.items():
            cdp.off_event(event, handle)

    def on_request(self, params) -> None:
        if self.fut.done():
            return
        request = (params or {}).get("request") or {}
        if self.matches(request.get("url")):
            self.info["request_id"] = (params or {}).get("requestId")

    def on_response(self, params) -> None:
        if self.fut.done():
            return
        params = params or {}
        response = params.get("response") or {}
        rid = params.get("requestId")
        if self.matches(response.get("url")):
            self.info["request_id"] = rid or self.info["request_id"]
        if rid and rid == self.info["request_id"]:
            self.info["mime"] = _response_mime(response)

    def on_finished(self, params) -> None:
        if self.fut.done():
            return
        if (params or {}).get("requestId") == self.info["request_id"]:
            self.fetcher._finish_network_body(self.fut, self.info)

    def on_failed(self, params) -> None:
        if self.fut.done():
            return
        if (params or {}).get("requestId") == self.info["request_id"]:
            self.fut.set_result(
                {"ok": False, "error": (params or {}).get("errorText") or "network load failed"}
            )


class NetworkBodyFinisher:
    """Network capture path — takes MediaFetcher at call time."""

    def __init__(self, fetcher):
        self._fetcher = fetcher

    async def _cache_disabled(self, cdp, value: bool) -> None:
        try:
            await cdp.send("Network.setCacheDisabled", {"cacheDisabled": value})
        except Exception:  # noqa: BLE001
            pass

    def _finish_network_body(self, fut: asyncio.Future, info: dict) -> None:
        async def work():
            if fut.done():
                return
            rid = info.get("request_id")
            try:
                raw = await self._fetcher._owner.cdp.send("Network.getResponseBody", {"requestId": rid})
                result = (raw or {}).get("result", {}) or {}
                body = result.get("body") or ""
                if result.get("base64Encoded"):
                    data = base64.b64decode(body)
                    b64 = body
                else:
                    data = body.encode("utf-8")
                    b64 = base64.b64encode(data).decode()
                if not data:
                    fut.set_result({"ok": False, "error": "empty response body"})
                    return
                fut.set_result({"ok": True, "b64": b64, "mime": info.get("mime") or "", "bytes": len(data)})
            except Exception as exc:  # noqa: BLE001
                fut.set_result({"ok": False, "error": f"getResponseBody: {exc}"})

        asyncio.ensure_future(work())

    async def _fetch_via_network(self, url: str) -> dict:
        cdp = self._fetcher._owner.cdp
        if cdp is None or not all(hasattr(cdp, name) for name in ("send", "on_event", "off_event")):
            return {"ok": False, "error": "CDP network capture unavailable"}
        watch = _NetworkWatch(self._fetcher, url)
        handles = watch.attach()
        try:
            await self._cache_disabled(cdp, True)
            js = (
                "(function(){window.__cvbFetchImage=new Image();"
                "window.__cvbFetchImage.src=%s;})()" % json.dumps(url, ensure_ascii=False)
            )
            try:
                await cdp.evaluate(js)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"load trigger failed: {exc}"}
            try:
                return await asyncio.wait_for(watch.fut, timeout=10)
            except asyncio.TimeoutError:
                return {"ok": False, "error": "network capture timed out"}
        finally:
            watch.detach(handles)
            await self._cache_disabled(cdp, False)
