from __future__ import annotations

import asyncio
from typing import Optional

from backend.chat_parser import ChatParser
from backend.history_query import HistoryQuery
from services.collector_service import Collector, DEFAULTS as COLLECTOR_DEFAULTS
from stores.history_db import HistoryDB
from stores.history_repo import HistoryRepo
from stores.media_store import MediaStore

from . import trash
from .export import HistoryExportService
from .mutate import HistoryMutateService
from .query import (HISTORY_DEFAULTS, MAX_FILE_MB_DEFAULT, OLD_MAX_FILE_MB,
                    HistoryQueryService, _db_stem, _merge)


class HistoryService(HistoryQueryService, HistoryMutateService, HistoryExportService):
    def __init__(self, cdp, config=None, db_path: Optional[str] = None,
                 session_id: str = "", memory=None, labels=None):
        self.cdp = cdp
        self.config = config
        self.session_id = session_id or ""
        self.memory = memory
        self._labels = labels
        self._settings = _merge(HISTORY_DEFAULTS, self._stored("history"))
        if db_path:
            self._settings["db_path"] = db_path
        self._migrate_media_cap()
        self.db = HistoryDB(self._settings["db_path"], use_fts=bool(self._settings["use_fts"]))
        media = self._settings["media"]
        self.media = MediaStore(self.db, cdp=cdp, cache_dir=media["cache_dir"], max_file_mb=media["max_file_mb"], max_cache_mb=media["max_cache_mb"], enabled=bool(media["enabled"]))
        self.repo = HistoryRepo(self.db, media=self.media, session_id=self.session_id)
        self.query = HistoryQuery(self.db)
        collector = _merge(COLLECTOR_DEFAULTS, self._stored("collector"))
        self.parser = ChatParser(cdp, chunk_size=int(collector.get("chunk_size", 80)), chunk_pause_ms=int(collector.get("chunk_pause_ms", 40)))
        self.collector = Collector(cdp=cdp, repo=self.repo, parser=self.parser, media=self.media, settings=collector, lease=getattr(cdp, "lease", None), memory=self.memory)
        self._task: Optional[asyncio.Task] = None
        self._binding = False
        self._detached_running = None

    # ── session-sized trash (services/history/trash.py) ──────────
    async def begin_session(self) -> dict:
        return await trash.begin_session(self)

    async def forget_old_trash(self) -> dict:
        return await trash.forget_old_trash(self)

    async def purge_trash(self, nick: str = "") -> dict:
        return await trash.purge_trash(self, nick)

    async def purge_tokens(self, tokens: list) -> dict:
        return await trash.purge_tokens(self, tokens)


__all__ = [
    "HistoryService", "HistoryQueryService", "HistoryMutateService",
    "HistoryExportService", "HISTORY_DEFAULTS", "MAX_FILE_MB_DEFAULT",
    "OLD_MAX_FILE_MB", "_merge", "_db_stem",
]
