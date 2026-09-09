"""DbBridge — database connection (create/load/delete/clean)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from PySide6.QtCore import QObject, Signal, Slot
try:
    from qasync import asyncSlot
except Exception:
    asyncSlot = lambda *a, **kw: (lambda f: f)

from backend.db_manager import DbManager

log = logging.getLogger("chatbot")


class DbBridge(QObject):
    db_info_ready = Signal(str, str)
    db_changed = Signal(str)
    log_message = Signal(str, str)
    userdb_changed = Signal(str)

    def __init__(self, ctx: dict, parent=None):
        super().__init__(parent)
        self._config = ctx.get("config")
        self._history = None
        self._dbs = DbManager(config=self._config)

    def attach_history(self, service):
        self._history = service
        self._dbs.attach(service)

    @property
    def db_manager(self): return self._dbs

    @Slot(result=str)
    def db_list(self):
        try: return json.dumps({"active": self._dbs.active_path(), "items": self._dbs.list_dbs()}, ensure_ascii=False)
        except Exception as exc: return json.dumps({"active":"", "items":[], "error": str(exc)})

    @Slot(str)
    def db_info(self, req_id):
        async def work():
            payload=await self._dbs.info(); payload["req_id"]=req_id; payload["items"]=self._dbs.list_dbs()
            self.db_info_ready.emit(req_id, json.dumps(payload, ensure_ascii=False))
        asyncio.ensure_future(work())

    def _emit(self, action, result):
        payload=dict(result or {}); payload["action"]=action
        self.db_changed.emit(json.dumps(payload, ensure_ascii=False))
        self.userdb_changed.emit(json.dumps({"action":"db_"+action,"ok":bool(payload.get("ok"))}, ensure_ascii=False))

    @Slot(str, result=bool)
    def db_create(self, name):
        async def work():
            res=await self._dbs.create(name); self._emit("create", res)
            if res.get("ok"): self.log_message.emit(f"🆕 {name} created","success")
        asyncio.ensure_future(work()); return True

    @Slot(str, result=bool)
    def db_load(self, path):
        async def work():
            res=await self._dbs.load(path); self._emit("load", res)
        asyncio.ensure_future(work()); return True

    @Slot(str, result=bool)
    def db_delete(self, path):
        async def work():
            res=await self._dbs.delete(path); self._emit("delete", res)
        asyncio.ensure_future(work()); return True

    @Slot(result=bool)
    def db_clean(self):
        async def work():
            res=await self._dbs.clean(); self._emit("clean", res)
        asyncio.ensure_future(work()); return True
