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

import base64
import json
import logging
import os
from urllib.parse import urljoin

from backend import chat_agent_js
from stores.media_layout import _now

log = logging.getLogger("chatbot")

from stores.media_network import NetworkFetchMixin  # noqa: E402


class MediaFetcher(NetworkFetchMixin):
    """Decide what media is pending and where a recovered body lands."""

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
