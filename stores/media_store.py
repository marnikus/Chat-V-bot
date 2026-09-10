"""Hybrid media storage for the archive — facade (AREA B).

Decision D-1: the database keeps the URL plus a hash; the BYTES live on disk
under a size cap. Previews then survive the site expiring an image, without
turning history.db into a multi-gigabyte blob store.

Bytes are fetched by an in-page `fetch()` and travel back as base64. When that
host blocks CORS the store falls back to Python download / CDP Network.
Everything is best-effort: missing file / dead URL degrades to "show the link".

This facade keeps the public API byte-identical; the heavy lifting lives in
``_media_nick``, ``_media_fetch`` and ``_media_cache`` (AREA B split).
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from stores.history_db import HistoryDB
from stores._media_nick import slugify_nick, infer_kind, _extension
from stores._media_fetch import MediaFetcher
from stores._media_cache import MediaCachePolicy

log = logging.getLogger("chatbot")

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")

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
        self._dirs: dict[str, str] = {}
        self._http_fetcher = None
        self._fetcher = MediaFetcher(self)
        self._cache = MediaCachePolicy(self)

    NICK_MARKER = "_nick.txt"

    def folder_for(self, nick: str, kind: str = "") -> str:
        parts = [self._person_dir(nick)]
        if kind:
            parts.append("gifs" if kind == "gif" else "images")
        return os.path.join(*parts)

    def _person_dir(self, nick: str) -> str:
        key = " ".join(str(nick or "").split())
        cached = self._dirs.get(key)
        if cached:
            return cached
        root = os.path.abspath(self.cache_dir)
        slug = slugify_nick(key)
        folder = os.path.join(root, slug)
        owner = self._marker(folder)
        claimed = any(path == folder for other, path in self._dirs.items() if other != key)
        if (owner and owner != key) or (not owner and claimed):
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:4]
            folder = os.path.join(root, f"{slug}_{digest}")
        self._dirs[key] = folder
        return folder

    def _marker(self, folder: str) -> str:
        try:
            with open(os.path.join(folder, self.NICK_MARKER), encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError:
            return ""

    def _write_marker(self, folder: str, nick: str) -> None:
        path = os.path.join(folder, self.NICK_MARKER)
        if os.path.exists(path):
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(" ".join(str(nick or "").split()) or "unknown")
        except OSError as e:
            log.debug("cannot write the nick marker in %s: %s", folder, e)

    def _free_name(self, folder: str, day: str, ext: str) -> str:
        used = 0
        try:
            for name in os.listdir(folder):
                if not name.startswith(day + "_"):
                    continue
                stem = os.path.splitext(name)[0][len(day) + 1:]
                if stem.isdigit():
                    used = max(used, int(stem))
        except OSError:
            pass
        return os.path.join(folder, f"{day}_{used + 1:03d}{ext}")

    def _target_path(self, nick: str, kind: str, day: str, ext: str) -> str:
        person = self._person_dir(nick)
        folder = os.path.join(person, "gifs" if kind == "gif" else "images")
        os.makedirs(folder, exist_ok=True)
        self._write_marker(person, nick)
        return self._free_name(folder, day, ext)

    def _day(self, value=None) -> str:
        text = str(value or "")[:10]
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            return text
        return self.now().strftime("%Y-%m-%d")

    async def register(self, url: str, kind: Optional[str] = None, nick: str = "", day: str = "") -> Optional[int]:
        clean = str(url or "").strip()
        if not clean:
            return None
        resolved = (kind or "").strip() or infer_kind(clean)
        if resolved not in ("image", "gif"):
            resolved = infer_kind(clean)
        owner = " ".join(str(nick or "").split())
        await self.db.execute(
            "INSERT INTO media(url, kind, state, owner, day, ref_count, created_at, last_used) VALUES(?,?,'pending',?,?,1,?,?) "
            "ON CONFLICT(url) DO UPDATE SET ref_count=ref_count+1, owner=CASE WHEN media.owner='' THEN excluded.owner ELSE media.owner END, "
            "day=CASE WHEN media.day='' THEN excluded.day ELSE media.day END, last_used=excluded.last_used",
            (clean, resolved, owner, self._day(day) if day else "", _now(), _now()))
        await self.db.commit()
        row = await self.db.fetchone("SELECT id FROM media WHERE url=?", (clean,))
        return int(row[0]) if row else None

    async def get(self, media_id) -> Optional[dict]:
        row = await self.db.fetchone("SELECT * FROM media WHERE id=?", (self._as_id(media_id),))
        return dict(row) if row else None

    async def get_by_url(self, url: str) -> Optional[dict]:
        row = await self.db.fetchone("SELECT * FROM media WHERE url=?", (str(url or "").strip(),))
        return dict(row) if row else None

    @staticmethod
    def _as_id(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    async def process_pending(self, limit: int = 25) -> int:
        if not self.enabled or self.paused or self.cdp is None:
            return 0
        limit = int(limit)
        if limit <= 0:
            return 0
        rows = await self.db.fetchdicts("SELECT id, url, kind, owner, day FROM media WHERE state='pending' ORDER BY id LIMIT ?", (limit,))
        stored = 0
        for row in rows:
            if not self.enabled or self.paused:
                break
            if await self._fetch_one(row):
                stored += 1
        return stored

    async def _abs_url(self, url: str) -> str:
        return await self._fetcher._abs_url(url)

    async def _fetch_one(self, row: dict) -> bool:
        return await self._fetcher._fetch_one(row)

    async def _fetch_in_page(self, url: str) -> dict:
        return await self._fetcher._fetch_in_page(url)

    async def _fetch_via_python(self, url: str) -> dict:
        return await self._fetcher._fetch_via_python(url)

    async def _fetch_via_network(self, url: str) -> dict:
        return await self._fetcher._fetch_via_network(url)

    def _finish_network_body(self, fut, info: dict) -> None:
        return self._fetcher._finish_network_body(fut, info)

    async def _twin(self, owner: str, digest: str) -> str:
        rows = await self.db.fetchdicts("SELECT cache_path FROM media WHERE sha256=? AND owner=? AND state='cached' AND cache_path<>''", (digest, owner))
        for row in rows:
            if os.path.exists(row["cache_path"]):
                return row["cache_path"]
        return ""

    async def migrate_layout(self) -> int:
        return await self._cache.migrate_layout()

    async def _fail(self, media_id: int, reason: str) -> None:
        await self.db.execute("UPDATE media SET state='failed', fail_reason=? WHERE id=?", (reason[:300], media_id))
        await self.db.commit()

    async def _skip(self, media_id: int, reason: str) -> None:
        await self.db.execute("UPDATE media SET state='skipped', fail_reason=? WHERE id=?", (reason[:300], media_id))
        await self.db.commit()

    async def retry_failed(self) -> int:
        cur = await self.db.execute("UPDATE media SET state='pending', fail_reason='', recovered_at=?, recovery_attempts=recovery_attempts+1 WHERE state IN ('failed','skipped')", (_now(),))
        await self.db.commit()
        return int(cur.rowcount or 0)

    async def requeue(self, media_id, reason: str = "retry") -> bool:
        row = await self.get(media_id)
        if not row or not row.get("url"):
            return False
        if row.get("state") not in ("failed", "skipped"):
            return False
        await self.db.execute("UPDATE media SET state='pending', fail_reason='', recovered_at=?, recovery_attempts=recovery_attempts+1, last_used=? WHERE id=?", (_now(), _now(), self._as_id(media_id)))
        await self.db.commit()
        return True

    async def download_one(self, media_id) -> dict:
        row = await self.get(media_id)
        if not row:
            return {"state": "missing", "id": media_id, "path": "", "url": ""}
        if not self.enabled or self.paused or self.cdp is None:
            return await self.path_for(media_id)
        path = row.get("cache_path") or ""
        if row.get("state") == "cached" and path and os.path.exists(path):
            return await self.path_for(media_id)
        await self.db.execute("UPDATE media SET state='pending', fail_reason='', recovered_at=?, recovery_attempts=recovery_attempts+1, last_used=? WHERE id=?", (_now(), _now(), self._as_id(media_id)))
        await self.db.commit()
        row = await self.get(media_id)
        if row:
            await self._fetch_one(row)
        return await self.path_for(media_id)

    async def retry_failed_uncached(self) -> int:
        cur = await self.db.execute("UPDATE media SET state='pending', fail_reason='', recovered_at=?, recovery_attempts=recovery_attempts+1 WHERE state='failed' AND (cache_path='' OR cache_path IS NULL)", (_now(),))
        await self.db.commit()
        return int(cur.rowcount or 0)

    async def path_for(self, media_id) -> dict:
        row = await self.get(media_id)
        if not row:
            return {"state": "missing", "path": "", "url": ""}
        path = row.get("cache_path") or ""
        usable = row.get("state") == "cached" and path and os.path.exists(path)
        if usable:
            await self.db.execute("UPDATE media SET last_used=? WHERE id=?", (_now(), row["id"]))
            await self.db.commit()
        return {"state": row.get("state"), "path": path if usable else "", "url": row.get("url") or "", "kind": row.get("kind") or "image", "bytes": int(row.get("bytes") or 0)}

    async def clipboard_payload(self, media_id) -> dict:
        row = await self.get(media_id)
        if not row:
            return {"ok": False, "mode": "", "path": "", "text": "", "url": "", "error": f"media {media_id} not found"}
        info = await self.path_for(row["id"])
        url = row.get("url") or ""
        if info["path"]:
            mode = "file_link" if row.get("kind") == "gif" else "image"
            return {"ok": True, "mode": mode, "path": info["path"], "text": url, "url": url, "error": ""}
        return {"ok": True, "mode": "link", "path": "", "text": url, "url": url, "error": ""}

    async def cache_usage(self) -> dict:
        return await self._cache.cache_usage()

    async def evict_if_needed(self) -> int:
        return await self._cache.evict_if_needed()

    async def _evict(self, media_id: int) -> None:
        return await self._cache._evict(media_id)

    async def clear_cache(self) -> int:
        return await self._cache.clear_cache()
