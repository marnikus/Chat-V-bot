"""How to actually get the bytes: three download strategies, tried in order.

Split out of `stores/media_fetch` in round H (H3). `media_fetch` owns the
QUEUE -- what to fetch, when to retry, what state a row is in. This module
owns the orthogonal question of how a single URL becomes bytes, and the
three answers exist because each fails where the next succeeds:

  1. `_fetch_in_page` -- ask the page to fetch it. Fastest, uses the live
     session, but CORS can refuse it.
  2. `_fetch_via_python` -- download from Python with the browser's cookies.
     Works around CORS; some hosts reject the non-browser request.
  3. `_fetch_via_network` -- render the URL in an <img> and read the response
     body back through CDP. The page can display an image even when both of
     the above are blocked, so this saves exactly the bytes the viewport
     shows.

`_NetworkWatch` belongs to strategy 3 and to nothing else: it is the CDP
event subscription that correlates a request id with its response body.

This is a MIXIN rather than a collaborator object because every strategy
reads the queue's state (`self._owner.cdp`, `max_file_bytes`) and returns
into the queue's retry bookkeeping; handing it a back-reference would be the
same coupling with extra indirection.

Imports point one way: `media_fetch` imports this; this imports only
`backend.chat_agent_js`, `stores.media_layout` and the standard library.
"""

from __future__ import annotations

import asyncio
import aiohttp
import base64
import json
import logging
from typing import Optional
from urllib.parse import urlparse

from backend import chat_agent_js

log = logging.getLogger("chatbot")

#: Sent with the Python-side download so the host sees a browser-shaped
#: request; the referer is the chat origin, which some CDNs require.
_FALLBACK_REFERER = "https://ru.virt-chat.com/"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def _response_mime(response: dict) -> str:
    # mimeType first; a CDN redirect sometimes only carries Content-Type.
    return response.get("mimeType") or (response.get("headers") or {}).get("Content-Type", "")
def _download_headers(url: str, cookies: str) -> dict:
    """Browser-like headers for the CORS-free Python download."""
    parsed = urlparse(str(url or ""))
    referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.netloc else _FALLBACK_REFERER
    headers = {"User-Agent": _USER_AGENT, "Referer": referer,
               "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
               "Accept-Language": "en-US,en;q=0.9,ru;q=0.8"}
    if cookies:
        headers["Cookie"] = cookies
    return headers
def _download_errors(payload: dict, errors: list) -> list:
    """The errors worth telling the user about a failed download."""
    useful = [e for e in errors if e and e != "no downloadable media"]
    return useful or [payload.get("error") or "no downloadable media"]

class _NetworkWatch:
    """The CDP network events of the one request an `<img>` triggers.

    `Network.getResponseBody` needs the `requestId` of the request that
    actually carried the bytes, which is not always the one whose URL matches:
    a CORS/CDN redirect keeps the id and changes the address. So the watcher
    remembers the id from the URL match, adopts it from any response on the
    same request, and resolves its future exactly once (`fut.done()` is the
    guard every handler shares).

    `info` is a live dict, not a snapshot: `_finish_network_body` runs as a
    separate task and must see the id and MIME as they stand when it starts.
    """

    EVENTS = (("Network.requestWillBeSent", "on_request"),
              ("Network.responseReceived", "on_response"),
              ("Network.loadingFinished", "on_finished"),
              ("Network.loadingFailed", "on_failed"))

    def __init__(self, fetcher, url: str):
        self.fetcher = fetcher
        self.url = url
        self.fut = asyncio.get_running_loop().create_future()
        self.info: dict = {"request_id": None, "mime": ""}

    @staticmethod
    def clean(value: Optional[str]) -> str:
        """The URL without the query or fragment the site hangs off it."""
        return str(value or "").split("#", 1)[0].split("?", 1)[0]

    def matches(self, value: Optional[str]) -> bool:
        return self.clean(value) == self.clean(self.url)

    def attach(self) -> dict:
        cdp = self.fetcher._owner.cdp
        return {event: cdp.on_event(event, getattr(self, handler))
                for event, handler in self.EVENTS}

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
        # a CORS/CDN redirect can change the visible URL; keep the bytes
        # and the real MIME for any response on the request we started.
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
            self.fut.set_result({"ok": False,
                                 "error": (params or {}).get("errorText")
                                 or "network load failed"})


async def _session_cookies(cdp, url: str) -> str:
    """The browser's cookies for `url` (empty when they cannot be read)."""
    try:
        return await cdp.get_cookies(url)
    except Exception:                                  # noqa: BLE001
        return ""

async def _read_download(resp, cap: int) -> dict:
    """One HTTP response as a download payload (an error dict when unusable)."""
    if resp.status != 200:
        return {"ok": False, "error": f"HTTP {resp.status}"}
    data = await resp.read()
    if len(data) > cap:
        return {"ok": False, "error": "too large (%d bytes, cap %d)" % (len(data), cap)}
    return {"ok": True, "b64": base64.b64encode(data).decode(), "mime": resp.headers.get("Content-Type", ""), "bytes": len(data)}


class MediaDownloadMixin:
    """The three ways to turn one URL into bytes, plus their plumbing."""

    async def _fetch_in_page(self, url: str) -> dict:
        """The original page-origin fetch (works when CORS permits it)."""
        try:
            raw = await self._owner.cdp.evaluate(
                chat_agent_js.fetch_media_expression(url))
        except Exception as e:                        # noqa: BLE001
            return {"ok": False, "error": f"probe error: {e}"}
        payload = raw
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                payload = None
        if not isinstance(payload, dict) or not payload.get("ok"):
            reason = (payload or {}).get("error") if isinstance(payload, dict) \
                else "no answer from the page"
            return {"ok": False, "error": str(reason or "no answer")}
        return payload
    async def _fetch_via_python(self, url: str) -> dict:
        """Download with the browser session cookies (CORS-free fallback)."""
        if callable(self._owner._http_fetcher):
            return await self._owner._http_fetcher(url)
        if self._owner.cdp is None or not hasattr(self._owner.cdp, "get_cookies"):
            return {"ok": False, "error": "no authenticated download available"}
        cookies = await _session_cookies(self._owner.cdp, url)
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession() as session:
                async with session.get(url,
                                       headers=_download_headers(url, cookies),
                                       timeout=timeout,
                                       allow_redirects=True) as resp:
                    return await _read_download(resp,
                                                self._owner.max_file_bytes)
        except Exception as e:                        # noqa: BLE001
            return {"ok": False, "error": str(e)}
    async def _fetch_via_network(self, url: str) -> dict:
        """Grab the response bytes through the browser's normal <img> path.

        The page can render an image even when `fetch()` is CORS-blocked and
        a plain Python download is rejected by the host.  CDP lets us watch
        the real network request made by an `<img>` element and read its
        response body, so we save exactly the bytes the viewport shows.
        """
        cdp = self._owner.cdp
        if cdp is None or not all(hasattr(cdp, name) for name in
                                  ("send", "on_event", "off_event")):
            return {"ok": False, "error": "CDP network capture unavailable"}
        watch = _NetworkWatch(self, url)
        handles = watch.attach()
        try:
            await self._cache_disabled(cdp, True)
            js = ("(function(){window.__cvbFetchImage=new Image();"
                  "window.__cvbFetchImage.src=%s;})()"
                  % json.dumps(url, ensure_ascii=False))
            try:
                await cdp.evaluate(js)
            except Exception as e:                    # noqa: BLE001
                return {"ok": False, "error": f"load trigger failed: {e}"}
            try:
                return await asyncio.wait_for(watch.fut, timeout=10)
            except asyncio.TimeoutError:
                return {"ok": False, "error": "network capture timed out"}
        finally:
            watch.detach(handles)
            await self._cache_disabled(cdp, False)
    @staticmethod
    async def _cache_disabled(cdp, value: bool) -> None:
        """`Network.setCacheDisabled`, best effort both ways.

        The load has to miss the browser cache or there is no in-flight
        request for `getResponseBody` to read.
        """
        try:
            await cdp.send("Network.setCacheDisabled", {"cacheDisabled": value})
        except Exception:                            # noqa: BLE001
            pass
    def _finish_network_body(self, fut: asyncio.Future, info: dict) -> None:
        async def work():
            if fut.done():
                return
            rid = info.get("request_id")
            try:
                raw = await self._owner.cdp.send("Network.getResponseBody",
                                          {"requestId": rid})
                result = (raw or {}).get("result", {}) or {}
                body = result.get("body") or ""
                if result.get("base64Encoded"):
                    data = base64.b64decode(body)
                    b64 = body
                else:
                    data = body.encode("utf-8")
                    b64 = base64.b64encode(data).decode()
                if not data:
                    fut.set_result({"ok": False,
                                    "error": "empty response body"})
                    return
                fut.set_result({"ok": True, "b64": b64,
                                "mime": info.get("mime") or "",
                                "bytes": len(data)})
            except Exception as e:                    # noqa: BLE001
                fut.set_result({"ok": False,
                                "error": f"getResponseBody: {e}"})
        asyncio.ensure_future(work())
