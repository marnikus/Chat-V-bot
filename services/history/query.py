from __future__ import annotations

import copy
import json
import logging
import os
import re

log = logging.getLogger("chatbot")
OLD_MAX_FILE_MB = 2
MAX_FILE_MB_DEFAULT = 25
HISTORY_DEFAULTS = {
    "enabled": True,
    "db_path": "history.db",
    "use_fts": True,
    "media": {"enabled": True, "download": True, "cache_dir": "saved_media",
               "max_file_mb": MAX_FILE_MB_DEFAULT, "max_cache_mb": 200},
    "preview": {"preload_rows": 40, "page_size": 50,
                "max_rows": 400, "show_images": True},
}
SETTING_KEYS = ("my_nick", "media_max_file_mb", "media_max_cache_mb", "preview")


def _merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (patch or {}).items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def _db_stem(path: str) -> str:
    stem = os.path.splitext(os.path.basename(str(path or "")))[0]
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", stem).strip("._-")
    return stem or "world"


class HistoryQueryService:
    def _stored(self, section: str) -> dict:
        if self.config is None:
            return {}
        value = self.config.get(section, default={})
        return value if isinstance(value, dict) else {}

    def _migrate_media_cap(self) -> None:
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

    async def load_app_settings(self) -> None:
        rows = await self.db.fetchdicts("SELECT key, value FROM app_settings")
        data = {row["key"]: row["value"] for row in rows}
        media = dict(self._settings.get("media") or {})
        preview = dict(self._settings.get("preview") or {})
        try:
            if "my_nick" in data:
                nick = json.loads(str(data["my_nick"]))
                if isinstance(nick, str):
                    self.collector.configure(my_nick=nick)
            if "media_max_file_mb" in data:
                media["max_file_mb"] = float(data["media_max_file_mb"])
            if "media_max_cache_mb" in data:
                media["max_cache_mb"] = float(data["media_max_cache_mb"])
            if "preview" in data:
                stored = json.loads(str(data["preview"]))
                if isinstance(stored, dict):
                    preview = _merge(preview, stored)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            pass
        self._settings["media"], self._settings["preview"] = media, preview
        self.media.max_file_bytes = int(float(media.get("max_file_mb", MAX_FILE_MB_DEFAULT)) * 1024 * 1024)
        self.media.max_cache_bytes = int(float(media.get("max_cache_mb", 200)) * 1024 * 1024)

    async def load_gaze(self) -> None:
        try:
            rows = await self.db.fetchdicts("SELECT key, value FROM gaze_data")
        except Exception as exc:
            log.debug("gaze load skipped: %s", exc)
            return
        data = {row["key"]: row["value"] for row in rows}
        if not data:
            return
        if data.get("partner"):
            self.collector._nick = str(data["partner"])
        for field in ("added", "total", "last_sync_added", "last_sync_count"):
            try:
                setattr(self.collector, "_" + field, int(data.get(field)))
            except (TypeError, ValueError):
                pass
        if data.get("last_sync_reason"):
            self.collector._last_sync_reason = str(data["last_sync_reason"])

    async def get_meta_flag(self, key: str) -> bool:
        try:
            value = await self.db.get_meta(key, None)
            return value is not None and str(value) != ""
        except Exception:
            return False

    async def load_world_undo(self) -> list[dict]:
        if not self.db.is_open:
            return []
        try:
            rows = await self.db.fetchall("SELECT seq, kind, value FROM undo_history ORDER BY seq")
        except Exception as exc:
            log.warning("undo load from %s failed: %s", self.db.path, exc)
            return []
        out = []
        for seq, kind, value in rows:
            try:
                out.append({"seq": int(seq), "kind": str(kind), "value": json.loads(str(value))})
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        return out

    async def page(self, nick: str, **kwargs) -> dict:
        payload = await self.query.page(nick, **kwargs)
        payload["stats"] = await self.query.person_stats(nick)
        payload["my_nick"] = self.my_nick
        return payload

    def preview_settings(self) -> dict:
        return dict(self._settings.get("preview") or {})

    def to_json(self) -> str:
        return json.dumps(self.settings(), ensure_ascii=False)
