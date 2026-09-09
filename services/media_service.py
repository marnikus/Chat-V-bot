"""MediaService — owns MediaStore access via HistoryService, no direct repo.

All methods return Result[T]; bridges await via @asyncSlot. Reusable without Qt.
MediaStore is only reachable through HistoryService (or this service which
delegates to HistoryService), never directly by CollectorService or bridges.
"""

from __future__ import annotations

import logging
from typing import Any

from core.result import Result

log = logging.getLogger("chatbot")


class MediaService:
    """Thin, reusable media facade — delegates to HistoryService's media."""

    def __init__(self, history_service) -> None:
        self._hs = history_service

    def _media(self):
        # HistoryService wraps BackendHistory which has .media after init
        inner = getattr(self._hs, "inner", None) or getattr(self._hs, "_inner", None) or self._hs
        return getattr(inner, "media", None)

    def media_base_dir(self) -> Result[str]:
        try:
            # prefer HistoryService's explicit method if available
            if hasattr(self._hs, "media_base_dir"):
                res = self._hs.media_base_dir()
                # HistoryService.media_base_dir already returns Result
                return res if isinstance(res, Result) else Result.ok(str(res))
            media = self._media()
            if media and hasattr(media, "base_dir"):
                return Result.ok(str(media.base_dir))
            return Result.err("media not available")
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    def world_media_dir(self, path: str = "") -> Result[str]:
        try:
            if hasattr(self._hs, "world_media_dir"):
                res = self._hs.world_media_dir(path)
                return res if isinstance(res, Result) else Result.ok(str(res))
            media = self._media()
            if media and hasattr(media, "folder_for"):
                return Result.ok(str(media.folder_for(path)))
            return Result.err("media not available")
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    def folder_for(self, nick: str) -> Result[str]:
        try:
            media = self._media()
            if media is None:
                return Result.err("media not available")
            # HistoryService's media has folder_for
            if hasattr(media, "folder_for"):
                return Result.ok(media.folder_for(nick))
            # fallback to HistoryService's media_base_dir + nick
            base = self.media_base_dir()
            if base.is_ok:
                return Result.ok(f"{base.value}/{nick}/images")
            return Result.err("folder_for not available")
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    async def path_for(self, media_ref: str) -> Result[dict[str, Any]]:
        try:
            media = self._media()
            if media is None:
                return Result.err("media not available")
            if hasattr(media, "path_for"):
                payload = await media.path_for(media_ref)
                return Result.ok(payload)
            return Result.err("path_for not available")
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    async def cache_usage(self) -> Result[dict[str, Any]]:
        try:
            media = self._media()
            if media is None:
                return Result.err("media not available")
            if hasattr(media, "cache_usage"):
                payload = await media.cache_usage()
                return Result.ok(payload)
            inner = getattr(self._hs, "inner", None) or self._hs
            if hasattr(inner, "media") and hasattr(inner.media, "cache_usage"):
                payload = await inner.media.cache_usage()
                return Result.ok(payload)
            return Result.ok({"cache_mb": 0})
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))
