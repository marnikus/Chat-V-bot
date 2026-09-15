"""History query — facade (H-C5 split)

Now ≤80 LOC via settings/merge/gaze split.
"""

from __future__ import annotations

import logging

from services.history.query_gaze import HistoryQueryGaze
from services.history.query_merge import _merge, _merge_media_settings, _merge_preview_settings
from services.history.query_settings import HistoryQuerySettings, _db_stem

log = logging.getLogger("chatbot")
OLD_MAX_FILE_MB = 2
MAX_FILE_MB_DEFAULT = 25
HISTORY_DEFAULTS = {
    "enabled": True,
    "db_path": "history.db",
    "use_fts": True,
    "media": {"enabled": True, "download": True, "cache_dir": "saved_media", "max_file_mb": MAX_FILE_MB_DEFAULT, "max_cache_mb": 200},
    "preview": {"preload_rows": 40, "page_size": 50, "max_rows": 400, "show_images": True},
}
SETTING_KEYS = ("my_nick", "media_max_file_mb", "media_max_cache_mb", "preview")


class HistoryQueryService(HistoryQuerySettings, HistoryQueryGaze):
    """Query service — loads app settings, gaze, undo, pages."""

    async def load_app_settings(self) -> None:
        rows = await self.db.fetchdicts("SELECT key, value FROM app_settings")
        data = {row["key"]: row["value"] for row in rows}
        media = dict(self._settings.get("media") or {})
        preview = dict(self._settings.get("preview") or {})
        try:
            self._apply_stored_my_nick(data)
            _merge_media_settings(data, media)
            preview = _merge_preview_settings(data, preview)
        except (TypeError, ValueError, KeyError, __import__("json").JSONDecodeError):
            pass
        self._settings["media"], self._settings["preview"] = media, preview
        self.media.max_file_bytes = int(float(media.get("max_file_mb", MAX_FILE_MB_DEFAULT)) * 1024 * 1024)
        self.media.max_cache_bytes = int(float(media.get("max_cache_mb", 200)) * 1024 * 1024)


__all__ = [
    "HistoryQueryService",
    "HISTORY_DEFAULTS",
    "MAX_FILE_MB_DEFAULT",
    "OLD_MAX_FILE_MB",
    "_merge",
    "_db_stem",
]
