"""Grid-section validation of a window-preset document (H-C5 split).

The sash-tree section: the tree is canonicalised through `LayoutService`,
then `window_count` and `sizes_unit` are checked. The tree is checked first
on purpose — a document with both faults has always reported the tree, and
callers match on that message.

Import direction: `.window_preset_contract` for `GRID_TYPE`;
`services.layout_service` for the canonical payload and the window set.
"""

from __future__ import annotations

import json
from typing import Any

from services.layout_service import LayoutService

from .window_preset_contract import GRID_TYPE

def _grid_tree(grid: dict) -> tuple[Any | None, str | None]:
    try:
        raw = json.dumps({"v": grid.get("version"), "tree": grid.get("tree")},
                         ensure_ascii=False)
    except (TypeError, ValueError):
        return None, "grid.tree must be JSON data"
    canonical, error = LayoutService.canonical_grid_payload(raw)
    if error:
        return None, f"invalid grid tree: {error}"
    return json.loads(canonical)["tree"], None

def _grid_limits(grid: dict, expected: int) -> str | None:
    # Checked after the tree on purpose: a document with both faults has always
    # reported the tree, and callers match on that message.
    if grid.get("window_count") != expected:
        return f"window_count must be {expected}"
    if grid.get("sizes_unit") != "percent":
        return "grid.sizes_unit must be 'percent'"
    return None

def _grid(doc: dict) -> tuple[dict | None, str | None]:
    grid = doc.get("grid")
    if not isinstance(grid, dict) or grid.get("type") != GRID_TYPE:
        return None, "grid.type must be 'sash-tree'"
    version = grid.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        return None, "grid.version must be an integer"
    tree, error = _grid_tree(grid)
    if error:
        return None, error
    expected = len(LayoutService.WINDOW_IDS)
    error = _grid_limits(grid, expected)
    if error:
        return None, error
    return {"type": GRID_TYPE, "version": LayoutService.GRID_VERSION,
            "window_count": expected, "sizes_unit": "percent",
            "tree": tree}, None
