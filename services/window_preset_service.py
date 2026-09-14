"""Portable window-preset document validation and compatibility metadata.

One file for cohesion, not size: pure validators form a strict DAG (_decode →
_header → _grid → _states → _windows → _screen → validate_document), each
returning (value, error) and short-circuiting on the first error, so the order
of the checks IS the error a caller sees. The WindowPresetService facade only
delegates. Imports run one way: this module reads services.layout_service and
services.preset_adapt and nothing imports back. §6 of
ROUND_F_DESIGN_2026-09-12.md ruled out splitting the DAG, so a function past
§18.1's ideal is decomposed in place, at seams the error precedence allows.

Since the 2026-09-14 adaptive-restore round the set-membership checks live in
services/preset_adapt.py (the mirror of ui/js/preset-adapt.js): window-set
DRIFT is repaired and reported inside the document's `restore_report`, while
structural corruption still short-circuits this DAG with the pinned errors.

Design: docs/archive/2026-09-14-grid-rows-adaptive-restore/GRID_ROWS_ADAPTIVE_RESTORE_DESIGN_2026-09-14.md
"""

from __future__ import annotations

import copy
import json
import math
from datetime import datetime
from typing import Any

from services import preset_adapt
from services.layout_service import LayoutService

FORMAT = "chat-v-bot.window-preset"
SCHEMA_VERSION = 1
APP_VERSION = "0.1.0"
GRID_TYPE = "sash-tree"


def _decode(raw: Any) -> tuple[dict | None, str | None]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            return None, f"bad JSON ({exc.msg})"
    if not isinstance(raw, dict):
        return None, "document must be a JSON object"
    return copy.deepcopy(raw), None


def _text(doc: dict, key: str) -> tuple[str | None, str | None]:
    value = doc.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip(), None
    return None, f"missing {key}"


def _header_error(doc: dict) -> str | None:
    if "format" not in doc:
        return "missing format"
    if doc.get("format") != FORMAT:
        return f"unsupported format {doc.get('format')!r}"
    if "schema_version" not in doc:
        return "missing schema_version"
    if doc.get("schema_version") != SCHEMA_VERSION:
        return f"unsupported schema version {doc.get('schema_version')!r}"
    return None


def _preset_name(doc: dict, name: str | None) -> tuple[str | None, str | None]:
    source = doc
    if name is not None:
        source = {"name": name}
    preset_name, error = _text(source, "name")
    if error:
        return None, error
    if len(preset_name) > 80:
        return None, "name is longer than 80 characters"
    return preset_name, None


def _timestamp(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _header(doc: dict, name: str | None) -> tuple[dict | None, str | None]:
    error = _header_error(doc)
    if error:
        return None, error
    app, error = _text(doc, "app_version")
    if error:
        return None, error
    preset_name, error = _preset_name(doc, name)
    if error:
        return None, error
    now = datetime.now().isoformat(timespec="seconds")
    return {"format": FORMAT, "schema_version": SCHEMA_VERSION,
            "app_version": app, "name": preset_name,
            "created_at": _timestamp(doc.get("created_at"), now),
            "updated_at": _timestamp(doc.get("updated_at"), now)}, None


def _grid_tree(grid: dict) -> tuple[Any | None, dict, str | None]:
    """(tree, tree_report, error) — the JSON guard stays, then the set
    drift is adapted (pruned/added) instead of refusing the document."""
    try:
        json.dumps({"v": grid.get("version"), "tree": grid.get("tree")},
                   ensure_ascii=False)
    except (TypeError, ValueError):
        return None, {}, "grid.tree must be JSON data"
    tree, report, error = preset_adapt.adapt_tree(grid.get("tree"),
                                                  grid.get("version"))
    if error:
        return None, {}, f"invalid grid tree: {error}"
    return tree, report, None


def _grid(doc: dict) -> tuple[dict | None, dict, str | None]:
    grid = doc.get("grid")
    if not isinstance(grid, dict) or grid.get("type") != GRID_TYPE:
        return None, {}, "grid.type must be 'sash-tree'"
    version = grid.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        return None, {}, "grid.version must be an integer"
    tree, tree_report, error = _grid_tree(grid)
    if error:
        return None, {}, error
    # Internal consistency only: the count must describe the DOCUMENT's own
    # windows list — the live set is what adaptation restores towards.
    # Checked after the tree on purpose: a document with both faults has
    # always reported the tree, and callers match on that message.
    entries = doc.get("windows")
    if isinstance(entries, list) and grid.get("window_count") != len(entries):
        return None, {}, f"window_count must be {len(entries)}"
    if grid.get("sizes_unit") != "percent":
        return None, {}, "grid.sizes_unit must be 'percent'"
    return {"type": GRID_TYPE, "version": LayoutService.GRID_VERSION,
            "window_count": len(LayoutService.WINDOW_IDS),
            "sizes_unit": "percent", "tree": tree}, tree_report, None


def _states(doc: dict) -> tuple[dict | None, list, str | None]:
    return preset_adapt.adapt_states(doc.get("window_states"))


def _windows(doc: dict, states: dict) -> tuple[list | None, dict, str | None]:
    return preset_adapt.adapt_windows(doc.get("windows"), states)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def _screen(doc: dict) -> tuple[dict | None, str | None]:
    screen = doc.get("screen")
    if not isinstance(screen, dict):
        return None, "screen must be an object"
    width, height = screen.get("width"), screen.get("height")
    dpr = screen.get("device_pixel_ratio", 1)
    if not _number(width) or not _number(height) or width <= 0 or height <= 0:
        return None, "screen width and height must be positive numbers"
    if not _number(dpr) or dpr <= 0:
        return None, "screen device_pixel_ratio must be positive"
    return {"width": int(width), "height": int(height),
            "device_pixel_ratio": round(dpr, 4)}, None


def _document_body(doc: dict) -> tuple[dict | None, str | None]:
    grid, tree_report, error = _grid(doc)
    if error:
        return None, error
    states, states_skipped, error = _states(doc)
    if error:
        return None, error
    windows, win_parts, error = _windows(doc, states)
    if error:
        return None, error
    screen, error = _screen(doc)
    if error:
        return None, error
    report = preset_adapt.build_report(tree_report, states_skipped,
                                       win_parts, windows)
    return {"grid": grid, "windows": windows,
            "window_states": states, "screen": screen,
            "restore_report": report}, None


def validate_document(raw: Any, name: str | None = None) -> tuple[dict | None, str | None]:
    doc, error = _decode(raw)
    if error:
        return None, error
    header, error = _header(doc, name)
    if error:
        return None, error
    body, error = _document_body(doc)
    if error:
        return None, error
    header.update(body)
    return header, None


class WindowPresetService:
    """Facade for the portable document contract used by bridge and tests."""

    FORMAT = FORMAT
    SCHEMA_VERSION = SCHEMA_VERSION
    APP_VERSION = APP_VERSION
    GRID_TYPE = GRID_TYPE

    @classmethod
    def validate(cls, raw: Any, name: str | None = None):
        return validate_document(raw, name=name)

    @staticmethod
    def compatibility_note(document: dict) -> str:
        version = document.get("app_version", "unknown")
        if version == APP_VERSION:
            return ""
        return f"Created by app version {version}; current version is {APP_VERSION}."

    @staticmethod
    def resolution_note(document: dict, width: int, height: int) -> str:
        screen = document.get("screen", {})
        if screen.get("width") == width and screen.get("height") == height:
            return ""
        return (f"Source screen {screen.get('width')}×{screen.get('height')}; "
                f"current screen {width}×{height} is different. "
                "Percentage layout will adapt.")
