"""HistoryExportService — runtime/export mixin (AREA C facade).

The four concerns this mixin used to fold together now live in
`services/history/runtime.py` (PushBindings, CollectorRuntime, WorldSwitcher,
ChatExporter), `migrate.py` (HistoryMigration) and `trash.py` (the
session-sized trash). Every method name and signature here is unchanged —
each delegates to its lazily-created collaborator, so
`HistoryService.__init__` (which deliberately calls no `super().__init__`)
is untouched and callers see the same surface.
"""

from __future__ import annotations

import asyncio
import logging

from services.history.trash import open_world

log = logging.getLogger("chatbot")


class HistoryExportService:
    # ── lazy collaborators ───────────────────────────────────────
    @property
    def _push(self):
        if getattr(self, "__push", None) is None:
            from services.history.runtime import PushBindings
            self.__push = PushBindings(self)
        return self.__push

    @property
    def _runtime(self):
        if getattr(self, "__runtime", None) is None:
            from services.history.runtime import CollectorRuntime
            self.__runtime = CollectorRuntime(self)
        return self.__runtime

    @property
    def _worlds(self):
        if getattr(self, "__worlds", None) is None:
            from services.history.runtime import WorldSwitcher
            self.__worlds = WorldSwitcher(self)
        return self.__worlds

    @property
    def _migrator(self):
        if getattr(self, "__migrator", None) is None:
            from services.history.migrate import HistoryMigration
            self.__migrator = HistoryMigration(self)
        return self.__migrator

    @property
    def _exporter(self):
        if getattr(self, "__exporter", None) is None:
            from services.history.runtime import ChatExporter
            self.__exporter = ChatExporter(self)
        return self.__exporter

    # ── lifecycle ────────────────────────────────────────────────
    async def init(self):
        await self.db.init()
        # Ctrl+Z reaches back only as far as this session: a world a closed
        # run left behind opens without its trash (trash.py, design §2.4)
        await open_world(self)
        await self.migrate_install()
        await self.load_app_settings()
        self._apply_world_media_dir()
        await self._worlds.load_labels()
        await self.load_gaze()
        try:
            import os
            os.makedirs(self.world_media_dir(), exist_ok=True)
        except OSError as exc:
            log.warning("media cache folder unavailable: %s", exc)
        try:
            moved = await self.media.migrate_layout()
            retried = await self.media.retry_failed_uncached()
            if moved:
                log.info("moved %d cached file(s) into the per-person "
                         "media tree", moved)
            if retried:
                log.info("re-queued %d media row(s) for the CORS-free "
                         "downloader", retried)
        except Exception as exc:                       # noqa: BLE001
            log.warning("media layout migration skipped: %s", exc)
        await self._install_push_binding()
        connected = getattr(self.cdp, "connected", None)
        disconnected = getattr(self.cdp, "disconnected", None)
        if connected is not None and hasattr(connected, "connect"):
            connected.connect(
                lambda: asyncio.ensure_future(self._rebind()))
        if disconnected is not None and hasattr(disconnected, "connect"):
            disconnected.connect(self._on_disconnected)
        log.info("Message archive ready: %s (fts=%s, world=%s)", self.db.path,
                 self.db.fts_enabled, self.world_media_dir())
        return self

    async def close(self) -> None:
        await self._stop_collector()
        try:
            await self.save_gaze()
            if self._labels is not None:
                await self._labels.flush_to_db()
        except Exception as exc:                       # noqa: BLE001
            log.warning("world flush on close failed: %s", exc)
        if self.db.is_open:
            await self.db.close()

    # ── push binding ─────────────────────────────────────────────
    async def _install_push_binding(self) -> None:
        await self._push.install()

    async def _rebind(self) -> None:
        await self._push.rebind()

    def _on_disconnected(self) -> None:
        self._push.on_disconnected()

    def _on_binding(self, params: dict):
        return self._push.on_binding(params)

    # ── collector runtime ────────────────────────────────────────
    def start(self) -> None:
        self._runtime.start()

    async def _stop_collector(self) -> dict:
        return await self._runtime.stop()

    def _restart_collector(self, state) -> None:
        self._runtime.restart(state)

    # ── world switching ──────────────────────────────────────────
    def _rebind_db(self, db) -> None:
        self._worlds._rebind_db(db)

    async def _flush_labels(self) -> None:
        await self._worlds._flush_labels()

    async def _load_world_state(self) -> None:
        await self._worlds._load_world_state()

    async def detach_db(self) -> bool:
        return await self._worlds.detach_db()

    async def switch_db(self, path: str) -> dict:
        return await self._worlds.switch_db(path)

    # ── migration ────────────────────────────────────────────────
    async def migrate_install(self) -> dict:
        return await self._migrator.run()

    # ── export ───────────────────────────────────────────────────
    async def export_chat(self, nick: str, fmt: str = "json"):
        return await self._exporter.export(nick, fmt)
