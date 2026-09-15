"""Media fetch queue — extracted from media_fetch (H-C5 split)

Retry/requeue/download_one, ≤120 LOC.
"""

from __future__ import annotations

import logging
import os

from stores.media_layout import _now

log = logging.getLogger("chatbot")


def _is_valid_row(row: dict | None) -> bool:
    return bool(row and row.get("url"))


def _is_failed_or_skipped(state: str) -> bool:
    return state in ("failed", "skipped")


def _is_cached_row(row: dict, path: str) -> bool:
    return row.get("state") == "cached" and bool(path) and os.path.exists(path)


def _is_enabled(owner) -> bool:
    return bool(owner.enabled and not owner.paused and owner.cdp is not None)


class MediaFetchQueue:
    def __init__(self, owner):
        self._owner = owner

    async def retry_failed(self) -> int:
        cur = await self._owner.db.execute(
            "UPDATE media SET state='pending', fail_reason='', recovered_at=?, recovery_attempts=recovery_attempts+1 WHERE state IN ('failed','skipped')",
            (_now(),),
        )
        await self._owner.db.commit()
        return int(cur.rowcount or 0)

    async def requeue(self, media_id, reason: str = "retry") -> bool:
        row = await self._owner.get(media_id)
        if not _is_valid_row(row):
            return False
        if not _is_failed_or_skipped(row.get("state") or ""):
            return False
        await self._owner.db.execute(
            "UPDATE media SET state='pending', fail_reason='', recovered_at=?, recovery_attempts=recovery_attempts+1, last_used=? WHERE id=?",
            (_now(), _now(), self._owner._as_id(media_id)),
        )
        await self._owner.db.commit()
        return True

    async def download_one(self, media_id) -> dict:
        row = await self._owner.get(media_id)
        if not row:
            return {"state": "missing", "id": media_id, "path": "", "url": ""}
        if not _is_enabled(self._owner):
            return await self._owner.path_for(media_id)
        path = row.get("cache_path") or ""
        if _is_cached_row(row, path):
            return await self._owner.path_for(media_id)
        await self._owner.db.execute(
            "UPDATE media SET state='pending', fail_reason='', recovered_at=?, recovery_attempts=recovery_attempts+1, last_used=? WHERE id=?",
            (_now(), _now(), self._owner._as_id(media_id)),
        )
        await self._owner.db.commit()
        row = await self._owner.get(media_id)
        if row:
            await self._fetch_one(row)
        return await self._owner.path_for(media_id)

    async def retry_failed_uncached(self) -> int:
        cur = await self._owner.db.execute(
            "UPDATE media SET state='pending', fail_reason='', recovered_at=?, recovery_attempts=recovery_attempts+1 WHERE state='failed' AND (cache_path='' OR cache_path IS NULL)",
            (_now(),),
        )
        await self._owner.db.commit()
        return int(cur.rowcount or 0)
