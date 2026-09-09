"""PeopleBridge — People queue (users table) domain."""

from __future__ import annotations

import asyncio
import json
import logging
from PySide6.QtCore import QObject, Signal, Slot
try:
    from qasync import asyncSlot
except Exception:
    asyncSlot = lambda *a, **kw: (lambda f: f)

log = logging.getLogger("chatbot")


class PeopleBridge(QObject):
    users_updated = Signal(str)
    stats_updated = Signal(str)
    users_deleted = Signal(str, int)
    log_message = Signal(str, str)
    history_changed = Signal()

    def __init__(self, ctx: dict, parent=None):
        super().__init__(parent)
        self._memory = ctx.get("memory")
        self._engine = ctx.get("engine")
        self._config = ctx.get("config")
        self._router = ctx.get("router")

    async def _people_rows(self):
        users = await self._memory.get_all()
        return [{"nick": u.nick, "gender": u.gender, "registered": bool(u.registered), "anonymous": bool(u.anonymous), "guest": bool(u.guest), "first_seen": u.first_seen or "", "last_seen": u.last_seen or "", "messaged": bool(u.messaged), "message_count": int(u.message_count or 0), "last_messaged": u.last_messaged, "notes": u.notes or ""} for u in users]

    async def _refresh_users(self):
        if self._memory is None: return
        users = await self._memory.get_all()
        try:
            ordered = self._engine.queue_order(users) if self._engine else []
            ranks = {nick: i+1 for i, nick in enumerate(ordered)}
        except Exception:
            queue = await self._memory.get_queue()
            ranks = {u.nick: i+1 for i, u in enumerate(queue)}
        self.users_updated.emit(json.dumps([{"nick": u.nick, "gender": u.gender, "registered": u.registered, "anonymous": u.anonymous, "guest": u.guest, "messaged": u.messaged, "first_seen": u.first_seen, "last_messaged": u.last_messaged, "order": ranks.get(u.nick)} for u in users], ensure_ascii=False))
        self.stats_updated.emit(json.dumps(await self._memory.get_stats()))

    @Slot()
    def refresh_users(self): asyncio.ensure_future(self._refresh_users())

    @Slot()
    def reset_messaged(self): asyncio.ensure_future(self._do_reset())
    @Slot()
    def clear_memory(self): asyncio.ensure_future(self._do_clear())
    @Slot(str)
    def delete_user(self, nick): asyncio.ensure_future(self._do_delete_one(nick))
    @Slot(str)
    def delete_users(self, nicks_json):
        try: nicks = json.loads(nicks_json or "[]")
        except json.JSONDecodeError: return
        asyncio.ensure_future(self._do_delete_many([str(n) for n in nicks]))
    @Slot(str, bool)
    def set_user_messaged(self, nick, messaged): asyncio.ensure_future(self._do_set_messaged(nick, bool(messaged)))

    async def _do_reset(self):
        c = await self._memory.reset_messaged()
        self.log_message.emit(f"🔄 Reset {c} users", "info")
        await self._refresh_users()
    async def _do_clear(self):
        c = await self._memory.clear_all()
        self.log_message.emit(f"🗑 Cleared {c} users", "warn")
        self.users_deleted.emit("[]", c)
        await self._refresh_users()
    async def _do_delete_one(self, nick):
        nick=(nick or "").strip()
        if not nick: return
        ok=await self._memory.delete_user(nick)
        if ok: self.log_message.emit(f"🗑 Deleted “{nick}”", "warn"); self.users_deleted.emit(json.dumps([nick], ensure_ascii=False),1)
        await self._refresh_users()
    async def _do_delete_many(self, nicks):
        if not nicks: return
        count=await self._memory.delete_users(nicks)
        self.log_message.emit(f"🗑 Deleted {count} selected", "warn")
        self.users_deleted.emit(json.dumps(nicks, ensure_ascii=False), count)
        await self._refresh_users()
    async def _do_set_messaged(self, nick, messaged):
        ok=await self._memory.set_messaged(nick, messaged)
        if ok: self.log_message.emit(f"{'✅' if messaged else '↩'} “{nick}”", "info")
        await self._refresh_users()
