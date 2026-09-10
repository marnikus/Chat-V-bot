"""Switch failure: original world remains usable, victim untouched."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempWorld, insert_media_row_sync, write_file


class TestSwitchFailure(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.w = TempWorld()
        await self.w.setup(with_b=True, with_c=False)

    async def asyncTearDown(self):
        await self.w.teardown()

    async def test_switch_failure_leaves_original_usable(self):
        mgr = self.w.manager
        victim = self.w.world_a  # active victim → requires switch to B
        base = self.w.media_base
        media = os.path.join(base, "work", "x.jpg")
        # victim media
        victim_media = os.path.join(self.w.media_dir_for(victim), "a.jpg")
        write_file(victim_media, b"v")
        insert_media_row_sync(victim, "https://x/v.jpg", victim_media)
        before_rows = await self.w.svc.db.fetchall(
            "SELECT COUNT(*) FROM messages")
        # Force switch to fail (patch both legacy + unlocked delegates)
        from contextlib import ExitStack
        with ExitStack() as stack:
            m1 = stack.enter_context(mock.patch.object(
                mgr.lifecycle, "load",
                return_value={"ok": False, "error": "boom-switch"}))
            if hasattr(mgr.lifecycle, "_load_unlocked"):
                stack.enter_context(mock.patch.object(
                    mgr.lifecycle, "_load_unlocked",
                    return_value={"ok": False, "error": "boom-switch"}))
            stack.enter_context(mock.patch.object(
                self.w.svc, "switch_db",
                side_effect=RuntimeError("boom-switch")))
            result = await mgr.delete(victim)
        self.assertFalse(result.get("ok"))
        self.assertIn("boom", str(result.get("error", "")))
        # victim files/media untouched
        self.assertTrue(os.path.exists(victim))
        self.assertTrue(os.path.exists(victim_media))
        # original still usable and connected
        self.assertTrue(self.w.svc.db.is_open)
        self.assertEqual(os.path.abspath(mgr.active_path()),
                         os.path.abspath(victim))
        after_rows = await self.w.svc.db.fetchall(
            "SELECT COUNT(*) FROM messages")
        self.assertEqual(before_rows, after_rows)
        self.assertEqual(result.get("phase"), "switch")
        self.assertFalse(result.get("world_changed"))
        self.assertFalse(result.get("partial"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
