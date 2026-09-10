"""HistoryLifecycle: internal HistoryService responsibilities."""

from __future__ import annotations
import asyncio
import logging
import os
from stores.history_db import HistoryDB

log = logging.getLogger("chatbot")


class HistoryLifecycle:
    async def init(self):
        await self.db.init()
        await self.migrate_install()
        await self.load_app_settings()
        self._apply_world_media_dir()
        if self._labels is not None:
            try:
                await self._labels.load_from_db(self.db)
            except Exception as exc:
                log.warning("label load from %s failed: %s", self.db.path, exc)
        await self.load_gaze()
        try:
            os.makedirs(self.world_media_dir(), exist_ok=True)
        except OSError as exc:
            log.warning("media cache folder unavailable: %s", exc)
        try:
            moved = await self.media.migrate_layout()
            retried = await self.media.retry_failed_uncached()
            if moved:
                log.info(
                    "moved %d cached file(s) into the per-person media tree", moved
                )
            if retried:
                log.info(
                    "re-queued %d media row(s) for the CORS-free downloader", retried
                )
        except Exception as exc:
            log.warning("media layout migration skipped: %s", exc)
        await self._install_push_binding()
        connected = getattr(self.cdp, "connected", None)
        disconnected = getattr(self.cdp, "disconnected", None)
        if connected is not None and hasattr(connected, "connect"):
            connected.connect(lambda: asyncio.ensure_future(self._rebind()))
        if disconnected is not None and hasattr(disconnected, "connect"):
            disconnected.connect(self._on_disconnected)
        log.info(
            "Message archive ready: %s (fts=%s, world=%s)",
            self.db.path,
            self.db.fts_enabled,
            self.world_media_dir(),
        )
        return self

    async def close(self) -> None:
        await self._stop_collector()
        try:
            await self.save_gaze()
            if self._labels is not None:
                await self._labels.flush_to_db()
        except Exception as exc:
            log.warning("world flush on close failed: %s", exc)
        if self.db.is_open:
            await self.db.close()

    def _rebind_db(self, db: HistoryDB) -> None:
        self.db = db
        self.repo.db = self.query.db = self.media.db = db

    async def _flush_labels(self) -> None:
        if self._labels is None:
            return
        try:
            await self._labels.flush_to_db()
        except Exception as exc:
            log.warning("label flush failed: %s", exc)

    async def _load_world_state(self) -> None:
        await self.load_app_settings()
        self._apply_world_media_dir()
        await self._flush_labels()
        if self._labels is not None:
            try:
                await self._labels.load_from_db(self.db)
            except Exception as exc:
                log.warning("label load from %s failed: %s", self.db.path, exc)
        await self.load_gaze()

    async def detach_db(self) -> bool:
        self._detached_running = await self._stop_collector()
        if self.db.is_open:
            await self.db.close()
        return True

    async def switch_db(self, path: str) -> dict:
        target = str(path or "").strip()
        if not target:
            raise ValueError("no database path given")
        previous = self.db.path
        parked = (
            getattr(self, "_detached_running", None) or await self._stop_collector()
        )
        self._detached_running = None
        try:
            await self.save_gaze()
        except Exception:
            pass
        await self._flush_labels()
        if self.db.is_open:
            await self.db.close()
        fresh = HistoryDB(target, use_fts=bool(self._settings.get("use_fts", True)))
        try:
            if self.memory is not None:
                await self.memory.switch_db(target)
            await fresh.init()
        except Exception as exc:
            log.warning("cannot open %s (%s) — reopening %s", target, exc, previous)
            fallback = HistoryDB(
                previous, use_fts=bool(self._settings.get("use_fts", True))
            )
            try:
                await fallback.init()
                if self.memory is not None:
                    try:
                        await self.memory.switch_db(previous)
                    except Exception as inner:
                        log.warning("queue reopen on %s failed: %s", previous, inner)
                self._rebind_db(fallback)
                try:
                    await self._load_world_state()
                except Exception as inner:
                    log.warning("reloading previous world state failed: %s", inner)
            except Exception as inner:
                log.error("reopening %s failed too: %s", previous, inner)
            self._restart_collector(parked)
            raise
        self._rebind_db(fresh)
        self._settings["db_path"] = target
        if self.config is not None:
            self.config.set(
                "history", {k: v for k, v in self._settings.items() if k != "collector"}
            )
            self.config.save()
        try:
            self.collector.reset_state()
        except Exception:
            pass
        await self._load_world_state()
        self._restart_collector(parked)
        log.info("Message archive switched to %s (world restart complete)", target)
        return self.settings()
