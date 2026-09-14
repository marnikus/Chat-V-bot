"""The raw network download of a media body (Round H step H-C4).

One named concept: getting bytes over HTTP when the in-page fetch cannot —
the CDP request/response watcher that recognises the download, the cookie and
header assembly, the body read and the error text. None of it knows about the
media cache or the archive; it answers "fetch this URL, give me bytes".

Split out of `stores/media_fetch.py` (464 lines, MI 31.5 — the densest file in
Area C) so that file is about *deciding* what to fetch and where to put it,
and this one is about the wire.

Import direction: no Qt and no `services/` import here; the CDP and aiohttp
sessions are passed in by the caller.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Optional
from urllib.parse import urlparse



log = logging.getLogger("chatbot")

#: The Referer has to look like the site's own origin or the CDN answers 403;
#: with no parseable netloc this pinned production origin is used instead.
_FALLBACK_REFERER = "https://ru.virt-chat.com/"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


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


def _response_mime(response: dict) -> str:
    # mimeType first; a CDN redirect sometimes only carries Content-Type.
    return response.get("mimeType") or (response.get("headers") or {}).get("Content-Type", "")


async def _session_cookies(cdp, url: str) -> str:
    """The browser's cookies for `url` (empty when they cannot be read)."""
    try:
        return await cdp.get_cookies(url)
    except Exception:                                  # noqa: BLE001
        return ""


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


async def _read_download(resp, cap: int) -> dict:
    """One HTTP response as a download payload (an error dict when unusable)."""
    if resp.status != 200:
        return {"ok": False, "error": f"HTTP {resp.status}"}
    data = await resp.read()
    if len(data) > cap:
        return {"ok": False, "error": "too large (%d bytes, cap %d)" % (len(data), cap)}
    return {"ok": True, "b64": base64.b64encode(data).decode(), "mime": resp.headers.get("Content-Type", ""), "bytes": len(data)}


def _download_errors(payload: dict, errors: list) -> list:
    """The errors worth telling the user about a failed download."""
    useful = [e for e in errors if e and e != "no downloadable media"]
    return useful or [payload.get("error") or "no downloadable media"]
