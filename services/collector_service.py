"""The passive private-chat collector.

A supervisor that watches the active tab without ever blocking the UI. One
cheap heartbeat probe per tick tells it what the page is showing; only when
something actually changed does it read message nodes, and even then in
paced chunks through the shared CDP lease at LOW priority.

Statuses are the vocabulary the feature request asked for:

    Collecting …            work in progress
    Collected N …           new lines were archived
    No new messages         the conversation is idle
    Not in private tab now  the active tab is a room, a group, or nothing

Decision D-3: an Action-Stack run does NOT pause collection — it throttles
it, so the archive stays complete while runs keep priority on the socket.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, Signal

from backend import chat_agent_js
from backend.chat_parser import (ChatParser, _signature, sync_conversation,
                                 verify_private)
from services.collector_loop import RunLoop
from services.collector_pacing import Pacing
from services.collector_partner import PartnerMemory
from services.collector_push import PushPath
from services.collector_report import Reporter
from services.collector_settings import TuningKnobs
from services.collector_states import CollectorState, DEFAULTS
from stores.history_repo import HistoryRepo

log = logging.getLogger("chatbot")


class Collector(QObject):
    """Non-blocking background monitor of the active conversation."""

    status_changed = Signal(str)        # json state payload
    history_appended = Signal(str)      # json {nick, items, added, total}
    people_changed = Signal(str)        # json {nick, kind, source}
    collector_log = Signal(str)         # json {ts, level, message, nick}

    def __init__(self, cdp, repo: HistoryRepo, parser: ChatParser,
                 media=None, settings: Optional[dict] = None,
                 lease=None, memory=None, parent=None):
        super().__init__(parent)

        # Built first, from `self` only: `__init__` below already calls
        # configure(), a delegator. State stays here -- collector_tick.py
        # reads it back as `host._settings`.
        self._pacing = Pacing(self)
        self._report = Reporter(self)
        self._push = PushPath(self)
        self._partner = PartnerMemory(self)
        self._knobs = TuningKnobs(self)
        self._loop = RunLoop(self)

        self.cdp = cdp
        self.repo = repo
        self.parser = parser
        self.media = media
        self.lease = lease
        self.memory = memory
        self._settings = dict(DEFAULTS)
        self.configure(**(settings or {}))
        self.now = datetime.now

        self._state = CollectorState.DISCONNECTED
        self._text = ""
        self._nick = ""
        self._verified = False      # the two-step gate passed for _nick
        self._added = 0
        self._total = 0
        self._error = ""
        self._warning = ""
        self._agent = 0
        self._self_heals = 0
        self._throttled = False
        self._paused = False
        self._running = True
        self._probe_penalty = 1.0
        self._last_emitted: tuple = ()
        self._stop_event: Optional[asyncio.Event] = None
        self._busy = False
        self._force_backfill = False
        self._backfill_pending = False
        self._last_probe: dict = {}
        self._last_sync_reason = ""
        self._last_sync_added = 0
        self._last_sync_count = 0
        self._last_media_repaired = 0
        self._last_media_requeued = 0
        self._detected_my_nick = ""

    @property
    def my_nick(self) -> str:
        return self._settings.get("my_nick", "")

    @property
    def enabled(self) -> bool:
        return bool(self._settings.get("enabled", True))

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def state(self) -> str:
        return self._state

    # ── lifecycle ────────────────────────────────────────────────
    def start(self) -> None:
        self._running = True
        self._paused = False
        if self._stop_event:
            self._stop_event.clear()

    def stop(self) -> None:
        self._running = False
        if self._stop_event:
            self._stop_event.set()

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    async def _tick(self) -> str:
        # The 212-LOC heartbeat coroutine is now the AREA C tick state
        # machine (`services/collector_tick.py`): PROBE → GATE → NICK →
        # VERIFY → ARCHIVE, each phase a CC ≤ 10 collaborator. The parser
        # helpers are injected so `collector_tick` adds no backend import;
        # the import is function-local to avoid a module cycle.
        from services.collector_tick import CollectorTick
        state, text = await CollectorTick(
            self,
            signature=_signature,
            verify_private=verify_private,
            agent_version=chat_agent_js.AGENT_VERSION,
        ).run()
        return self._set(state, text)

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

    # ── delegators: the facade keeps every name its callers and
    # collector_tick.py's host protocol use; the bodies live in the
    # collaborator modules named above.

    def on_run_started(self) -> None:
        return self._pacing.on_run_started()

    def on_run_finished(self) -> None:
        return self._pacing.on_run_finished()

    def note_probe_duration(self, seconds: float) -> None:
        return self._pacing.note_probe_duration(seconds)

    def next_interval_ms(self) -> int:
        return self._pacing.next_interval_ms()

    def reset_state(self) -> None:
        return self._report.reset_state()

    def _log(self, message: str, level: str = "info",
             nick: Optional[str] = None) -> None:
        return self._report._log(message, level, nick)

    def _notify_people(self, nick: str, kind: str) -> None:
        return self._report._notify_people(nick, kind)

    @staticmethod
    def _payload(payload) -> dict:
        return Reporter._payload(payload)

    @classmethod
    def _records(cls, payload) -> list:
        return Reporter._records(payload)

    def state_payload(self) -> dict:
        return self._report.state_payload()

    def _no_new_text(self) -> str:
        return self._report._no_new_text()

    def _set(self, state: str, text: str) -> str:
        return self._report._set(state, text)

    def _emit(self) -> None:
        return self._report._emit()

    def _refuse(self, state: str, text: str) -> str:
        return self._push._refuse(state, text)

    @staticmethod
    def _gate_status(check, nick: str) -> tuple:
        return PushPath._gate_status(check, nick)

    def _push_ready(self) -> bool:
        return self._push._push_ready()

    def _gate_check(self, data: dict, items: list):
        return self._push._gate_check(data, items)

    async def _append_push(self, items: list):
        return await self._push._append_push(items)

    async def _announce_push(self, result) -> None:
        return await self._push._announce_push(result)

    async def handle_push(self, payload) -> int:
        return await self._push.handle_push(payload)

    def person_cleared(self, nick: str) -> None:
        return self._partner.person_cleared(nick)

    async def _remember_partner(self, nick: str,
                                state: Optional[dict] = None) -> str:
        return await self._partner._remember_partner(nick, state)

    async def _notify_appended(self, nick: str, items: list, added: int,
                               total: int) -> None:
        return await self._partner._notify_appended(nick, items, added, total)

    def configure(self, **kwargs) -> dict:
        return self._knobs.configure(**kwargs)

    def settings(self) -> dict:
        return self._knobs.settings()

    async def run(self) -> None:
        return await self._loop.run()

    async def tick(self) -> str:
        return await self._loop.tick()
