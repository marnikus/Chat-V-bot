"""Making the partner exist in both places.

Owns the archive-plus-People-Memory registration of whoever is on the
other side of the conversation, and the `history_appended` announcement
after a sync. Built from the aggregate only; `repo` and `memory` stay on
`Collector`.
"""

from __future__ import annotations

import json
import logging

from typing import Optional

from backend.history_query import HistoryQuery
from stores.user_memory import UserRecord

log = logging.getLogger("chatbot")


class PartnerMemory:
    """One responsibility of `Collector`, built from it."""

    def __init__(self, owner):
        self._o = owner

    def person_cleared(self, nick: str) -> None:
        """The archive history of `nick` was just cleared in the UI.

        The cursor is already reset on the write path, so the next tick
        re-reads the conversation from scratch; here we only stop showing
        the old totals in the Radar window (Bug 4, 2026-09-08).
        """
        clean = " ".join(str(nick or "").split()).strip()
        if not clean or self._o._nick != clean:
            return
        self._o._total = 0
        self._o._added = 0
        self._o._last_sync_reason = "history_cleared"
        self._o._last_sync_added = 0
        self._o._last_sync_count = 0
        self._o._emit()

    async def _remember_partner(self, nick: str, state: Optional[dict] = None) -> str:
        """Make sure the partner exists in BOTH the archive and the People list.

        The archive person is created by `HistoryRepo.ensure_person` regardless
        of whether any message lines were written yet; the People Memory row is
        only added when this app owns a UserMemory (production does, tests may
        not). Nothing is marked messaged — appearing in a private chat is not
        the same as having been messaged by an action run.
        """
        clean = self._o.repo.normalise_nick(nick)
        await self._o.repo.ensure_person(clean)
        if self._o.memory is None:
            return "archive_only"
        try:
            existing = await self._o.memory.get_user(clean)
            if existing:
                # refresh last_seen without touching the messaged flag
                await self._o.memory.upsert_user(
                    UserRecord(nick=clean,
                               gender=existing.gender,
                               registered=existing.registered,
                               anonymous=existing.anonymous,
                               guest=existing.guest,
                               messaged=existing.messaged,
                               message_count=existing.message_count,
                               last_messaged=existing.last_messaged,
                               notes=existing.notes))
                return "known"
            result = await self._o.memory.upsert_user(UserRecord(nick=clean))
            if result == "new":
                self._o._notify_people(clean, "new")
            return result
        except Exception as e:                       # noqa: BLE001
            log.warning("cannot add %s to the People list: %s", clean, e)
            return "error"

    async def _notify_appended(self, nick: str, items: list, added: int,
                               total: int) -> None:
        """Emit UI-shaped rows, never the raw parser records.

        The UI rows need `ord`, `day`, `time` and the joined media fields;
        `AppendResult.records` now carries that shape from the write.  If it
        is somehow empty, re-read the newest page from SQLite as a fallback.
        """
        live = list(items or [])[:200]
        if not live:
            try:
                page = await HistoryQuery(self._o.repo.db).page(
                    nick, limit=min(200, max(50, added or 50)))
                live = page.get("items") or []
                if page.get("total") is not None:
                    total = int(page.get("total") or 0)
            except Exception as e:                    # noqa: BLE001
                log.debug("live history page for %s failed: %s", nick, e)
        try:
            self._o.history_appended.emit(json.dumps(
                {"nick": nick, "my_nick": self._o.my_nick, "items": live,
                 "added": added, "total": total}, ensure_ascii=False))
        except Exception as e:                        # noqa: BLE001
            log.debug("history_appended emit failed: %s", e)
