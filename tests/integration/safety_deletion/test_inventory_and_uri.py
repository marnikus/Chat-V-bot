"""Inventory + URI edges: remembered out-of-folder, dupes, same-stem, metachars.

- Known in-root world in another folder must be scanned (baseline misses it).
- Duplicate paths deduped.
- Same-stem worlds share one media folder → ambiguous, retain not sweep.
- Spaces / Unicode / ? # % in DB names must scan correctly (URI escaping).
"""

import os
import shutil
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempWorld, insert_media_row_sync, write_file


class TestInventoryAndUri(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.w = TempWorld()
        await self.w.setup(with_b=True, with_c=False)

    async def asyncTearDown(self):
        await self.w.teardown()

    async def test_remembered_world_outside_active_folder_is_protected(self):
        mgr = self.w.manager
        base = self.w.media_base
        # Create a world file in a SUBFOLDER inside root, remember it
        sub = os.path.join(self.w.dir, "sub")
        os.makedirs(sub, exist_ok=True)
        other_path = os.path.join(sub, "far.db")
        # clone schema from A via copy (real world file)
        shutil.copyfile(self.w.world_a, other_path)
        # also copy wal/shm if present (HistoryDB uses WAL? copy best-effort)
        for suffix in ("-wal", "-shm"):
            src = self.w.world_a + suffix
            if os.path.exists(src):
                shutil.copyfile(src, other_path + suffix)
        # remember it (simulates previously loaded world)
        mgr._remember(other_path)
        self.assertIn(other_path, mgr.known_paths())
        # Both victim B and far world reference shared file
        shared = os.path.join(base, "farshared", "a.jpg")
        write_file(shared, b"bytes")
        insert_media_row_sync(self.w.world_b, "https://x/f.jpg", shared)
        insert_media_row_sync(other_path, "https://x/f.jpg", shared)
        victim = self.w.world_b
        result = await mgr.delete(victim)
        # Fixed: shared survives because far world scanned. Baseline: deleted.
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(os.path.exists(shared),
                        "remembered out-of-folder world must be scanned; "
                        "shared file must survive")

    async def test_same_stem_worlds_do_not_sweep_shared_folder(self):
        mgr = self.w.manager
        # Two worlds with same stem in different dirs → same media_dir
        # e.g. history.db in root and history.db in sub/ → both map to
        # saved_media/history/. Create sub/history.db as same-stem sibling.
        sub = os.path.join(self.w.dir, "sub2")
        os.makedirs(sub, exist_ok=True)
        sibling = os.path.join(sub, "history.db")
        shutil.copyfile(self.w.world_a, sibling)
        for suffix in ("-wal", "-shm"):
            src = self.w.world_a + suffix
            if os.path.exists(src):
                shutil.copyfile(src, sibling + suffix)
        mgr._remember(sibling)
        # sibling references a file inside the shared stem folder
        stem_folder = self.w.media_dir_for(self.w.world_a)
        # victim B's folder is different stem (work), so to test same-stem
        # ambiguity we delete A (active) whose folder is shared with sibling?
        # Simpler: assert media_dir collision detected
        sibling_folder = mgr.media_dir(sibling)
        victim_folder_a = mgr.media_dir(self.w.world_a)
        self.assertEqual(os.path.abspath(sibling_folder),
                         os.path.abspath(victim_folder_a),
                         "test setup must collide stems")
        shared = os.path.join(stem_folder, "keep.jpg")
        write_file(shared, b"keep")
        insert_media_row_sync(sibling, "https://x/k.jpg", shared)
        # Delete A (active) → must switch to B, then shared must survive
        # because sibling (same folder) references it.
        result = await mgr.delete(self.w.world_a)
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(os.path.exists(shared),
                        "same-stem shared folder must not be swept")

    async def test_uri_metachars_scan_correctly(self):
        mgr = self.w.manager
        base = self.w.media_base
        # DB names with spaces, unicode, ? # % — must be creatable via manager?
        # Manager.create sanitizes via safe_db_name, so ?# become _. Instead
        # test scan directly on files with those chars created manually.
        # For now, test a world with space + unicode in stem via direct file.
        tricky = os.path.join(self.w.dir, "my world \u00e9\u00e8.db")
        shutil.copyfile(self.w.world_a, tricky)
        mgr._remember(tricky)
        shared = os.path.join(base, "tricky", "a.jpg")
        write_file(shared, b"b")
        insert_media_row_sync(self.w.world_b, "https://x/t.jpg", shared)
        insert_media_row_sync(tricky, "https://x/t.jpg", shared)
        result = await mgr.delete(self.w.world_b)
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(os.path.exists(shared),
                        "URI metachar world must be scanned correctly")

    async def test_duplicate_paths_deduped(self):
        mgr = self.w.manager
        # remembering same path twice keeps one entry (existing behavior)
        p = self.w.world_b
        mgr._remember(p)
        mgr._remember(p)
        paths = mgr.known_paths()
        self.assertEqual(paths.count(p), 1)
        # delete still works
        result = await mgr.delete(p)
        self.assertTrue(result.get("ok"), result)

    async def test_uri_question_hash_percent_world_scanned(self):
        """DB filename with ? # % must be URI-escaped and scanned."""
        import shutil
        mgr = self.w.manager
        base = self.w.media_base
        tricky = os.path.join(self.w.dir, "we?ird#name%.db")
        try:
            shutil.copyfile(self.w.world_a, tricky)
        except OSError as exc:
            self.skipTest(f"cannot create metachar file: {exc}")
        mgr._remember(tricky)
        shared = os.path.join(base, "metashared", "a.jpg")
        write_file(shared, b"b")
        insert_media_row_sync(self.w.world_b, "https://x/m.jpg", shared)
        try:
            insert_media_row_sync(tricky, "https://x/m.jpg", shared)
        except Exception as exc:
            self.skipTest(f"cannot write metachar DB (URI?): {exc}")
        result = await mgr.delete(self.w.world_b)
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(os.path.exists(shared),
                        "?#% world must be scanned (URI escaping)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
