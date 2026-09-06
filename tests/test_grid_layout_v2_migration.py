"""Upgrading a saved v1 grid layout to the v2 window set.

The archive adds three windows (Person History, User Database, Chat Message
Collector). A stored layout is validated against the window set and rejected
on mismatch, so without a migration every existing user would silently lose
their arrangement on first start after the update.

Rules proven here:
  * a v1 payload holding exactly the seven legacy windows is ACCEPTED and
    upgraded — the old arrangement is preserved and the new windows are added;
  * a v1 payload that was never legal (missing/duplicated windows) is still
    rejected, so migration cannot be used to smuggle a broken tree in;
  * what gets stored afterwards is canonical v2.

Run with:  python3 tests/test_grid_layout_v2_migration.py
"""

import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject  # noqa: E402

from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402

LEGACY_WINDOWS = ["stats", "filters", "stack", "config", "composer", "people",
                  "log"]
NEW_WINDOWS = ["history", "userdb", "collector"]
ALL_WINDOWS = LEGACY_WINDOWS + NEW_WINDOWS


def leaf(i):
    return {"t": "leaf", "id": i}


def split(d, kids, sizes):
    return {"t": "split", "dir": d, "children": kids, "sizes": sizes}


def v1(tree):
    return json.dumps({"v": 1, "tree": tree}, ensure_ascii=False)


def v2(tree):
    return json.dumps({"v": 2, "tree": tree}, ensure_ascii=False)


def flat_v1():
    """The shipped v1 default shape: a flat column of the seven windows."""
    return split("col", [leaf(i) for i in LEGACY_WINDOWS],
                 [16, 14, 14, 14, 14, 14, 14])


def nested_v1():
    """A hand-made v1 arrangement worth preserving."""
    return split("row", [
        leaf("stats"),
        split("col", [leaf("filters"), leaf("stack"), leaf("config")],
              [34, 33, 33]),
        split("col", [leaf("composer"), leaf("people"), leaf("log")],
              [34, 33, 33]),
    ], [20, 40, 40])


def make_bridge():
    tmp = tempfile.mkdtemp()
    cfg = ConfigManager(os.path.join(tmp, "config.json"))
    br = Bridge.__new__(Bridge)
    QObject.__init__(br)
    br._config = cfg
    br._engine = types.SimpleNamespace(load_stack=lambda _blocks: None)
    return br, cfg


def sizes_of(node):
    out = []
    if node.get("t") == "split":
        out.append(sum(node["sizes"]))
        for child in node["children"]:
            out.extend(sizes_of(child))
    return out


class TestWindowSet(unittest.TestCase):
    def test_the_three_new_windows_exist(self):
        for wid in NEW_WINDOWS:
            self.assertIn(wid, Bridge.WINDOW_IDS)

    def test_no_legacy_window_was_dropped(self):
        for wid in LEGACY_WINDOWS:
            self.assertIn(wid, Bridge.WINDOW_IDS)

    def test_the_default_layout_shows_all_of_them(self):
        tree = Bridge._default_grid_tree()
        self.assertEqual(sorted(Bridge._leaf_ids(tree)), sorted(ALL_WINDOWS))
        self.assertIsNone(Bridge._validate_grid_tree(tree))


class TestMigration(unittest.TestCase):
    def parse(self, raw):
        tree, err = Bridge._parse_grid_payload(raw)
        self.assertIsNone(err, f"unexpected rejection: {err}")
        return tree

    def test_a_v1_layout_is_accepted(self):
        self.parse(v1(flat_v1()))

    def test_the_new_windows_are_added(self):
        tree = self.parse(v1(flat_v1()))
        self.assertEqual(sorted(Bridge._leaf_ids(tree)), sorted(ALL_WINDOWS))

    def test_the_old_windows_keep_their_relative_order(self):
        tree = self.parse(v1(nested_v1()))
        got = [i for i in Bridge._leaf_ids(tree) if i in LEGACY_WINDOWS]
        self.assertEqual(got, Bridge._leaf_ids(nested_v1()))

    def test_the_result_is_a_valid_tree(self):
        for source in (flat_v1(), nested_v1()):
            tree = self.parse(v1(source))
            self.assertIsNone(Bridge._validate_grid_tree(tree))
            for total in sizes_of(tree):
                self.assertAlmostEqual(total, 100, delta=0.5)

    def test_no_pane_is_migrated_to_zero_size(self):
        tree = self.parse(v1(nested_v1()))

        def walk(node):
            if node.get("t") == "split":
                for size in node["sizes"]:
                    self.assertGreaterEqual(size, Bridge.MIN_GRID_SIZE)
                for child in node["children"]:
                    walk(child)
        walk(tree)

    def test_migrating_twice_is_stable(self):
        once = self.parse(v1(flat_v1()))
        twice = self.parse(v2(once))
        self.assertEqual(twice, once)

    def test_an_already_v2_layout_is_untouched(self):
        tree = a = Bridge._default_grid_tree()
        self.assertEqual(self.parse(v2(tree)), a)


class TestMigrationRefusals(unittest.TestCase):
    def _err(self, raw):
        return Bridge._parse_grid_payload(raw)[1]

    def test_an_incomplete_v1_tree_is_still_rejected(self):
        tree = split("row", [leaf("stats"), leaf("log")], [50, 50])
        self.assertIn("window set", self._err(v1(tree)))

    def test_a_v1_tree_with_a_duplicate_is_still_rejected(self):
        ids = LEGACY_WINDOWS + ["log"]
        tree = split("col", [leaf(i) for i in ids], [12.5] * 8)
        self.assertIn("window set", self._err(v1(tree)))

    def test_a_v1_tree_with_an_unknown_window_is_rejected(self):
        ids = LEGACY_WINDOWS + ["ghost"]
        tree = split("col", [leaf(i) for i in ids], [12.5] * 8)
        self.assertIn("window set", self._err(v1(tree)))

    def test_a_structurally_broken_v1_tree_is_rejected(self):
        self.assertIn("children", self._err(
            v1(split("row", [leaf("stats")], [100]))))

    def test_an_unknown_version_is_rejected(self):
        self.assertIn("version", self._err(
            json.dumps({"v": 3, "tree": Bridge._default_grid_tree()})))


class TestPersistedUpgrade(unittest.TestCase):
    def test_saving_a_v1_layout_stores_v2(self):
        br, cfg = make_bridge()
        self.assertTrue(br.save_grid_layout(v1(nested_v1())))
        stored = json.loads(cfg.get_state("grid_layout"))
        self.assertEqual(stored["v"], 2)
        self.assertEqual(sorted(Bridge._leaf_ids(stored["tree"])),
                         sorted(ALL_WINDOWS))

    def test_a_layout_stored_by_the_old_version_reads_back_upgraded(self):
        br, cfg = make_bridge()
        cfg.set_state(grid_layout=v1(nested_v1()))
        got = json.loads(br.get_grid_layout())
        self.assertEqual(got["v"], 2)
        self.assertEqual(sorted(Bridge._leaf_ids(got["tree"])),
                         sorted(ALL_WINDOWS))

    def test_a_stored_layout_that_cannot_be_migrated_falls_back(self):
        br, cfg = make_bridge()
        cfg.set_state(grid_layout=v1({"t": "leaf", "id": "stats"}))
        raw = br.get_grid_layout()
        self.assertTrue(raw == "" or
                        sorted(Bridge._leaf_ids(json.loads(raw)["tree"])) ==
                        sorted(ALL_WINDOWS),
                        "an unusable layout must not crash the grid")

    def test_the_upgrade_is_a_normal_undo_step(self):
        br, _cfg = make_bridge()
        br.save_grid_layout(v1(flat_v1()))
        br.save_grid_layout(v2(Bridge._default_grid_tree()))
        result = json.loads(br.undo())
        self.assertEqual(result["kind"], "grid")
        self.assertEqual(json.loads(result["value"])["v"], 2)
        self.assertEqual(
            sorted(Bridge._leaf_ids(json.loads(result["value"])["tree"])),
            sorted(ALL_WINDOWS))


class TestUiKnowsTheNewWindows(unittest.TestCase):
    def setUp(self):
        base = os.path.join(os.path.dirname(__file__), "..", "ui")
        self.html = open(os.path.join(base, "index.html"),
                         encoding="utf-8").read()
        self.core = open(os.path.join(base, "js", "sash-core.js"),
                         encoding="utf-8").read()

    def test_the_core_lists_the_new_windows(self):
        for wid in NEW_WINDOWS:
            self.assertIn(f"'{wid}'", self.core)

    def test_the_html_has_a_panel_for_each_new_window(self):
        for wid in NEW_WINDOWS:
            self.assertIn(f'data-window="{wid}"', self.html)

    def test_the_pinned_header_has_a_my_nick_field(self):
        self.assertIn("myNickInput", self.html)

    def test_the_collector_panel_shows_a_status(self):
        self.assertIn("collectorStatus", self.html)

    def test_the_new_scripts_are_loaded(self):
        for src in ("history-model.js", "history-view.js", "history-store.js",
                    "history-db.js", "collector-panel.js"):
            self.assertIn(src, self.html)
        self.assertIn("history.css", self.html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
