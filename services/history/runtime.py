"""HistoryService runtime collaborators (AREA C extraction).

`HistoryExportService` was four services stapled together. Each is now a
small collaborator that holds a reference to the host `HistoryService` and
mutates its attributes exactly where the old methods did:

    PushBindings      the CDP push channel (_install_push_binding / _rebind /
                      _on_disconnected / _on_binding)
    CollectorRuntime  start / _stop_collector / _restart_collector
    WorldSwitcher     detach_db / switch_db (fail closed) + the state reload
    HistoryMigration  migrate_install (queue merge, label import, recent
                      prune, undo re-home)
    ChatExporter      export_chat (json / text / csv)

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
        host = self._host
        await host.load_app_settings()
        host._apply_world_media_dir()
        await self._flush_labels()
        if host._labels is not None:
            try:
                await host._labels.load_from_db(host.db)
            except Exception as exc:                   # noqa: BLE001
                log.warning("label load from %s failed: %s", host.db.path,
                            exc)
        await host.load_gaze()

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
        try:
            await host.save_gaze()
        except Exception:                              # noqa: BLE001
            pass
        await self._flush_labels()
        if host.db.is_open:
            await host.db.close()
        fresh = HistoryDB(target,
                          use_fts=bool(host._settings.get("use_fts", True)))
        try:
            if host.memory is not None:
                await host.memory.switch_db(target)
            await fresh.init()
        except Exception as exc:
            log.warning("cannot open %s (%s) — reopening %s", target, exc,
                        previous)
            fallback = HistoryDB(previous, use_fts=bool(
                host._settings.get("use_fts", True)))
            try:
                await fallback.init()
                if host.memory is not None:
                    try:
                        await host.memory.switch_db(previous)
                    except Exception as inner:         # noqa: BLE001
                        log.warning("queue reopen on %s failed: %s",
                                    previous, inner)
                self._rebind_db(fallback)
                try:
                    await self._load_world_state()
                except Exception as inner:             # noqa: BLE001
                    log.warning("reloading previous world state failed: %s",
                                inner)
            except Exception as inner:                 # noqa: BLE001
                log.error("reopening %s failed too: %s", previous, inner)
            host._restart_collector(parked)
            raise
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


class HistoryMigration:
    """The one-time unified-DB install migration."""

    def __init__(self, host):
        self._host = host

    async def run(self) -> dict:
        """Merge a legacy queue / labels / prune ghosts / re-home undo."""
        host = self._host
        report = {"queue_merged": False, "labels_imported": False,
                  "recent_pruned": False, "undo_rehomed": False}
        if host.config is None:
            return report
        if await self._merge_queue(report):
            report["queue_merged"] = True
        await self._import_labels(report)
        await self._prune_recent(report)
        await self._rehome_undo(report)
        if any(report.values()):
            log.info("unified-DB migration: %s",
                     ", ".join(k for k, v in report.items() if v))
        return report

    async def _merge_queue(self, report: dict) -> bool:
        host = self._host
        legacy = str(getattr(host.memory, "db_path", "") or "") \
            if host.memory is not None else ""
        if not (legacy and os.path.exists(legacy)
                and os.path.abspath(legacy) != os.path.abspath(host.db.path)):
            return False
        try:
            await host._merge_legacy_queue(legacy)
            return True
        except Exception as exc:                       # noqa: BLE001
            log.warning("queue merge from %s failed: %s", legacy, exc)
            return False

    async def _import_labels(self, report: dict) -> None:
        host = self._host
        if host._labels is None or \
                await host.get_meta_flag("labels_migrated_from_config"):
            return
        try:
            if await host._import_config_labels():
                report["labels_imported"] = True
                await host.set_meta_flag("labels_migrated_from_config")
        except Exception as exc:                       # noqa: BLE001
            log.warning("label import from config failed: %s", exc)

    async def _prune_recent(self, report: dict) -> None:
        host = self._host
        try:
            raw = host.config.get_state("db_recent", [])
            if isinstance(raw, list):
                kept = [p for p in raw
                        if isinstance(p, str) and p and os.path.exists(p)]
                if len(kept) != len(raw):
                    host.config.set_state(db_recent=kept[:12])
                    report["recent_pruned"] = True
        except Exception as exc:                       # noqa: BLE001
            log.debug("db_recent prune failed: %s", exc)

    async def _rehome_undo(self, report: dict) -> None:
        host = self._host
        if await host.get_meta_flag("undo_migrated_v6"):
            return
        try:
            if await host._rehome_undo_entries():
                report["undo_rehomed"] = True
                await host.set_meta_flag("undo_migrated_v6")
        except Exception as exc:                       # noqa: BLE001
            log.warning("undo re-home failed: %s", exc)


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
