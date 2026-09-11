"""The size cap, the dedupe lookup and the folder migration.

The housekeeping half of `stores/media_store.py`: least-recently-used eviction
under `max_cache_bytes`, the report the settings panel shows, `clear_cache`,
the dedupe twin lookup (identical bytes already filed for the same person are
reused, never written twice) and moving an older flat `<sha256>.<ext>` cache
into the per-person tree.
"""

from __future__ import annotations

import logging
import os

from stores.media_layout import _extension

log = logging.getLogger("chatbot")


class MediaCachePolicy:
    """The size cap, the dedupe lookup and the folder migration."""

    def __init__(self, owner):
        """`owner` is the `MediaStore` this part borrows state from."""
        self._owner = owner

    async def _twin(self, owner: str, digest: str) -> str:
        """An already-cached file with the same bytes in the same folder."""
        rows = await self._owner.db.fetchdicts(
            "SELECT cache_path FROM media WHERE sha256=? AND owner=? "
            "AND state='cached' AND cache_path<>''", (digest, owner))
        for row in rows:
            if os.path.exists(row["cache_path"]):
                return row["cache_path"]
        return ""

    async def migrate_layout(self) -> int:
        """Move an older flat `<sha256>.<ext>` cache into the person tree."""
        rows = await self._owner.db.fetchdicts(
            "SELECT id, url, kind, owner, day, cache_path, created_at "
            "FROM media WHERE state='cached' AND cache_path<>''")
        moved = 0
        root = os.path.abspath(self._owner.cache_dir)
        for row in rows:
            if await self._rehome_one(row, root):
                moved += 1
        if moved:
            await self._owner.db.commit()
        return moved

    async def _rehome_one(self, row: dict, root: str) -> bool:
        """Move one flat-cached file into its person folder (False = skipped)."""
        old = row["cache_path"]
        if not old or not os.path.exists(old):
            return False
        if os.path.dirname(os.path.abspath(old)) != root:
            return False                       # already inside the tree
        ext = os.path.splitext(old)[1] or _extension(row["url"], "")
        day = self._owner._day(row.get("day") or row.get("created_at"))
        try:
            new = self._owner._target_path(row.get("owner") or "",
                                    row.get("kind") or "image", day, ext)
            os.replace(old, new)
        except OSError as e:               # noqa: PERF203
            log.warning("cannot move %s into the media tree: %s", old, e)
            return False
        await self._owner.db.execute(
            "UPDATE media SET cache_path=? WHERE id=?", (new, row["id"]))
        return True

    async def cache_usage(self) -> dict:
        row = await self._owner.db.fetchone(
            "SELECT COUNT(*) AS files, COALESCE(SUM(bytes),0) AS bytes "
            "FROM media WHERE state='cached'")
        pending = int(await self._owner.db.scalar(
            "SELECT COUNT(*) FROM media WHERE state='pending'", (), 0))
        failed = int(await self._owner.db.scalar(
            "SELECT COUNT(*) FROM media WHERE state IN ('failed','skipped')",
            (), 0))
        return {"files": int(row["files"] or 0), "bytes": int(row["bytes"] or 0),
                "max_bytes": self._owner.max_cache_bytes, "pending": pending,
                "failed": failed, "dir": self._owner.cache_dir,
                "enabled": self._owner.enabled, "paused": self._owner.paused}

    async def evict_if_needed(self) -> int:
        """Drop least-recently-used files until we are under the cap."""
        removed = 0
        while True:
            total = int(await self._owner.db.scalar(
                "SELECT COALESCE(SUM(bytes),0) FROM media WHERE state='cached'",
                (), 0))
            if total <= self._owner.max_cache_bytes:
                return removed
            row = await self._owner.db.fetchone(
                "SELECT id FROM media WHERE state='cached' "
                "ORDER BY last_used ASC, id ASC LIMIT 1")
            if not row:
                return removed
            await self._evict(int(row[0]))
            removed += 1

    async def _evict(self, media_id: int) -> None:
        row = await self._owner.get(media_id)
        if not row:
            return
        path = row.get("cache_path") or ""
        shared = int(await self._owner.db.scalar(
            "SELECT COUNT(*) FROM media WHERE cache_path=? AND state='cached' "
            "AND id<>?", (path, media_id), 0))
        if path and not shared and os.path.exists(path):
            try:
                os.remove(path)
            except OSError as e:
                log.warning("cannot remove cached media %s: %s", path, e)
        await self._owner.db.execute(
            "UPDATE media SET state='evicted', bytes=0 WHERE id=?", (media_id,))
        await self._owner.db.commit()

    async def clear_cache(self) -> int:
        rows = await self._owner.db.fetchdicts(
            "SELECT id FROM media WHERE state='cached'")
        for row in rows:
            await self._evict(int(row["id"]))
        return len(rows)
