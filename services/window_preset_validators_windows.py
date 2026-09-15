"""Window preset validators — windows part (H-C5 split)

Window list, states validation, ≤150 LOC via bounds split.
"""

from __future__ import annotations

from typing import Any

from services.layout_service import LayoutService
from services.window_preset_predicates import _is_known_id, _is_list, _is_obj, _overlaps, _valid_id
from services.window_preset_validators_bounds import _bounds

_BOUNDS_KEYS = ("x", "y", "width", "height")


def _id_list(value: Any, label: str) -> tuple[list[str] | None, str | None]:
    if not _is_list(value):
        return None, f"{label} must be a list"
    known = set(LayoutService.WINDOW_IDS)
    res: list[str] = []
    seen = set()
    for item in value:
        if not _is_known_id(item, known):
            return None, f"{label} contains an unknown window"
        if item in seen:
            return None, f"{label} contains a duplicate window"
        seen.add(item)
        res.append(item)
    return res, None


def _states(doc: dict) -> tuple[dict | None, str | None]:
    s = doc.get("window_states")
    if not _is_obj(s):
        return None, "window_states must be an object"
    closed, err = _id_list(s.get("closed"), "closed")
    if err:
        return None, err
    minimized, err = _id_list(s.get("minimized"), "minimized")
    if err:
        return None, err
    if _overlaps(closed, minimized):
        return None, "closed and minimized window states overlap"
    return {"closed": closed, "minimized": minimized}, None


def _window_id(entry: dict, exp: set[str], seen: set[str]) -> tuple[str | None, str | None]:
    wid = entry.get("id")
    if _valid_id(wid, exp, seen):
        return wid, None
    return None, "windows contain an unknown or duplicate id"


def _window_state(entry: dict, wid: str, states: dict) -> tuple[str | None, str | None]:
    want = "closed" if wid in states["closed"] else "open"
    if wid in states["minimized"]:
        want = "minimized"
    if entry.get("state") != want:
        return None, f"window {wid!r} has an inconsistent state"
    return want, None


def _window_entry(entry: Any, exp: set[str], seen: set[str], states: dict) -> tuple[dict | None, str | None]:
    if not _is_obj(entry):
        return None, "each window entry must be an object"
    wid, err = _window_id(entry, exp, seen)
    if err:
        return None, err
    st, err = _window_state(entry, wid, states)
    if err:
        return None, err
    b, err = _bounds(entry)
    if err:
        return None, f"window {wid!r}: {err}"
    title = entry.get("title")
    return {"id": wid, "title": title if isinstance(title, str) else wid, "state": st, "bounds": b}, None


def _windows(doc: dict, states: dict) -> tuple[list[dict] | None, str | None]:
    ents = doc.get("windows")
    if not _is_list(ents):
        return None, "windows must be a list"
    exp = set(LayoutService.WINDOW_IDS)
    seen: set[str] = set()
    clean: list[dict] = []
    for e in ents:
        w, err = _window_entry(e, exp, seen, states)
        if err:
            return None, err
        clean.append(w)
        seen.add(w["id"])
    if seen != exp:
        return None, "windows do not contain the current window set"
    return clean, None
