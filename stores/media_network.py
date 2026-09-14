"""The network half of media fetching (Round H step H-C4).

`MediaFetcher` decides what is pending and where a body lands; this mixin is
the path it takes when the body has to come over the network instead of out of
the page: try the in-page fetch, fall back to a direct download, finish the
body into the cache, and classify what went wrong.

Split out of `stores/media_fetch.py`, with the raw download helpers in
`stores/media_download.py`. `MediaFetcher` keeps `process_pending`,
`retry_failed`, `requeue` and the URL helpers; both are inherited, so
`MediaStore`'s delegators are unchanged.

Import direction: `stores.media_download` for the wire helpers,
`stores.media_layout` for the cache-path rules; nothing imports back.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging

import aiohttp

from stores.media_download import _NetworkWatch, _download_errors, _download_headers, _read_download, _session_cookies
from stores.media_layout import _extension, _now, infer_kind

log = logging.getLogger("chatbot")


class NetworkFetchMixin:
    """In-page fetch, direct download, finishing the body; on ``MediaFetcher``."""

    async def _download(self, url: str) -> tuple[dict, list]:
        """The three tiers in order, plus the errors worth telling the user.

        "no downloadable media" is noise when a later tier also failed for a
        real reason, so it only survives as the report when nothing else was
        said at all.
        """
        payload = await self._fetch_in_page(url)
        errors: list = ([] if payload.get("ok")
                        else [payload.get("error") or ""])
        for step in (self._fetch_via_python, self._fetch_via_network):
            if payload.get("ok"):
                break
            payload = await step(url)
            if not payload.get("ok"):
                errors.append(payload.get("error") or "")
        if payload.get("ok"):
            return payload, []
        return payload, _download_errors(payload, errors)

    async def _file_bytes(self, row: dict, url: str, data: bytes,
                          payload: dict) -> bool:
        """Write the bytes into the person's folder and stamp the row cached."""
        digest = hashlib.sha256(data).hexdigest()
        ext = _extension(url, payload.get("mime", ""))
        kind = row.get("kind") or infer_kind(url)
        try:
            # identical bytes already filed for this person ⇒ reuse the file
            path = await self._owner._twin(row.get("owner") or "", digest)
            if not path:
                path = self._owner._target_path(row.get("owner") or "", kind,
                                                self._owner._day(row.get("day")),
                                                ext)
                with open(path, "wb") as handle:
                    handle.write(data)
        except OSError as e:
            await self._owner._fail(row["id"], f"cannot write cache: {e}")
            return False
        await self._owner.db.execute(
            "UPDATE media SET state='cached', sha256=?, bytes=?, "
            "cache_path=?, fail_reason='', last_used=? WHERE id=?",
            (digest, len(data), path, _now(), row["id"]))
        await self._owner.db.commit()
        return True

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
