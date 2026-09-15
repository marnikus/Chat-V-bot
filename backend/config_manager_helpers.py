"""Config manager helpers — extracted from config_manager (H-C5 split)

_deep_merge, _set_nested, ≤80 LOC.
"""

from __future__ import annotations

from typing import Any


def _deep_merge(base: dict, overlay: Any) -> dict:
    if not isinstance(overlay, dict):
        return overlay
    out = dict(base)
    for key, value in overlay.items():
        current = out.get(key)
        out[key] = _deep_merge(current, value) if isinstance(current, dict) and isinstance(value, dict) else value
    return out


def _set_nested(tree: Any, path, value) -> bool:
    node = tree
    for key in path[:-1]:
        if not isinstance(node, dict):
            return False
        if not isinstance(node.get(key), dict):
            node[key] = {}
        node = node[key]
    if not isinstance(node, dict):
        return False
    node[path[-1]] = value
    return True
