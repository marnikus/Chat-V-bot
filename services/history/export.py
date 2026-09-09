from __future__ import annotations
import asyncio, json, logging, os
from stores.history_db import HistoryDB
log = logging.getLogger("chatbot")

class HistoryExportService:
    async def init(self):
        await self.db.init(); await self.migrate_install(); await self.load_app_settings(); self._apply_world_media_dir()
        if self._labels is not None:
            try: await self._labels.load_from_db(self.db)
            except Exception as exc: log.warning("label load from %s failed: %s", self.db.path, exc)
        await self.load_gaze()
        try: os.makedirs(self.world_media_dir(), exist_ok=True)
        except OSError as exc: log.warning("media cache folder unavailable: %s", exc)
        try:
            moved = await self.media.migrate_layout(); retried = await self.media.retry_failed_uncached()
            if moved: log.info("moved %d cached file(s) into the per-person media tree", moved)
            if retried: log.info("re-queued %d media row(s) for the CORS-free downloader", retried)
        except Exception as exc: log.warning("media layout migration skipped: %s", exc)
        await self._install_push_binding()
        connected = getattr(self.cdp, "connected", None); disconnected = getattr(self.cdp, "disconnected", None)
        if connected is not None and hasattr(connected, "connect"): connected.connect(lambda: asyncio.ensure_future(self._rebind()))
        if disconnected is not None and hasattr(disconnected, "connect"): disconnected.connect(self._on_disconnected)
        log.info("Message archive ready: %s (fts=%s, world=%s)", self.db.path, self.db.fts_enabled, self.world_media_dir())
        return self

    async def close(self) -> None:
        await self._stop_collector()
        try:
            await self.save_gaze()
            if self._labels is not None: await self._labels.flush_to_db()
        except Exception as exc: log.warning("world flush on close failed: %s", exc)
        if self.db.is_open: await self.db.close()

    async def _install_push_binding(self) -> None:
        if self._binding or not hasattr(self.cdp, "add_binding"): return
        try: ok = await self.cdp.add_binding("__cvbPush")
        except Exception as exc:
            log.debug("push binding unavailable: %s", exc); return
        if ok:
            self._binding = True
            if hasattr(self.cdp, "on_event"): self.cdp.on_event("Runtime.bindingCalled", self._on_binding)

    async def _rebind(self) -> None:
        self._binding = False; await self._install_push_binding()

    def _on_disconnected(self) -> None:
        self._binding = False

    def _on_binding(self, params: dict):
        return None if (params or {}).get("name") != "__cvbPush" else self.collector.handle_push((params or {}).get("payload") or "")

    def start(self) -> None:
        if not ((self._task and not self._task.done()) or not self.enabled): self._task = asyncio.ensure_future(self.collector.run())

    async def migrate_install(self) -> dict:
        report = {"queue_merged": False, "labels_imported": False, "recent_pruned": False, "undo_rehomed": False}
        if self.config is None: return report
        legacy = str(getattr(self.memory, "db_path", "") or "") if self.memory is not None else ""
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
                kept = [path for path in raw if isinstance(path, str) and path and os.path.exists(path)]
                if len(kept) != len(raw): self.config.set_state(db_recent=kept[:12]); report["recent_pruned"] = True
        except Exception as exc: log.debug("db_recent prune failed: %s", exc)
        if not await self.get_meta_flag("undo_migrated_v6"):
            try:
                if await self._rehome_undo_entries(): report["undo_rehomed"] = True; await self.set_meta_flag("undo_migrated_v6")
            except Exception as exc: log.warning("undo re-home failed: %s", exc)
        if any(report.values()): log.info("unified-DB migration: %s", ", ".join(k for k, v in report.items() if v))
        return report

    async def _stop_collector(self) -> dict:
        state = {"task": bool(self._task and not self._task.done()), "collector": bool(getattr(self.collector, "running", False))}
        self.collector.stop()
        if self._task:
            self._task.cancel()
            try: await self._task
            except (asyncio.CancelledError, Exception): pass
            self._task = None
        return state

    def _restart_collector(self, state) -> None:
        if state and state.get("task"): self.start()
        elif state and state.get("collector"): self.collector.start()

    def _rebind_db(self, db: HistoryDB) -> None:
        self.db = db; self.repo.db = self.query.db = self.media.db = db

    async def _flush_labels(self) -> None:
        if self._labels is None: return
        try: await self._labels.flush_to_db()
        except Exception as exc: log.warning("label flush failed: %s", exc)

    async def _load_world_state(self) -> None:
        await self.load_app_settings(); self._apply_world_media_dir(); await self._flush_labels()
        if self._labels is not None:
            try: await self._labels.load_from_db(self.db)
            except Exception as exc: log.warning("label load from %s failed: %s", self.db.path, exc)
        await self.load_gaze()

    async def detach_db(self) -> bool:
        self._detached_running = await self._stop_collector()
        if self.db.is_open: await self.db.close()
        return True

    async def switch_db(self, path: str) -> dict:
        target = str(path or "").strip()
        if not target: raise ValueError("no database path given")
        previous = self.db.path; parked = getattr(self, "_detached_running", None) or await self._stop_collector(); self._detached_running = None
        try: await self.save_gaze()
        except Exception: pass
        await self._flush_labels()
        if self.db.is_open: await self.db.close()
        fresh = HistoryDB(target, use_fts=bool(self._settings.get("use_fts", True)))
        try:
            if self.memory is not None: await self.memory.switch_db(target)
            await fresh.init()
        except Exception as exc:
            log.warning("cannot open %s (%s) — reopening %s", target, exc, previous)
            fallback = HistoryDB(previous, use_fts=bool(self._settings.get("use_fts", True)))
            try:
                await fallback.init()
                if self.memory is not None:
                    try: await self.memory.switch_db(previous)
                    except Exception as inner: log.warning("queue reopen on %s failed: %s", previous, inner)
                self._rebind_db(fallback)
                try: await self._load_world_state()
                except Exception as inner: log.warning("reloading previous world state failed: %s", inner)
            except Exception as inner: log.error("reopening %s failed too: %s", previous, inner)
            self._restart_collector(parked); raise
        self._rebind_db(fresh); self._settings["db_path"] = target
        if self.config is not None: self.config.set("history", {k: v for k, v in self._settings.items() if k != "collector"}); self.config.save()
        try: self.collector.reset_state()
        except Exception: pass
        await self._load_world_state(); self._restart_collector(parked)
        log.info("Message archive switched to %s (world restart complete)", target)
        return self.settings()

    async def export_chat(self, nick: str, fmt: str = "json"):
        page = await self.query.page(nick, limit=500); items = page.get("items") or []
        if fmt == "text": return "\n".join(f"[{i.get('time','')}] {i.get('from','')}: {i.get('text','')}" for i in items)
        if fmt == "csv":
            rows = ["time,from,text"] + [json.dumps([i.get("time", ""), i.get("from", ""), i.get("text", "")], ensure_ascii=False)[1:-1] for i in items]
            return "\n".join(rows)
        return json.dumps(page, ensure_ascii=False)
