"""LayoutService payload — extracted from layout_service (H-C5 split)

Payload parsing, migration, canonical, ≤150 LOC.
"""

from __future__ import annotations

import json
import logging

from services.layout_service_tree import LayoutServiceTree

log = logging.getLogger("chatbot")


class LayoutServicePayload(LayoutServiceTree):
    @classmethod
    def _decode_payload(cls, raw: str):
        try:
            data = json.loads(raw)
        except Exception as exc:
            return None, f"bad JSON ({exc})"
        if not isinstance(data, dict):
            return None, "payload must be an object"
        version = data.get("v")
        if not isinstance(version, int) or not 1 <= version <= cls.GRID_VERSION:
            return None, f"unsupported version {version!r}"
        return data, None

    @classmethod
    def _window_set_ok(cls, tree, version):
        got = sorted(i for i in cls.leaf_ids(tree) if i)
        known = {1: sorted(cls.V1_WINDOW_IDS), 2: sorted(cls.V2_WINDOW_IDS), 3: sorted(cls.V3_WINDOW_IDS)}
        if version < cls.GRID_VERSION and got == known.get(version):
            tree = cls.migrate_grid_tree(tree)
            got = sorted(i for i in cls.leaf_ids(tree) if i)
        if got != sorted(cls.WINDOW_IDS):
            return None, "window set mismatch (every window must appear once)"
        return tree, None

    @classmethod
    def parse_grid_payload(cls, raw: str):
        data, err = cls._decode_payload(raw)
        if err:
            return None, err
        tree, err = cls.normalize_grid_tree(data.get("tree"))
        if err:
            return None, err
        return cls._window_set_ok(tree, data.get("v"))

    @classmethod
    def migrate_grid_tree(cls, tree: dict) -> dict:
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
            extra = {"t": "split", "dir": "row", "children": [{"t": "leaf", "id": i} for i in missing], "sizes": sizes}
        room = min(40, max(cls.MIN_GRID_SIZE, len(missing) * 9))
        return {"t": "split", "dir": "col", "children": [tree, extra], "sizes": [100 - room, room]}

    @classmethod
    def canonical_grid_payload(cls, raw: str):
        tree, err = cls.parse_grid_payload(raw)
        if err:
            return None, err
        return json.dumps({"v": cls.GRID_VERSION, "tree": tree}, ensure_ascii=False, separators=(",", ":")), None

    @classmethod
    def default_grid_tree(cls) -> dict:
        def leaf(i):
            return {"t": "leaf", "id": i}

        def split(d, kids, sizes):
            return {"t": "split", "dir": d, "children": kids, "sizes": sizes}

        return split(
            "col",
            [
                split("row", [split("col", [leaf("stats"), leaf("filters")], [35, 65]), split("col", [leaf("stack"), leaf("config")], [72, 28])], [17, 83]),
                leaf("composer"),
                split("row", [leaf("people"), leaf("log")], [70, 30]),
                split("row", [leaf("history"), leaf("userdb"), leaf("collector")], [40, 35, 25]),
                split("row", [leaf("labels"), leaf("dbconn")], [55, 45]),
                split("row", [leaf("botchat"), leaf("botprompt")], [62, 38]),
            ],
            [26, 13, 18, 17, 12, 14],
        )

    @classmethod
    def default_payload(cls) -> str:
        return json.dumps({"v": cls.GRID_VERSION, "tree": cls.default_grid_tree()}, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def legacy_grid_payload(cls, raw: str):
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return raw

        def convert(node):
            if not isinstance(node, dict):
                return node
            if cls.node_type(node) == "leaf":
                return {"type": "leaf", "id": node.get("id")}
            return {"type": "split", "dir": node.get("dir"), "children": [convert(k) for k in node.get("children", [])], "sizes": node.get("sizes", [])}

        if isinstance(data, dict) and data.get("v") == 1:
            data["tree"] = convert(data.get("tree"))
        return json.dumps(data, ensure_ascii=False)
