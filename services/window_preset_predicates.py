"""Window preset predicates — extracted from window_preset_service (H-C4).

Named responsibility: predicates for MI lift, ≤200 LOC.
"""

from __future__ import annotations

import math
from typing import Any

GRID_TYPE = "sash-tree"


def _is_obj(v: Any) -> bool:
    return isinstance(v, dict)


def _is_list(v: Any) -> bool:
    return isinstance(v, list)


def _is_text(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _is_finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _is_positive(v: Any) -> bool:
    return _is_finite(v) and v > 0


def _is_normalized(v: Any) -> bool:
    return _is_finite(v) and 0 <= v <= 1


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_known_id(v: Any, known: set[str]) -> bool:
    return isinstance(v, str) and v in known


def _is_grid_type(v: Any) -> bool:
    return _is_obj(v) and v.get("type") == GRID_TYPE


def _overlaps(a: list[str], b: list[str]) -> bool:
    return bool(set(a).intersection(b))


def _extends_outside(vals: dict) -> bool:
    return vals["x"] + vals["width"] > 1.001 or vals["y"] + vals["height"] > 1.001


def _valid_id(wid: Any, exp: set[str], seen: set[str]) -> bool:
    return isinstance(wid, str) and wid in exp and wid not in seen
