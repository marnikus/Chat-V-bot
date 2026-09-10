"""Shared file OUTSIDE victim folder but inside media root is retained.

Unrelated folders untouched; unshared legacy sweep still works.
Passes on baseline (per-file keep works outside victim folder) — pins it.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempWorld, insert_media_row_sync, read_bytes, write_file


class TestSharedOutsideVictim(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.w = TempWorld()
        await self.w.setup(with_b=True, with_c=True)

    async def asyncTearDown(self):
        await self.w.teardown()

    async def test_shared_outside_retained_unrelated_untouched(self):
        mgr = self.w.manager
        base = self.w.media_base
        shared = os.path.join(base, "shared", "Nick", "images", "a.jpg")
        write_file(shared, b"shared-bytes")
        unrelated = os.path.join(base, "unrelated", "keep.jpg")
        write_file(unrelated, b"keep-me")
        # A and B share; C references nothing
        insert_media_row_sync(self.w.world_a, "https://x/a.jpg", shared)
        insert_media_row_sync(self.w.world_b, "https://x/a.jpg", shared)
        # delete B (non-active victim)
        victim = self.w.world_b
        result = await mgr.delete(victim)
        self.assertTrue(result.get("ok"), result)
        self.assertFalse(os.path.exists(victim))
        self.assertTrue(os.path.exists(shared),
                        "shared file must survive")
        self.assertEqual(read_bytes(shared), b"shared-bytes")
        self.assertTrue(os.path.exists(unrelated),
                        "unrelated folder must be untouched")
        self.assertTrue(os.path.exists(self.w.world_c),
                        "unrelated world must survive")

    async def test_last_reference_removes_and_sweeps_empty_legacy(self):
        mgr = self.w.manager
        base = self.w.media_base
        shared = os.path.join(base, "legacy", "a.jpg")
        write_file(shared, b"bytes")
        # Only victim references it
        insert_media_row_sync(self.w.world_b, "https://x/b.jpg", shared)
        result = await mgr.delete(self.w.world_b)
        self.assertTrue(result.get("ok"), result)
        self.assertFalse(os.path.exists(shared),
                         "last reference gone → file removed")
        self.assertFalse(os.path.isdir(os.path.join(base, "legacy")),
                         "empty legacy folders swept")


if __name__ == "__main__":
    unittest.main(verbosity=2)
