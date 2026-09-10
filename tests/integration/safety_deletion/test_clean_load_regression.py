"""Clean / load / create regression: reversible clean + fail-closed switch."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempWorld, write_file


class TestCleanLoadRegression(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.w = TempWorld()
        await self.w.setup(with_b=True, with_c=False)

    async def asyncTearDown(self):
        await self.w.teardown()

    async def test_clean_stays_reversible(self):
        mgr = self.w.manager
        # seed a message row via service db
        await self.w.svc.db.execute(
            "INSERT INTO persons(nick, nick_lc) VALUES(?,?)", ("Nick", "nick"))
        await self.w.svc.db.commit()
        # media folder moved to trash, not deleted
        folder = self.w.media_dir_for(self.w.world_a)
        keep = os.path.join(folder, "a.jpg")
        write_file(keep, b"x")
        result = await mgr.clean()
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(os.path.exists(result.get("backup", "")),
                        "clean must keep a backup")
        self.assertTrue(os.path.exists(self.w.world_a),
                        "clean keeps the file")
        # restore brings rows back
        restored = await mgr.restore_backup(result["backup"], self.w.world_a)
        self.assertTrue(restored.get("ok"), restored)

    async def test_failed_switch_stays_connected(self):
        mgr = self.w.manager
        broken = os.path.join(self.w.dir, "broken.db")
        write_file(broken, b"not-sqlite" * 50)
        before = mgr.active_path()
        result = await mgr.load(broken)
        self.assertFalse(result.get("ok"))
        self.assertTrue(self.w.svc.db.is_open)
        self.assertEqual(os.path.abspath(mgr.active_path()),
                         os.path.abspath(before))

    async def test_create_then_load_roundtrip(self):
        mgr = self.w.manager
        made = await mgr.create("roundtrip")
        self.assertTrue(made.get("ok"), made)
        back = await mgr.load(self.w.world_a)
        self.assertTrue(back.get("ok"), back)
        self.assertEqual(os.path.abspath(mgr.active_path()),
                         os.path.abspath(self.w.world_a))


if __name__ == "__main__":
    unittest.main(verbosity=2)
