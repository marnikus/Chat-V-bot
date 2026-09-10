"""Config/finalization failure: removed stay reported, active observed."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempWorld, write_file


class TestFinalizeFailure(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.w = TempWorld()
        await self.w.setup(with_b=True, with_c=False)

    async def asyncTearDown(self):
        await self.w.teardown()

    async def test_finalize_failure_reports_removed_and_observed_active(self):
        from contextlib import ExitStack
        mgr = self.w.manager
        victim = self.w.world_b
        media = os.path.join(self.w.media_dir_for(victim), "a.jpg")
        write_file(media, b"x")
        # Fail config persistence during _forget/_persist. _forget uses
        # set_state (→ settings.save) for pruning and set+save for db_path.
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                self.w.cfg, "save", side_effect=OSError("disk-full")))
            stack.enter_context(mock.patch.object(
                self.w.cfg, "set_state", side_effect=OSError("disk-full")))
            # Baseline _forget does not catch → raises (red: no dict).
            # Fixed: returns partial finalize with removed lists.
            try:
                result = await mgr.delete(victim)
            except OSError:
                self.fail("delete must not raise on finalize failure; "
                          "it must return a truthful partial result")
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("phase"), "finalize")
        self.assertTrue(result.get("partial"))
        # files already removed remain reported removed
        self.assertFalse(os.path.exists(victim))
        self.assertIn(os.path.abspath(victim),
                      [os.path.abspath(p)
                       for p in result.get("removed_paths", [])])
        # active_path observed, not guessed fallback
        self.assertEqual(os.path.abspath(result.get("active_path", "")),
                         os.path.abspath(mgr.active_path()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
