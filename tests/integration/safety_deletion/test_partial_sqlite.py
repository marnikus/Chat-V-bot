"""Partial SQLite group removal: exact survivors + truthful partial result.

Inject failure at every group element. Baseline returns ok False without
partial/removed/failed lists (red). Fixed returns partial True, phase
database, exact lists, media preserved (no media cleanup after DB partial).
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempWorld, insert_media_row_sync, write_file


class TestPartialSqlite(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.w = TempWorld()
        await self.w.setup(with_b=True, with_c=False)

    async def asyncTearDown(self):
        await self.w.teardown()

    def _ensure_group(self, victim):
        # Ensure main + wal + shm exist (journal best-effort)
        for suffix in ("", "-wal", "-shm"):
            p = victim + suffix
            if not os.path.exists(p):
                write_file(p, b"data-" + suffix.encode() or b"d")

    async def _run_partial(self, fail_suffix):
        mgr = self.w.manager
        victim = self.w.world_b
        self._ensure_group(victim)
        # victim media must be PRESERVED on DB partial
        media = os.path.join(self.w.media_dir_for(victim), "keep.jpg")
        write_file(media, b"keep")
        insert_media_row_sync(victim, "https://x/k.jpg", media)
        real_unlink = os.unlink

        def flaky(path, *a, **k):
            if str(path) == victim + fail_suffix:
                raise OSError("injected group failure")
            return real_unlink(path, *a, **k)

        with mock.patch("os.unlink", side_effect=flaky):
            result = await mgr.delete(victim)
        return victim, media, result

    async def test_fail_at_main(self):
        victim, media, result = await self._run_partial("")
        self.assertFalse(result.get("ok"))
        # main failed → main survives
        self.assertTrue(os.path.exists(victim),
                        "failed main must survive")
        self.assertTrue(os.path.exists(media),
                        "media preserved on DB partial")
        self.assertTrue(result.get("partial"))
        self.assertEqual(result.get("phase"), "database")
        self.assertIn(victim + "", result.get("failed_paths", []))
        self.assertEqual(result.get("media_files_removed"), 0)

    async def test_fail_at_wal(self):
        victim, media, result = await self._run_partial("-wal")
        self.assertFalse(result.get("ok"))
        # main removed (first), wal survives, shm? depends on order: main,
        # wal(fail) → stop, shm preserved (not attempted after fail? or
        # attempted? Our design stops at first failure to preserve rest.
        # Assert truthful reporting rather than exact order beyond survivors.
        self.assertFalse(os.path.exists(victim),
                         "main removed before wal failure")
        self.assertTrue(os.path.exists(victim + "-wal"),
                        "failed wal must survive")
        self.assertTrue(os.path.exists(media))
        self.assertTrue(result.get("partial"))
        self.assertIn(victim, result.get("removed_paths", []))
        self.assertIn(victim + "-wal", result.get("failed_paths", []))

    async def test_fail_at_shm(self):
        victim, media, result = await self._run_partial("-shm")
        self.assertFalse(result.get("ok"))
        self.assertFalse(os.path.exists(victim))
        # wal removed (second), shm survives
        self.assertTrue(os.path.exists(victim + "-shm"))
        self.assertTrue(os.path.exists(media))
        self.assertTrue(result.get("partial"))
        self.assertEqual(result.get("phase"), "database")


if __name__ == "__main__":
    unittest.main(verbosity=2)
