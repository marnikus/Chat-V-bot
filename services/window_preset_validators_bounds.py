"""Window preset validators — bounds part (H-C5 split)

Bounds validation, ≤100 LOC.
"""

from __future__ import annotations

from services.window_preset_predicates import _extends_outside, _is_finite, _is_normalized, _is_obj

_BOUNDS_KEYS = ("x", "y", "width", "height")


def _bound_values(entry: dict) -> tuple[dict | None, str | None]:
    b = entry.get("bounds")
    if not _is_obj(b):
        return None, "window bounds must be an object"
    vals = {k: b.get(k) for k in _BOUNDS_KEYS}
    if not all(_is_finite(v) for v in vals.values()):
        return None, "window bounds must contain finite numbers"
    if not all(_is_normalized(v) for v in vals.values()):
        return None, "window bounds must be normalized between 0 and 1"
    return vals, None


def _bounds(entry: dict) -> tuple[dict | None, str | None]:
    vals, err = _bound_values(entry)
    if err:
        return None, err
    if _extends_outside(vals):
        return None, "window bounds extend outside the screen"
    return {k: round(v, 6) for k, v in vals.items()}, None
