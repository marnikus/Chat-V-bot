"""World B — collector park, switch_db, world state (<150)."""
import asyncio, logging, os
from backend.history_db import HistoryDB
log = logging.getLogger("chatbot")
class HistoryWorldBMixin:
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
        if not state: return
        if state.get("task"): self.start()
        elif state.get("collector"): self.collector.start()
    def _rebind_db(self, db: HistoryDB) -> None:
        self.db = db; self.repo.db = db; self.query.db = db; self.media.db = db
    async def _flush_labels(self) -> None:
        if self._labels is not None:
            try: await self._labels.flush_to_db()
            except Exception as exc: log.warning("label flush failed: %s", exc)
    async def _load_world_state(self) -> None:
        await self.load_app_settings(); self._apply_world_media_dir(); await self._flush_labels()
        if self._labels is not None:
            try: await self._labels.load_from_db(self.db)
            except Exception as exc: log.warning("label load from %s failed: %s", self.db.path, exc)
        await self.load_gaze()
    async def detach_db(self) -> bool:
        self._detached_running = await self._stop_collector(); await self.db.close(); return True
    async def switch_db(self, path: str) -> dict:
        target = str(path or "").strip()
        if not target: raise ValueError("no database path given")
        previous = self.db.path
        parked = getattr(self, "_detached_running", None)
        if parked is None: parked = await self._stop_collector()
        self._detached_running = None
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
        if self.config is not None:
            stored = {k: v for k, v in self._settings.items() if k not in ("collector",)}
            self.config.set("history", stored); self.config.save()
        try: self.collector.reset_state()
        except Exception: pass
        await self._load_world_state(); self._restart_collector(parked)
        log.info("Message archive switched to %s (world restart complete)", target); return self.settings()
