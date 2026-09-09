"""Collector mixin 2 (<150)."""
import asyncio, json, logging
from datetime import datetime
from typing import Optional

class CollectorMixin2:
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

    def reset_state(self) -> None:
        """Forget everything learned about the CURRENT conversation.

        Called when the archive database is swapped underneath us: the
        cursors, totals and the verified private-chat gate all describe the
        old file, and acting on them would attribute the next batch to a
        conversation this database has never seen (RULE 15 fails closed).
        """
        self._nick = ""
        self._text = ""
        self._verified = False
        self._added = 0
        self._total = 0
        self._error = ""
        self._warning = ""
        self._last_probe = {}
        self._last_sync_reason = ""
        self._last_sync_added = 0
        self._last_sync_count = 0
        self._backfill_pending = False
        self._force_backfill = False
        self._last_emitted = ()

    def on_run_started(self) -> None:
        """An Action-Stack run began: keep collecting, but stay out of its way."""
        self._throttled = True
        self._emit()

    def on_run_finished(self) -> None:
        self._throttled = False
        self._emit()

    def person_cleared(self, nick: str) -> None:
        """The archive history of `nick` was just cleared in the UI.

        The cursor is already reset on the write path, so the next tick
        re-reads the conversation from scratch; here we only stop showing
        the old totals in the Radar window (Bug 4, 2026-09-08).
        """
        clean = " ".join(str(nick or "").split()).strip()
        if not clean or self._nick != clean:
            return
        self._total = 0
        self._added = 0
        self._last_sync_reason = "history_cleared"
        self._last_sync_added = 0
        self._last_sync_count = 0
        self._emit()

