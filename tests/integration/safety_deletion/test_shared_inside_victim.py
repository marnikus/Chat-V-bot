"""Shared file INSIDE the victim folder must survive (rmtree bypass).

Baseline defect: _delete_world_media skips `keep` per file, then does
shutil.rmtree(world_folder) unconditionally. This test MUST FAIL on baseline
(file deleted) and PASS after the fix (file + bytes survive, victim DB gone).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempWorld, insert_media_row_sync, read_bytes, write_file


class TestSharedInsideVictim(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.w = TempWorld()
        await self.w.setup(with_b=True, with_c=False)

    async def asyncTearDown(self):
        await self.w.teardown()

    async def test_shared_file_inside_victim_folder_survives(self):
        mgr = self.w.manager
        victim = self.w.world_b  # non-active victim
        survivor = self.w.world_a  # active, references shared file
        victim_folder = self.w.media_dir_for(victim)
        shared = os.path.join(victim_folder, "Nick", "images", "shared.jpg")
        write_file(shared, b"shared-bytes-123")
        # BOTH worlds reference the SAME file inside B's folder
        insert_media_row_sync(victim, "https://x/shared.jpg", shared, "Nick")
        insert_media_row_sync(survivor, "https://x/shared.jpg", shared, "Nick")
        # sanity: file exists before delete
        self.assertTrue(os.path.exists(shared))
        result = await mgr.delete(victim)
        # Permitted deletion: victim DB gone, file + bytes survive
        self.assertTrue(result.get("ok"), result)
        self.assertFalse(os.path.exists(victim),
                         "victim DB must be gone on permitted deletion")
        self.assertTrue(os.path.exists(shared),
                        "shared file inside victim folder must survive "
                        "(rmtree bypass defect)")
        self.assertEqual(read_bytes(shared), b"shared-bytes-123",
                         "surviving file must keep its bytes")
        # survivor still references it
        rows = [r for r in [shared] if os.path.exists(r)]
        self.assertEqual(rows, [shared])

    async def test_unshared_file_inside_victim_folder_is_removed(self):
        """Control: unshared victim-folder files ARE removed (not a no-op)."""
        mgr = self.w.manager
        victim = self.w.world_b
        victim_folder = self.w.media_dir_for(victim)
        solo = os.path.join(victim_folder, "Nick", "images", "solo.jpg")
        write_file(solo, b"solo-bytes")
        insert_media_row_sync(victim, "https://x/solo.jpg", solo, "Nick")
        # survivor references nothing
        result = await mgr.delete(victim)
        self.assertTrue(result.get("ok"), result)
        self.assertFalse(os.path.exists(victim))
        self.assertFalse(os.path.exists(solo),
                         "unshared victim file must be cleaned up")


if __name__ == "__main__":
    unittest.main(verbosity=2)
