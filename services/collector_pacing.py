"""How fast the next heartbeat is allowed to fire.

Owns the throttle and the probe-duration penalty: a slow probe buys a
longer pause, and an Action-Stack run throttles collection instead of
pausing it (decision D-3). Built from the aggregate only; the counters it
adjusts stay on `Collector` because `services/collector_tick.py` reads
them as `host._throttled`.
"""

from __future__ import annotations

from services.collector_states import IDLE_STATES, MAX_PROBE_PENALTY


class Pacing:
    """One responsibility of `Collector`, built from it."""

    def __init__(self, owner):
        self._o = owner

    def on_run_started(self) -> None:
        """An Action-Stack run began: keep collecting, but stay out of its way."""
        self._o._throttled = True
        self._o._emit()

    def on_run_finished(self) -> None:
        self._o._throttled = False
        self._o._emit()

    def note_probe_duration(self, seconds: float) -> None:
        """Back off when the page answers slowly (a busy or huge chat)."""
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return
        self._o._probe_penalty = max(1.0, min(MAX_PROBE_PENALTY, value / 0.1))

    def next_interval_ms(self) -> int:
        base = int(self._o._settings["idle_heartbeat_ms" if self._o._state in
                                  IDLE_STATES else "heartbeat_ms"])
        interval = base * self._o._probe_penalty
        if self._o._throttled:
            interval *= max(1, int(self._o._settings["throttle_factor"]))
        return int(interval)
