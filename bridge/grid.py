"""Grid mixin — SashCore layout versioning and validation (<150)."""
import json

class GridMixin:
    """GRID_VERSION, WINDOW_IDS and tree validation/migration."""

    V1_WINDOW_IDS = {"stats", "filters", "stack", "config", "composer", "people", "log"}
    V2_WINDOW_IDS = V1_WINDOW_IDS | {"history", "userdb", "collector"}
    V3_WINDOW_IDS = V2_WINDOW_IDS | {"labels", "dbconn"}
    LEGACY_WINDOW_IDS = V1_WINDOW_IDS
    NEW_WINDOW_IDS = V3_WINDOW_IDS - V1_WINDOW_IDS
    WINDOW_IDS = V3_WINDOW_IDS
    GRID_VERSION = 3
    MIN_GRID_SIZE = 4

    @classmethod
    def _node_type(cls, node):
        return node.get("t", node.get("type")) if isinstance(node, dict) else None

    @classmethod
    def _normalize_grid_tree(cls, node, depth: int = 0):
        if depth > 12:
            return None, "tree too deep"
        if not isinstance(node, dict):
            return None, "node must be an object"
        node_type = cls._node_type(node)
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
            if isinstance(size, bool) or not isinstance(size, (int, float)) or size < cls.MIN_GRID_SIZE:
                return None, "bad size value (panel below minimum size)"
            clean_sizes.append(size)
        if not 99.5 <= sum(clean_sizes) <= 100.5:
            return None, "sizes must sum to 100"
        clean_kids = []
        for kid in kids:
            clean, err = cls._normalize_grid_tree(kid, depth + 1)
            if err:
                return None, err
            clean_kids.append(clean)
        return {"t": "split", "dir": node["dir"], "children": clean_kids, "sizes": clean_sizes}, None

    @classmethod
    def _validate_grid_tree(cls, node, depth: int = 0):
        _, err = cls._normalize_grid_tree(node, depth)
        return err

    @classmethod
    def _leaf_ids(cls, node, out=None):
        out = [] if out is None else out
        if isinstance(node, dict):
            node_type = cls._node_type(node)
            if node_type == "leaf":
                out.append(node.get("id"))
            elif node_type == "split":
                for kid in node.get("children") or []:
                    cls._leaf_ids(kid, out)
        return out

    @classmethod
    def _parse_grid_payload(cls, raw: str):
        try:
            data = json.loads(raw)
        except Exception as exc:
            return None, f"bad JSON ({exc})"
        if not isinstance(data, dict):
            return None, "payload must be an object"
        version = data.get("v")
        if not isinstance(version, int) or not 1 <= version <= cls.GRID_VERSION:
            return None, f"unsupported version {version!r}"
        tree, err = cls._normalize_grid_tree(data.get("tree"))
        if err:
            return None, err
        got = sorted(i for i in cls._leaf_ids(tree) if i)
        known = {1: sorted(cls.V1_WINDOW_IDS), 2: sorted(cls.V2_WINDOW_IDS)}
        if version < cls.GRID_VERSION and got == known.get(version):
            tree = cls._migrate_grid_tree(tree)
            got = sorted(i for i in cls._leaf_ids(tree) if i)
        if got != sorted(cls.WINDOW_IDS):
            return None, "window set mismatch (every window must appear once)"
        return tree, None

    @classmethod
    def _migrate_grid_tree(cls, tree: dict) -> dict:
        present = {i for i in cls._leaf_ids(tree) if i}
        missing = [i for i in sorted(cls.WINDOW_IDS) if i not in present]
        if not missing:
            return tree
        if len(missing) == 1:
            extra = {"t": "leaf", "id": missing[0]}
        else:
            share = round(100 / len(missing), 4)
            sizes = [share] * len(missing)
            sizes[0] = round(100 - share * (len(missing) - 1), 4)
            extra = {"t": "split", "dir": "row", "children": [{"t": "leaf", "id": i} for i in missing], "sizes": sizes}
        room = min(40, max(cls.MIN_GRID_SIZE, len(missing) * 9))
        return {"t": "split", "dir": "col", "children": [tree, extra], "sizes": [100 - room, room]}

    @classmethod
    def _canonical_grid_payload(cls, raw: str):
        tree, err = cls._parse_grid_payload(raw)
        if err:
            return None, err
        return json.dumps({"v": cls.GRID_VERSION, "tree": tree}, ensure_ascii=False, separators=(",", ":")), None

    @staticmethod
    def _default_grid_tree() -> dict:
        def leaf(i):
            return {"t": "leaf", "id": i}
        def split(d, kids, sizes):
            return {"t": "split", "dir": d, "children": kids, "sizes": sizes}
        return split("col", [
            split("row", [split("col", [leaf("stats"), leaf("filters")], [35, 65]), split("col", [leaf("stack"), leaf("config")], [72, 28])], [17, 83]),
            leaf("composer"),
            split("row", [leaf("people"), leaf("log")], [70, 30]),
            split("row", [leaf("history"), leaf("userdb"), leaf("collector")], [40, 35, 25]),
            split("row", [leaf("labels"), leaf("dbconn")], [55, 45]),
        ], [30, 15, 21, 20, 14])
