"""Media fetching — extracted from MediaStore (AREA B)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

from backend import chat_agent_js
import aiohttp

log = logging.getLogger("chatbot")

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")

class MediaFetcher:
    """Handles the three-stage fetch (page → python → network capture)."""

    def __init__(self, store):
        self.store = store

    async def _abs_url(self, url: str) -> str:
        text = str(url or "").strip()
        if not text:
            return text
        if text.startswith(("data:", "blob:", "javascript:", "about:")) or "://" in text:
            return text
        cdp = self.store.cdp
        if callable(getattr(cdp, "evaluate", None)):
            try:
                base = await cdp.evaluate("document.baseURI")
                if str(base or "").startswith(("http://", "https://")):
                    return urljoin(str(base), text)
            except Exception:
                pass
        return text

    async def _fetch_one(self, row: dict) -> bool:
        store = self.store
        url = await self._abs_url(row["url"])
        payload = await self._fetch_in_page(url)
        page_ok = bool(payload.get("ok"))
        page_error = (payload.get("error") or "") if not page_ok else ""
        python_error = ""
        if not payload.get("ok"):
            payload = await self._fetch_via_python(url)
            python_error = payload.get("error") or ""
        network_error = ""
        if not payload.get("ok"):
            payload = await self._fetch_via_network(url)
            network_error = payload.get("error") or ""
        if not payload.get("ok"):
            errors = [e for e in (page_error, python_error, network_error) if e and e != "no downloadable media"]
            if not errors:
                errors = [payload.get("error") or "no downloadable media"]
            await store._fail(row["id"], "CORS/page fetch failed: " + " / ".join(dict.fromkeys(errors)))
            return False
        try:
            data = base64.b64decode(payload.get("b64") or "")
        except Exception as e:
            await store._fail(row["id"], f"undecodable payload: {e}")
            return False
        if not data:
            await store._fail(row["id"], "empty payload")
            return False
        if len(data) > store.max_file_bytes:
            await store._skip(row["id"], "too large (%d bytes, cap %d)" % (len(data), store.max_file_bytes))
            return False
        from stores._media_nick import _extension, infer_kind
        digest = hashlib.sha256(data).hexdigest()
        ext = _extension(url, payload.get("mime", ""))
        kind = row.get("kind") or infer_kind(url)
        try:
            path = await store._twin(row.get("owner") or "", digest)
            if not path:
                path = store._target_path(row.get("owner") or "", kind, store._day(row.get("day")), ext)
                with open(path, "wb") as handle:
                    handle.write(data)
        except OSError as e:
            await store._fail(row["id"], f"cannot write cache: {e}")
            return False
        await store.db.execute(
            "UPDATE media SET state='cached', sha256=?, bytes=?, cache_path=?, fail_reason='', last_used=? WHERE id=?",
            (digest, len(data), path, _now(), row["id"]))
        await store.db.commit()
        return True

    async def _fetch_in_page(self, url: str) -> dict:
        try:
            raw = await self.store.cdp.evaluate(chat_agent_js.fetch_media_expression(url))
        except Exception as e:
            return {"ok": False, "error": f"probe error: {e}"}
        payload = raw
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                payload = None
        if not isinstance(payload, dict) or not payload.get("ok"):
            reason = (payload or {}).get("error") if isinstance(payload, dict) else "no answer from the page"
            return {"ok": False, "error": str(reason or "no answer")}
        return payload

    async def _fetch_via_python(self, url: str) -> dict:
        store = self.store
        if callable(store._http_fetcher):
            return await store._http_fetcher(url)
        if store.cdp is None or not hasattr(store.cdp, "get_cookies"):
            return {"ok": False, "error": "no authenticated download available"}
        try:
            cookies = await store.cdp.get_cookies(url)
        except Exception:
            cookies = ""
        parsed = urlparse(str(url or ""))
        referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.netloc else "https://ru.virt-chat.com/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": referer,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        }
        if cookies:
            headers["Cookie"] = cookies
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=timeout, allow_redirects=True) as resp:
                    if resp.status != 200:
                        return {"ok": False, "error": f"HTTP {resp.status}"}
                    data = await resp.read()
                    if len(data) > store.max_file_bytes:
                        return {"ok": False, "error": "too large (%d bytes, cap %d)" % (len(data), store.max_file_bytes)}
                    return {"ok": True, "b64": base64.b64encode(data).decode(), "mime": resp.headers.get("Content-Type", ""), "bytes": len(data)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _fetch_via_network(self, url: str) -> dict:
        store = self.store
        if store.cdp is None or not all(hasattr(store.cdp, name) for name in ("send", "on_event", "off_event")):
            return {"ok": False, "error": "CDP network capture unavailable"}
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        info = {"request_id": None, "mime": ""}
        def clean(value: Optional[str]) -> str:
            return str(value or "").split("#", 1)[0].split("?", 1)[0]
        def matches(value: Optional[str]) -> bool:
            return clean(value) == clean(url)
        def on_request(params) -> None:
            if fut.done():
                return
            request = (params or {}).get("request") or {}
            if matches(request.get("url")):
                info["request_id"] = (params or {}).get("requestId")
        def on_response(params) -> None:
            if fut.done():
                return
            response = (params or {}).get("response") or {}
            rid = (params or {}).get("requestId")
            if matches(response.get("url")):
                info["request_id"] = rid or info["request_id"]
            if rid and rid == info["request_id"]:
                info["mime"] = (response.get("mimeType") or (response.get("headers") or {}).get("Content-Type", ""))
        def on_finished(params) -> None:
            if fut.done():
                return
            if (params or {}).get("requestId") == info["request_id"]:
                self._finish_network_body(fut, info)
        def on_failed(params) -> None:
            if fut.done():
                return
            if (params or {}).get("requestId") == info["request_id"]:
                fut.set_result({"ok": False, "error": (params or {}).get("errorText") or "network load failed"})
        on_req = store.cdp.on_event("Network.requestWillBeSent", on_request)
        on_resp = store.cdp.on_event("Network.responseReceived", on_response)
        cb = store.cdp.on_event("Network.loadingFinished", on_finished)
        on_fail = store.cdp.on_event("Network.loadingFailed", on_failed)
        try:
            try:
                await store.cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
            except Exception:
                pass
            js = "(function(){window.__cvbFetchImage=new Image();window.__cvbFetchImage.src=%s;})()" % json.dumps(url, ensure_ascii=False)
            try:
                await store.cdp.evaluate(js)
            except Exception as e:
                return {"ok": False, "error": f"load trigger failed: {e}"}
            try:
                return await asyncio.wait_for(fut, timeout=10)
            except asyncio.TimeoutError:
                return {"ok": False, "error": "network capture timed out"}
        finally:
            store.cdp.off_event("Network.requestWillBeSent", on_req)
            store.cdp.off_event("Network.responseReceived", on_resp)
            store.cdp.off_event("Network.loadingFinished", cb)
            store.cdp.off_event("Network.loadingFailed", on_fail)
            try:
                await store.cdp.send("Network.setCacheDisabled", {"cacheDisabled": False})
            except Exception:
                pass

    def _finish_network_body(self, fut: asyncio.Future, info: dict) -> None:
        store = self.store
        async def work():
            if fut.done():
                return
            rid = info.get("request_id")
            try:
                raw = await store.cdp.send("Network.getResponseBody", {"requestId": rid})
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
            except Exception as e:
                fut.set_result({"ok": False, "error": f"getResponseBody: {e}"})
        asyncio.ensure_future(work())
