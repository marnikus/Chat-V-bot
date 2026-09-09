"""CollectorBridge — passive chat collector controls."""

from __future__ import annotations

import asyncio
import json
import logging
from PySide6.QtCore import QObject, Signal, Slot

log = logging.getLogger("chatbot")


class CollectorBridge(QObject):
    collector_status = Signal(str)
    collector_log = Signal(str)
    history_appended = Signal(str)
    my_nick_changed = Signal(str)
    log_message = Signal(str, str)
    history_error = Signal(str, str)

    def __init__(self, ctx: dict, parent=None):
        super().__init__(parent)
        self._history = None
        self._config = ctx.get("config")

    def attach_history(self, service):
        self._history = service
        if service:
            try:
                service.collector.status_changed.connect(self.collector_status.emit)
                service.collector.collector_log.connect(self.collector_log.emit)
                service.collector.history_appended.connect(self.history_appended.emit)
            except Exception as exc:  # noqa: BLE001
                log.warning("collector signals not connected: %s", exc)

    @Slot(result=str)
    def collector_state(self):
        if self._history is None:
            return json.dumps({"state":"off","text":"Archive not running","settings":{},"paused":False})
        return json.dumps(self._history.collector.state_payload(), ensure_ascii=False)

    @Slot(str)
    def collector_set(self, settings_json):
        if self._history is None: return
        try: patch=json.loads(settings_json or "{}")
        except json.JSONDecodeError: return
        applied=self._history.collector.configure(**patch)
        stored=self._config.get_copy("collector", default={}) if self._config else {}
        stored.update({k:v for k,v in applied.items()})
        if self._config: self._config.set("collector", stored); self._config.save()
        self.collector_status.emit(json.dumps(self._history.collector.state_payload(), ensure_ascii=False))

    @Slot(str)
    def collector_command(self, command):
        if self._history is None: return
        c=self._history.collector; act=str(command or "").strip().lower()
        if act=="pause": c.pause()
        elif act=="resume": c.resume()
        elif act=="start": c.start(); self._history.start()
        elif act=="stop": c.stop()
        elif act=="tick": asyncio.ensure_future(c.tick())
        elif act in ("backfill_older","backfill"): asyncio.ensure_future(c.backfill_older())
        else: return
        self.collector_status.emit(json.dumps(c.state_payload(), ensure_ascii=False))

    @Slot(result=str)
    def get_my_nick(self):
        return str(self._config.get("collector","my_nick",default="") or "") if self._config else ""

    @Slot(str)
    def set_my_nick(self, nick):
        clean=" ".join(str(nick or "").split()).strip()
        if self._config:
            stored=self._config.get_copy("collector", default={}) or {}
            stored["my_nick"]=clean; self._config.set("collector", stored)
            recent=[n for n in (self._config.get_state("my_nick_recent",[]) or []) if isinstance(n,str) and n and n!=clean]
            if clean: recent.insert(0,clean)
            self._config.set_state(my_nick_recent=recent[:10])
        if self._history: self._history.set_my_nick(clean)
        self.my_nick_changed.emit(clean)
        self.log_message.emit(f"👤 My Nick set to “{clean}”" if clean else "👤 My Nick cleared","info")

    @Slot(str)
    def detect_my_nick(self, req_id):
        if self._history is None: self.history_error.emit("detect_my_nick","archive not running"); return
        async def work():
            state=await self._history.parser.state()
            from PySide6.QtCore import Signal  # noqa: F401
            self.collector_status.emit(json.dumps(state, ensure_ascii=False))
        asyncio.ensure_future(work())
