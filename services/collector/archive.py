"""The archive side of one tick: sync, partner rows, backfill, gate helpers.

`ArchiveMixin` owns everything that writes or prepares to write: the
`sync_conversation` call, the People-list partner upsert, the manual backfill
entry point, and the two refusal helpers the tick state machine reuses.
"""

import logging
from typing import Optional

from services import collector_service
from stores.user_memory import UserRecord

from .constants import CollectorState

log = logging.getLogger("chatbot")


class ArchiveMixin:
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
                return await collector_service.sync_conversation(
                    self.parser, self.repo, nick, **kwargs)
        return await collector_service.sync_conversation(
            self.parser, self.repo, nick, **kwargs)

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

    async def backfill_older(self) -> str:
        """Force one scroll-to-top full-history pass for the current person."""
        if not self._nick:
            self._log("Backfill needs a partner: open the private chat "
                      "first, then click Backfill older", "warn")
            return self._state
        try:
            await self.repo.reset_cursor(self._nick)
        except Exception as e:                        # noqa: BLE001
            self._error = str(e)
            return self._set(CollectorState.ERROR, f"Backfill failed: {e}")
        self._set(CollectorState.COLLECTING,
                  f"Backfilling older messages from {self._nick}…")
        self._force_backfill = True
        self._backfill_pending = False
        self._log(f"Manual backfill requested for “{self._nick}”", "info",
                  self._nick)
        return await self.tick()

    # ── the gate helpers ─────────────────────────────────────────
    def _refuse(self, state: str, text: str) -> str:
        """Refuse to save: the push channel is disarmed with the tick."""
        self._verified = False
        return self._set(state, text)

    @staticmethod
    def _gate_status(check, nick: str) -> tuple:
        """Turn a failed PrivateCheck into (state, status text)."""
        if check.reason == "strangers":
            shown = ", ".join(check.strangers[:3])
            if len(check.strangers) > 3:
                shown += "…"
            return (CollectorState.GROUP_TAB,
                    f"Not a private chat — {shown} write here too "
                    f"(nothing saved for {nick})")
        if check.reason == "title_mismatch":
            return (CollectorState.NOT_PRIVATE,
                    f"Tab does not match “{nick}” — nothing saved")
        if check.reason == "self_chat":
            return (CollectorState.NOT_PRIVATE,
                    "Partner is ambiguous (same as My Nick)")
        if check.reason == "no_author_data":
            return (CollectorState.NOT_PRIVATE,
                    "Cannot verify this chat yet — nothing saved")
        return (CollectorState.NOT_PRIVATE, "Not in private tab now")
