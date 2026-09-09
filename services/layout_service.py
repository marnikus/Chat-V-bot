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
        """Return a canonical `t` tree or an explanatory validation error."""
        if depth > 12:
            return None, "tree too deep"
        if not isinstance(node, dict):
            return None, "node must be an object"
        node_type = cls.node_type(node)
        if node_type == "leaf":
            if not isinstance(node.get("id"), str) or not node.get("id"):
                return None, "leaf without id"
            return {"t": "leaf", "id": node["id"]}, None
        if node_type != "split":
            return None, "unknown node type"
        if node.get("dir") not in ("row", "col"):
            return None, "bad dir"
        kids, sizes = node.get("children"), node.get("sizes")
        if not isinstance(kids, list) or len(kids) < 2:
            return None, "split needs >=2 children"
        if not isinstance(sizes, list) or len(sizes) != len(kids):
            return None, "sizes must match children"
        clean_sizes = []
        for size in sizes:
            if (isinstance(size, bool) or not isinstance(size, (int, float))
                    or size < cls.MIN_GRID_SIZE):
                return None, "bad size value (panel below minimum size)"
            clean_sizes.append(size)
        if not 99.5 <= sum(clean_sizes) <= 100.5:
            return None, "sizes must sum to 100"
        clean_kids = []
        for kid in kids:
            clean, err = cls.normalize_grid_tree(kid, depth + 1)
            if err:
                return None, err
            clean_kids.append(clean)
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
        if not isinstance(version, int) or \
                not 1 <= version <= cls.GRID_VERSION:
            return None, f"unsupported version {version!r}"
        tree, err = cls.normalize_grid_tree(data.get("tree"))
        if err:
            return None, err
        got = sorted(i for i in cls.leaf_ids(tree) if i)
        known = {1: sorted(cls.V1_WINDOW_IDS), 2: sorted(cls.V2_WINDOW_IDS)}
        if version < cls.GRID_VERSION and got == known.get(version):
            # A layout saved before newer windows existed. Rejecting it
            # would throw away the user's arrangement on first start
            # after the update, so it is upgraded instead.
            tree = cls.migrate_grid_tree(tree)
            got = sorted(i for i in cls.leaf_ids(tree) if i)
        if got != sorted(cls.WINDOW_IDS):
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
