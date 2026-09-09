"""PeopleBridge — the People table: list payload, deletions, marks.

@Slot methods for the people domain. The PeopleService (services/) owns
the business logic; this bridge forwards PeopleChanged / UsersDeleted
events and the engine's live-collection Qt signals to JS.
"""

from __future__ import annotations

import asyncio
import json
import logging

from PySide6.QtCore import QObject, Signal, Slot

from core.events import PeopleChanged, UsersDeleted
from core.result import Ok

log = logging.getLogger("chatbot")


class PeopleBridge(QObject):
    users_updated = Signal(str)
    stats_updated = Signal(str)
    users_deleted = Signal(str, int)         # JSON nicks, deleted count
    person_found = Signal(str)               # JSON: one newly collected person
    person_removed = Signal(str)             # JSON: one purged person

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        ctx.bus.subscribe(PeopleChanged, lambda e: self._refresh())
        ctx.bus.subscribe(UsersDeleted,
                          lambda e: self.users_deleted.emit(e.nicks_json,
                                                           e.count))
        self._connect_engine(ctx.engine)

    def _connect_engine(self, engine) -> None:
        if engine is None:
            return
        try:
            engine.person_found.connect(self._on_person_found)
            engine.person_removed.connect(self._on_person_removed)
            engine.person_marked.connect(self._on_person_marked)
            engine.stack_complete.connect(
                lambda: self._refresh())
        except Exception as exc:                         # noqa: BLE001
            log.debug("engine people signals not connected: %s", exc)

    # ── live collection hooks ────────────────────────────────────
    def _on_person_found(self, payload: str) -> None:
        self.person_found.emit(payload)
        self._refresh()

    def _on_person_removed(self, payload: str) -> None:
        self.person_removed.emit(payload)
        self._refresh()

    def _on_person_marked(self, nick: str) -> None:
        self._refresh()

    # ── refresh ──────────────────────────────────────────────────
    def _refresh(self) -> None:
        """Fire-and-forget refresh (signal/event handlers)."""
        self._schedule(self._refresh_users_async())

    async def _refresh_users_async(self) -> None:
        """The awaited refresh: one users_updated + one stats_updated."""
        if self.ctx.memory is None:       # archive-only bridges (tests)
            return
        result = await self.ctx.people.payload()
        if result.is_ok:
            payload = result.value
            self.users_updated.emit(json.dumps(payload["users"],
                                               ensure_ascii=False))
            self.stats_updated.emit(json.dumps(payload["stats"]))

    @staticmethod
    def _schedule(coro) -> None:
        try:
            asyncio.ensure_future(coro)
        except RuntimeError:
            coro.close()

    # ── slots ────────────────────────────────────────────────────
    @Slot()
    def refresh_users(self):
        """Explicit refresh so the people list is filled on app start too."""
        self._refresh()

    @Slot(str)
    def delete_user(self, nick):
        self._schedule(self._do_delete_one(nick))

    @Slot(str)
    def delete_users(self, nicks_json):
        try:
            nicks = json.loads(nicks_json or "[]")
        except json.JSONDecodeError:
            from core.events import LogMessage
            self.ctx.bus.emit(LogMessage(
                message="❌ Delete aborted: bad selection payload",
                level="error"))
            return
        if not isinstance(nicks, list):
            from core.events import LogMessage
            self.ctx.bus.emit(LogMessage(
                message="❌ Delete aborted: selection is not a list",
                level="error"))
            return
        self._schedule(self._do_delete_many([str(n) for n in nicks]))

    @Slot(str, bool)
    def set_user_messaged(self, nick, messaged):
        self._schedule(self._do_set_messaged(nick, bool(messaged)))

    @Slot()
    def reset_messaged(self):
        self._schedule(self._do_reset())

    @Slot()
    def clear_memory(self):
        self._schedule(self._do_clear())

    # ── legacy instance methods used by tests ────────────────────
    # Each mutation ends with the AWAITED refresh, exactly as the
    # pre-split bridge did: callers can read the payload right after.
    async def _refresh_users(self):
        await self._refresh_users_async()

    async def _do_delete_one(self, nick):
        await self.ctx.people.delete_one(nick)
        await self._refresh_users_async()

    async def _do_delete_many(self, nicks):
        await self.ctx.people.delete_many(nicks)
        await self._refresh_users_async()

    async def _do_set_messaged(self, nick, messaged):
        await self.ctx.people.set_messaged(nick, messaged)
        await self._refresh_users_async()

    async def _do_reset(self):
        await self.ctx.people.reset_messaged()
        await self._refresh_users_async()

    async def _do_clear(self):
        await self.ctx.people.clear_all()
        await self._refresh_users_async()
