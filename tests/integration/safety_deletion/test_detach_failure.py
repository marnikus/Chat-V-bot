"""Detach / memory-close failure: no unlink, accurate state + phase."""

import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempWorld, write_file


class TestDetachFailure(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.w = TempWorld()
        await self.w.setup(with_b=True, with_c=False)

    async def asyncTearDown(self):
        await self.w.teardown()

    async def _force_point_at_victim(self, victim):
        """Make service handles point at victim so detach path triggers."""
        svc = self.w.svc
        # service.db.path is read for detach decision; patch to victim
        # Keep real db object but spoof path via mock? Simpler: create a
        # shallow fake service wrapper? We patch the instance attribute.
        # HistoryDB.path is plain attribute, safe to spoof then restore.
        self._orig_db_path = svc.db.path
        svc.db.path = victim
        if getattr(svc, "memory", None) is not None:
            # UserMemory.db_path is property over _db_path; patch underlying
            try:
                self._orig_mem_path = svc.memory._db_path
                svc.memory._db_path = victim
            except Exception:
                self._orig_mem_path = None
        else:
            self._orig_mem_path = None

    async def _restore_point(self):
        svc = self.w.svc
        try:
            svc.db.path = self._orig_db_path
        except Exception:
            pass
        if getattr(self, "_orig_mem_path", None) is not None:
            try:
                svc.memory._db_path = self._orig_mem_path
            except Exception:
                pass

    async def test_detach_failure_no_unlink(self):
        # Active victim: mock load to report success WITHOUT actually
        # switching (so service.db.path stays on victim), then detach fails.
        from contextlib import ExitStack
        mgr = self.w.manager
        victim = self.w.world_a  # active
        media = os.path.join(self.w.media_dir_for(victim), "a.jpg")
        write_file(media, b"x")
        self.assertEqual(os.path.abspath(self.w.svc.db.path),
                         os.path.abspath(victim))
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                mgr.lifecycle, "load",
                return_value={"ok": True, "path": self.w.world_b,
                              "before_path": victim}))
            if hasattr(mgr.lifecycle, "_load_unlocked"):
                stack.enter_context(mock.patch.object(
                    mgr.lifecycle, "_load_unlocked",
                    return_value={"ok": True, "path": self.w.world_b,
                                  "before_path": victim}))
            stack.enter_context(mock.patch.object(
                self.w.svc, "detach_db",
                side_effect=RuntimeError("detach-boom")))
            result = await mgr.delete(victim)
        self.assertFalse(result.get("ok"))
        self.assertIn("detach-boom", str(result.get("error", "")))
        self.assertTrue(os.path.exists(victim),
                        "no unlink on detach failure")
        self.assertTrue(os.path.exists(media))
        self.assertEqual(result.get("phase"), "detach")

    async def test_memory_close_failure_no_unlink(self):
        mgr = self.w.manager
        victim = self.w.world_b
        # Only when memory exists; HistoryService(cdp=None) has memory=None
        # by default. Attach a fake memory pointing at victim.
        fake_mem = types.SimpleNamespace(db_path=victim)
        async def _boom_close():
            raise RuntimeError("mem-boom")
        fake_mem.close = _boom_close
        orig_mem = self.w.svc.memory
        self.w.svc.memory = fake_mem
        # Ensure db detach path does NOT trigger (db points at A, not victim)
        # so we reach memory-close branch.
        try:
            result = await mgr.delete(victim)
        finally:
            self.w.svc.memory = orig_mem
        self.assertFalse(result.get("ok"))
        self.assertIn("mem-boom", str(result.get("error", "")))
        self.assertTrue(os.path.exists(victim))
        self.assertEqual(result.get("phase"), "detach")


if __name__ == "__main__":
    unittest.main(verbosity=2)
