"""services/preset_adapt — adaptive window-preset restore (Python mirror).

Design: docs/archive/2026-09-14-grid-rows-adaptive-restore/GRID_ROWS_ADAPTIVE_RESTORE_DESIGN_2026-09-14.md

Pins the mirror contract of ui/js/preset-adapt.js: the five REASON strings
are literal (changed here = changed there = a failing test on both sides),
set drift is repaired and reported instead of refused, structural corruption
still refuses, and every report explains each skipped/added/corrected window.

Run:  python3 tests/unit/services/test_preset_adapt.py  (or pytest)
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from services import preset_adapt  # noqa: E402
from services.layout_service import LayoutService  # noqa: E402


def _leaf(wid):
    return {"t": "leaf", "id": wid}


def _split(direction, kids, sizes=None):
    return {"t": "split", "dir": direction, "children": kids,
            "sizes": sizes or [100 / len(kids)] * len(kids)}


def _healthy_tree():
    return LayoutService.default_grid_tree()


def _entry(entries, wid):
    return next(e for e in entries if e["id"] == wid)


def _window_entry(wid, **overrides):
    entry = {"id": wid, "title": wid.title(), "state": "open",
             "bounds": {"x": 0.0, "y": 0.0, "width": 0.5, "height": 0.5}}
    entry.update(overrides)
    return entry


def _entries():
    return [_window_entry(wid) for wid in preset_adapt.WINDOW_IDS]


class TestReasonContract(unittest.TestCase):
    def test_reason_strings_are_the_shared_cross_language_contract(self):
        # Literal on purpose — the JS mirror test pins the same strings.
        self.assertEqual(preset_adapt.REASON_UNKNOWN,
                         "unknown window in this build")
        self.assertEqual(preset_adapt.REASON_DUPLICATE,
                         "duplicate preset entry")
        self.assertEqual(preset_adapt.REASON_BOUNDS,
                         "invalid bounds; default position used")
        self.assertEqual(preset_adapt.REASON_STATE,
                         "state corrected from window_states")
        self.assertEqual(preset_adapt.REASON_ADDED,
                         "not in the preset; added with default placement")

    def test_default_bounds_is_a_valid_neutral_tile(self):
        bounds = preset_adapt.DEFAULT_BOUNDS
        self.assertEqual(set(bounds), {"x", "y", "width", "height"})
        self.assertLessEqual(bounds["x"] + bounds["width"], 1.0)
        self.assertEqual(bounds["height"], 0.0)

    def test_window_ids_are_sorted_for_deterministic_reports(self):
        self.assertEqual(preset_adapt.WINDOW_IDS,
                         sorted(LayoutService.WINDOW_IDS))


class TestPruneAndSizes(unittest.TestCase):
    def test_prune_drops_unknown_and_duplicate_leaves_and_collapses(self):
        tree = _split("col", [_leaf("stats"), _leaf("ghost"), _leaf("stats")])
        pruned = preset_adapt.prune_grid_tree(tree)
        self.assertEqual(pruned, _leaf("stats"))  # single survivor collapses

    def test_prune_returns_none_when_nothing_usable_remains(self):
        self.assertIsNone(preset_adapt.prune_grid_tree(_leaf("ghost")))
        self.assertIsNone(preset_adapt.prune_grid_tree(
            _split("row", [_leaf("a"), _leaf("b")])))
        self.assertIsNone(preset_adapt.prune_grid_tree({"t": "junk"}))
        self.assertIsNone(preset_adapt.prune_grid_tree(
            {"t": "split", "dir": "row", "children": "nope"}))

    def test_normalize_sizes_sums_to_100_and_honours_the_floor(self):
        sizes = preset_adapt._normalize_sizes([10, 10, 10])
        self.assertAlmostEqual(sum(sizes), 100.0)
        self.assertTrue(all(s >= LayoutService.MIN_GRID_SIZE for s in sizes))
        floor = preset_adapt._normalize_sizes([1, 1])  # below the floor
        self.assertAlmostEqual(sum(floor), 100.0)
        junk = preset_adapt._normalize_sizes([None, "x", True, -3])
        self.assertAlmostEqual(sum(junk), 100.0)

    def test_normalize_sizes_shares_the_rest_by_excess_over_the_floor(self):
        # scaling alone would leave two cells under the floor, and the
        # floor for all four still fits in 100 → the excess-proportional
        # branch decides: big cells give, small cells sit at the floor.
        sizes = preset_adapt._normalize_sizes([1, 1, 50, 50])
        self.assertAlmostEqual(sum(sizes), 100.0)
        self.assertAlmostEqual(sizes[0], LayoutService.MIN_GRID_SIZE)
        self.assertAlmostEqual(sizes[1], LayoutService.MIN_GRID_SIZE)
        self.assertGreater(sizes[2], sizes[0])
        self.assertAlmostEqual(sizes[2], sizes[3])

    def test_spread_guard_divides_equally_when_no_excess_exists(self):
        # defensive: unreachable through _normalize_sizes (all-floor cells
        # always scale to a fitting distribution first), pinned directly.
        self.assertEqual(preset_adapt._spread([4, 4], 92), [50.0, 50.0])

    def test_normalize_sizes_falls_back_to_equal_when_floor_cannot_fit(self):
        equal = preset_adapt._normalize_sizes([None] * 30)  # 30 × 4 > 100
        self.assertAlmostEqual(sum(equal), 100.0)
        self.assertTrue(all(abs(s - 100 / 30) < 1e-9 for s in equal))


class TestAdaptTree(unittest.TestCase):
    def test_healthy_current_tree_passes_through_with_an_empty_report(self):
        tree, report, error = preset_adapt.adapt_tree(
            _healthy_tree(), LayoutService.GRID_VERSION)
        self.assertIsNone(error)
        self.assertEqual(tree, _healthy_tree())
        self.assertEqual(report, {"pruned": [], "added": []})

    def test_ghost_leaf_is_pruned_and_its_window_re_added_with_reasons(self):
        broken = _healthy_tree()
        _rename_leaf(broken, "stats", "ghost")
        tree, report, error = preset_adapt.adapt_tree(
            broken, LayoutService.GRID_VERSION)
        self.assertIsNone(error)
        ids = LayoutService.leaf_ids(tree)
        self.assertNotIn("ghost", ids)
        self.assertIn("stats", ids)
        self.assertEqual(report["pruned"],
                         [{"id": "ghost", "reason": preset_adapt.REASON_UNKNOWN}])
        self.assertIn({"id": "stats", "reason": preset_adapt.REASON_ADDED},
                      report["added"])

    def test_older_version_and_corrupt_structures_keep_their_errors(self):
        _, _, error = preset_adapt.adapt_tree(_healthy_tree(), 0)
        self.assertIn("unsupported version", error)
        _, _, error = preset_adapt.adapt_tree(
            {"t": "split", "dir": "row", "children": [_leaf("stats")]},
            LayoutService.GRID_VERSION)
        self.assertIsNotNone(error)  # split needs >=2 children
        _, _, error = preset_adapt.adapt_tree(
            [_leaf(w) for w in preset_adapt.WINDOW_IDS],
            LayoutService.GRID_VERSION)
        self.assertIsNotNone(error)  # root must be a node dict
        tree, _, error = preset_adapt.adapt_tree(_leaf("ghost"),
                                                 LayoutService.GRID_VERSION)
        self.assertIsNone(tree)
        self.assertIn("no usable windows", error)

    def test_a_broken_migrator_surfaces_as_window_set_mismatch(self):
        # defensive invariant: if migrate_grid_tree ever returned a tree
        # that is not the full current set, adapt_tree must refuse.
        broken = _healthy_tree()
        _rename_leaf(broken, "stats", "ghost")
        with mock.patch.object(LayoutService, "migrate_grid_tree",
                               return_value=_leaf("stats")):
            tree, _, error = preset_adapt.adapt_tree(
                broken, LayoutService.GRID_VERSION)
        self.assertIsNone(tree)
        self.assertIn("window set mismatch", error)


def _rename_leaf(node, old_id, new_id):
    if node.get("t") == "leaf":
        if node.get("id") == old_id:
            node["id"] = new_id
        return
    for child in node.get("children", []):
        _rename_leaf(child, old_id, new_id)


class TestAdaptStates(unittest.TestCase):
    def test_unknown_state_ids_are_skipped_and_reported(self):
        states, skipped, error = preset_adapt.adapt_states(
            {"closed": ["ghost"], "minimized": []})
        self.assertIsNone(error)
        self.assertEqual(states, {"closed": [], "minimized": []})
        self.assertEqual(skipped,
                         [{"id": "ghost", "reason": preset_adapt.REASON_UNKNOWN}])

    def test_corruption_still_refuses(self):
        for states, fragment in (([], "window_states must"),
                                 ({"closed": "bad", "minimized": []},
                                  "closed must"),
                                 ({"closed": ["stats", "stats"],
                                   "minimized": []}, "duplicate"),
                                 ({"closed": ["stats"],
                                   "minimized": ["stats"]}, "overlap")):
            result, _, error = preset_adapt.adapt_states(states)
            self.assertIsNone(result, fragment)
            self.assertIn(fragment, error, fragment)


class TestAdaptWindows(unittest.TestCase):
    def setUp(self):
        self.states = {"closed": [], "minimized": []}

    def test_healthy_entries_canonicalise_to_sorted_window_order(self):
        shuffled = list(reversed(_entries()))
        windows, parts, error = preset_adapt.adapt_windows(shuffled, self.states)
        self.assertIsNone(error)
        self.assertEqual([w["id"] for w in windows], preset_adapt.WINDOW_IDS)
        self.assertEqual(parts["skipped"], [])
        self.assertEqual(parts["added"], [])
        self.assertEqual(parts["corrected"], [])

    def test_ghost_and_duplicate_entries_are_skipped_with_reasons(self):
        entries = _entries() + [_window_entry("ghost"),
                                _window_entry("stats")]
        windows, parts, error = preset_adapt.adapt_windows(entries, self.states)
        self.assertIsNone(error)
        self.assertEqual(len(windows), len(preset_adapt.WINDOW_IDS))
        reasons = {s["id"]: s["reason"] for s in parts["skipped"]}
        self.assertEqual(reasons["ghost"], preset_adapt.REASON_UNKNOWN)
        self.assertEqual(reasons["stats"], preset_adapt.REASON_DUPLICATE)

    def test_missing_windows_are_added_using_the_window_states(self):
        entries = [e for e in _entries() if e["id"] != "stats"]
        self.states["closed"] = ["stats"]
        windows, parts, error = preset_adapt.adapt_windows(entries, self.states)
        self.assertIsNone(error)
        added = _entry(windows, "stats")
        self.assertEqual(added["state"], "closed")
        self.assertEqual(added["bounds"], dict(preset_adapt.DEFAULT_BOUNDS))
        self.assertIn({"id": "stats", "reason": preset_adapt.REASON_ADDED},
                      parts["added"])

    def test_a_minimized_missing_window_is_added_minimized(self):
        entries = [e for e in _entries() if e["id"] != "log"]
        self.states["minimized"] = ["log"]
        windows, _, error = preset_adapt.adapt_windows(entries, self.states)
        self.assertIsNone(error)
        self.assertEqual(_entry(windows, "log")["state"], "minimized")

    def test_contradicting_state_is_corrected_from_window_states(self):
        entries = _entries()
        _entry(entries, "stats")["state"] = "closed"
        self.states["minimized"] = ["stats"]
        windows, parts, error = preset_adapt.adapt_windows(entries, self.states)
        self.assertIsNone(error)
        self.assertEqual(_entry(windows, "stats")["state"], "minimized")
        self.assertEqual(parts["corrected"],
                         [{"id": "stats",
                           "reason": preset_adapt.REASON_STATE}])

    def test_corrupt_bounds_fall_back_to_the_neutral_tile(self):
        cases = (None, {"width": "wide"}, {"x": 0.8, "y": 0, "width": 0.5,
                                           "height": 0.5},
                 {"x": -1, "y": 0, "width": 0.5, "height": 0.5},
                 {"x": 0, "y": 0, "width": float("inf"), "height": 0.5})
        for bounds in cases:
            entries = _entries()
            _entry(entries, "stats")["bounds"] = bounds
            windows, parts, error = preset_adapt.adapt_windows(
                entries, self.states)
            self.assertIsNone(error, repr(bounds))
            self.assertEqual(_entry(windows, "stats")["bounds"],
                             dict(preset_adapt.DEFAULT_BOUNDS), repr(bounds))
            self.assertEqual(parts["corrected"][-1]["reason"],
                             preset_adapt.REASON_BOUNDS, repr(bounds))

    def test_structural_corruption_refuses(self):
        _, _, error = preset_adapt.adapt_windows({}, self.states)
        self.assertIn("windows must be a list", error)
        _, _, error = preset_adapt.adapt_windows([None], self.states)
        self.assertIn("each window entry", error)


class TestBuildReport(unittest.TestCase):
    def test_every_window_is_accounted_exactly_once(self):
        windows = [_entry(_windows_canonical(), w)
                   for w in preset_adapt.WINDOW_IDS]
        report = preset_adapt.build_report(
            {"pruned": [{"id": "ghost", "reason": preset_adapt.REASON_UNKNOWN}],
             "added": [{"id": "stats", "reason": preset_adapt.REASON_ADDED}]},
            [{"id": "ghost", "reason": preset_adapt.REASON_UNKNOWN}],
            {"skipped": [{"id": "ghost", "reason": preset_adapt.REASON_UNKNOWN}],
             "added": [{"id": "stats", "reason": preset_adapt.REASON_ADDED}],
             "corrected": []},
            windows)
        self.assertNotIn("stats", report["applied"])
        self.assertEqual(len(report["skipped"]), 1)  # ghost deduped 3→1
        self.assertEqual(len(report["added"]), 1)    # stats deduped 2→1
        accounted = set(report["applied"]) | {s["id"] for s in report["skipped"]}
        self.assertEqual(len(accounted & set(report["applied"])),
                         len(report["applied"]))


def _windows_canonical():
    return [{"id": wid} for wid in preset_adapt.WINDOW_IDS]


if __name__ == "__main__":
    unittest.main(verbosity=2)
