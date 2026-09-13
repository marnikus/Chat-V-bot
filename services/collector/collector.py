"""`Collector` — the facade over the five collector responsibilities.

The class owns construction, configuration and the Qt signals; the behaviour
lives one responsibility per mixin (lifecycle / heartbeat / push / archive /
status). The facade composes them so the public surface other areas import
stays a single `services.collector_service.Collector`.

    run()                                     [heartbeat]
      └─ tick()          gate the tick       [heartbeat]
           └─ _tick()    CollectorTick (PROBE→GATE→NICK→VERIFY→ARCHIVE)
    handle_push()                             [push]

Layout: the mixins own no state and never import this module, so the facade
is the only module that imports them (the `services/run/` precedent).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, Signal

from backend.chat_parser import ChatParser
from stores.history_repo import HistoryRepo

from .archive import ArchiveMixin
from .constants import CollectorState, DEFAULTS
from .heartbeat import HeartbeatMixin
from .lifecycle import LifecycleMixin
from .push import PushMixin
from .status import StatusMixin


class Collector(QObject, LifecycleMixin, HeartbeatMixin, PushMixin,
                ArchiveMixin, StatusMixin):
    """Non-blocking background monitor of the active conversation."""

    status_changed = Signal(str)        # json state payload
    history_appended = Signal(str)      # json {nick, items, added, total}
    people_changed = Signal(str)        # json {nick, kind, source}
    collector_log = Signal(str)         # json {ts, level, message, nick}

    def __init__(self, cdp, repo: HistoryRepo, parser: ChatParser,
                 media=None, settings: Optional[dict] = None,
                 lease=None, memory=None, parent=None):
        super().__init__(parent)
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

    # ── settings ─────────────────────────────────────────────────
    def configure(self, **kwargs) -> dict:
        for key, value in (kwargs or {}).items():
            if key not in DEFAULTS:
                continue                       # unknown keys are ignored
            if isinstance(DEFAULTS[key], bool):
                self._settings[key] = bool(value)
            elif isinstance(DEFAULTS[key], int):
                try:
                    self._settings[key] = int(value)
                except (TypeError, ValueError):
                    pass
            else:
                self._settings[key] = str(value or "")
        self.parser.chunk_size = max(1, int(self._settings["chunk_size"]))
        self.parser.chunk_pause_ms = max(0, int(self._settings["chunk_pause_ms"]))
        return self.settings()

    def settings(self) -> dict:
        return dict(self._settings)

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
