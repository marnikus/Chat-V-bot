"""Collector mixin 3d (<150)."""
import asyncio, json, logging
from datetime import datetime
from typing import Optional

class CollectorMixin3d:
    async def _sync(self, nick: str, my_nick: str, bootstrap: bool,
                    backfill_older: bool = False):
        cap = int(self._settings["max_bootstrap"] or 0) if bootstrap else 0
        kwargs = dict(my_nick=my_nick,
                      require_private=bool(self._settings["require_private"]),
                      verify_partner=True,
                      max_messages=cap or None,
                      backfill_older=backfill_older,
                      backfill_wait_s=float(self._settings.get("backfill_wait_s", 2.0)),
                      now=self.now(),
                      media=self.media if self._settings["download_media"] else None)
        if self.lease is not None:
            async with self.lease.low():
                return await sync_conversation(self.parser, self.repo, nick,
                                               **kwargs)
        return await sync_conversation(self.parser, self.repo, nick, **kwargs)

    async def _remember_partner(self, nick: str, state: Optional[dict] = None) -> str:
        """Make sure the partner exists in BOTH the archive and the People list.

        The archive person is created by `HistoryRepo.ensure_person` regardless
        of whether any message lines were written yet; the People Memory row is
        only added when this app owns a UserMemory (production does, tests may
        not). Nothing is marked messaged — appearing in a private chat is not
        the same as having been messaged by an action run.
        """
        clean = self.repo.normalise_nick(nick)
        await self.repo.ensure_person(clean)
        if self.memory is None:
            return "archive_only"
        try:
            existing = await self.memory.get_user(clean)
            if existing:
                # refresh last_seen without touching the messaged flag
                await self.memory.upsert_user(
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
            result = await self.memory.upsert_user(UserRecord(nick=clean))
            if result == "new":
                self._notify_people(clean, "new")
            return result
        except Exception as e:                       # noqa: BLE001
            log.warning("cannot add %s to the People list: %s", clean, e)
            return "error"

    def _log(self, message: str, level: str = "info",
             nick: Optional[str] = None) -> None:
        """One line for the Collector window's own log.

        Kept deliberately separate from `log.debug`: this is user-facing
        (parsing history / trying to identify the nick), not a stack trace.
        """
        try:
            payload = {
                "ts": self.now().strftime("%H:%M:%S"),
                "level": str(level or "info"),
                "message": str(message or ""),
                "nick": nick or self._nick or "",
            }
            self.collector_log.emit(json.dumps(payload, ensure_ascii=False))
        except Exception as e:                       # noqa: BLE001
            log.debug("collector_log emit failed: %s", e)

