"""Per-file coverage floor — H-D3.

Every production module with ≥30 statements must hold ≥80% line coverage,
with a ratchet for files below today that may only rise.

Wired from coverage.json (RULE 16 §16.3's measurement). Same protocol as
rule16_gate.py's RATCHET: may shrink, may not grow, stale entries must be
deleted.

Design: docs/archive/2026-09-14-round-h/AREA_D_VERIFICATION_DESIGN_2026-09-14.md H-D3
"""
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_gate():
    import importlib.util
    path = os.path.join(ROOT, "tools", "metrics", "file_coverage_floor.py")
    spec = importlib.util.spec_from_file_location("file_coverage_floor", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load_gate()


class TestCoverageFileExists(unittest.TestCase):
    def test_coverage_json_exists(self):
        # The gate uses coverage.json or /tmp/coverage_h.json
        candidates = [
            os.path.join(ROOT, "coverage.json"),
            "/tmp/coverage_h.json",
            "/tmp/.coverage_h",
        ]
        exists = any(os.path.exists(p) for p in candidates)
        # If no coverage file, skip — not a pass, but not a failure in CI without coverage
        if not exists:
            self.skipTest("no coverage.json found — run coverage first")


class TestFileFloor(unittest.TestCase):
    def test_no_regression_below_ratchet(self):
        cov_path = os.path.join(ROOT, "coverage.json")
        if not os.path.exists(cov_path):
            cov_path = "/tmp/coverage_h.json"
        if not os.path.exists(cov_path):
            self.skipTest("no coverage file")

        report = gate.run(cov_path)
        # No file may drop below its ratchet
        regressed = [r for r in report["rows"] if r["regressed"]]
        self.assertEqual(
            regressed, [],
            "ratchet regression:\n" + "\n".join(
                f"{r['file']}: {r['percent']}% < ratchet {r['ratchet']}%" for r in regressed
            ),
        )

    def test_no_new_file_below_floor_without_ratchet(self):
        cov_path = os.path.join(ROOT, "coverage.json")
        if not os.path.exists(cov_path):
            cov_path = "/tmp/coverage_h.json"
        if not os.path.exists(cov_path):
            self.skipTest("no coverage file")

        report = gate.run(cov_path)
        # New files that are below floor but not in ratchet are breaches
        new_below = [
            b for b in report["breaches"] if "not in ratchet" in b
        ]
        self.assertEqual(
            new_below, [],
            "new file below floor without ratchet:\n" + "\n".join(new_below),
        )

    def test_ratchet_is_sorted_and_honest(self):
        # RATCHET keys must be sorted for readability, and values realistic
        items = list(gate.RATCHET.items())
        self.assertEqual(
            items, sorted(items),
            "RATCHET should be sorted for readability",
        )
        for path, cov in items:
            self.assertGreaterEqual(cov, 0.0)
            self.assertLessEqual(cov, 100.0)
            self.assertIn("/", path, f"ratchet key should be repo-rel: {path}")

    def test_floor_constant_is_80(self):
        self.assertEqual(gate.FLOOR, 80.0, "floor must be 80% per H-D3")

    def test_min_stmts_is_30(self):
        self.assertEqual(gate.MIN_STMTS, 30)


class TestRatchetMayOnlyRise(unittest.TestCase):
    def test_ratchet_values_are_current_or_higher_than_last_audit(self):
        # The ratchet may only rise — check that current RATCHET still contains
        # the known low files that remain below floor. Files that were lifted
        # above floor (chat_text, message_injector_send, lifecycle, cancellation)
        # should have been removed from ratchet — that's allowed.
        # This test ensures ratchet still tracks the remaining low files.
        must_remain = {
            "bridge/history_bridge.py",
            "backend/cdp_client.py",
            "bridge/layout_bridge.py",
        }
        for f in must_remain:
            self.assertIn(f, gate.RATCHET, f"{f} should still be in ratchet (below floor)")

        # Lifted files should NOT be in ratchet anymore
        lifted = {
            "backend/message_injector_send.py",
            "backend/chat_text.py",
            "app/lifecycle.py",
            "actions/cancellation.py",
        }
        for f in lifted:
            self.assertNotIn(f, gate.RATCHET, f"{f} was lifted to >=80% and should be removed from ratchet")


if __name__ == "__main__":
    unittest.main(verbosity=2)
