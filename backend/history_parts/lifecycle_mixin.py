"""Lifecycle — init/close/start + migrate_install (<150)."""
import asyncio, logging, os
log = logging.getLogger("chatbot")
class HistoryLifecycleMixin:
    async def init(self) -> "HistoryLifecycleMixin":
        await self.db.init(); await self.migrate_install(); await self.load_app_settings(); self._apply_world_media_dir()
        if self._labels is not None:
            try: await self._labels.load_from_db(self.db)
            except Exception as exc: log.warning("label load from %s failed: %s", self.db.path, exc)
        await self.load_gaze()
        folder = self.world_media_dir()
        if folder:
            try: os.makedirs(folder, exist_ok=True)
            except OSError as e: log.warning("media cache folder unavailable: %s", e)
        try:
            moved = await self.media.migrate_layout()
            if moved: log.info("moved %d cached file(s) into per-person media tree", moved)
            retried = await self.media.retry_failed_uncached()
            if retried: log.info("re-queued %d media row(s) for CORS-free downloader", retried)
        except Exception as e: log.warning("media layout migration skipped: %s", e)
        await self._install_push_binding()
        connected = getattr(self.cdp, "connected", None)
        if connected is not None and hasattr(connected, "connect"): connected.connect(lambda: asyncio.ensure_future(self._rebind()))
        disconnected = getattr(self.cdp, "disconnected", None)
        if disconnected is not None and hasattr(disconnected, "connect"): disconnected.connect(self._on_disconnected)
        log.info("Message archive ready: %s (fts=%s, world=%s)", self.db.path, self.db.fts_enabled, self.world_media_dir()); return self
    async def close(self) -> None:
        self.collector.stop()
        if self._task:
            self._task.cancel()
            try: await self._task
            except (asyncio.CancelledError, Exception): pass
            self._task = None
        try:
            await self.save_gaze()
            if self._labels is not None: await self._labels.flush_to_db()
        except Exception as exc: log.warning("world flush on close failed: %s", exc)
        await self.db.close()
    async def _install_push_binding(self) -> None:
        if self._binding or not hasattr(self.cdp, "add_binding"): return
        try: ok = await self.cdp.add_binding("__cvbPush")
        except Exception as e: log.debug("push binding unavailable: %s", e); return
        if not ok: return
        self._binding = True
        if hasattr(self.cdp, "on_event"): self.cdp.on_event("Runtime.bindingCalled", self._on_binding)
    async def _rebind(self) -> None: self._binding = False; await self._install_push_binding()
    def _on_disconnected(self) -> None: self._binding = False
    def _on_binding(self, params: dict):
        if (params or {}).get("name") != "__cvbPush": return None
        return self.collector.handle_push((params or {}).get("payload") or "")
    def start(self) -> None:
        if self._task and not self._task.done(): return
        if not self.enabled: return
        self._task = asyncio.ensure_future(self.collector.run())
    async def migrate_install(self) -> dict:
        report = {"queue_merged": False, "labels_imported": False, "recent_pruned": False, "undo_rehomed": False}
        if self.config is None: return report
        memory = self.memory
        if memory is not None:
            legacy = str(getattr(memory, "db_path", "") or "")
            if legacy and os.path.exists(legacy) and os.path.abspath(legacy) != os.path.abspath(self.db.path):
                try: await self._merge_legacy_queue(legacy); report["queue_merged"] = True
                except Exception as exc: log.warning("queue merge from %s failed: %s", legacy, exc)
        if self._labels is not None and not await self.get_meta_flag("labels_migrated_from_config"):
            try:
                if await self._import_config_labels(): report["labels_imported"] = True; await self.set_meta_flag("labels_migrated_from_config")
            except Exception as exc: log.warning("label import from config failed: %s", exc)
        try:
            raw = self.config.get_state("db_recent", [])
            if isinstance(raw, list):
                kept = [p for p in raw if isinstance(p, str) and p and os.path.exists(p)]
                if len(kept) != len(raw): self.config.set_state(db_recent=kept[:12]); report["recent_pruned"] = True
        except Exception as exc: log.debug("db_recent prune failed: %s", exc)
        if not await self.get_meta_flag("undo_migrated_v6"):
            try:
                if await self._rehome_undo_entries(): report["undo_rehomed"] = True; await self.set_meta_flag("undo_migrated_v6")
            except Exception as exc: log.warning("undo re-home failed: %s", exc)
        if any(report.values()): log.info("unified-DB migration: %s", ", ".join(k for k, v in report.items() if v))
        return report
    async def get_meta_flag(self, key: str) -> bool:
        try: v = await self.db.get_meta(key, None); return v is not None and str(v) != ""
        except Exception: return False
    async def set_meta_flag(self, key: str) -> None:
        try: await self.db.set_meta(key, "1"); await self.db.commit()
        except Exception as exc: log.warning("cannot set migration flag %s: %s", key, exc)
