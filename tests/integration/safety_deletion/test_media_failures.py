"""Media unlink/prune failure: no false success, truthful counts/lists."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempWorld, insert_media_row_sync, write_file


class TestMediaFailures(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.w = TempWorld()
        await self.w.setup(with_b=True, with_c=False)

    async def asyncTearDown(self):
        await self.w.teardown()

    async def test_media_unlink_failure_is_not_success(self):
        mgr = self.w.manager
        victim = self.w.world_b
        base = self.w.media_base
        good = os.path.join(base, "m", "good.jpg")
        bad = os.path.join(base, "m", "bad.jpg")
        write_file(good, b"g")
        write_file(bad, b"b")
        insert_media_row_sync(victim, "https://x/g.jpg", good)
        insert_media_row_sync(victim, "https://x/b.jpg", bad)
        real_unlink = os.unlink

        def flaky(path, *a, **k):
            if os.path.abspath(str(path)) == os.path.abspath(bad):
                raise OSError("injected media failure")
            return real_unlink(path, *a, **k)

        with mock.patch("os.unlink", side_effect=flaky):
            result = await mgr.delete(victim)
        # Baseline: ok True (false success, red). Fixed: ok False, partial.
        self.assertFalse(result.get("ok"),
                         f"media failure must not report success, got {result}")
        # good removed, bad survives, victim DB gone (DB phase succeeded)
        self.assertFalse(os.path.exists(victim))
        self.assertFalse(os.path.exists(good))
        self.assertTrue(os.path.exists(bad))
        self.assertTrue(result.get("partial"))
        self.assertEqual(result.get("phase"), "media")
        self.assertEqual(result.get("media_files_removed"), 1,
                         "count actual removals, not attempts")
        self.assertIn(os.path.abspath(bad),
                      [os.path.abspath(p) for p in result.get("failed_paths", [])])
        self.assertIn(os.path.abspath(good),
                      [os.path.abspath(p) for p in result.get("removed_paths", [])])

    async def test_shared_media_not_counted_as_failure(self):
        mgr = self.w.manager
        victim = self.w.world_b
        base = self.w.media_base
        shared = os.path.join(base, "s", "a.jpg")
        solo = os.path.join(base, "s", "solo.jpg")
        write_file(shared, b"s")
        write_file(solo, b"o")
        insert_media_row_sync(victim, "https://x/a.jpg", shared)
        insert_media_row_sync(victim, "https://x/s.jpg", solo)
        insert_media_row_sync(self.w.world_a, "https://x/a.jpg", shared)
        result = await mgr.delete(victim)
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(os.path.exists(shared),
                        "shared retained, not a failure")
        self.assertFalse(os.path.exists(solo))
        self.assertEqual(result.get("media_files_removed"), 1)
        self.assertEqual(result.get("failed_paths"), [])
        self.assertIn(os.path.abspath(shared),
                      [os.path.abspath(p) for p in result.get("retained_paths", [])])


if __name__ == "__main__":
    unittest.main(verbosity=2)
