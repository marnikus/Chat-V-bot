"""services/layout_service — grid tree validation, migration, canonical payloads.

Pure logic, no I/O. The contract (docs/archive/2026-09-09-test-suite/SERVICES_TEST_DESIGN_2026-09-09.md
§2.2): a layout payload is ``{"v": N, "tree": {t: leaf|split}}``; older
payloads are UPGRADED, never rejected; invalid payloads return
``(None, error)`` — they never raise and never destroy a stored layout.

Run with:  python3 tests/integration/services/test_services_layout.py
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from services.layout_service import LayoutService  # noqa: E402

LS = LayoutService


def split_of(ids, d="col", spelling="t"):
    """One flat split containing exactly `ids` (sums to 100)."""
    n = len(ids)
    share = round(100.0 / n, 4)
    sizes = [share] * (n - 1)
    sizes.append(round(100.0 - share * (n - 1), 4))
    leaf = (lambda i: {"t": "leaf", "id": i}) if spelling == "t" \
        else (lambda i: {"type": "leaf", "id": i})
    return {"t": "split", "dir": d,
            "children": [leaf(i) for i in ids],
            "sizes": sizes}


def payload(tree, v=3):
    return json.dumps({"v": v, "tree": tree})


class TestWindowSets(unittest.TestCase):
    def test_every_window_id_is_known_at_least_once(self):
        for wid in LS.WINDOW_IDS:
            self.assertIn(wid, LS.LEGACY_WINDOW_IDS | LS.NEW_WINDOW_IDS)
        self.assertEqual(LS.GRID_VERSION, 3)

    def test_default_tree_contains_every_window_once(self):
        tree = LS.default_grid_tree()
        self.assertIsNone(LS.validate_grid_tree(tree))
        ids = LS.leaf_ids(tree)
        self.assertEqual(sorted(ids), sorted(LS.WINDOW_IDS))
        self.assertEqual(len(ids), len(set(ids)), "no duplicate windows")

    def test_default_payload_parses_and_is_canonical(self):
        raw = LS.default_payload()
        tree, err = LS.parse_grid_payload(raw)
        self.assertIsNone(err)
        self.assertIsNotNone(tree)
        self.assertEqual(sorted(LS.leaf_ids(tree)), sorted(LS.WINDOW_IDS))
        again, err2 = LS.canonical_grid_payload(raw)
        self.assertIsNone(err2)
        self.assertEqual(again, raw, "default payload is already canonical")


class TestNodeType(unittest.TestCase):
    def test_both_spellings_are_read(self):
        self.assertEqual(LS.node_type({"t": "leaf"}), "leaf")
        self.assertEqual(LS.node_type({"type": "split"}), "split")

    def test_non_dict_returns_none(self):
        self.assertIsNone(LS.node_type(None))
        self.assertIsNone(LS.node_type("leaf"))
        # an unknown string is returned as-is; validation decides
        self.assertEqual(LS.node_type({"t": "bogus"}), "bogus")
        self.assertEqual(LS.node_type({"type": "leaf"}), "leaf")


class TestNormalizeTree(unittest.TestCase):
    def test_valid_leaf(self):
        clean, err = LS.normalize_grid_tree({"t": "leaf", "id": "stats"})
        self.assertIsNone(err)
        self.assertEqual(clean, {"t": "leaf", "id": "stats"})

    def test_leaf_without_id(self):
        _, err = LS.normalize_grid_tree({"t": "leaf"})
        self.assertEqual(err, "leaf without id")
        _, err = LS.normalize_grid_tree({"t": "leaf", "id": ""})
        self.assertEqual(err, "leaf without id")

    def test_unknown_node_type(self):
        _, err = LS.normalize_grid_tree({"t": "window", "id": "stats"})
        self.assertEqual(err, "unknown node type")

    def test_non_object_node(self):
        _, err = LS.normalize_grid_tree(["stats"])
        self.assertEqual(err, "node must be an object")

    def test_split_bad_dir(self):
        tree = {"t": "split", "dir": "diag",
                "children": [{"t": "leaf", "id": "a"},
                             {"t": "leaf", "id": "b"}],
                "sizes": [50, 50]}
        _, err = LS.normalize_grid_tree(tree)
        self.assertEqual(err, "bad dir")

    def test_split_requires_two_children(self):
        tree = {"t": "split", "dir": "row", "children": [{"t": "leaf", "id": "a"}],
                "sizes": [100]}
        _, err = LS.normalize_grid_tree(tree)
        self.assertEqual(err, "split needs >=2 children")

    def test_sizes_must_match_children(self):
        tree = {"t": "split", "dir": "row",
                "children": [{"t": "leaf", "id": "a"}, {"t": "leaf", "id": "b"}],
                "sizes": [60]}
        _, err = LS.normalize_grid_tree(tree)
        self.assertEqual(err, "sizes must match children")

    def test_size_minimum_and_bool_rejected(self):
        base = {"t": "split", "dir": "row",
                "children": [{"t": "leaf", "id": "a"}, {"t": "leaf", "id": "b"}]}
        for bad in ([0, 100], [3, 97], [True, 100], ["50", 50]):
            tree = dict(base, sizes=bad)
            _, err = LS.normalize_grid_tree(tree)
            self.assertTrue(err and "size" in err, err)

    def test_sizes_must_sum_to_100(self):
        tree = {"t": "split", "dir": "row",
                "children": [{"t": "leaf", "id": "a"}, {"t": "leaf", "id": "b"}],
                "sizes": [4, 4]}
        _, err = LS.normalize_grid_tree(tree)
        self.assertEqual(err, "sizes must sum to 100")

    def test_depth_guard(self):
        kid = {"t": "leaf", "id": "x"}
        node = kid
        for i in range(15):
            node = {"t": "split", "dir": "row", "children": [node, kid],
                    "sizes": [50, 50]}
        _, err = LS.normalize_grid_tree(node)
        self.assertEqual(err, "tree too deep")

    def test_legacy_type_spelling_normalized(self):
        tree = {"type": "split", "dir": "row",
                "children": [{"type": "leaf", "id": "a"},
                             {"type": "leaf", "id": "b"}],
                "sizes": [50, 50]}
        clean, err = LS.normalize_grid_tree(tree)
        self.assertIsNone(err)
        self.assertEqual(clean["t"], "split")
        self.assertNotIn("type", clean)
        self.assertEqual(clean["children"][0], {"t": "leaf", "id": "a"})


class TestLeafIds(unittest.TestCase):
    def test_lists_every_leaf_including_duplicates(self):
        tree = {"t": "split", "dir": "row",
                "children": [{"t": "leaf", "id": "dup"},
                             {"t": "leaf", "id": "dup"},
                             {"t": "leaf", "id": "x"}],
                "sizes": [34, 33, 33]}
        self.assertEqual(LS.leaf_ids(tree), ["dup", "dup", "x"])

    def test_non_tree_empty(self):
        self.assertEqual(LS.leaf_ids(None), [])
        self.assertEqual(LS.leaf_ids({"t": "bogus"}), [])


class TestParsePayload(unittest.TestCase):
    def test_bad_json_returns_error(self):
        _, err = LS.parse_grid_payload("{not json")
        self.assertTrue(err and "bad JSON" in err, err)

    def test_non_object_payload(self):
        _, err = LS.parse_grid_payload("[]")
        self.assertEqual(err, "payload must be an object")

    def test_unsupported_version(self):
        for v in (0, 4, "3", None):
            _, err = LS.parse_grid_payload(json.dumps(
                {"v": v, "tree": LS.default_grid_tree()}))
            self.assertTrue(err and "unsupported version" in err, err)

    def test_window_set_mismatch_rejected(self):
        tree = split_of(sorted(LS.WINDOW_IDS)[:-1])
        _, err = LS.parse_grid_payload(payload(tree))
        self.assertTrue(err and "window set mismatch" in err, err)

    def test_legacy_v1_upgraded_not_rejected(self):
        ids = sorted(LS.V1_WINDOW_IDS)
        legacy = {"type": "split", "dir": "col",
                  "children": [{"type": "leaf", "id": i} for i in ids],
                  "sizes": split_of(ids)["sizes"]}
        tree, err = LS.parse_grid_payload(payload(legacy, v=1))
        self.assertIsNone(err, "a pre-update layout must never be rejected")
        got = sorted(LS.leaf_ids(tree))
        self.assertEqual(got, sorted(LS.WINDOW_IDS),
                         "missing new windows must be appended")
        self.assertNotIn("type", json.dumps(tree))

    def test_v2_upgraded(self):
        ids = sorted(LS.V2_WINDOW_IDS)
        tree = split_of(ids, spelling="type")
        parsed, err = LS.parse_grid_payload(payload(tree, v=2))
        self.assertIsNone(err)
        self.assertEqual(sorted(LS.leaf_ids(parsed)), sorted(LS.WINDOW_IDS))


class TestMigrate(unittest.TestCase):
    def test_no_missing_windows_returns_same_object(self):
        full = LS.default_grid_tree()
        self.assertIs(LS.migrate_grid_tree(full), full)

    def test_one_missing_window_appends_a_leaf(self):
        missing = sorted(LS.WINDOW_IDS)[-1]
        tree = split_of(sorted(LS.WINDOW_IDS)[:-1])
        self.assertIsNone(LS.validate_grid_tree(tree))
        moved = LS.migrate_grid_tree(tree)
        got = sorted(LS.leaf_ids(moved))
        self.assertIsNone(LS.validate_grid_tree(moved))
        self.assertEqual(got, sorted(LS.WINDOW_IDS))
        self.assertIn(missing, got)

    def test_several_missing_windows_share_one_split(self):
        tree = split_of(sorted(LS.WINDOW_IDS)[:8])
        moved = LS.migrate_grid_tree(tree)
        self.assertIsNone(LS.validate_grid_tree(moved))
        self.assertEqual(sorted(LS.leaf_ids(moved)), sorted(LS.WINDOW_IDS))
        # the extra split must sum to 100 and respect the minimum size
        sizes = moved["sizes"]
        self.assertGreaterEqual(min(sizes), LS.MIN_GRID_SIZE)
        self.assertLessEqual(sum(sizes), 100.5)
        self.assertGreaterEqual(sum(sizes), 99.5)


class TestCanonicalAndLegacy(unittest.TestCase):
    def test_canonical_payload_is_compact(self):
        raw = json.dumps({"v": 3, "tree": LS.default_grid_tree()},
                         ensure_ascii=False, indent=2)
        out, err = LS.canonical_grid_payload(raw)
        self.assertIsNone(err)
        self.assertNotIn("\n", out)
        self.assertEqual(json.loads(out)["v"], 3)

    def test_canonical_rejects_invalid(self):
        out, err = LS.canonical_grid_payload("{bad")
        self.assertIsNone(out)
        self.assertTrue(err)

    def test_legacy_payload_converts_v1_only(self):
        raw = payload({"type": "split", "dir": "row", "children": [], "sizes": []}, v=1)
        out = LS.legacy_grid_payload(raw)
        data = json.loads(out)
        self.assertEqual(data["v"], 1)
        self.assertIn("type", json.dumps(data["tree"]))

    def test_legacy_payload_leaves_v3_untouched(self):
        raw = LS.default_payload()
        out = LS.legacy_grid_payload(raw)
        self.assertEqual(json.loads(out), json.loads(raw),
                         "a v3 payload must keep its canonical `t` tree")
        self.assertNotIn("type", out)

    def test_legacy_payload_passthrough_on_bad_json(self):
        self.assertEqual(LS.legacy_grid_payload("{nope"), "{nope")

    def test_payload_round_trip_is_idempotent(self):
        raw = payload(split_of(sorted(LS.WINDOW_IDS)))
        can1, err = LS.canonical_grid_payload(raw)
        self.assertIsNone(err)
        can2, err = LS.canonical_grid_payload(can1)
        self.assertIsNone(err)
        self.assertEqual(can1, can2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
