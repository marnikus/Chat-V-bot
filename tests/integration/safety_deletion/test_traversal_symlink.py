"""Traversal / symlink / ambiguous ownership: no escape, no root removal."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempWorld, insert_media_row_sync, write_file


class TestTraversalSymlink(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.w = TempWorld()
        await self.w.setup(with_b=True, with_c=False)

    async def asyncTearDown(self):
        await self.w.teardown()

    async def test_outside_root_reference_never_unlinked(self):
        mgr = self.w.manager
        victim = self.w.world_b
        outside = os.path.join(self.w.dir, "outside_root.txt")
        write_file(outside, b"outside")
        # victim references outside file (legacy absolute row)
        insert_media_row_sync(victim, "https://x/o.jpg", outside)
        result = await mgr.delete(victim)
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(os.path.exists(outside),
                        "outside-root file must never be unlinked")
        self.assertIn(os.path.abspath(outside),
                      [os.path.abspath(p)
                       for p in result.get("retained_paths", [])])

    async def test_media_root_never_removed(self):
        mgr = self.w.manager
        victim = self.w.world_b
        base = self.w.media_base
        # victim references base itself? (pathological row)
        insert_media_row_sync(victim, "https://x/root.jpg", base)
        result = await mgr.delete(victim)
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(os.path.isdir(base),
                        "media root must never be removed")

    async def test_symlink_dir_inside_root_pointing_outside(self):
        # Symlink escape: victim/link -> outside dir; victim row points at
        # victim/link/evil.jpg (string-inside base, realpath outside).
        # Baseline unlinks outside file (red). Fixed retains (pass).
        mgr = self.w.manager
        victim = self.w.world_b
        victim_folder = self.w.media_dir_for(victim)
        os.makedirs(victim_folder, exist_ok=True)
        outside_dir = os.path.join(self.w.dir, "outside_dir")
        os.makedirs(outside_dir, exist_ok=True)
        evil = os.path.join(outside_dir, "evil.jpg")
        write_file(evil, b"evil")
        link = os.path.join(victim_folder, "link")
        try:
            os.symlink(outside_dir, link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable on this platform: {exc}")
        via_link = os.path.join(link, "evil.jpg")
        insert_media_row_sync(victim, "https://x/evil.jpg", via_link)
        result = await mgr.delete(victim)
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(os.path.exists(evil),
                        "symlink escape must not delete outside target")

    async def test_another_world_folder_never_swept(self):
        mgr = self.w.manager
        victim = self.w.world_b
        other_folder = self.w.media_dir_for(self.w.world_a)
        keep = os.path.join(other_folder, "keep.jpg")
        write_file(keep, b"keep")
        # victim references a file inside OTHER world's folder (pathological
        # but possible via legacy absolute rows). Other world does NOT
        # reference it. Policy: never sweep another world's folder → retain?
        # Decision: file inside another world's folder is retained even when
        # unreferenced elsewhere (ambiguous ownership → retain).
        insert_media_row_sync(victim, "https://x/k.jpg", keep)
        result = await mgr.delete(victim)
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(os.path.exists(keep),
                        "another world's folder must never be swept")


if __name__ == "__main__":
    unittest.main(verbosity=2)
