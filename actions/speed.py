"""Global wait-speed rate shared by every action block (SPEED_MULTIPLIER).

Leaf module: stdlib only, no services/Qt imports — every block and the run
engine may import it without a cycle. One coefficient multiplies each
user-facing wait of the run: 1.0 is normal speed, 0.5 halves every wait
(2× faster), 2.0 doubles every wait (2× slower).

Design: docs/archive/2026-09-13-speed-multiplier/SPEED_MULTIPLIER_DESIGN_2026-09-13.md
"""

from __future__ import annotations

import math

#: the block whose value becomes the run's rate (must match its block_id)
SPEED_BLOCK_ID = "SPEED_MULTIPLIER"
#: no SPEED block, a disabled one, or garbage anywhere along the way
_DEFAULT = 1.0
#: near-instant; below this a wait would vanish into nothing
_MIN = 0.1
#: beyond this a typo would look like a hung run
_MAX = 10.0


def coerce_multiplier(value) -> float:
    """Any preset/UI value as a sane rate; garbage fails open to 1.0."""
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return _DEFAULT
    if not math.isfinite(rate):
        return _DEFAULT
    return min(_MAX, max(_MIN, rate))


def read_multiplier(engine) -> float:
    """The run's current rate; 1.0 when there is no run (fail-open)."""
    if engine is None:
        return _DEFAULT
    return coerce_multiplier(getattr(engine, "speed_multiplier", _DEFAULT))


def scale_ms(ms, engine=None) -> int:
    """A wait in ms, scaled by the run's rate (0 stays 0)."""
    clean = max(0, int(ms or 0))
    mult = read_multiplier(engine)
    if mult == 1.0:
        return clean
    return max(0, int(round(clean * mult)))


def _fmt_rate(value: float) -> str:
    """The coefficient as the UI shows it: 2.0 keeps its decimal."""
    text = f"{value:g}"
    return text if "." in text else text + ".0"


def describe(multiplier) -> str:
    """The one-line preview — "×0.5 (2× faster)" — the UI and logs share."""
    mult = coerce_multiplier(multiplier)
    if mult == 1.0:
        return f"\u00d7{_fmt_rate(mult)} (normal speed)"
    if mult < 1.0:
        return f"\u00d7{_fmt_rate(mult)} ({1 / mult:.2g}\u00d7 faster)"
    return f"\u00d7{_fmt_rate(mult)} ({mult:.2g}\u00d7 slower)"


def _is_active_speed(block) -> bool:
    """An enabled SPEED block — the only thing that votes for the rate."""
    return (getattr(block, "block_id", "") == SPEED_BLOCK_ID
            and getattr(block, "enabled", True))


def resolve_stack_multiplier(blocks) -> float:
    """The run's rate: the last enabled SPEED block wins; none means 1.0."""
    found = None
    for block in blocks or []:
        if _is_active_speed(block):
            value = getattr(block, "multiplier", None)
            if value is not None:
                found = value
    return coerce_multiplier(_DEFAULT if found is None else found)
