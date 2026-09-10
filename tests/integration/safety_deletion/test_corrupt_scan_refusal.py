"""Corrupt/locked/unsupported other DB must REFUSE deletion (fail-closed).

Baseline defect: _media_references catches all and returns set(), so an
unreadable other world contributes nothing and deletion proceeds. Fixed
behavior: incomplete scan distinguished from empty; NO victim/media unlink.
These tests MUST FAIL on baseline (victim deleted) and PASS after fix.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempWorld, insert_media_row_sync, write_file


class TestCorruptScanRefusal(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.w = TempWorld()
        await self.w.setup(with_b=True, with_c=False)

    async def asyncTearDown(self):
        await self.w.teardown()

    async def _shared_setup(self):
        mgr = self.w.manager
        victim = self.w.world_b
        other = self.w.world_a
        base = self.w.media_base
        shared = os.path.join(base, "shared", "Nick", "images", "a.jpg")
        write_file(shared, b"shared-bytes")
        insert_media_row_sync(victim, "https://x/a.jpg", shared, "Nick")
        insert_media_row_sync(other, "https://x/a.jpg", shared, "Nick")
        return mgr, victim, other, shared

    async def test_corrupt_other_db_refuses_without_unlink(self):
        mgr, victim, other, shared = await self._shared_setup()
        # Corrupt the OTHER world (active) by overwriting with garbage.
        # Must close live connection first to allow overwrite on all platforms.
        await self.w.svc.db.close()
        with open(other, "wb") as fh:
            fh.write(b"not-a-sqlite-file" * 100)
        # Re-point manager at a valid world? No — active is now corrupt.
        # For deletion of victim (non-active), the scan of `other` must be
        # incomplete and refuse. Use a fresh manager with service=None to
        # avoid needing live connection? No — use real manager but service
        # db is closed; scan uses independent read-only connection, so it
        # will see corrupt file and must refuse.
        # Reopen service on victim to keep app connected? Simpler: create
        # third world C as active, corrupt B? Let's do robust variant below.
        # Here: victim=B, other=A(corrupt). Delete B must refuse.
        # Service is closed; attach still points at corrupt path. Delete of
        # non-active B should still scan A (corrupt) and refuse.
        result = await mgr.delete(victim)
        self.assertFalse(result.get("ok"),
                         f"corrupt other DB must refuse deletion, got {result}")
        self.assertTrue(os.path.exists(victim),
                        "victim DB must survive refused deletion")
        self.assertTrue(os.path.exists(shared),
                        "shared media must survive refused deletion")
        # phase/error must indicate scan problem
        err = str(result.get("error", "")).lower()
        self.assertTrue(err, "refusal must carry readable error")
        self.assertEqual(result.get("phase"), "scan")

    async def test_corrupt_other_db_with_valid_active_refuses(self):
        """Cleaner variant: A active valid, B victim, C corrupt other."""
        # Build third world C and corrupt it; delete B (victim) must refuse
        # because C cannot be verified, even though A is fine.
        mgr = self.w.manager
        # create C
        made = await mgr.create("other")
        self.assertTrue(made.get("ok"), made)
        world_c = made["path"]
        # back to A
        back = await mgr.load(self.w.world_a)
        self.assertTrue(back.get("ok"), back)
        victim = self.w.world_b
        base = self.w.media_base
        shared = os.path.join(base, "shared2", "a.jpg")
        write_file(shared, b"bytes")
        insert_media_row_sync(victim, "https://x/b.jpg", shared, "Nick")
        # C is corrupt: overwrite
        with open(world_c, "wb") as fh:
            fh.write(b"garbage-not-sqlite" * 200)
        result = await mgr.delete(victim)
        self.assertFalse(result.get("ok"),
                         f"unverifiable third world must refuse, got {result}")
        self.assertTrue(os.path.exists(victim))
        self.assertTrue(os.path.exists(shared))
        self.assertEqual(result.get("phase"), "scan")

    async def test_unsupported_schema_without_media_table_refuses(self):
        """Valid SQLite but no media table → incomplete, not empty."""
        import sqlite3
        mgr = self.w.manager
        made = await mgr.create("other2")
        self.assertTrue(made.get("ok"), made)
        world_c = made["path"]
        back = await mgr.load(self.w.world_a)
        self.assertTrue(back.get("ok"), back)
        victim = self.w.world_b
        base = self.w.media_base
        shared = os.path.join(base, "unsupported", "a.jpg")
        write_file(shared, b"bytes")
        insert_media_row_sync(victim, "https://x/u.jpg", shared, "Nick")
        # Replace C with valid SQLite lacking media table
        conn = sqlite3.connect(world_c)
        try:
            conn.execute("DROP TABLE IF EXISTS media")
            conn.commit()
        finally:
            conn.close()
        result = await mgr.delete(victim)
        self.assertFalse(result.get("ok"),
                         f"missing media table must refuse, got {result}")
        self.assertTrue(os.path.exists(victim))
        self.assertTrue(os.path.exists(shared))
        self.assertEqual(result.get("phase"), "scan")


if __name__ == "__main__":
    unittest.main(verbosity=2)
