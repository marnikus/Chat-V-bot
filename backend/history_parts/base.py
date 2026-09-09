"""HistoryService base — constants, helpers, __init__ (<150)."""
from __future__ import annotations
import copy, json, logging, os, re
from datetime import datetime
from typing import Optional
from backend.chat_parser import ChatParser
from backend.collector import Collector, DEFAULTS as COLLECTOR_DEFAULTS
from backend.history_db import HistoryDB
from backend.history_query import HistoryQuery
from backend.history_repo import HistoryRepo
from backend.media_store import MediaStore
log = logging.getLogger("chatbot")
OLD_MAX_FILE_MB = 2
MAX_FILE_MB_DEFAULT = 25
HISTORY_DEFAULTS = {
    "enabled": True, "db_path": "history.db", "use_fts": True,
    "media": {"enabled": True, "download": True, "cache_dir": "saved_media", "max_file_mb": MAX_FILE_MB_DEFAULT, "max_cache_mb": 200},
    "preview": {"preload_rows": 40, "page_size": 50, "max_rows": 400, "show_images": True},
}
SETTING_KEYS = ("my_nick", "media_max_file_mb", "media_max_cache_mb", "preview")
def _merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out
def _db_stem(path: str) -> str:
    stem = os.path.splitext(os.path.basename(str(path or "")))[0]
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", stem).strip("._-")
    return stem or "world"
class HistoryServiceBase:
    def __init__(self, cdp, config=None, db_path: Optional[str]=None, session_id: str="", memory=None, labels=None):
        self.cdp = cdp; self.config = config; self.session_id = session_id or ""; self.memory = memory; self._labels = labels
        self._settings = _merge(HISTORY_DEFAULTS, self._stored("history"))
        if db_path: self._settings["db_path"] = db_path
        self._migrate_media_cap()
        self.db = HistoryDB(self._settings["db_path"], use_fts=bool(self._settings["use_fts"]))
        m = self._settings["media"]
        self.media = MediaStore(self.db, cdp=cdp, cache_dir=m["cache_dir"], max_file_mb=m["max_file_mb"], max_cache_mb=m["max_cache_mb"], enabled=bool(m["enabled"]))
        self.repo = HistoryRepo(self.db, media=self.media, session_id=self.session_id)
        self.query = HistoryQuery(self.db)
        cfg = _merge(COLLECTOR_DEFAULTS, self._stored("collector"))
        self.parser = ChatParser(cdp, chunk_size=int(cfg.get("chunk_size",80)), chunk_pause_ms=int(cfg.get("chunk_pause_ms",40)))
        self.collector = Collector(cdp=cdp, repo=self.repo, parser=self.parser, media=self.media, settings=cfg, lease=getattr(cdp,"lease",None), memory=self.memory)
        self._task = None; self._binding = False
    def _stored(self, section: str) -> dict:
        if self.config is None: return {}
        v = self.config.get(section, default={})
        return v if isinstance(v, dict) else {}
    def _migrate_media_cap(self) -> None:
        m = self._settings.get("media") or {}
        try: cap = float(m.get("max_file_mb", MAX_FILE_MB_DEFAULT))
        except (TypeError, ValueError): cap = MAX_FILE_MB_DEFAULT
        if cap <= OLD_MAX_FILE_MB: m["max_file_mb"] = MAX_FILE_MB_DEFAULT; self._settings["media"] = m
