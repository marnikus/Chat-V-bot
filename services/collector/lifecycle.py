"""The collector's lifecycle knobs: run/stop/pause, reset, throttle, backoff.

`LifecycleMixin` owns everything that steers the supervisor without touching
the archive: the run flag, the reset-on-db-swap, the run-throttle flags, the
probe-duration backoff and the heartbeat interval. The heartbeat loop itself
lives in `heartbeat.HeartbeatMixin`.
"""

import asyncio
import logging

from .constants import IDLE_STATES, MAX_PROBE_PENALTY

log = logging.getLogger("chatbot")


class LifecycleMixin:
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

    def note_probe_duration(self, seconds: float) -> None:
        """Back off when the page answers slowly (a busy or huge chat)."""
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return
        self._probe_penalty = max(1.0, min(MAX_PROBE_PENALTY, value / 0.1))

    def next_interval_ms(self) -> int:
        base = int(self._settings["idle_heartbeat_ms" if self._state in
                                  IDLE_STATES else "heartbeat_ms"])
        interval = base * self._probe_penalty
        if self._throttled:
            interval *= max(1, int(self._settings["throttle_factor"]))
        return int(interval)
