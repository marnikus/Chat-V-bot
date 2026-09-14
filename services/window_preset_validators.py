"""Window preset validators — extracted from window_preset_service (H-C4).

Named responsibility: document validation DAG, ≤300 LOC.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any

from services.layout_service import LayoutService
from services.window_preset_predicates import (
    _extends_outside,
    _is_finite,
    _is_grid_type,
    _is_int,
    _is_known_id,
    _is_list,
    _is_normalized,
    _is_obj,
    _is_positive,
    _is_text,
    _overlaps,
    _valid_id,
)

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
    if not _is_obj(raw):
        return None, "document must be a JSON object"
    return copy.deepcopy(raw), None


def _text(doc: dict, key: str) -> tuple[str | None, str | None]:
    v = doc.get(key)
    if _is_text(v):
        return v.strip(), None
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
    src = doc if name is None else {"name": name}
    n, err = _text(src, "name")
    if err:
        return None, err
    if len(n) > 80:
        return None, "name is longer than 80 characters"
    return n, None


def _timestamp(v: Any, fb: str) -> str:
    return v if isinstance(v, str) and v else fb


def _header(doc: dict, name: str | None) -> tuple[dict | None, str | None]:
    err = _header_error(doc)
    if err:
        return None, err
    app, err = _text(doc, "app_version")
    if err:
        return None, err
    pname, err = _preset_name(doc, name)
    if err:
        return None, err
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "app_version": app,
        "name": pname,
        "created_at": _timestamp(doc.get("created_at"), now),
        "updated_at": _timestamp(doc.get("updated_at"), now),
    }, None


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


def _document_body(doc: dict) -> tuple[dict | None, str | None]:
    g, err = _grid(doc)
    if err:
        return None, err
    st, err = _states(doc)
    if err:
        return None, err
    wins, err = _windows(doc, st)
    if err:
        return None, err
    scr, err = _screen(doc)
    if err:
        return None, err
    return {"grid": g, "windows": wins, "window_states": st, "screen": scr}, None


def validate_document(raw: Any, name: str | None = None) -> tuple[dict | None, str | None]:
    doc, err = _decode(raw)
    if err:
        return None, err
    hdr, err = _header(doc, name)
    if err:
        return None, err
    body, err = _document_body(doc)
    if err:
        return None, err
    hdr.update(body)
    return hdr, None
