"""HTTP and in-page fetch tiers — extracted from media_fetch (H-C5 MI lift).

Part of the media fetcher family: `media_fetch.py` (orchestration),
`media_network.py` (CDP Network body), this file (in-page + Python HTTP).

Design: RULE 19 step 3 — named predicates for every gate, ≤150 LOC.
"""

from __future__ import annotations

import base64
import json
import logging
from urllib.parse import urlparse

import aiohttp

from backend import chat_agent_js

log = logging.getLogger("chatbot")

_FALLBACK_REFERER = "https://ru.virt-chat.com/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _is_payload_ok(payload: dict) -> bool:
    return bool(payload.get("ok"))


def _has_http_fetcher(owner) -> bool:
    return callable(owner._http_fetcher)


def _has_cdp_cookies(cdp) -> bool:
    return cdp is not None and hasattr(cdp, "get_cookies")


def _is_too_large(size: int, cap: int) -> bool:
    return size > cap


async def _session_cookies(cdp, url: str) -> str:
    try:
        return await cdp.get_cookies(url)
    except Exception:  # noqa: BLE001
        return ""


def _download_headers(url: str, cookies: str) -> dict:
    parsed = urlparse(str(url or ""))
    referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.netloc else _FALLBACK_REFERER
    headers = {
        "User-Agent": _USER_AGENT,
        "Referer": referer,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    }
    if cookies:
        headers["Cookie"] = cookies
    return headers


async def _read_download(resp, cap: int) -> dict:
    if resp.status != 200:
        return {"ok": False, "error": f"HTTP {resp.status}"}
    data = await resp.read()
    if _is_too_large(len(data), cap):
        return {"ok": False, "error": "too large (%d bytes, cap %d)" % (len(data), cap)}
    return {
        "ok": True,
        "b64": base64.b64encode(data).decode(),
        "mime": resp.headers.get("Content-Type", ""),
        "bytes": len(data),
    }


class MediaFetchHttp:
    """In-page and Python HTTP tiers."""

    def __init__(self, owner):
        self._owner = owner

    async def fetch_in_page(self, url: str) -> dict:
        try:
            raw = await self._owner.cdp.evaluate(chat_agent_js.fetch_media_expression(url))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"probe error: {exc}"}
        payload = raw
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                payload = None
        if not isinstance(payload, dict) or not _is_payload_ok(payload):
            reason = (payload or {}).get("error") if isinstance(payload, dict) else "no answer from the page"
            return {"ok": False, "error": str(reason or "no answer")}
        return payload

    async def fetch_via_python(self, url: str) -> dict:
        if _has_http_fetcher(self._owner):
            return await self._owner._http_fetcher(url)
        if not _has_cdp_cookies(self._owner.cdp):
            return {"ok": False, "error": "no authenticated download available"}
        cookies = await _session_cookies(self._owner.cdp, url)
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=_download_headers(url, cookies), timeout=timeout, allow_redirects=True
                ) as resp:
                    return await _read_download(resp, self._owner.max_file_bytes)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
