"""The `windows` section of a window-preset document (H-C5 split).

One entry per current window: a known, non-duplicate id; a `state` consistent
with the closed/minimized lists; and normalized bounds that stay on screen.
The two document-level sections (`window_states`, `screen`) are in
`window_preset_sections.py`.

Import direction: `.window_preset_contract` for the leaf predicates;
`services.layout_service` for the current window set.
"""

from __future__ import annotations

from typing import Any

from services.layout_service import LayoutService

from .window_preset_contract import _BOUNDS_KEYS, _number

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
