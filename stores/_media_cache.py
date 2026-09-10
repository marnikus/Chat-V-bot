"""Media cache policy — extracted from MediaStore (AREA B)."""

from __future__ import annotations

import logging
import os
from datetime import datetime

log = logging.getLogger("chatbot")

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")

class MediaCachePolicy:
    def __init__(self, store):
        self.store = store

    async def cache_usage(self) -> dict:
        store = self.store
        row = await store.db.fetchone(
            "SELECT COUNT(*) AS files, COALESCE(SUM(bytes),0) AS bytes FROM media WHERE state='cached'")
        pending = int(await store.db.scalar("SELECT COUNT(*) FROM media WHERE state='pending'", (), 0))
        failed = int(await store.db.scalar("SELECT COUNT(*) FROM media WHERE state IN ('failed','skipped')", (), 0))
        return {"files": int(row["files"] or 0), "bytes": int(row["bytes"] or 0),
                "max_bytes": store.max_cache_bytes, "pending": pending,
                "failed": failed, "dir": store.cache_dir,
                "enabled": store.enabled, "paused": store.paused}

    async def evict_if_needed(self) -> int:
        store = self.store
        removed = 0
        while True:
            total = int(await store.db.scalar("SELECT COALESCE(SUM(bytes),0) FROM media WHERE state='cached'", (), 0))
            if total <= store.max_cache_bytes:
                return removed
            row = await store.db.fetchone("SELECT id FROM media WHERE state='cached' ORDER BY last_used ASC, id ASC LIMIT 1")
            if not row:
                return removed
            await self._evict(int(row[0]))
            removed += 1

    async def _evict(self, media_id: int) -> None:
        store = self.store
        row = await store.get(media_id)
        if not row:
            return
        path = row.get("cache_path") or ""
        shared = int(await store.db.scalar(
            "SELECT COUNT(*) FROM media WHERE cache_path=? AND state='cached' AND id<>?", (path, media_id), 0))
        if path and not shared and os.path.exists(path):
            try:
                os.remove(path)
            except OSError as e:
                log.warning("cannot remove cached media %s: %s", path, e)
        await store.db.execute("UPDATE media SET state='evicted', bytes=0 WHERE id=?", (media_id,))
        await store.db.commit()

    async def clear_cache(self) -> int:
        rows = await self.store.db.fetchdicts("SELECT id FROM media WHERE state='cached'")
        for row in rows:
            await self._evict(int(row["id"]))
        return len(rows)

    async def migrate_layout(self) -> int:
        store = self.store
        from stores._media_nick import _extension
        rows = await store.db.fetchdicts(
            "SELECT id, url, kind, owner, day, cache_path, created_at FROM media WHERE state='cached' AND cache_path<>''")
        moved = 0
        root = os.path.abspath(store.cache_dir)
        for row in rows:
            old = row["cache_path"]
            if not old or not os.path.exists(old):
                continue
            if os.path.dirname(os.path.abspath(old)) != root:
                continue
            ext = os.path.splitext(old)[1] or _extension(row["url"], "")
            day = store._day(row.get("day") or row.get("created_at"))
            try:
                new = store._target_path(row.get("owner") or "", row.get("kind") or "image", day, ext)
                os.replace(old, new)
            except OSError as e:
                log.warning("cannot move %s into the media tree: %s", old, e)
                continue
            await store.db.execute("UPDATE media SET cache_path=? WHERE id=?", (new, row["id"]))
            moved += 1
        if moved:
            await store.db.commit()
        return moved
