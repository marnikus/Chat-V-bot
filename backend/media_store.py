"""Hybrid media storage for the archive.

Decision D-1: the database keeps the URL plus a hash; the BYTES live on disk
under a size cap. Previews then survive the site expiring an image, without
turning history.db into a multi-gigabyte blob store.

Bytes are fetched by an in-page `fetch()` (the page owns the session cookies)
and travel back as base64 through one CDP evaluate. Everything here is
best-effort: a missing file, a dead URL or a disabled cache degrades to
"show the link", never to an exception in the UI.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from backend import chat_agent_js
from backend.history_db import HistoryDB

log = logging.getLogger("chatbot")

IMAGE_EXT = {".jpg": "image", ".jpeg": "image", ".png": "image",
             ".webp": "image", ".bmp": "image", ".gif": "gif"}
MIME_EXT = {"image/gif": ".gif", "image/png": ".png", "image/jpeg": ".jpg",
            "image/webp": ".webp", "image/bmp": ".bmp"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def infer_kind(url: str) -> str:
    ext = os.path.splitext(urlparse(str(url or "")).path)[1].lower()
    return IMAGE_EXT.get(ext, "image")


def _extension(url: str, mime: str) -> str:
    ext = os.path.splitext(urlparse(str(url or "")).path)[1].lower()
    if ext in IMAGE_EXT:
        return ext
    return MIME_EXT.get((mime or "").split(";")[0].strip(), ".bin")


class MediaStore:
    """URL registry + on-disk byte cache for images and GIFs."""

    def __init__(self, db: HistoryDB, cdp=None, cache_dir: str = "media_cache",
                 max_file_mb: float = 1, max_cache_mb: float = 10,
                 enabled: bool = True):
        self.db = db
        self.cdp = cdp
        self.cache_dir = cache_dir
        self.max_file_bytes = int(float(max_file_mb) * 1024 * 1024)
        self.max_cache_bytes = int(float(max_cache_mb) * 1024 * 1024)
        self.enabled = bool(enabled)
        self.paused = False

    # ── registration ─────────────────────────────────────────────
    async def register(self, url: str, kind: Optional[str] = None) -> Optional[int]:
        """Remember a media URL. Returns its id (existing rows are reused)."""
        clean = str(url or "").strip()
        if not clean:
            return None
        resolved = (kind or "").strip() or infer_kind(clean)
        if resolved not in ("image", "gif"):
            resolved = infer_kind(clean)
        await self.db.execute(
            "INSERT INTO media(url, kind, state, ref_count, created_at, "
            "last_used) VALUES(?,?,'pending',1,?,?) "
            "ON CONFLICT(url) DO UPDATE SET ref_count=ref_count+1, "
            "last_used=excluded.last_used",
            (clean, resolved, _now(), _now()))
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
    async def process_pending(self, limit: int = 25) -> int:
        """Cache up to `limit` pending files. Returns how many were stored."""
        if not self.enabled or self.paused or self.cdp is None:
            return 0
        rows = await self.db.fetchdicts(
            "SELECT id, url, kind FROM media WHERE state='pending' "
            "ORDER BY id LIMIT ?", (max(1, int(limit)),))
        stored = 0
        for row in rows:
            if not self.enabled or self.paused:
                break
            if await self._fetch_one(row):
                stored += 1
        return stored

    async def _fetch_one(self, row: dict) -> bool:
        url = row["url"]
        try:
            raw = await self.cdp.evaluate(
                chat_agent_js.fetch_media_expression(url))
        except Exception as e:                        # noqa: BLE001
            await self._fail(row["id"], f"probe error: {e}")
            return False
        payload = raw
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                payload = None
        if not isinstance(payload, dict) or not payload.get("ok"):
            reason = (payload or {}).get("error") or "no answer from the page"
            await self._fail(row["id"], str(reason))
            return False
        try:
            data = base64.b64decode(payload.get("b64") or "")
        except Exception as e:                        # noqa: BLE001
            await self._fail(row["id"], f"undecodable payload: {e}")
            return False
        if len(data) > self.max_file_bytes:
            await self._skip(row["id"], "too large (%d bytes, cap %d)"
                             % (len(data), self.max_file_bytes))
            return False
        digest = hashlib.sha256(data).hexdigest()
        path = os.path.join(self.cache_dir,
                            digest + _extension(url, payload.get("mime", "")))
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            if not os.path.exists(path):
                with open(path, "wb") as handle:      # identical bytes ⇒
                    handle.write(data)                # one file, many rows
        except OSError as e:
            await self._fail(row["id"], f"cannot write cache: {e}")
            return False
        await self.db.execute(
            "UPDATE media SET state='cached', sha256=?, bytes=?, "
            "cache_path=?, fail_reason='', last_used=? WHERE id=?",
            (digest, len(data), path, _now(), row["id"]))
        await self.db.commit()
        return True

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
        """Explicitly give up-front failures another chance (user action)."""
        cur = await self.db.execute(
            "UPDATE media SET state='pending', fail_reason='' "
            "WHERE state IN ('failed','skipped')")
        await self.db.commit()
        return int(cur.rowcount or 0)

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
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS files, COALESCE(SUM(bytes),0) AS bytes "
            "FROM media WHERE state='cached'")
        pending = int(await self.db.scalar(
            "SELECT COUNT(*) FROM media WHERE state='pending'", (), 0))
        failed = int(await self.db.scalar(
            "SELECT COUNT(*) FROM media WHERE state IN ('failed','skipped')",
            (), 0))
        return {"files": int(row["files"] or 0), "bytes": int(row["bytes"] or 0),
                "max_bytes": self.max_cache_bytes, "pending": pending,
                "failed": failed, "dir": self.cache_dir,
                "enabled": self.enabled, "paused": self.paused}

    async def evict_if_needed(self) -> int:
        """Drop least-recently-used files until we are under the cap."""
        removed = 0
        while True:
            total = int(await self.db.scalar(
                "SELECT COALESCE(SUM(bytes),0) FROM media WHERE state='cached'",
                (), 0))
            if total <= self.max_cache_bytes:
                return removed
            row = await self.db.fetchone(
                "SELECT id FROM media WHERE state='cached' "
                "ORDER BY last_used ASC, id ASC LIMIT 1")
            if not row:
                return removed
            await self._evict(int(row[0]))
            removed += 1

    async def _evict(self, media_id: int) -> None:
        row = await self.get(media_id)
        if not row:
            return
        path = row.get("cache_path") or ""
        shared = int(await self.db.scalar(
            "SELECT COUNT(*) FROM media WHERE cache_path=? AND state='cached' "
            "AND id<>?", (path, media_id), 0))
        if path and not shared and os.path.exists(path):
            try:
                os.remove(path)
            except OSError as e:
                log.warning("cannot remove cached media %s: %s", path, e)
        await self.db.execute(
            "UPDATE media SET state='evicted', bytes=0 WHERE id=?", (media_id,))
        await self.db.commit()

    async def clear_cache(self) -> int:
        rows = await self.db.fetchdicts(
            "SELECT id FROM media WHERE state='cached'")
        for row in rows:
            await self._evict(int(row["id"]))
        return len(rows)
