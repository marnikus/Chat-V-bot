"""History query — settings and path helpers.

Part of `history/query.py` family (H-C5 MI lift + method-count fix).
Settings projection and media dir helpers, ≤150 LOC.
"""

from __future__ import annotations

import copy
import json
import os
import re


def _db_stem(path: str) -> str:
    stem = os.path.splitext(os.path.basename(str(path or "")))[0]
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", stem).strip("._-")
    return stem or "world"


class HistoryQuerySettings:
    """Settings and path helpers for HistoryQueryService."""

    def _stored(self, section: str) -> dict:
        if self.config is None:
            return {}
        value = self.config.get(section, default={})
        return value if isinstance(value, dict) else {}

    def _migrate_media_cap(self) -> None:
        from services.history.query import OLD_MAX_FILE_MB, MAX_FILE_MB_DEFAULT
        media = self._settings.get("media") or {}
        try:
            cap = float(media.get("max_file_mb", MAX_FILE_MB_DEFAULT))
        except (TypeError, ValueError):
            cap = MAX_FILE_MB_DEFAULT
        if cap <= OLD_MAX_FILE_MB:
            media["max_file_mb"] = MAX_FILE_MB_DEFAULT
            self._settings["media"] = media

    @property
    def enabled(self) -> bool:
        return bool(self._settings.get("enabled", True))

    @property
    def my_nick(self) -> str:
        return self.collector.my_nick

    def settings(self) -> dict:
        data = copy.deepcopy(self._settings)
        data.update({"collector": self.collector.settings(),
                     "fts": bool(self.db.fts_enabled), "db_path": self.db.path})
        return data

    def media_base_dir(self) -> str:
        return str((self._settings.get("media") or {}).get("cache_dir") or "saved_media")

    def world_media_dir(self, path: str = "") -> str:
        return os.path.join(self.media_base_dir(), _db_stem(path or self.db.path))

    def _apply_world_media_dir(self) -> None:
        self.media.cache_dir = self.media_base_dir() if not self.db.is_open else self.world_media_dir()
        if self.db.is_open:
            self.media._dirs.clear()

    def _apply_stored_my_nick(self, data: dict) -> None:
        if "my_nick" not in data:
            return
        nick = json.loads(str(data["my_nick"]))
        if isinstance(nick, str):
            self.collector.configure(my_nick=nick)

    def preview_settings(self) -> dict:
        return dict(self._settings.get("preview") or {})

    def to_json(self) -> str:
        return json.dumps(self.settings(), ensure_ascii=False)
