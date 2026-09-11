"""LayoutService — grid layout validation, migration and canonical payloads.

The sash-grid tree spec used to live inside the bridge monolith; it is
domain logic (pure functions, no I/O), shared by the LayoutBridge (slots)
and the UndoService (timeline entries). Extracted 2026-09-09.

A layout payload is `{"v": N, "tree": {t: leaf|split}}`; older payloads
are UPGRADED, never rejected, so nobody loses their arrangement on an
app update.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger("chatbot")

#: a split is only meaningful when it divides the space at least twice
_MIN_CHILDREN = 2


def _clean_leaf(node: dict):
    """Canonical form of a leaf, or the `leaf without id` error."""
    node_id = node.get("id")
    if not isinstance(node_id, str) or not node_id:
        return None, "leaf without id"
    return {"t": "leaf", "id": node_id}, None


def _split_shape_error(kids, sizes) -> str | None:
    """Why this split is not a split, or None when its shape is sound."""
    if not isinstance(kids, list) or len(kids) < _MIN_CHILDREN:
        return "split needs >=2 children"
    if not isinstance(sizes, list) or len(sizes) != len(kids):
        return "sizes must match children"
    return None


def _clean_sizes(sizes, min_size):
    """Validate the size list (type, floor, sum to 100) and copy it."""
    for size in sizes:
        if (isinstance(size, bool) or not isinstance(size, (int, float))
                or size < min_size):
            return None, "bad size value (panel below minimum size)"
    if not 99.5 <= sum(sizes) <= 100.5:
        return None, "sizes must sum to 100"
    return list(sizes), None


def _clean_children(kids, depth, normalize):
    """Normalise every child with `normalize` (the classmethod, so a subclass
    override still reaches the leaves)."""
    out = []
    for kid in kids:
        clean, err = normalize(kid, depth + 1)
        if err:
            return None, err
        out.append(clean)
    return out, None


class LayoutService:
    """Grid tree spec: window sets, versions, validation, migration."""

    #: window sets per layout version
    V1_WINDOW_IDS = {"stats", "filters", "stack", "config", "composer",
                     "people", "log"}
    V2_WINDOW_IDS = V1_WINDOW_IDS | {"history", "userdb", "collector"}
    V3_WINDOW_IDS = V2_WINDOW_IDS | {"labels", "dbconn"}
    LEGACY_WINDOW_IDS = V1_WINDOW_IDS            # kept for older callers
    NEW_WINDOW_IDS = V3_WINDOW_IDS - V1_WINDOW_IDS
    WINDOW_IDS = V3_WINDOW_IDS
    GRID_VERSION = 3
    MIN_GRID_SIZE = 4

    # ── tree helpers ─────────────────────────────────────────────
    @classmethod
    def node_type(cls, node):
        """Read both spellings, with SashCore's `t` as the canonical one."""
        return node.get("t", node.get("type")) if isinstance(node, dict) \
            else None

    @classmethod
    def normalize_grid_tree(cls, node, depth: int = 0):
        """Return a canonical `t` tree or an explanatory validation error.

        The four decisions are the module-level validators above; this method
        is only their order: depth, object, leaf, split shape, sizes, children.
        """
        if depth > 12:
            return None, "tree too deep"
        if not isinstance(node, dict):
            return None, "node must be an object"
        kind = cls.node_type(node)
        if kind == "leaf":
            return _clean_leaf(node)
        if kind != "split":
            return None, "unknown node type"
        if node.get("dir") not in ("row", "col"):
            return None, "bad dir"
        kids, sizes = node.get("children"), node.get("sizes")
        shape = _split_shape_error(kids, sizes)
        if shape:
            return None, shape
        clean_sizes, err = _clean_sizes(sizes, cls.MIN_GRID_SIZE)
        if err:
            return None, err
        clean_kids, err = _clean_children(kids, depth, cls.normalize_grid_tree)
        if err:
            return None, err
        return {"t": "split", "dir": node["dir"],
                "children": clean_kids, "sizes": clean_sizes}, None

    @classmethod
    def validate_grid_tree(cls, node, depth: int = 0):
        """Validate both legacy `type` and current SashCore `t` nodes."""
        _, err = cls.normalize_grid_tree(node, depth)
        return err

    @classmethod
    def leaf_ids(cls, node, out=None):
        out = [] if out is None else out
        if isinstance(node, dict):
            node_type = cls.node_type(node)
            if node_type == "leaf":
                out.append(node.get("id"))
            elif node_type == "split":
                for kid in node.get("children") or []:
                    cls.leaf_ids(kid, out)
        return out

    # ── payload parsing ──────────────────────────────────────────
    @classmethod
    def parse_grid_payload(cls, raw: str):
        """Return (canonical tree, None) or (None, error)."""
        try:
            data = json.loads(raw)
        except Exception as exc:                        # noqa: BLE001
            return None, f"bad JSON ({exc})"
        if not isinstance(data, dict):
            return None, "payload must be an object"
        version = data.get("v")
        if not isinstance(version, int) or not 1 <= version <= cls.GRID_VERSION:
            return None, f"unsupported version {version!r}"
        tree, err = cls.normalize_grid_tree(data.get("tree"))
        if err:
            return None, err
        return cls._match_window_set(tree, version)

    @classmethod
    def _match_window_set(cls, tree, version: int):
        """The tree, checked to cover every window — an older set upgraded first.

        A layout saved before newer windows existed is migrated rather than
        rejected: rejecting it would throw the user's own arrangement away on
        the first start after an update, which is the worse bug.
        """
        if version < cls.GRID_VERSION:
            previous = {1: sorted(cls.V1_WINDOW_IDS),
                        2: sorted(cls.V2_WINDOW_IDS)}.get(version)
            if sorted(i for i in cls.leaf_ids(tree) if i) == previous:
                tree = cls.migrate_grid_tree(tree)
        if sorted(i for i in cls.leaf_ids(tree) if i) != sorted(cls.WINDOW_IDS):
            return None, ("window set mismatch "
                          "(every window must appear once)")
        return tree, None

    @classmethod
    def migrate_grid_tree(cls, tree: dict) -> dict:
        """Keep the stored arrangement and append whatever windows are new."""
        present = {i for i in cls.leaf_ids(tree) if i}
        missing = [i for i in sorted(cls.WINDOW_IDS) if i not in present]
        if not missing:
            return tree
        if len(missing) == 1:
            extra = {"t": "leaf", "id": missing[0]}
        else:
            share = round(100 / len(missing), 4)
            sizes = [share] * len(missing)
            sizes[0] = round(100 - share * (len(missing) - 1), 4)
            extra = {"t": "split", "dir": "row",
                     "children": [{"t": "leaf", "id": i} for i in missing],
                     "sizes": sizes}
        room = min(40, max(cls.MIN_GRID_SIZE, len(missing) * 9))
        return {"t": "split", "dir": "col", "children": [tree, extra],
                "sizes": [100 - room, room]}

    @classmethod
    def canonical_grid_payload(cls, raw: str):
        """Canonical JSON payload for a valid layout, or (None, error)."""
        tree, err = cls.parse_grid_payload(raw)
        if err:
            return None, err
        return json.dumps({"v": cls.GRID_VERSION, "tree": tree},
                          ensure_ascii=False, separators=(",", ":")), None

    @classmethod
    def default_grid_tree(cls) -> dict:
        """Mirror of SashCore.defaultTree(): every window, classic order."""
        def leaf(i):
            return {"t": "leaf", "id": i}

        def split(d, kids, sizes):
            return {"t": "split", "dir": d, "children": kids, "sizes": sizes}

        return split("col", [
            split("row", [
                split("col", [leaf("stats"), leaf("filters")], [35, 65]),
                split("col", [leaf("stack"), leaf("config")], [72, 28]),
            ], [17, 83]),
            leaf("composer"),
            split("row", [leaf("people"), leaf("log")], [70, 30]),
            split("row", [leaf("history"), leaf("userdb"),
                          leaf("collector")], [40, 35, 25]),
            split("row", [leaf("labels"), leaf("dbconn")], [55, 45]),
        ], [30, 15, 21, 20, 14])

    @classmethod
    def default_payload(cls) -> str:
        return json.dumps({"v": cls.GRID_VERSION, "tree":
                           cls.default_grid_tree()},
                          ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def legacy_grid_payload(cls, raw: str):
        """Render a canonical payload in the old `type` spelling only for
        callers of the retired compatibility slots."""
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return raw

        def convert(node):
            if not isinstance(node, dict):
                return node
            if cls.node_type(node) == "leaf":
                return {"type": "leaf", "id": node.get("id")}
            return {"type": "split", "dir": node.get("dir"),
                    "children": [convert(k) for k in node.get("children", [])],
                    "sizes": node.get("sizes", [])}

        if isinstance(data, dict) and data.get("v") == 1:
            data["tree"] = convert(data.get("tree"))
        return json.dumps(data, ensure_ascii=False)
