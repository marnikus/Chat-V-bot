"""Adaptive window-preset restore — Python mirror of ui/js/preset-adapt.js.

A portable preset whose window set drifted from the live build (created
before a window was added, or after one was removed) used to be refused
wholesale. This module repairs what matches and REPORTS the rest:

  * unknown ids anywhere (tree leaves, ``windows[]``, ``window_states``)
    are pruned / skipped and explained;
  * live windows the preset does not have are appended by
    ``LayoutService.migrate_grid_tree`` into a default bottom row;
  * a known entry contradicting ``window_states`` is corrected from it
    (``window_states`` is authoritative);
  * a known entry with corrupt bounds keeps its TREE placement and gets
    default bounds, explained.

Structural corruption (non-lists, duplicates inside ``window_states``,
closed/minimized overlap, unparsable trees) still REFUSES — the I-11
invariant: never hand back a document that cannot be read back.

The REASON strings are a shared contract with the JS mirror, pinned by
tests on both sides (AGENT_RULES RULE 3). Imports run one way: this module
reads services.layout_service and nothing imports back.

Design: docs/archive/2026-09-14-grid-rows-adaptive-restore/GRID_ROWS_ADAPTIVE_RESTORE_DESIGN_2026-09-14.md
"""

from __future__ import annotations

from services.layout_service import LayoutService

#: shared with ui/js/preset-adapt.js — pinned on both sides
REASON_UNKNOWN = "unknown window in this build"
REASON_DUPLICATE = "duplicate preset entry"
REASON_BOUNDS = "invalid bounds; default position used"
REASON_STATE = "state corrected from window_states"
REASON_ADDED = "not in the preset; added with default placement"

#: neutral tile: valid, zero-height, never covers the real preview
DEFAULT_BOUNDS = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 0.0}

WINDOW_IDS = sorted(LayoutService.WINDOW_IDS)
_KNOWN = set(WINDOW_IDS)
_BOUNDS_KEYS = ("x", "y", "width", "height")
_MIN = LayoutService.MIN_GRID_SIZE


def _unique(items: list) -> list:
    """De-duplicate report entries by (id, reason), keeping first order."""
    seen, out = set(), []
    for item in items:
        key = (item["id"], item["reason"])
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _usable(value) -> float:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    return value if ok and value > 0 else _MIN


def _fits(values: list) -> bool:
    return all(v >= _MIN for v in values)


def _spread(base: list, remaining: float) -> list:
    excess = [max(0.0, s - _MIN) for s in base]
    total = sum(excess)
    if not total:
        return [100 / len(base)] * len(base)
    return [_MIN + e / total * remaining for e in excess]


def _normalize_sizes(sizes: list) -> list:
    """Mirror of SashCore.normalizeSizes: sum to 100, honour the floor."""
    base = [_usable(s) for s in sizes]
    total = sum(base) or 1
    if abs(total - 100) < 1e-9 and _fits(base):
        return base
    scaled = [s / total * 100 for s in base]
    if _fits(scaled):
        return scaled
    floor_total = _MIN * len(base)
    if floor_total >= 100:
        return [100 / len(base)] * len(base)
    return _spread(base, 100 - floor_total)


def _prune_leaf(node, seen, allowed):
    nid = node.get("id")
    if not isinstance(nid, str) or nid not in allowed or nid in seen:
        return None
    seen.add(nid)
    return {"t": "leaf", "id": nid}


def _child_size(raw_sizes: list, i: int) -> float:
    return _usable(raw_sizes[i] if i < len(raw_sizes) else None)


def _pruned_split(node, kids: list, sizes: list):
    if not kids:
        return None
    if len(kids) == 1:
        return kids[0]
    return {"t": "split",
            "dir": "col" if node.get("dir") == "col" else "row",
            "children": kids, "sizes": _normalize_sizes(sizes)}


def prune_grid_tree(node, seen=None, allowed=None):
    """Mirror of SashCore.pruneTree: drop unknown/duplicate leaves and
    collapse single-child splits; None when nothing usable remains."""
    seen = set() if seen is None else seen
    allowed = _KNOWN if allowed is None else allowed
    kind = LayoutService.node_type(node)
    if kind == "leaf":
        return _prune_leaf(node, seen, allowed)
    if kind != "split" or not isinstance(node.get("children"), list):
        return None
    raw_sizes = node.get("sizes") if isinstance(node.get("sizes"), list) else []
    kids, sizes = [], []
    for i, child in enumerate(node["children"]):
        kept = prune_grid_tree(child, seen, allowed)
        if kept is not None:
            kids.append(kept)
            sizes.append(_child_size(raw_sizes, i))
    return _pruned_split(node, kids, sizes)


def _tree_pruned(before: list) -> list:
    """Report entries for the leaves the repair drops."""
    seen, pruned = set(), []
    for nid in before:
        dup = nid in seen
        seen.add(nid)
        if nid not in _KNOWN or dup:
            pruned.append({"id": nid,
                           "reason": REASON_DUPLICATE if dup else REASON_UNKNOWN})
    return _unique(pruned)


def _is_current_set(ids: list) -> bool:
    """Exactly the current window set, each id once."""
    return sorted(set(ids)) == WINDOW_IDS and len(ids) == len(set(ids))


def adapt_tree(tree, version: int):
    """(tree, report, None) repaired to the CURRENT window set, or
    (None, {}, error). Structural rules stay strict; set drift adapts."""
    if not 1 <= version <= LayoutService.GRID_VERSION:
        return None, {}, f"unsupported version {version!r}"
    normalized, err = LayoutService.normalize_grid_tree(tree)
    if err:
        return None, {}, err
    before = [i for i in LayoutService.leaf_ids(normalized) if isinstance(i, str)]
    if _is_current_set(before):
        return normalized, {"pruned": [], "added": []}, None
    repaired = prune_grid_tree(normalized)
    if repaired is None:
        return None, {}, "tree has no usable windows"
    migrated = LayoutService.migrate_grid_tree(repaired)
    after = set(LayoutService.leaf_ids(migrated))
    if after != _KNOWN:
        return None, {}, "window set mismatch (every window must appear once)"
    added = [{"id": i, "reason": REASON_ADDED}
             for i in WINDOW_IDS if i not in set(before)]
    return migrated, {"pruned": _tree_pruned(before), "added": added}, None


def adapt_states(states):
    """(states, skipped, None) or (None, skipped, error). Unknown ids are
    skipped + reported; duplicates and overlap stay corruption."""
    if not isinstance(states, dict):
        return None, [], "window_states must be an object"
    skipped = []

    def clean(value, label):
        if not isinstance(value, list):
            return None, f"{label} must be a list"
        out = []
        for item in value:
            if not isinstance(item, str) or item not in _KNOWN:
                skipped.append({"id": str(item), "reason": REASON_UNKNOWN})
                continue
            if item in out:
                return None, f"{label} contains a duplicate window"
            out.append(item)
        return out, None

    closed, err = clean(states.get("closed"), "closed")
    if err:
        return None, skipped, err
    minimized, err = clean(states.get("minimized"), "minimized")
    if err:
        return None, skipped, err
    if set(closed) & set(minimized):
        return None, skipped, "closed and minimized window states overlap"
    return {"closed": closed, "minimized": minimized}, _unique(skipped), None


def _entry_state(wid: str, entry: dict, states: dict, corrected: list) -> str:
    if wid in states["closed"]:
        wanted = "closed"
    elif wid in states["minimized"]:
        wanted = "minimized"
    else:
        wanted = "open"
    if entry.get("state") != wanted:
        corrected.append({"id": wid, "reason": REASON_STATE})
    return wanted


def _bound_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and 0 <= value <= 1


def _entry_bounds(entry: dict, wid: str, corrected: list) -> dict:
    bounds = entry.get("bounds")
    if isinstance(bounds, dict):
        values = {k: bounds.get(k) for k in _BOUNDS_KEYS}
        if all(_bound_number(v) for v in values.values()) \
                and values["x"] + values["width"] <= 1.001 \
                and values["y"] + values["height"] <= 1.001:
            return {k: round(values[k], 6) for k in _BOUNDS_KEYS}
    corrected.append({"id": wid, "reason": REASON_BOUNDS})
    return dict(DEFAULT_BOUNDS)


def _index_entries(entries: list, parts: dict):
    """(by_id, None) or (None, error): unknown/duplicate → skipped+reported."""
    by_id = {}
    for entry in entries:
        if not isinstance(entry, dict):
            return None, "each window entry must be an object"
        wid = entry.get("id")
        if not isinstance(wid, str) or wid not in _KNOWN:
            parts["skipped"].append({"id": str(wid), "reason": REASON_UNKNOWN})
            continue
        if wid in by_id:
            parts["skipped"].append({"id": wid, "reason": REASON_DUPLICATE})
            continue
        by_id[wid] = entry
    return by_id, None


def _canonical_entry(entry: dict, states: dict, corrected: list) -> dict:
    wid = entry["id"]
    title = entry.get("title")
    return {"id": wid,
            "title": title if isinstance(title, str) else wid,
            "state": _entry_state(wid, entry, states, corrected),
            "bounds": _entry_bounds(entry, wid, corrected)}


def _added_entry(wid: str, states: dict) -> dict:
    if wid in states["closed"]:
        state = "closed"
    elif wid in states["minimized"]:
        state = "minimized"
    else:
        state = "open"
    return {"id": wid, "title": wid, "state": state,
            "bounds": dict(DEFAULT_BOUNDS)}


def adapt_windows(entries, states: dict):
    """(windows, report_parts, None) — the canonical CURRENT set in
    WINDOW_IDS order — or (None, parts, error) on structural corruption."""
    parts = {"skipped": [], "added": [], "corrected": []}
    if not isinstance(entries, list):
        return None, parts, "windows must be a list"
    by_id, error = _index_entries(entries, parts)
    if error:
        return None, parts, error
    for wid, entry in list(by_id.items()):
        by_id[wid] = _canonical_entry(entry, states, parts["corrected"])
    for wid in WINDOW_IDS:
        if wid not in by_id:
            by_id[wid] = _added_entry(wid, states)
            parts["added"].append({"id": wid, "reason": REASON_ADDED})
    parts["skipped"] = _unique(parts["skipped"])
    parts["corrected"] = _unique(parts["corrected"])
    return [by_id[w] for w in WINDOW_IDS], parts, None


def build_report(tree_report: dict, states_skipped: list,
                 win_parts: dict, windows: list) -> dict:
    """One report shape on both mirrors: every window accounted for."""
    added = _unique(tree_report.get("added", []) + win_parts["added"])
    added_ids = {a["id"] for a in added}
    return {
        "applied": [w["id"] for w in windows if w["id"] not in added_ids],
        "skipped": _unique(tree_report.get("pruned", []) + states_skipped
                           + win_parts["skipped"]),
        "added": added,
        "corrected": win_parts["corrected"],
    }
