"""Tests for the JavaScript quality gate (tools/metrics/js_gate.py).

The comparison logic is tested with synthetic reports (fast, no Node);
one integration test runs the real gate against the real tree — it is
green exactly when the tree satisfies its own committed baselines.

Run:  .venv/bin/python -m pytest tests/test_js_gate.py -q
"""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "metrics"))

import js_gate  # noqa: E402


def file_(name, lines, functions=(), obj_loc=0, obj_meth=0):
    over = sum(1 for f in functions if f[1] > 30)
    return {
        "file": name, "lines": lines,
        "functions": [{"name": n, "line": l, "loc": loc}
                      for n, l, loc in functions],
        "objects": [],
        "summary": {"functions": len(functions), "over_30": over,
                    "over_60": sum(1 for f in functions if f[1] > 60),
                    "over_100": sum(1 for f in functions if f[1] > 100),
                    "max_object_loc": obj_loc,
                    "max_object_methods": obj_meth},
    }


def cov_file_(pct, covered=10, executable=10):
    return {"lines": 100, "executable": executable, "covered": covered,
            "pct": pct}


def make_size(files):
    return {"files": files,
            "totals": {"files": len(files),
                       "lines": sum(f["lines"] for f in files),
                       "functions": sum(f["summary"]["functions"]
                                        for f in files),
                       "over_30": sum(f["summary"]["over_30"]
                                      for f in files),
                       "over_60": sum(f["summary"]["over_60"]
                                      for f in files),
                       "over_100": sum(f["summary"]["over_100"]
                                       for f in files)}}


def make_cov(files, pct):
    return {"files": {n: cov_file_(p) for n, p in files.items()},
            "totals": {"files": len(files), "lines": 0, "executable": 100,
                       "covered": 0, "pct": pct},
            "never_loaded": sorted(n for n, p in files.items()
                                   if p == 0.0),
            "test_failures": []}


class TestCompareSizes(unittest.TestCase):
    def test_unchanged_tree_passes(self):
        tree = [file_("a.js", 100, [("f", 10, 5), ("g", 20, 8)]),
                file_("b.js", 1300, [("god", 400, 120)],
                      obj_loc=1200, obj_meth=60)]
        v, _n = js_gate.compare_sizes(make_size(tree), make_size(tree))
        self.assertEqual(v, [])

    def test_new_function_over_30_fails(self):
        base = make_size([file_("a.js", 100, [("f", 10, 5)])])
        cur = make_size([file_("a.js", 140, [("f", 10, 5),
                                              ("newBig", 55, 40)])])
        v, _n = js_gate.compare_sizes(cur, base)
        self.assertTrue(any("newBig" in x and "NEW" in x for x in v))

    def test_new_function_in_band_passes(self):
        base = make_size([file_("a.js", 100, [("f", 10, 5)])])
        cur = make_size([file_("a.js", 110, [("f", 10, 5),
                                              ("newSmall", 44, 12)])])
        v, _n = js_gate.compare_sizes(cur, base)
        self.assertEqual(v, [])

    def test_baseline_function_growing_fails(self):
        base = make_size([file_("a.js", 100, [("f", 10, 5)])])
        cur = make_size([file_("a.js", 110, [("f", 10, 15)])])
        v, _n = js_gate.compare_sizes(cur, base)
        self.assertTrue(any("f" in x and "grew" in x for x in v))

    def test_baseline_function_may_shrink(self):
        base = make_size([file_("a.js", 100, [("f", 10, 35)])])
        cur = make_size([file_("a.js", 80, [("f", 10, 18)])])
        v, _n = js_gate.compare_sizes(cur, base)
        self.assertEqual(v, [])

    def test_file_over_500_new_fails(self):
        v, _n = js_gate.compare_sizes(make_size([file_("new.js", 600)]),
                                      make_size([]))
        self.assertTrue(any("600 lines" in x for x in v))

    def test_legacy_big_file_ratchets_only_down(self):
        base = make_size([file_("big.js", 1300, [("god", 400, 120)])])
        cur_ok = make_size([file_("big.js", 1299, [("god", 399, 120)])])
        v, _n = js_gate.compare_sizes(cur_ok, base)
        self.assertEqual(v, [])
        cur_bad = make_size([file_("big.js", 1301, [("god", 400, 120)])])
        v, _n = js_gate.compare_sizes(cur_bad, base)
        self.assertTrue(any("1301 lines" in x for x in v))

    def test_object_ratchet(self):
        base = make_size([file_("a.js", 100, obj_loc=200, obj_meth=30)])
        v, _n = js_gate.compare_sizes(
            make_size([file_("a.js", 100, obj_loc=200, obj_meth=30)]), base)
        self.assertEqual(v, [])
        v, _n = js_gate.compare_sizes(
            make_size([file_("a.js", 100, obj_loc=201, obj_meth=30)]), base)
        self.assertTrue(any("201 lines" in x for x in v))
        v, _n = js_gate.compare_sizes(
            make_size([file_("a.js", 100, obj_loc=200, obj_meth=31)]), base)
        self.assertTrue(any("31 methods" in x for x in v))

    def test_new_file_object_limited_to_150_15(self):
        v, _n = js_gate.compare_sizes(
            make_size([file_("new.js", 100, obj_loc=151, obj_meth=15)]),
            make_size([]))
        self.assertTrue(any("151 lines" in x for x in v))
        v, _n = js_gate.compare_sizes(
            make_size([file_("new.js", 100, obj_loc=150, obj_meth=16)]),
            make_size([]))
        self.assertTrue(any("16 methods" in x for x in v))


class TestCompareCoverage(unittest.TestCase):
    def test_stable_passes(self):
        base = make_cov({"a.js": 80.0}, 80.0)
        cur = make_cov({"a.js": 80.0}, 80.0)
        v, _n = js_gate.compare_coverage(cur, base)
        self.assertEqual(v, [])

    def test_per_file_drop_fails(self):
        base = make_cov({"a.js": 90.0, "b.js": 50.0}, 70.0)
        cur = make_cov({"a.js": 89.0, "b.js": 40.0}, 64.5)
        v, _n = js_gate.compare_coverage(cur, base)
        self.assertTrue(any("b.js" in x for x in v))
        self.assertTrue(any("64.50%" in x for x in v))

    def test_lift_passes(self):
        base = make_cov({"a.js": 50.0}, 50.0)
        cur = make_cov({"a.js": 85.0}, 85.0)
        v, _n = js_gate.compare_coverage(cur, base)
        self.assertEqual(v, [])

    def test_never_loaded_file_must_gain_coverage(self):
        base = make_cov({"dead.js": 0.0}, 0.0)
        v, _n = js_gate.compare_coverage(make_cov({"dead.js": 0.0}, 0.0),
                                         base)
        self.assertTrue(any("dead.js" in x and "never loaded" in x
                            for x in v))
        v, _n = js_gate.compare_coverage(make_cov({"dead.js": 45.0}, 45.0),
                                         base)
        self.assertEqual(v, [])

    def test_new_file_must_be_loaded(self):
        v, _n = js_gate.compare_coverage(make_cov({"new.js": 0.0}, 0.0),
                                         make_cov({}, 0.0))
        self.assertTrue(any("new.js" in x for x in v))

    def test_failed_node_suite_fails(self):
        cur = make_cov({"a.js": 80.0}, 80.0)
        cur["test_failures"] = [{"test": "test_x.js", "exit": 1,
                                 "stderr": "boom"}]
        v, _n = js_gate.compare_coverage(cur, make_cov({"a.js": 80.0}, 80.0))
        self.assertTrue(any("test_x.js" in x for x in v))


class TestGateEndToEnd(unittest.TestCase):
    def test_tree_satisfies_its_own_baselines(self):
        """The gate is green on the committed tree: both baselines exist and
        no check fires. Fails mid-round by design — the baselines are the
        acceptance criteria for the work they ratchet."""
        for p in (js_gate.SIZE_BASELINE, js_gate.COV_BASELINE):
            self.assertTrue(os.path.exists(p), p)
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tools", "metrics",
                                          "js_gate.py")],
            cwd=ROOT, capture_output=True, text=True, timeout=600)
        self.assertEqual(proc.returncode, 0,
                         "JS gate violations:\n" + proc.stdout[-3000:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
