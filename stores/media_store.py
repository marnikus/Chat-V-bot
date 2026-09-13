"""Hybrid media storage for the archive.

Decision D-1: the database keeps the URL plus a hash; the BYTES live on disk
under a size cap. Previews then survive the site expiring an image, without
turning history.db into a multi-gigabyte blob store.

Bytes are fetched by an in-page `fetch()` (the page owns the session cookies)
and travel back as base64 through one CDP evaluate. When that host blocks
CORS the store falls back to a cookied Python download, then to reading the
network response body of the request the browser itself already made for the
visible `<img>` (CDP `Network.getResponseBody`). Everything here is
best-effort: a missing file, a dead URL or a disabled cache degrades to
"show the link", never to an exception in the UI.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

from stores.history_db import HistoryDB
from stores.media_cache import MediaCachePolicy
from stores.media_fetch import MediaFetcher
from stores.media_layout import MediaLayout
from stores.media_layout import (                     # noqa: F401
    IMAGE_EXT,
    MIME_EXT,
    RESERVED,
    SAFE_CHARS,
    TRANSLIT,
    _now,
    infer_kind,
    slugify_nick,
)

log = logging.getLogger("chatbot")

#: the surface `stores/media_store.py` promised before B2 split it, kept
#: importable from here (`backend/media_store.py` and three test modules
#: import `slugify_nick` from this name) — see `tools/metrics/stores_api.py`
__all__ = ["MediaStore", "slugify_nick", "infer_kind", "IMAGE_EXT",
           "MIME_EXT", "TRANSLIT", "SAFE_CHARS", "RESERVED"]


class MediaStore:
    """URL registry + on-disk byte cache for images and GIFs."""

    def __init__(self, db: HistoryDB, cdp=None, cache_dir: str = "saved_media",
                 max_file_mb: float = 25, max_cache_mb: float = 10,
                 enabled: bool = True):
        self.db = db
        self.cdp = cdp
        self.cache_dir = cache_dir
        self.now = datetime.now
        self.max_file_bytes = int(float(max_file_mb) * 1024 * 1024)
        self.max_cache_bytes = int(float(max_cache_mb) * 1024 * 1024)
        self.enabled = bool(enabled)
        self.paused = False
        self._dirs: dict[str, str] = {}      # nick → person folder
        self._http_fetcher = None            # test hook for the Python downloader
        # the B2 split (design §2.2): three parts, no state of their own —
        # each one reads `db` / `cdp` / `cache_dir` / the caps back off this
        # object at call time, which is why a backfill can pause the queue
        # between two rows and why `media.cache_dir = …` still redirects
        # every write that follows
        self.layout = MediaLayout(self)
        self.fetcher = MediaFetcher(self)
        self.policy = MediaCachePolicy(self)

    # ── the readable tree on disk ────────────────────────────────
    NICK_MARKER = "_nick.txt"

    def folder_for(self, nick: str, kind: str='') -> str:
        """See `MediaLayout.folder_for` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return self.layout.folder_for(nick, kind)

    def _person_dir(self, nick: str) -> str:
        """See `MediaLayout._person_dir` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return self.layout._person_dir(nick)

    def _marker(self, folder: str) -> str:
        """See `MediaLayout._marker` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return self.layout._marker(folder)

    def _write_marker(self, folder: str, nick: str) -> None:
        """See `MediaLayout._write_marker` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        self.layout._write_marker(folder, nick)

    def _free_name(self, folder: str, day: str, ext: str) -> str:
        """See `MediaLayout._free_name` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return self.layout._free_name(folder, day, ext)

    def _target_path(self, nick: str, kind: str, day: str, ext: str) -> str:
        """See `MediaLayout._target_path` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return self.layout._target_path(nick, kind, day, ext)

    def _day(self, value=None) -> str:
        """See `MediaLayout._day` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return self.layout._day(value)

    # ── registration ─────────────────────────────────────────────
    async def register(self, url: str, kind: Optional[str] = None,
                       nick: str = "", day: str = "") -> Optional[int]:
        """Remember a media URL. Returns its id (existing rows are reused).

        `nick` is the conversation the file belongs to — it decides which
        person folder the bytes land in.
        """
        clean = str(url or "").strip()
        if not clean:
            return None
        resolved = (kind or "").strip() or infer_kind(clean)
        if resolved not in ("image", "gif"):
            resolved = infer_kind(clean)
        owner = " ".join(str(nick or "").split())
        await self.db.execute(
            "INSERT INTO media(url, kind, state, owner, day, ref_count, "
            "created_at, last_used) VALUES(?,?,'pending',?,?,1,?,?) "
            "ON CONFLICT(url) DO UPDATE SET ref_count=ref_count+1, "
            "owner=CASE WHEN media.owner='' THEN excluded.owner "
            "ELSE media.owner END, "
            "day=CASE WHEN media.day='' THEN excluded.day "
            "ELSE media.day END, "
            "last_used=excluded.last_used",
            (clean, resolved, owner, self._day(day) if day else "",
             _now(), _now()))
        await self.db.commit()
        row = await self.db.fetchone("SELECT id FROM media WHERE url=?",
                                     (clean,))
        return int(row[0]) if row else None

    async def get(self, media_id) -> Optional[dict]:
        row = await self.db.fetchone("SELECT * FROM media WHERE id=?",
                                     (self._as_id(media_id),))
        return dict(row) if row else None

    async def get_by_url(self, url: str) -> Optional[dict]:
        row = await self.db.fetchone("SELECT * FROM media WHERE url=?",
                                     (str(url or "").strip(),))
        return dict(row) if row else None

    @staticmethod
    def _as_id(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    # ── downloading ──────────────────────────────────────────────
    async def process_pending(self, limit: int=25) -> int:
        """See `MediaFetcher.process_pending` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return await self.fetcher.process_pending(limit)

    async def _abs_url(self, url: str) -> str:
        """See `MediaFetcher._abs_url` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return await self.fetcher._abs_url(url)

    async def _fetch_one(self, row: dict) -> bool:
        """See `MediaFetcher._fetch_one` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return await self.fetcher._fetch_one(row)

    async def _fetch_in_page(self, url: str) -> dict:
        """See `MediaFetcher._fetch_in_page` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return await self.fetcher._fetch_in_page(url)

    async def _fetch_via_python(self, url: str) -> dict:
        """See `MediaFetcher._fetch_via_python` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return await self.fetcher._fetch_via_python(url)

    async def _fetch_via_network(self, url: str) -> dict:
        """See `MediaFetcher._fetch_via_network` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return await self.fetcher._fetch_via_network(url)

    def _finish_network_body(self, fut: asyncio.Future, info: dict) -> None:
        """See `MediaFetcher._finish_network_body` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        self.fetcher._finish_network_body(fut, info)

    async def _twin(self, owner: str, digest: str) -> str:
        """See `MediaCachePolicy._twin` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return await self.policy._twin(owner, digest)

    async def migrate_layout(self) -> int:
        """See `MediaCachePolicy.migrate_layout` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return await self.policy.migrate_layout()

    async def _fail(self, media_id: int, reason: str) -> None:
        await self.db.execute(
            "UPDATE media SET state='failed', fail_reason=? WHERE id=?",
            (reason[:300], media_id))
        await self.db.commit()

    async def _skip(self, media_id: int, reason: str) -> None:
        await self.db.execute(
            "UPDATE media SET state='skipped', fail_reason=? WHERE id=?",
            (reason[:300], media_id))
        await self.db.commit()

    async def retry_failed(self) -> int:
        """See `MediaFetcher.retry_failed` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return await self.fetcher.retry_failed()

    async def requeue(self, media_id, reason: str='retry') -> bool:
        """See `MediaFetcher.requeue` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return await self.fetcher.requeue(media_id, reason)

    async def download_one(self, media_id) -> dict:
        """See `MediaFetcher.download_one` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return await self.fetcher.download_one(media_id)

    async def retry_failed_uncached(self) -> int:
        """See `MediaFetcher.retry_failed_uncached` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return await self.fetcher.retry_failed_uncached()

    # ── serving ──────────────────────────────────────────────────
    async def path_for(self, media_id) -> dict:
        row = await self.get(media_id)
        if not row:
            return {"state": "missing", "path": "", "url": ""}
        path = row.get("cache_path") or ""
        usable = row.get("state") == "cached" and path and os.path.exists(path)
        if usable:
            await self.db.execute("UPDATE media SET last_used=? WHERE id=?",
                                  (_now(), row["id"]))
            await self.db.commit()
        return {"state": row.get("state"), "path": path if usable else "",
                "url": row.get("url") or "", "kind": row.get("kind") or "image",
                "bytes": int(row.get("bytes") or 0)}

    async def clipboard_payload(self, media_id) -> dict:
        """What the UI should put on the clipboard for a left click."""
        row = await self.get(media_id)
        if not row:
            return {"ok": False, "mode": "", "path": "", "text": "",
                    "url": "", "error": f"media {media_id} not found"}
        info = await self.path_for(row["id"])
        url = row.get("url") or ""
        if info["path"]:
            mode = "file_link" if row.get("kind") == "gif" else "image"
            return {"ok": True, "mode": mode, "path": info["path"],
                    "text": url, "url": url, "error": ""}
        return {"ok": True, "mode": "link", "path": "", "text": url,
                "url": url, "error": ""}

    # ── housekeeping ─────────────────────────────────────────────
    async def cache_usage(self) -> dict:
        """See `MediaCachePolicy.cache_usage` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return await self.policy.cache_usage()

    async def evict_if_needed(self) -> int:
        """See `MediaCachePolicy.evict_if_needed` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return await self.policy.evict_if_needed()

    async def _evict(self, media_id: int) -> None:
        """See `MediaCachePolicy._evict` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        await self.policy._evict(media_id)

    async def clear_cache(self) -> int:
        """See `MediaCachePolicy.clear_cache` — the name stays on the facade, which is what `services/`, the bridges and the media tests call (design §2.2)."""
        return await self.policy.clear_cache()
