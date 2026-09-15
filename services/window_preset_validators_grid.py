"""Window preset validators — grid + screen part (H-C5 split)

Grid and screen validation, ≤150 LOC.
"""

from __future__ import annotations

import json
from typing import Any

from services.layout_service import LayoutService
from services.window_preset_predicates import _is_grid_type, _is_int, _is_obj, _is_positive

GRID_TYPE = "sash-tree"


def _grid_tree(grid: dict) -> tuple[Any | None, str | None]:
    try:
        raw = json.dumps({"v": grid.get("version"), "tree": grid.get("tree")}, ensure_ascii=False)
    except (TypeError, ValueError):
        return None, "grid.tree must be JSON data"
    canon, err = LayoutService.canonical_grid_payload(raw)
    if err:
        return None, f"invalid grid tree: {err}"
    return json.loads(canon)["tree"], None


def _grid_limits(grid: dict, exp: int) -> str | None:
    if grid.get("window_count") != exp:
        return f"window_count must be {exp}"
    if grid.get("sizes_unit") != "percent":
        return "grid.sizes_unit must be 'percent'"
    return None


def _grid(doc: dict) -> tuple[dict | None, str | None]:
    g = doc.get("grid")
    if not _is_grid_type(g):
        return None, "grid.type must be 'sash-tree'"
    if not _is_int(g.get("version")):
        return None, "grid.version must be an integer"
    tree, err = _grid_tree(g)
    if err:
        return None, err
    exp = len(LayoutService.WINDOW_IDS)
    err = _grid_limits(g, exp)
    if err:
        return None, err
    return {
        "type": GRID_TYPE,
        "version": LayoutService.GRID_VERSION,
        "window_count": exp,
        "sizes_unit": "percent",
        "tree": tree,
    }, None


def _screen(doc: dict) -> tuple[dict | None, str | None]:
    scr = doc.get("screen")
    if not _is_obj(scr):
        return None, "screen must be an object"
    w, h = scr.get("width"), scr.get("height")
    dpr = scr.get("device_pixel_ratio", 1)
    if not _is_positive(w) or not _is_positive(h):
        return None, "screen width and height must be positive numbers"
    if not _is_positive(dpr):
        return None, "screen device_pixel_ratio must be positive"
    return {"width": int(w), "height": int(h), "device_pixel_ratio": round(dpr, 4)}, None
