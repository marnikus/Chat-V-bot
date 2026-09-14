"""The two document-level sections of a window-preset document (H-C5 split).

Neither is per-window: `window_states` is the pair of id lists saying which
windows are closed and which are minimized (they must not overlap, and every
entry's `state` is checked against them in `window_preset_windows.py`), and
`screen` is the display the percentages were measured on.

Import direction: `.window_preset_contract` for the leaf predicates;
`services.layout_service` for the current window set.
"""

from __future__ import annotations

from services.layout_service import LayoutService

from .window_preset_contract import _id_list, _number

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
