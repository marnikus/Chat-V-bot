"""Last-world / invalid / missing / out-of-root refusals.

No unlink, no switch, no config mutation, clear refusal, phase=validate.
These pass on baseline too (existing guards) — they pin the contract so the
refactor cannot regress it.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempWorld


class TestLastAndValidate(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.w = TempWorld()
        await self.w.setup(with_b=False, with_c=False)

    async def asyncTearDown(self):
        await self.w.teardown()

    async def test_last_world_refuses_without_mutation(self):
        mgr = self.w.manager
        before_active = mgr.active_path()
        before_recent = list(mgr.known_paths())
        before_cfg = self.w.cfg.get("history", "db_path", default="")
        result = await mgr.delete(self.w.world_a)
        self.assertFalse(result.get("ok"))
        self.assertIn("last database", str(result.get("error", "")).lower())
        self.assertTrue(os.path.exists(self.w.world_a))
        self.assertTrue(self.w.svc.db.is_open)
        self.assertEqual(mgr.active_path(), before_active)
        self.assertEqual(mgr.known_paths(), before_recent)
        self.assertEqual(self.w.cfg.get("history", "db_path", default=""),
                         before_cfg)
        self.assertEqual(result.get("phase"), "validate")
        self.assertFalse(result.get("partial"))
        self.assertEqual(result.get("removed_paths"), [])

    async def test_missing_file_refuses(self):
        mgr = self.w.manager
        # need 2 worlds so last-rule doesn't mask missing-file path
        made = await mgr.create("second")
        self.assertTrue(made.get("ok"), made)
        ghost = os.path.join(self.w.dir, "ghost.db")
        result = await mgr.delete(ghost)
        self.assertFalse(result.get("ok"))
        self.assertTrue(str(result.get("error", "")))
        self.assertEqual(result.get("phase"), "validate")

    async def test_empty_and_out_of_root_refuse(self):
        mgr = self.w.manager
        made = await mgr.create("second")
        self.assertTrue(made.get("ok"), made)
        for bad in ("", "   ", "../evil.db",
                    os.path.join(self.w.dir, "..", "escape.db")):
            result = await mgr.delete(bad)
            self.assertFalse(result.get("ok"), f"input {bad!r} must refuse")
            self.assertTrue(str(result.get("error", "")),
                            f"input {bad!r} needs readable error")
        # no escape file created outside
        self.assertFalse(os.path.exists(
            os.path.join(self.w.dir, "..", "escape.db")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
