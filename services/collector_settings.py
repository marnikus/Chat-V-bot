"""The tuning knobs: what the collector is allowed to cost.

Owns `configure()` -- which validates and coerces incoming knobs against
`DEFAULTS` and pushes the chunk settings through to the parser -- and
`settings()`, the copy the Radar window reads. Built from the aggregate
only; `_settings` and `parser` stay on `Collector` because
`services/collector_tick.py` reads them as `host._settings`.
"""

from __future__ import annotations

from services.collector_states import DEFAULTS


class TuningKnobs:
    """One responsibility of `Collector`, built from it."""

    def __init__(self, owner):
        self._o = owner

    # ── settings ─────────────────────────────────────────────────
    def configure(self, **kwargs) -> dict:
        for key, value in (kwargs or {}).items():
            if key not in DEFAULTS:
                continue                       # unknown keys are ignored
            if isinstance(DEFAULTS[key], bool):
                self._o._settings[key] = bool(value)
            elif isinstance(DEFAULTS[key], int):
                try:
                    self._o._settings[key] = int(value)
                except (TypeError, ValueError):
                    pass
            else:
                self._o._settings[key] = str(value or "")
        self._o.parser.chunk_size = max(
            1, int(self._o._settings["chunk_size"]))
        self._o.parser.chunk_pause_ms = max(
            0, int(self._o._settings["chunk_pause_ms"]))
        return self._o.settings()

    def settings(self) -> dict:
        return dict(self._o._settings)
