"""The three-tier byte fetcher behind the media cache.

The download half of `stores/media_store.py`. Bytes are tried in order: an
in-page `fetch()` (the page owns the session cookies), a cookied Python
download, and finally the response body of the request the browser already
made for the visible `<img>` (CDP `Network.getResponseBody`). Everything is
best-effort — a dead URL or a CORS block leaves a `failed` row, never an
exception in the UI.

The switches and caps (`enabled`, `paused`, `cdp`, `max_file_bytes`) are read
off the `MediaStore` at call time: that is what lets a backfill pause the
queue between two rows, and what lets a retry succeed after the cap was
raised.
"""

from __future__ import annotations

import asyncio
import aiohttp
import base64
import hashlib
import json
import logging
import os
from typing import Optional
from urllib.parse import urljoin, urlparse

from core import chat_agent_js
from stores.media_layout import _extension, _now, infer_kind

log = logging.getLogger("chatbot")


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
        response = (params or {}).get("response") or {}
        rid = (params or {}).get("requestId")
        if self.matches(response.get("url")):
            self.info["request_id"] = rid or self.info["request_id"]
        # a CORS/CDN redirect can change the visible URL; keep the bytes
        # and the real MIME for any response on the request we started.
        if rid and rid == self.info["request_id"]:
            self.info["mime"] = (response.get("mimeType")
                                 or (response.get("headers") or {})
                                 .get("Content-Type", ""))

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


class MediaFetcher:
    """The three-tier byte fetcher behind the media cache."""

    def __init__(self, owner):
        """`owner` is the `MediaStore` this part borrows state from."""
        self._owner = owner

    async def process_pending(self, limit: int = 25) -> int:
        """Cache up to `limit` pending files. Returns how many were stored."""
        if not self._owner.enabled or self._owner.paused or self._owner.cdp is None:
            return 0
        limit = int(limit)
        if limit <= 0:
            return 0
        rows = await self._owner.db.fetchdicts(
            "SELECT id, url, kind, owner, day FROM media WHERE "
            "state='pending' ORDER BY id LIMIT ?", (limit,))
        stored = 0
        for row in rows:
            if not self._owner.enabled or self._owner.paused:
                break
            if await self._fetch_one(row):
                stored += 1
        return stored

    async def _abs_url(self, url: str) -> str:
        """Resolve a relative/`//` image URL against the live page address.

        The chat page may keep the real address in `data-src` or hand the
        collector a path like `m_Питер2к7_7a861….jpg` instead of a full URL.
        The `<img>` element resolves it against the page, so Python has to do
        the same or every download gets a bogus relative path.
        """
        text = str(url or "").strip()
        if not text:
            return text
        if text.startswith(("data:", "blob:", "javascript:", "about:")) \
                or "://" in text:
            return text
        if callable(getattr(self._owner.cdp, "evaluate", None)):
            try:
                # document.baseURI follows the page's <base href> — the chat
                # can keep its CDN in <base> so the visible <img> works while
                # location.href alone would resolve the path to the wrong host.
                base = await self._owner.cdp.evaluate("document.baseURI")
                if str(base or "").startswith(("http://", "https://")):
                    return urljoin(str(base), text)
            except Exception:                    # noqa: BLE001
                pass
        return text

    async def _fetch_one(self, row: dict) -> bool:
        """Cache one media row.

        The in-page fetch is tried first (fastest). When the image host has no
        CORS headers the page fetch fails — the fallback downloads from Python
        with the browser's cookies instead, which is exactly the case the bug
        report showed.  The last resort reads the bytes out of the network
        request the browser itself already made for the visible `<img>`.
        """
        url = await self._abs_url(row["url"])
        payload, errors = await self._download(url)
        if not payload.get("ok"):
            reason = "CORS/page fetch failed: " + " / ".join(
                dict.fromkeys(errors))
            await self._owner._fail(row["id"], reason)
            return False
        try:
            data = base64.b64decode(payload.get("b64") or "")
        except Exception as e:                        # noqa: BLE001
            await self._owner._fail(row["id"], f"undecodable payload: {e}")
            return False
        if not data:
            await self._owner._fail(row["id"], "empty payload")
            return False
        if len(data) > self._owner.max_file_bytes:
            await self._owner._skip(row["id"], "too large (%d bytes, cap %d)"
                                    % (len(data), self._owner.max_file_bytes))
            return False
        return await self._file_bytes(row, url, data, payload)

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
        useful = [e for e in errors if e and e != "no downloadable media"]
        return payload, useful or [payload.get("error")
                                   or "no downloadable media"]

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
        try:
            cookies = await self._owner.cdp.get_cookies(url)
        except Exception:                               # noqa: BLE001
            cookies = ""
        parsed = urlparse(str(url or ""))
        referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.netloc \
            else "https://ru.virt-chat.com/"
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/131.0.0.0 Safari/537.36"),
            "Referer": referer,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        }
        if cookies:
            headers["Cookie"] = cookies
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers,
                                       timeout=timeout,
                                       allow_redirects=True) as resp:
                    if resp.status != 200:
                        return {"ok": False,
                                "error": f"HTTP {resp.status}"}
                    data = await resp.read()
                    if len(data) > self._owner.max_file_bytes:
                        return {"ok": False,
                                "error": "too large (%d bytes, cap %d)"
                                         % (len(data), self._owner.max_file_bytes)}
                    return {"ok": True,
                            "b64": base64.b64encode(data).decode(),
                            "mime": resp.headers.get("Content-Type", ""),
                            "bytes": len(data)}
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

    async def retry_failed(self) -> int:
        """Explicitly give up-front failures another chance (user action)."""
        cur = await self._owner.db.execute(
            "UPDATE media SET state='pending', fail_reason='', "
            "recovered_at=?, recovery_attempts=recovery_attempts+1 "
            "WHERE state IN ('failed','skipped')",
            (_now(),))
        await self._owner.db.commit()
        return int(cur.rowcount or 0)

    async def requeue(self, media_id, reason: str = "retry") -> bool:
        """Re-queue one failed/skipped media row for another download.

        Used by backfill recovery. The row is stamped so the UI/DB can prove
        it was recovered (or tried again) and so a single backfill never
        loops over the same URL endlessly.
        """
        row = await self._owner.get(media_id)
        if not row or not row.get("url"):
            return False
        if row.get("state") not in ("failed", "skipped"):
            return False
        await self._owner.db.execute(
            "UPDATE media SET state='pending', fail_reason='', "
            "recovered_at=?, recovery_attempts=recovery_attempts+1, "
            "last_used=? WHERE id=?",
            (_now(), _now(), self._owner._as_id(media_id)))
        await self._owner.db.commit()
        return True

    async def download_one(self, media_id) -> dict:
        """Force a single media row through the downloader and return its state.

        Used by the "click to restore" marker in the History window.  A row
        that is already cached and whose file still exists is returned as-is;
        anything failed, skipped, pending or whose saved file is gone is
        re-queued and downloaded once right here.
        """
        row = await self._owner.get(media_id)
        if not row:
            return {"state": "missing", "id": media_id, "path": "", "url": ""}
        if not self._owner.enabled or self._owner.paused or self._owner.cdp is None:
            return await self._owner.path_for(media_id)
        path = row.get("cache_path") or ""
        if row.get("state") == "cached" and path and os.path.exists(path):
            return await self._owner.path_for(media_id)
        await self._owner.db.execute(
            "UPDATE media SET state='pending', fail_reason='', "
            "recovered_at=?, recovery_attempts=recovery_attempts+1, "
            "last_used=? WHERE id=?",
            (_now(), _now(), self._owner._as_id(media_id)))
        await self._owner.db.commit()
        row = await self._owner.get(media_id)
        if row:
            await self._fetch_one(row)
        return await self._owner.path_for(media_id)

    async def retry_failed_uncached(self) -> int:
        """Re-queue failed rows that have no local file.

        This is the one-time startup repair for the CORS download regression:
        rows that were marked failed by the old page-only fetch get a chance
        with the Python/cookie downloader.
        """
        cur = await self._owner.db.execute(
            "UPDATE media SET state='pending', fail_reason='', "
            "recovered_at=?, recovery_attempts=recovery_attempts+1 "
            "WHERE state='failed' AND (cache_path='' OR cache_path IS NULL)",
            (_now(),))
        await self._owner.db.commit()
        return int(cur.rowcount or 0)
