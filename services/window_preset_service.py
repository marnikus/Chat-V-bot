"""Portable window-preset document validation and compatibility metadata."""

from __future__ import annotations

import copy
import json
import math
from datetime import datetime
from typing import Any

from services.layout_service import LayoutService

FORMAT = "chat-v-bot.window-preset"
SCHEMA_VERSION = 1
APP_VERSION = "0.1.0"
GRID_TYPE = "sash-tree"
_BOUNDS_KEYS = ("x", "y", "width", "height")


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


def _grid(doc: dict) -> tuple[dict | None, str | None]:
    grid = doc.get("grid")
    if not isinstance(grid, dict) or grid.get("type") != GRID_TYPE:
        return None, "grid.type must be 'sash-tree'"
    version = grid.get("version")
    tree = grid.get("tree")
    if isinstance(version, bool) or not isinstance(version, int):
        return None, "grid.version must be an integer"
    try:
        raw = json.dumps({"v": version, "tree": tree}, ensure_ascii=False)
    except (TypeError, ValueError):
        return None, "grid.tree must be JSON data"
    canonical, error = LayoutService.canonical_grid_payload(raw)
    if error:
        return None, f"invalid grid tree: {error}"
    tree = json.loads(canonical)["tree"]
    expected = len(LayoutService.WINDOW_IDS)
    if grid.get("window_count") != expected:
        return None, f"window_count must be {expected}"
    if grid.get("sizes_unit") != "percent":
        return None, "grid.sizes_unit must be 'percent'"
    return {"type": GRID_TYPE, "version": LayoutService.GRID_VERSION,
            "window_count": expected, "sizes_unit": "percent",
            "tree": tree}, None


def _id_list(value: Any, label: str) -> tuple[list[str] | None, str | None]:
    if not isinstance(value, list):
        return None, f"{label} must be a list"
    known = set(LayoutService.WINDOW_IDS)
    result = []
    for item in value:
        if not isinstance(item, str) or item not in known:
            return None, f"{label} contains an unknown window"
        if item in result:
            return None, f"{label} contains a duplicate window"
        result.append(item)
    return result, None


def _states(doc: dict) -> tuple[dict | None, str | None]:
    states = doc.get("window_states")
    if not isinstance(states, dict):
        return None, "window_states must be an object"
    closed, error = _id_list(states.get("closed"), "closed")
    if error:
        return None, error
    minimized, error = _id_list(states.get("minimized"), "minimized")
    if error:
        return None, error
    overlap = set(closed).intersection(minimized)
    if overlap:
        return None, "closed and minimized window states overlap"
    return {"closed": closed, "minimized": minimized}, None


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def _bound_values(entry: dict) -> tuple[dict | None, str | None]:
    bounds = entry.get("bounds")
    if not isinstance(bounds, dict):
        return None, "window bounds must be an object"
    values = {key: bounds.get(key) for key in _BOUNDS_KEYS}
    if not all(_number(value) for value in values.values()):
        return None, "window bounds must contain finite numbers"
    if any(value < 0 or value > 1 for value in values.values()):
        return None, "window bounds must be normalized between 0 and 1"
    return values, None


def _bounds_extend_screen(values: dict) -> bool:
    return values["x"] + values["width"] > 1.001 or \
        values["y"] + values["height"] > 1.001


def _bounds(entry: dict) -> tuple[dict | None, str | None]:
    values, error = _bound_values(entry)
    if error:
        return None, error
    if _bounds_extend_screen(values):
        return None, "window bounds extend outside the screen"
    return {key: round(value, 6) for key, value in values.items()}, None


def _window_id(entry: dict, expected: set[str], seen: set[str]) -> tuple[str | None, str | None]:
    wid = entry.get("id")
    if isinstance(wid, str) and wid in expected and wid not in seen:
        return wid, None
    return None, "windows contain an unknown or duplicate id"


def _window_state(entry: dict, wid: str, states: dict) -> tuple[str | None, str | None]:
    wanted = "closed" if wid in states["closed"] else "open"
    if wid in states["minimized"]:
        wanted = "minimized"
    if entry.get("state") != wanted:
        return None, f"window {wid!r} has an inconsistent state"
    return wanted, None


def _window_entry(
    entry: Any, expected: set[str], seen: set[str], states: dict
) -> tuple[dict | None, str | None]:
    if not isinstance(entry, dict):
        return None, "each window entry must be an object"
    wid, error = _window_id(entry, expected, seen)
    if error:
        return None, error
    state, error = _window_state(entry, wid, states)
    if error:
        return None, error
    bounds, error = _bounds(entry)
    if error:
        return None, f"window {wid!r}: {error}"
    title = entry.get("title")
    return {"id": wid, "title": title if isinstance(title, str) else wid,
            "state": state, "bounds": bounds}, None


def _windows(doc: dict, states: dict) -> tuple[list[dict] | None, str | None]:
    entries = doc.get("windows")
    if not isinstance(entries, list):
        return None, "windows must be a list"
    expected = set(LayoutService.WINDOW_IDS)
    seen = set()
    clean = []
    for entry in entries:
        window, error = _window_entry(entry, expected, seen, states)
        if error:
            return None, error
        clean.append(window)
        seen.add(window["id"])
    if seen != expected:
        return None, "windows do not contain the current window set"
    return clean, None


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


def validate_document(raw: Any, name: str | None = None) -> tuple[dict | None, str | None]:
    doc, error = _decode(raw)
    if error:
        return None, error
    header, error = _header(doc, name)
    if error:
        return None, error
    grid, error = _grid(doc)
    if error:
        return None, error
    states, error = _states(doc)
    if error:
        return None, error
    windows, error = _windows(doc, states)
    if error:
        return None, error
    screen, error = _screen(doc)
    if error:
        return None, error
    header.update({"grid": grid, "windows": windows,
                   "window_states": states, "screen": screen})
    return header, None


class WindowPresetService:
    """Facade for the portable document contract used by bridge and tests."""

    FORMAT = FORMAT
    SCHEMA_VERSION = SCHEMA_VERSION
    APP_VERSION = APP_VERSION
    GRID_TYPE = GRID_TYPE

    @classmethod
    def validate(cls, raw: Any, name: str | None = None):
        return validate_document(raw, name)

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
