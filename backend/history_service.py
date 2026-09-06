"""One object that owns the message archive.

`main.py` creates a single `HistoryService`; the Bridge talks to it for every
read, the ActionEngine exposes it to the COLLECT_HISTORY block, and the
passive collector lives inside it. Keeping the wiring here means there is
exactly one database connection, one media cache and one parser in the
process, however many surfaces use them.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from typing import Optional

from backend.chat_parser import ChatParser
from backend.collector import Collector, DEFAULTS as COLLECTOR_DEFAULTS
from backend.history_db import HistoryDB
from backend.history_query import HistoryQuery
from backend.history_repo import HistoryRepo
from backend.media_store import MediaStore

log = logging.getLogger("chatbot")

HISTORY_DEFAULTS = {
    "enabled": True,
    "db_path": "history.db",
    "use_fts": True,
    "media": {
        "enabled": True,
        "download": True,
        "cache_dir": "media_cache",
        "max_file_mb": 2,
        "max_cache_mb": 200,
    },
    "preview": {
        "preload_rows": 40,
        "page_size": 50,
        "max_rows": 400,
        "show_images": True,
    },
}


def _merge(base: dict, patch: dict) -> dict:
    """Deep-merge `patch` into a copy of `base`."""
    out = copy.deepcopy(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class HistoryService:
    """Database + repository + query + media + parser + collector."""

    def __init__(self, cdp, config=None, db_path: Optional[str] = None,
                 session_id: str = ""):
        self.cdp = cdp
        self.config = config
        self.session_id = session_id or ""
        self._settings = _merge(HISTORY_DEFAULTS, self._stored("history"))
        if db_path:
            self._settings["db_path"] = db_path
        self.db = HistoryDB(self._settings["db_path"],
                            use_fts=bool(self._settings["use_fts"]))
        media_cfg = self._settings["media"]
        self.media = MediaStore(self.db, cdp=cdp,
                                cache_dir=media_cfg["cache_dir"],
                                max_file_mb=media_cfg["max_file_mb"],
                                max_cache_mb=media_cfg["max_cache_mb"],
                                enabled=bool(media_cfg["enabled"]))
        self.repo = HistoryRepo(self.db, media=self.media,
                                session_id=self.session_id)
        self.query = HistoryQuery(self.db)
        collector_cfg = _merge(COLLECTOR_DEFAULTS, self._stored("collector"))
        self.parser = ChatParser(
            cdp, chunk_size=int(collector_cfg.get("chunk_size", 80)),
            chunk_pause_ms=int(collector_cfg.get("chunk_pause_ms", 40)))
        self.collector = Collector(cdp=cdp, repo=self.repo, parser=self.parser,
                                   media=self.media, settings=collector_cfg,
                                   lease=getattr(cdp, "lease", None))
        self._task: Optional[asyncio.Task] = None
        self._binding = False

    # ── settings ─────────────────────────────────────────────────
    def _stored(self, section: str) -> dict:
        if self.config is None:
            return {}
        value = self.config.get(section, default={})
        return value if isinstance(value, dict) else {}

    @property
    def enabled(self) -> bool:
        return bool(self._settings.get("enabled", True))

    @property
    def my_nick(self) -> str:
        return self.collector.my_nick

    def settings(self) -> dict:
        data = copy.deepcopy(self._settings)
        data["collector"] = self.collector.settings()
        data["fts"] = bool(self.db.fts_enabled)
        data["db_path"] = self.db.path
        return data

    def apply_settings(self, patch: dict) -> dict:
        """Merge a UI patch into the history settings and apply it live."""
        patch = dict(patch or {})
        collector_patch = patch.pop("collector", None)
        self._settings = _merge(self._settings, patch)
        media_cfg = self._settings["media"]
        self.media.enabled = bool(media_cfg.get("enabled", True))
        self.media.cache_dir = media_cfg.get("cache_dir", self.media.cache_dir)
        self.media.max_file_bytes = int(float(
            media_cfg.get("max_file_mb", 2)) * 1024 * 1024)
        self.media.max_cache_bytes = int(float(
            media_cfg.get("max_cache_mb", 200)) * 1024 * 1024)
        if collector_patch:
            self.collector.configure(**collector_patch)
        if self.config is not None:
            stored = {k: v for k, v in self._settings.items()
                      if k not in ("collector",)}
            self.config.set("history", stored)
            self.config.save()
        return self.settings()

    def set_my_nick(self, nick: str) -> str:
        clean = " ".join(str(nick or "").split()).strip()
        self.collector.configure(my_nick=clean)
        return clean

    # ── lifecycle ────────────────────────────────────────────────
    async def init(self) -> "HistoryService":
        await self.db.init()
        folder = self._settings["media"].get("cache_dir")
        if folder:
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError as e:
                log.warning("media cache folder unavailable: %s", e)
        await self._install_push_binding()
        # A reconnect (or a Chrome restart) drops the binding — put it back.
        connected = getattr(self.cdp, "connected", None)
        if connected is not None and hasattr(connected, "connect"):
            connected.connect(lambda: asyncio.ensure_future(self._rebind()))
        disconnected = getattr(self.cdp, "disconnected", None)
        if disconnected is not None and hasattr(disconnected, "connect"):
            disconnected.connect(self._on_disconnected)
        log.info("Message archive ready: %s (fts=%s)", self.db.path,
                 self.db.fts_enabled)
        return self

    async def _install_push_binding(self) -> None:
        """Let the in-page agent hand us new lines without polling."""
        if self._binding or not hasattr(self.cdp, "add_binding"):
            return
        try:
            ok = await self.cdp.add_binding("__cvbPush")
        except Exception as e:                        # noqa: BLE001
            log.debug("push binding unavailable: %s", e)
            return
        if not ok:
            return
        self._binding = True
        if hasattr(self.cdp, "on_event"):
            self.cdp.on_event("Runtime.bindingCalled", self._on_binding)

    async def _rebind(self) -> None:
        self._binding = False
        await self._install_push_binding()

    def _on_disconnected(self) -> None:
        self._binding = False

    def _on_binding(self, params: dict):
        if (params or {}).get("name") != "__cvbPush":
            return None
        return self.collector.handle_push((params or {}).get("payload") or "")

    def start(self) -> None:
        """Run the collector heartbeat in the background."""
        if self._task and not self._task.done():
            return
        if not self.enabled:
            return
        self._task = asyncio.ensure_future(self.collector.run())

    async def close(self) -> None:
        self.collector.stop()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):   # noqa: BLE001
                pass
            self._task = None
        await self.db.close()

    # ── convenience used by the bridge ───────────────────────────
    async def page(self, nick: str, **kwargs) -> dict:
        payload = await self.query.page(nick, **kwargs)
        payload["stats"] = await self.query.person_stats(nick)
        payload["my_nick"] = self.my_nick
        return payload

    def preview_settings(self) -> dict:
        return dict(self._settings.get("preview") or {})

    def to_json(self) -> str:
        return json.dumps(self.settings(), ensure_ascii=False)
