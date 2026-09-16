"""Smell inventory — H-D5.

7 vulture findings, 13 clone groups, 4 boundary crossings, 11 wide params.

Design: docs/archive/2026-09-14-round-h/AREA_D_VERIFICATION_DESIGN_2026-09-14.md H-D5
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    import importlib.util
    path = os.path.join(ROOT, "tools", "metrics", "smell_inventory.py")
    spec = importlib.util.spec_from_file_location("smell_inventory", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


class TestVultureInventory(unittest.TestCase):
    def test_count_is_7(self):
        self.assertEqual(len(mod.VULTURE_FINDINGS), 7)

    def test_each_has_disposition(self):
        for f in mod.VULTURE_FINDINGS:
            self.assertIn(f["disposition"], {"delete", "protocol"})
            self.assertGreaterEqual(len(f["reason"]), 20)

    def test_protocol_findings_are_context_manager_or_hook(self):
        protos = [f for f in mod.VULTURE_FINDINGS if f["disposition"] == "protocol"]
        # exc_type, tb are context manager protocol; coordinator are hook protocol
        self.assertGreaterEqual(len(protos), 4)


class TestCloneBaseline(unittest.TestCase):
    def test_clone_count_matches_gate(self):
        # rule16_gate.py CLONE_BASELINE has 12 groups (2026-09-16: the
        # final H wave re-grouped the bridge set to five members, dropped
        # two stale pairs, and admitted one preset_store/undo_world pair).
        import importlib.util
        path = os.path.join(ROOT, "tools", "metrics", "rule16_gate.py")
        spec = importlib.util.spec_from_file_location("rule16_gate", path)
        rg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rg)
        self.assertEqual(len(rg.CLONE_BASELINE), 12)


class TestBoundaryCrossings(unittest.TestCase):
    def test_boundary_count(self):
        self.assertGreaterEqual(len(mod.BOUNDARY_CROSSINGS), 4)

    def test_each_has_owner_area(self):
        for b in mod.BOUNDARY_CROSSINGS:
            self.assertIn(b["owner_area"], {"B", "C"})


class TestWideParams(unittest.TestCase):
    def test_wide_count_is_11(self):
        self.assertEqual(len(mod.WIDE_PARAMS), 11)

    def test_rule3_count(self):
        rule3 = [w for w in mod.WIDE_PARAMS if "RULE 3" in w["status"]]
        self.assertEqual(len(rule3), 9)

    def test_non_block_queued(self):
        non_block = [w for w in mod.WIDE_PARAMS if "not a block" in w["status"]]
        self.assertEqual(len(non_block), 2)
        files = {w["file"] for w in non_block}
        self.assertIn("bridge/router.py", files)
        self.assertIn("backend/chat_sync.py", files)


if __name__ == "__main__":
    unittest.main(verbosity=2)
