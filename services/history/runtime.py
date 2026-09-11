"""HistoryService runtime collaborators (AREA C extraction).

`HistoryExportService` was four services stapled together. Each is now a
small collaborator that holds a reference to the host `HistoryService` and
mutates its attributes exactly where the old methods did:

    PushBindings      the CDP push channel (_install_push_binding / _rebind /
                      _on_disconnected / _on_binding)
    CollectorRuntime  start / _stop_collector / _restart_collector
    WorldSwitcher     detach_db / switch_db (fail closed) + the state reload
                      (which also sweeps a closed run's trash — trash.py)
    ChatExporter      export_chat (json / text / csv)

HistoryMigration (the one-time install migration) moved to
`services/history/migrate.py` when this file reached the RULE 18 300-line
mark: one file, one responsibility.

`HistoryExportService` keeps every method name as a one-line delegate to a
lazily-created collaborator (memoised property) — no `__init__` change, so
`HistoryService.__init__` (which deliberately calls no `super().__init__`)
stays untouched.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from services.history.trash import open_world
from stores.history_db import HistoryDB

log = logging.getLogger("chatbot")


class PushBindings:
    """The in-page observer push channel (Runtime.bindingCalled)."""

    def __init__(self, host):
        self._host = host

    async def install(self) -> None:
        host = self._host
        if host._binding or not hasattr(host.cdp, "add_binding"):
            return
        try:
            ok = await host.cdp.add_binding("__cvbPush")
        except Exception as exc:                       # noqa: BLE001
            log.debug("push binding unavailable: %s", exc)
            return
        if ok:
            host._binding = True
            if hasattr(host.cdp, "on_event"):
                host.cdp.on_event("Runtime.bindingCalled", host._on_binding)

    async def rebind(self) -> None:
        self._host._binding = False
        await self.install()

    def on_disconnected(self) -> None:
        self._host._binding = False

    def on_binding(self, params: dict):
        if (params or {}).get("name") != "__cvbPush":
            return None
        return self._host.collector.handle_push(
            (params or {}).get("payload") or "")


class CollectorRuntime:
    """The collector heartbeat loop lifetime (start / stop / restart)."""

    def __init__(self, host):
        self._host = host

    def start(self) -> None:
        host = self._host
        if not ((host._task and not host._task.done()) or not host.enabled):
            host._task = asyncio.ensure_future(host.collector.run())

    async def stop(self) -> dict:
        """Stop the collector; returns the state a later restart needs."""
        host = self._host
        state = {"task": bool(host._task and not host._task.done()),
                 "collector": bool(getattr(host.collector, "running",
                                           False))}
        host.collector.stop()
        if host._task:
            host._task.cancel()
            try:
                await host._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            host._task = None
        return state

    def restart(self, state) -> None:
        if state and state.get("task"):
            self.start()
        elif state and state.get("collector"):
            self._host.collector.start()


class WorldSwitcher:
    """Switch the archive to another world file; fail closed."""

    def __init__(self, host):
        self._host = host

    def _rebind_db(self, db: HistoryDB) -> None:
        host = self._host
        host.db = db
        host.repo.db = host.query.db = host.media.db = db

    async def _flush_labels(self) -> None:
        host = self._host
        if host._labels is None:
            return
        try:
            await host._labels.flush_to_db()
        except Exception as exc:                       # noqa: BLE001
            log.warning("label flush failed: %s", exc)

    async def _load_world_state(self) -> None:
        """Reload what follows the world file; a switched-in world sweeps first."""
        host = self._host
        await open_world(host)
        await host.load_app_settings()
        host._apply_world_media_dir()
        await self._flush_labels()
        await self.load_labels()
        await host.load_gaze()

    async def load_labels(self) -> None:
        """Load this world's labels; a broken store must not block the open."""
        host = self._host
        if host._labels is None:
            return
        try:
            await host._labels.load_from_db(host.db)
        except Exception as exc:                       # noqa: BLE001
            log.warning("label load from %s failed: %s", host.db.path, exc)

    async def detach_db(self) -> bool:
        host = self._host
        host._detached_running = await host._stop_collector()
        if host.db.is_open:
            await host.db.close()
        return True

    async def switch_db(self, path: str) -> dict:
        host = self._host
        target = str(path or "").strip()
        if not target:
            raise ValueError("no database path given")
        previous = host.db.path
        parked = getattr(host, "_detached_running", None) \
            or await host._stop_collector()
        host._detached_running = None
        await self._teardown_world()
        try:
            fresh = await self._open_target(target)
        except Exception as exc:
            log.warning("cannot open %s (%s) — reopening %s", target, exc,
                        previous)
            await self._rollback_open(previous)
            host._restart_collector(parked)
            raise
        return await self._commit_target(fresh, target, parked)

    async def _teardown_world(self) -> None:
        """Persist what the old world holds and close its DB."""
        host = self._host
        try:
            await host.save_gaze()
        except Exception:                              # noqa: BLE001
            pass
        await self._flush_labels()
        if host.db.is_open:
            await host.db.close()

    async def _open_target(self, target: str) -> HistoryDB:
        """Bind memory to `target` and open its fresh DB (raises on failure)."""
        host = self._host
        fresh = HistoryDB(target,
                          use_fts=bool(host._settings.get("use_fts", True)))
        if host.memory is not None:
            await host.memory.switch_db(target)
        await fresh.init()
        return fresh

    async def _rollback_open(self, previous: str) -> None:
        """Re-open the previous world after the target failed; best effort."""
        fallback = HistoryDB(previous, use_fts=bool(
            self._host._settings.get("use_fts", True)))
        try:
            await fallback.init()
            await self._warn_memory_switch(previous)
            self._rebind_db(fallback)
            await self._warn_load_world_state()
        except Exception as inner:                     # noqa: BLE001
            log.error("reopening %s failed too: %s", previous, inner)

    async def _warn_memory_switch(self, target: str) -> None:
        if self._host.memory is None:
            return
        try:
            await self._host.memory.switch_db(target)
        except Exception as inner:                     # noqa: BLE001
            log.warning("queue reopen on %s failed: %s", target, inner)

    async def _warn_load_world_state(self) -> None:
        try:
            await self._load_world_state()
        except Exception as inner:                     # noqa: BLE001
            log.warning("reloading previous world state failed: %s", inner)

    async def _commit_target(self, fresh: HistoryDB, target: str,
                             parked) -> dict:
        """Install the new world: rebind, persist settings, restart."""
        host = self._host
        self._rebind_db(fresh)
        host._settings["db_path"] = target
        if host.config is not None:
            host.config.set("history", {k: v for k, v in host._settings.items()
                                        if k != "collector"})
            host.config.save()
        try:
            host.collector.reset_state()
        except Exception:                              # noqa: BLE001
            pass
        await self._load_world_state()
        host._restart_collector(parked)
        log.info("Message archive switched to %s (world restart complete)",
                 target)
        return host.settings()


class ChatExporter:
    """export_chat — the json / text / csv export shapes."""

    def __init__(self, host):
        self._host = host

    async def export(self, nick: str, fmt: str = "json"):
        page = await self._host.query.page(nick, limit=500)
        items = page.get("items") or []
        if fmt == "text":
            return "\n".join(
                f"[{i.get('time', '')}] {i.get('from', '')}: "
                f"{i.get('text', '')}" for i in items)
        if fmt == "csv":
            rows = ["time,from,text"] + [
                json.dumps([i.get("time", ""), i.get("from", ""),
                            i.get("text", "")], ensure_ascii=False)[1:-1]
                for i in items]
            return "\n".join(rows)
        return json.dumps(page, ensure_ascii=False)
