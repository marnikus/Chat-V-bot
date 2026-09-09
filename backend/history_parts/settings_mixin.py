"""Settings + per-world pieces (<150)."""
import copy, json, os
from .base import MAX_FILE_MB_DEFAULT
class HistorySettingsMixin:
    @property
    def enabled(self) -> bool: return bool(self._settings.get("enabled", True))
    @property
    def my_nick(self) -> str: return self.collector.my_nick
    def settings(self) -> dict:
        d = copy.deepcopy(self._settings); d["collector"] = self.collector.settings(); d["fts"] = bool(self.db.fts_enabled); d["db_path"] = self.db.path; return d
    def apply_settings(self, patch: dict) -> dict:
        patch = dict(patch or {}); cp = patch.pop("collector", None)
        from .base import _merge
        self._settings = _merge(self._settings, patch); m = self._settings["media"]
        self.media.enabled = bool(m.get("enabled", True)); self._apply_world_media_dir()
        self.media.max_file_bytes = int(float(m.get("max_file_mb", MAX_FILE_MB_DEFAULT)) * 1024 * 1024)
        self.media.max_cache_bytes = int(float(m.get("max_cache_mb", 200)) * 1024 * 1024)
        if cp: self.collector.configure(**cp)
        if self.config is not None:
            stored = {k: v for k, v in self._settings.items() if k not in ("collector",)}
            self.config.set("history", stored); self.config.save()
        self._persist_app_settings(); return self.settings()
    def set_my_nick(self, nick: str) -> str:
        clean = " ".join(str(nick or "").split()).strip(); self.collector.configure(my_nick=clean); self._persist_app_settings(); return clean
    def bind_labels(self, store) -> None: self._labels = store
    def media_base_dir(self) -> str: return str((self._settings.get("media") or {}).get("cache_dir") or "saved_media")
    def world_media_dir(self, path: str="") -> str:
        from .base import _db_stem
        return os.path.join(self.media_base_dir(), _db_stem(path or self.db.path))
    def _apply_world_media_dir(self) -> None:
        if not self.db.is_open: self.media.cache_dir = self.media_base_dir(); return
        self.media.cache_dir = self.world_media_dir(); self.media._dirs.clear()
