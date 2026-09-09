"""DbBridge — world database lifecycle: create / load / delete / clean.

Orchestration that is inherently ordered (db op → world restart → undo
entry) lives here in the bridge layer, calling services in sequence.
Deletions are permanent by design (D4): they record no undo entry.
"""

from __future__ import annotations

import json
import logging
import os

from PySide6.QtCore import QObject, Signal, Slot

from core.events import DbChanged, LogMessage
from services.undo_service import emit_db_change, restart_world

log = logging.getLogger("chatbot")


class DbBridge(QObject):
    db_changed = Signal(str)                # JSON {action, path, ok, ...}
    db_info_ready = Signal(str, str)        # req_id, JSON db size info

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        ctx.bus.subscribe(DbChanged,
                          lambda e: self.db_changed.emit(e.payload))

    @property
    def db_manager(self):
        manager = self.ctx.db_manager()
        if self.ctx.archive is not None:
            manager.attach(self.ctx.archive)
        return manager

    @Slot(result=str)
    def db_list(self):
        try:
            return json.dumps({"active": self.db_manager.active_path(),
                               "items": self.db_manager.list_dbs()},
                              ensure_ascii=False)
        except Exception as exc:                        # noqa: BLE001
            log.warning("db_list failed: %s", exc)
            return json.dumps({"active": "", "items": [],
                               "error": str(exc)})

    @Slot(str)
    def db_info(self, req_id):
        manager = self.db_manager

        async def work():
            payload = await manager.info()
            payload["req_id"] = req_id
            payload["items"] = manager.list_dbs()
            self.db_info_ready.emit(req_id, json.dumps(payload,
                                                       ensure_ascii=False))
        self._run_async("db_info", work())

    def _db_action(self, op: str, runner, success: str) -> bool:
        """Run one DB action; reversible ones become one undo entry."""
        manager = self.db_manager

        async def work():
            result = await runner(manager)
            result = dict(result or {})
            result["op"] = result.get("op", op)
            if result.get("ok") and not result.get("unchanged") \
                    and not result.get("offline"):
                if op in ("create", "load", "delete"):
                    # REBUILD the timeline before recording this step
                    # (the in-memory copy still holds the world being LEFT)
                    await restart_world(self.ctx.memory, self.ctx.archive,
                                        self.ctx.label_store(),
                                        self.ctx.undo, self.ctx.bus, op)
                if op != "delete":
                    self.ctx.undo.push("dbconn", {
                        "op": result["op"],
                        "path": result.get("path", ""),
                        "before_path": result.get("before_path", ""),
                        "backup": result.get("backup", ""),
                    })
                self.ctx.bus.emit(LogMessage(message=success.format(**{
                    "path": result.get("path", ""),
                    "name": os.path.basename(result.get("path", "")),
                }), level="success"))
            elif result.get("error"):
                self.ctx.bus.emit(LogMessage(
                    message="⚠ " + str(result["error"]), level="warn"))
            emit_db_change(self.ctx.bus, op, result)
        self._run_async("db_" + op, work())
        return True

    @Slot(str, result=bool)
    def db_create(self, name):
        return self._db_action(
            "create", lambda m: m.create(name),
            "🆕 New database “{name}” created and connected — fresh world")

    @Slot(str, result=bool)
    def db_load(self, path):
        return self._db_action(
            "load", lambda m: m.load(path),
            "🔌 Connected to “{name}” — fresh world")

    @Slot(str, result=bool)
    def db_delete(self, path):
        return self._db_action(
            "delete", lambda m: m.delete(path),
            "🗑 {name} deleted permanently (database + its media)")

    @Slot(result=bool)
    def db_clean(self):
        return self._db_action(
            "clean", lambda m: m.clean(),
            "🧹 Database emptied (a backup went to db_trash — "
            "Ctrl+Z restores it)")

    def _run_async(self, scope: str, coro) -> None:
        async def guarded():
            try:
                await coro
            except Exception as exc:                     # noqa: BLE001
                log.warning("db %s failed: %s", scope, exc)
                from core.events import UserDbChanged
                self.ctx.bus.emit(UserDbChanged(payload=json.dumps(
                    {"action": "error", "ok": False, "error": str(exc)},
                    ensure_ascii=False)))
        try:
            import asyncio
            asyncio.ensure_future(guarded())
        except RuntimeError:
            coro.close()
