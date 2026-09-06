"""Flexible grid persistence, global undo/redo, and reset.

The sash layout is stored in config.json and participates in the same tagged
undo timeline as action-stack edits. Legacy `type` node payloads and legacy
history keys are accepted only during migration; new persisted trees use the
canonical `t` key and new edits use `undo_history`.

Run with:  python3 tests/test_grid_persistence.py
"""

import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import (MAX_STACK_HISTORY,  # noqa: E402
                                    ConfigManager)

ALL_WINDOWS = {"stats", "filters", "stack", "config", "composer", "people",
               "log"}


def leaf(i):
    return {"t": "leaf", "id": i}


def split(d, kids, sizes):
    return {"t": "split", "dir": d, "children": kids, "sizes": sizes}


def legacy_leaf(i):
    return {"type": "leaf", "id": i}


def legacy_split(d, kids, sizes):
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
    br._engine = types.SimpleNamespace(load_stack=lambda _blocks: None)
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
        for key in ("grid_layout", "undo_history", "undo_history_index",
                    "block_config_pinned", "window_geometry"):
            self.assertIn(key, cm.DEFAULTS["state"], key)
        import inspect
        src = inspect.getsource(Bridge.get_app_state)
        self.assertIn("undo_history", src)
        self.assertIn("grid_layout", src)
        self.assertIn("block_config_pinned", src)


# ── requirement 2: one global, tagged undo timeline ──────────────
class TestGlobalHistory(unittest.TestCase):
    def test_save_pushes_a_tagged_global_history_step(self):
        br, _ = make_bridge()
        br.save_grid_layout(payload(Bridge._default_grid_tree()))
        br.save_grid_layout(payload(a_valid_tree()))
        history, idx = br._get_global_history()
        self.assertEqual([entry["kind"] for entry in history], ["grid", "grid"])
        self.assertEqual(idx, 1)

    def test_undo_returns_the_previous_layout(self):
        br, _ = make_bridge()
        first = payload(Bridge._default_grid_tree())
        second = payload(a_valid_tree())
        br.save_grid_layout(first)
        br.save_grid_layout(second)
        result = json.loads(br.undo())
        self.assertEqual(result["kind"], "grid")
        self.assertEqual(json.loads(result["value"]), json.loads(first))
        self.assertEqual(json.loads(br.get_grid_layout()), json.loads(first))

    def test_redo_walks_forward_again(self):
        br, _ = make_bridge()
        first = payload(Bridge._default_grid_tree())
        second = payload(a_valid_tree())
        br.save_grid_layout(first)
        br.save_grid_layout(second)
        br.undo()
        result = json.loads(br.redo())
        self.assertEqual(result["kind"], "grid")
        self.assertEqual(json.loads(result["value"]), json.loads(second))

    def test_undo_at_the_start_is_null(self):
        br, _ = make_bridge()
        br.save_grid_layout(payload(a_valid_tree()))
        self.assertEqual(br.undo(), "null")

    def test_redo_at_the_tip_is_null(self):
        br, _ = make_bridge()
        br.save_grid_layout(payload(a_valid_tree()))
        self.assertEqual(br.redo(), "null")

    def test_saving_the_same_layout_twice_is_not_two_steps(self):
        br, _ = make_bridge()
        same = payload(a_valid_tree())
        br.save_grid_layout(same)
        br.save_grid_layout(same)
        history, _ = br._get_global_history()
        self.assertEqual(len(history), 1)

    def test_editing_after_an_undo_discards_the_redo_tail(self):
        br, _ = make_bridge()
        br.save_grid_layout(payload(Bridge._default_grid_tree()))
        br.save_grid_layout(payload(a_valid_tree()))
        br.undo()
        other = a_valid_tree()
        other["sizes"] = [20, 10, 14, 14, 14, 14, 14]
        br.save_grid_layout(payload(other))
        self.assertEqual(br.redo(), "null", "the old redo branch must be gone")

    def test_history_is_capped(self):
        br, _ = make_bridge()
        for i in range(MAX_STACK_HISTORY + 20):
            tree = a_valid_tree()
            tree["sizes"] = [16 + (i % 5), 14, 14, 14, 14, 14, 14 - (i % 5)]
            br.save_grid_layout(payload(tree))
        history, idx = br._get_global_history()
        self.assertLessEqual(len(history), MAX_STACK_HISTORY)
        self.assertEqual(idx, len(history) - 1)

    def test_interleaved_grid_and_stack_edits_share_one_timeline(self):
        br, _ = make_bridge()
        stack_a = [{"block_id": "SCROLL_PARSE"}]
        stack_b = [{"block_id": "CLICK_USER"}]
        br._push_hist("stack", stack_a)
        br._push_hist("stack", stack_b)
        br.save_grid_layout(payload(Bridge._default_grid_tree()))
        br.save_grid_layout(payload(a_valid_tree()))

        result = json.loads(br.undo())
        self.assertEqual(result["kind"], "grid")
        self.assertEqual(json.loads(result["value"]),
                         json.loads(payload(Bridge._default_grid_tree())))
        history, index = br._get_global_history()
        self.assertEqual([entry["kind"] for entry in history],
                         ["stack", "stack", "grid", "grid"])
        self.assertEqual(index, 2)

        # The next global undo crosses the grid/stack boundary and restores
        # the stack edit, proving there is no separate layout undo system.
        # Blocks are normalized on every store/emit path (retired keys
        # stripped, enabled defaulted true), so compare to the cleaned form.
        result = json.loads(br.undo())
        self.assertEqual(result["kind"], "stack")
        self.assertEqual(result["value"], br._clean_blocks(stack_b))

    def test_legacy_type_nodes_are_normalized_to_t(self):
        legacy = legacy_split("col", [legacy_leaf(i) for i in
                                      ["stats", "filters", "stack", "config",
                                       "composer", "people", "log"]],
                              [16, 14, 14, 14, 14, 14, 14])
        br, _ = make_bridge()
        self.assertTrue(br.save_grid_layout(payload(legacy)))
        tree = json.loads(br.get_grid_layout())["tree"]
        self.assertEqual(tree["t"], "split")
        self.assertNotIn("type", tree)
        self.assertEqual(tree["children"][0]["t"], "leaf")

    def test_legacy_history_is_migrated_once(self):
        br, cfg = make_bridge()
        legacy = payload(legacy_split("col", [legacy_leaf(i) for i in
                                               ["stats", "filters", "stack", "config",
                                                "composer", "people", "log"]],
                                     [16, 14, 14, 14, 14, 14, 14]))
        cfg.set_state(grid_layout_history=[legacy], grid_layout_history_index=0)
        history, index = br._get_global_history()
        self.assertEqual(index, 0)
        self.assertEqual([entry["kind"] for entry in history], ["grid"])
        self.assertEqual(json.loads(history[0]["value"])["tree"]["t"], "split")
        self.assertEqual(cfg.get_state("undo_history_index", None), 0)


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
        result = json.loads(br.undo())
        self.assertEqual(result["kind"], "grid")
        self.assertEqual(json.loads(result["value"]), json.loads(custom),
                         "a mis-clicked reset must be recoverable")


# ── the UI wires all of it up ────────────────────────────────────
class TestUIWiring(unittest.TestCase):
    def setUp(self):
        base = os.path.join(os.path.dirname(__file__), "..", "ui")
        self.html = open(os.path.join(base, "index.html"), encoding="utf-8").read()
        self.grid = open(os.path.join(base, "js", "sash-grid.js"),
                         encoding="utf-8").read()

    def test_reset_and_global_undo_controls_exist(self):
        self.assertIn("resetLayoutBtn", self.html)
        self.assertNotIn("gridUndoBtn", self.html)
        self.assertNotIn("gridRedoBtn", self.html)
        self.assertIn("undoBtn", self.html)
        self.assertIn("redoBtn", self.html)

    def test_grid_saves_through_the_bridge_not_only_localstorage(self):
        self.assertIn("save_grid_layout", self.grid)
        self.assertIn("get_grid_layout", self.grid)
        self.assertIn("localStorage", self.grid, "offline fallback kept")

    def test_reset_unhides_every_window(self):
        self.assertIn("showAllWindows", self.grid)
        self.assertIn("resetToDefault", self.grid)

    def test_grid_uses_global_history_without_grid_shortcuts(self):
        """Grid edits use App's global timeline, not a second shortcut path."""
        self.assertIn("App.recordGlobal", self.grid)
        self.assertNotIn("undo_grid_layout", self.grid)
        self.assertNotIn("redo_grid_layout", self.grid)
        self.assertNotIn("e.shiftKey", self.grid)

    def test_close_flushes_the_current_tree_before_shutdown(self):
        main = open(os.path.join(os.path.dirname(__file__), "..", "main.py"),
                    encoding="utf-8").read()
        self.assertIn("flushPersistence", self.grid)
        self.assertIn("_request_grid_flush", main)
        self.assertIn("grid_layout_persisted", main)
        self.assertIn("_layout_flush_pending", main)

    def test_sortable_people_headers_cover_required_columns(self):
        for key in ("nick", "gender", "registered", "status", "first_seen",
                    "last_messaged"):
            self.assertIn(f'data-sort="{key}"', self.html)
        self.assertGreaterEqual(self.html.count('class="sort-button"'), 6)
        self.assertIn("Actions", self.html)

    def test_config_panel_has_an_empty_state(self):
        self.assertIn("blockConfigEmpty", self.html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
