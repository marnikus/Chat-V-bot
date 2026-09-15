"""LayoutService tree — extracted from layout_service (H-C5 split)

Tree helpers, ≤150 LOC.
"""

from __future__ import annotations

import logging

log = logging.getLogger("chatbot")


class LayoutServiceTree:
    V1_WINDOW_IDS = {"stats", "filters", "stack", "config", "composer", "people", "log"}
    V2_WINDOW_IDS = V1_WINDOW_IDS | {"history", "userdb", "collector"}
    V3_WINDOW_IDS = V2_WINDOW_IDS | {"labels", "dbconn"}
    V4_WINDOW_IDS = V3_WINDOW_IDS | {"botchat", "botprompt"}
    LEGACY_WINDOW_IDS = V1_WINDOW_IDS
    NEW_WINDOW_IDS = V4_WINDOW_IDS - V1_WINDOW_IDS
    WINDOW_IDS = V4_WINDOW_IDS
    GRID_VERSION = 4
    MIN_GRID_SIZE = 4

    @classmethod
    def node_type(cls, node):
        return node.get("t", node.get("type")) if isinstance(node, dict) else None

    @classmethod
    def _clean_leaf(cls, node):
        if not isinstance(node.get("id"), str) or not node.get("id"):
            return None, "leaf without id"
        return {"t": "leaf", "id": node["id"]}, None

    @classmethod
    def _clean_sizes(cls, sizes):
        clean_sizes = []
        for size in sizes:
            if isinstance(size, bool) or not isinstance(size, (int, float)) or size < cls.MIN_GRID_SIZE:
                return None, "bad size value (panel below minimum size)"
            clean_sizes.append(size)
        if not 99.5 <= sum(clean_sizes) <= 100.5:
            return None, "sizes must sum to 100"
        return clean_sizes, None

    @classmethod
    def _clean_split(cls, node, depth):
        kids, sizes = node.get("children"), node.get("sizes")
        if not isinstance(kids, list) or len(kids) < 2:
            return None, "split needs >=2 children"
        if not isinstance(sizes, list) or len(sizes) != len(kids):
            return None, "sizes must match children"
        clean_sizes, err = cls._clean_sizes(sizes)
        if err:
            return None, err
        clean_kids = []
        for kid in kids:
            clean, err = cls.normalize_grid_tree(kid, depth + 1)
            if err:
                return None, err
            clean_kids.append(clean)
        return {"t": "split", "dir": node["dir"], "children": clean_kids, "sizes": clean_sizes}, None

    @classmethod
    def normalize_grid_tree(cls, node, depth: int = 0):
        if depth > 12:
            return None, "tree too deep"
        if not isinstance(node, dict):
            return None, "node must be an object"
        node_type = cls.node_type(node)
        if node_type == "leaf":
            return cls._clean_leaf(node)
        if node_type != "split":
            return None, "unknown node type"
        if node.get("dir") not in ("row", "col"):
            return None, "bad dir"
        return cls._clean_split(node, depth)

    @classmethod
    def validate_grid_tree(cls, node, depth: int = 0):
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
