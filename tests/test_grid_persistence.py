"""Flexible grid: config.json persistence, its own undo history, and reset.

The merged sash layout persisted only to localStorage and had no undo and no
reset. This suite covers the four follow-up requirements:

  1. the layout is STORABLE — it lives in config.json, not just the browser;
  2. it participates in an UNDO system — a separate history from the action
     stack, so undoing a window drag never reverts a block edit;
  3. RESET TO DEFAULT exists;
  4. the default layout contains EVERY window.

Run with:  python3 tests/test_grid_persistence.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import (MAX_STACK_HISTORY,  # noqa: E402
                                    ConfigManager)

ALL_WINDOWS = {"stats", "filters", "stack", "config", "composer", "people",
               "log"}


def leaf(i):
    return {"type": "leaf", "id": i}


def split(d, kids, sizes):
    return {"type": "split", "dir": d, "children": kids, "sizes": sizes}


def a_valid_tree():
    """A non-default but legal arrangement: one flat column of all 7."""
    ids = ["stats", "filters", "stack", "config", "composer", "people", "log"]
    return split("col", [leaf(i) for i in ids], [16, 14, 14, 14, 14, 14, 14])


def payload(tree):
    return json.dumps({"v": 1, "tree": tree}, ensure_ascii=False)


class FakeBridge(Bridge):
    """Bridge with a throwaway config and no Qt signal plumbing needed."""


def make_bridge():
    tmp = tempfile.mkdtemp()
    cfg = ConfigManager(os.path.join(tmp, "config.json"))
    br = Bridge.__new__(Bridge)          # skip QObject.__init__ machinery
    from PySide6.QtCore import QObject
    QObject.__init__(br)
    br._config = cfg
    return br, cfg


# ── requirement 4: the default shows everything ──────────────────
class TestDefaultLayout(unittest.TestCase):
    def test_default_contains_every_window(self):
        tree = Bridge._default_grid_tree()
        self.assertEqual(sorted(Bridge._leaf_ids(tree)), sorted(ALL_WINDOWS))

    def test_default_is_valid(self):
        self.assertIsNone(Bridge._validate_grid_tree(Bridge._default_grid_tree()))

    def test_default_round_trips(self):
        tree, err = Bridge._parse_grid_payload(payload(Bridge._default_grid_tree()))
        self.assertIsNone(err)
        self.assertEqual(sorted(Bridge._leaf_ids(tree)), sorted(ALL_WINDOWS))


# ── validation: never store a tree we cannot read back ───────────
class TestValidation(unittest.TestCase):
    def _err(self, raw):
        return Bridge._parse_grid_payload(raw)[1]

    def test_rejects_malformed_json(self):
        self.assertIn("bad JSON", self._err("{not json"))

    def test_rejects_wrong_version(self):
        self.assertIn("version", self._err(json.dumps({"v": 2, "tree": {}})))

    def test_rejects_missing_window(self):
        tree = split("row", [leaf("stats"), leaf("log")], [50, 50])
        self.assertIn("window set", self._err(payload(tree)))

    def test_rejects_duplicate_window(self):
        ids = ["stats", "filters", "stack", "config", "composer", "people",
               "log", "log"]
        tree = split("col", [leaf(i) for i in ids], [12.5] * 8)
        self.assertIn("window set", self._err(payload(tree)))

    def test_rejects_sizes_that_do_not_sum_to_100(self):
        tree = a_valid_tree()
        tree["sizes"] = [10] * 7
        self.assertIn("sum to 100", self._err(payload(tree)))

    def test_rejects_split_with_one_child(self):
        tree = split("row", [leaf("stats")], [100])
        self.assertIn("children", self._err(payload(tree)))

    def test_rejects_unknown_node_type(self):
        self.assertIn("unknown node type",
                      self._err(json.dumps({"v": 1, "tree": {"type": "blob"}})))

    def test_accepts_a_legal_custom_tree(self):
        self.assertIsNone(self._err(payload(a_valid_tree())))


# ── requirement 1: stored in config.json ─────────────────────────
class TestPersistence(unittest.TestCase):
    def test_unset_layout_reads_as_empty(self):
        br, _ = make_bridge()
        self.assertEqual(br.get_grid_layout(), "")

    def test_save_then_read_round_trips(self):
        br, _ = make_bridge()
        self.assertTrue(br.save_grid_layout(payload(a_valid_tree())))
        got = json.loads(br.get_grid_layout())
        self.assertEqual(got["v"], 1)
        self.assertEqual(sorted(Bridge._leaf_ids(got["tree"])),
                         sorted(ALL_WINDOWS))

    def test_layout_survives_a_reload_of_config_json(self):
        br, cfg = make_bridge()
        br.save_grid_layout(payload(a_valid_tree()))
        reopened = ConfigManager(cfg._path)
        self.assertTrue(reopened.get_state("grid_layout", None),
                        "layout must live in config.json, not just memory")

    def test_a_rejected_layout_leaves_the_previous_one_intact(self):
        br, _ = make_bridge()
        br.save_grid_layout(payload(a_valid_tree()))
        before = br.get_grid_layout()
        self.assertFalse(br.save_grid_layout("{garbage"))
        self.assertEqual(br.get_grid_layout(), before,
                         "a bad payload must not brick the stored layout")

    def test_layout_is_exposed_in_app_state(self):
        """restoreSession() must be able to see the stored layout."""
        import backend.config_manager as cm
        for key in ("grid_layout", "grid_layout_history",
                    "grid_layout_history_index"):
            self.assertIn(key, cm.DEFAULTS["state"], key)
        import inspect
        src = inspect.getsource(Bridge.get_app_state)
        self.assertIn("grid_layout", src)


# ── requirement 2: undo/redo, separate from the stack ────────────
class TestGridHistory(unittest.TestCase):
    def test_save_pushes_a_history_step(self):
        br, _ = make_bridge()
        br.save_grid_layout(payload(Bridge._default_grid_tree()))
        br.save_grid_layout(payload(a_valid_tree()))
        hist, idx = br._get_hist("grid")
        self.assertEqual(len(hist), 2)
        self.assertEqual(idx, 1)

    def test_undo_returns_the_previous_layout(self):
        br, _ = make_bridge()
        first = payload(Bridge._default_grid_tree())
        second = payload(a_valid_tree())
        br.save_grid_layout(first)
        br.save_grid_layout(second)
        got = br.undo_grid_layout()
        self.assertEqual(json.loads(got), json.loads(first))
        self.assertEqual(json.loads(br.get_grid_layout()), json.loads(first))

    def test_redo_walks_forward_again(self):
        br, _ = make_bridge()
        first = payload(Bridge._default_grid_tree())
        second = payload(a_valid_tree())
        br.save_grid_layout(first)
        br.save_grid_layout(second)
        br.undo_grid_layout()
        self.assertEqual(json.loads(br.redo_grid_layout()), json.loads(second))

    def test_undo_at_the_start_is_null(self):
        br, _ = make_bridge()
        br.save_grid_layout(payload(a_valid_tree()))
        self.assertEqual(br.undo_grid_layout(), "null")

    def test_redo_at_the_tip_is_null(self):
        br, _ = make_bridge()
        br.save_grid_layout(payload(a_valid_tree()))
        self.assertEqual(br.redo_grid_layout(), "null")

    def test_saving_the_same_layout_twice_is_not_two_steps(self):
        br, _ = make_bridge()
        same = payload(a_valid_tree())
        br.save_grid_layout(same)
        br.save_grid_layout(same)
        hist, _ = br._get_hist("grid")
        self.assertEqual(len(hist), 1)

    def test_editing_after_an_undo_discards_the_redo_tail(self):
        br, _ = make_bridge()
        br.save_grid_layout(payload(Bridge._default_grid_tree()))
        br.save_grid_layout(payload(a_valid_tree()))
        br.undo_grid_layout()
        other = a_valid_tree()
        other["sizes"] = [20, 10, 14, 14, 14, 14, 14]
        br.save_grid_layout(payload(other))
        self.assertEqual(br.redo_grid_layout(), "null",
                         "the old redo branch must be gone")

    def test_history_is_capped(self):
        br, _ = make_bridge()
        for i in range(MAX_STACK_HISTORY + 20):
            tree = a_valid_tree()
            tree["sizes"] = [16 + (i % 5), 14, 14, 14, 14, 14, 14 - (i % 5)]
            br.save_grid_layout(payload(tree))
        hist, idx = br._get_hist("grid")
        self.assertLessEqual(len(hist), MAX_STACK_HISTORY)
        self.assertEqual(idx, len(hist) - 1)

    def test_grid_and_stack_histories_are_independent(self):
        """Undoing a window drag must not revert a block edit."""
        br, _ = make_bridge()
        br._push_hist("stack", [{"block_id": "SCROLL_PARSE"}])
        br._push_hist("stack", [{"block_id": "CLICK_USER"}])
        s_hist_before, s_idx_before = br._get_hist("stack")

        br.save_grid_layout(payload(Bridge._default_grid_tree()))
        br.save_grid_layout(payload(a_valid_tree()))
        br.undo_grid_layout()

        s_hist_after, s_idx_after = br._get_hist("stack")
        self.assertEqual(s_hist_before, s_hist_after)
        self.assertEqual(s_idx_before, s_idx_after,
                         "grid undo moved the STACK history index")


# ── requirement 3: reset to default ──────────────────────────────
class TestReset(unittest.TestCase):
    def test_reset_returns_the_default_with_all_windows(self):
        br, _ = make_bridge()
        br.save_grid_layout(payload(a_valid_tree()))
        got = json.loads(br.reset_grid_layout())
        self.assertEqual(sorted(Bridge._leaf_ids(got["tree"])),
                         sorted(ALL_WINDOWS))
        self.assertEqual(json.loads(br.get_grid_layout()), got)

    def test_reset_is_undoable(self):
        br, _ = make_bridge()
        custom = payload(a_valid_tree())
        br.save_grid_layout(custom)
        br.reset_grid_layout()
        self.assertEqual(json.loads(br.undo_grid_layout()), json.loads(custom),
                         "a mis-clicked reset must be recoverable")


# ── the UI wires all of it up ────────────────────────────────────
class TestUIWiring(unittest.TestCase):
    def setUp(self):
        base = os.path.join(os.path.dirname(__file__), "..", "ui")
        self.html = open(os.path.join(base, "index.html"), encoding="utf-8").read()
        self.grid = open(os.path.join(base, "js", "sash-grid.js"),
                         encoding="utf-8").read()

    def test_reset_and_undo_controls_exist(self):
        for el in ("resetLayoutBtn", "gridUndoBtn", "gridRedoBtn"):
            self.assertIn(el, self.html, el)

    def test_grid_saves_through_the_bridge_not_only_localstorage(self):
        self.assertIn("save_grid_layout", self.grid)
        self.assertIn("get_grid_layout", self.grid)
        self.assertIn("localStorage", self.grid, "offline fallback kept")

    def test_reset_unhides_every_window(self):
        self.assertIn("showAllWindows", self.grid)
        self.assertIn("resetToDefault", self.grid)

    def test_grid_shortcuts_do_not_collide_with_stack_undo(self):
        """Stack owns Ctrl+Z/Y; the grid must require Shift."""
        self.assertIn("e.shiftKey", self.grid)

    def test_config_panel_has_an_empty_state(self):
        self.assertIn("blockConfigEmpty", self.html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
