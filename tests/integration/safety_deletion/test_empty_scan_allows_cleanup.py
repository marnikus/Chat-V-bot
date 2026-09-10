"""Valid empty reference set must still allow normal cleanup.

Prevents fail-safe from becoming a universal no-op: when every scan is
complete and empty, unshared victim files ARE removed.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempWorld, insert_media_row_sync, write_file


class TestEmptyScanAllowsCleanup(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.w = TempWorld()
        await self.w.setup(with_b=True, with_c=False)

    async def asyncTearDown(self):
        await self.w.teardown()

    async def test_empty_worlds_allow_unshared_cleanup(self):
        mgr = self.w.manager
        victim = self.w.world_b
        base = self.w.media_base
        # victim owns one file, nobody else references anything
        solo = os.path.join(base, "solo", "x.jpg")
        write_file(solo, b"data")
        insert_media_row_sync(victim, "https://x/solo.jpg", solo)
        # other world A has zero media rows (valid empty)
        result = await mgr.delete(victim)
        self.assertTrue(result.get("ok"), result)
        self.assertFalse(os.path.exists(victim))
        self.assertFalse(os.path.exists(solo),
                         "fail-safe must not block valid cleanup")
        if "media_files_removed" in result:
            self.assertGreaterEqual(result["media_files_removed"], 1)

    async def test_both_empty_deletes_cleanly(self):
        mgr = self.w.manager
        victim = self.w.world_b
        # no media rows anywhere, no files
        result = await mgr.delete(victim)
        self.assertTrue(result.get("ok"), result)
        self.assertFalse(os.path.exists(victim))


if __name__ == "__main__":
    unittest.main(verbosity=2)
