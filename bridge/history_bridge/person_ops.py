"""Whole-person archive operations that are not a removal.

`PersonOpsMixin` owns the permanent purge of the hidden rows, the
restore of a soft-deleted person, the merge of one conversation into
another, and the two People-list helpers the removals read
(`_people_snapshot` before/after, `_refresh_people` when the list moved).
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import Slot

from core.events import LogMessage

log = logging.getLogger("chatbot")


class PersonOpsMixin:
    @Slot(str, result=bool)
    def history_purge_deleted(self, nick):
        if self.ctx.archive is None:
            return False

        async def work():
            gone = await self.ctx.archive.repo.purge_deleted(
                " ".join(str(nick or "").split()).strip())
            self.ctx.bus.emit(LogMessage(
                message=f"🔥 {gone} hidden message(s) erased permanently",
                level="warn"))
            self.userdb_changed.emit(json.dumps(
                {"action": "purged", "nick": nick, "count": gone},
                ensure_ascii=False))
        self._run_async("history_purge_deleted", work())
        return True

    @Slot(str, result=bool)
    def history_restore_person(self, nick):
        if self.ctx.archive is None:
            return False

        async def work():
            ok = await self.ctx.archive.repo.restore_person(nick)
            self.userdb_changed.emit(json.dumps(
                {"action": "restored", "nick": nick, "ok": ok},
                ensure_ascii=False))
            self._refresh_people()
        self._run_async("history_restore_person", work())
        return True

    @Slot(str, str, result=bool)
    def history_merge(self, from_nick, into_nick):
        if self.ctx.archive is None:
            return False

        async def work():
            moved = await self.ctx.archive.repo.merge_persons(from_nick,
                                                              into_nick)
            self.userdb_changed.emit(json.dumps(
                {"action": "merged", "nick": into_nick, "from": from_nick,
                 "moved": moved}, ensure_ascii=False))
        self._run_async("history_merge", work())
        return True

    # ── helpers ──────────────────────────────────────────────────
    async def _people_snapshot(self):
        if self.ctx.memory is None:
            return None
        try:
            return await self.ctx.people.rows()
        except Exception as exc:                         # noqa: BLE001
            log.debug("people snapshot unavailable: %s", exc)
            return None

    def _refresh_people(self) -> None:
        from core.events import PeopleChanged
        self.ctx.bus.emit(PeopleChanged(reason="archive"))
