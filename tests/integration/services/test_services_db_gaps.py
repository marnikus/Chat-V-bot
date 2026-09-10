"""services/db_service — seams NOT covered by tests/test_db_manager.py.

test_db_manager.py (42 tests) already pins create/load/delete/clean against a
real archive, the last-world rule, media sharing and the undo integration.
This file covers the untested seams only (docs/SERVICES_TEST_DESIGN
_2026-09-09.md §2.6): path resolution, offline modes, restore_backup, list
sorting and the size helpers.

Run with:  python3 tests/integration/services/test_services_db_gaps.py
"""

import asyncio
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from backend.config_manager import ConfigManager  # noqa: E402
from services.db_service import (DbManager, db_stem,  # noqa: E402
                                 file_group_size, folder_size, safe_db_name)


class TestNameAndStem(unittest.TestCase):
    def test_plain_name_gets_suffix_once(self):
        self.assertEqual(safe_db_name("work"), "work.db")
        self.assertEqual(safe_db_name("work.db"), "work.db")
        self.assertEqual(safe_db_name("work.db.db"), "work.db.db")

    def test_hostile_names_cannot_escape(self):
        for hostile in ("../../etc/passwd", "/etc/passwd", "..\\..\\x",
                        "a/b/c", "CON", "   "):
            clean = safe_db_name(hostile)
            self.assertNotIn("/", clean)
            self.assertNotIn("\\", clean)
            self.assertNotIn("..", clean)
            self.assertTrue(clean.endswith(".db"))

    def test_name_is_capped_at_80(self):
        self.assertLessEqual(len(safe_db_name("x" * 300)), 80)

    def test_db_stem(self):
        self.assertEqual(db_stem("work.db"), "work")
        self.assertEqual(db_stem("/a/b/my world 2.db"), "my_world_2")
        self.assertEqual(db_stem("nope.txt"), "nope")
        self.assertEqual(db_stem(""), "world")

    def test_folder_size_and_file_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "images"))
            with open(os.path.join(tmp, "images", "a.bin"), "wb") as fh:
                fh.write(b"a" * 10)
            size, files = folder_size(tmp)
            self.assertEqual((size, files), (10, 1))
            self.assertEqual(folder_size(os.path.join(tmp, "nope")), (0, 0))
            path = os.path.join(tmp, "x.db")
            with open(path, "wb") as fh:
                fh.write(b"a" * 4)
            with open(path + "-wal", "wb") as fh:
                fh.write(b"b" * 3)
            self.assertEqual(file_group_size(path), 7)


class ConfigOnlyCase(unittest.TestCase):
    """DbManager without a live HistoryService (offline seams)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        self.cfg.set("history", "media", {"cache_dir": os.path.join(self.dir, "media")})
        self.manager = DbManager(config=self.cfg, root=self.dir)
        self.cfg.set("history", "db_path", os.path.join(self.dir, "base.db"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_active_path_uses_service_first_then_config(self):
        self.assertEqual(self.manager.active_path(),
                         os.path.join(self.dir, "base.db"))
        service = types.SimpleNamespace(db=types.SimpleNamespace(
            path=os.path.join(self.dir, "live.db")))
        manager2 = DbManager(config=self.cfg, service=service)
        self.assertEqual(manager2.active_path(),
                         os.path.join(self.dir, "live.db"))

    def test_active_path_default(self):
        manager = DbManager(config=ConfigManager(
            os.path.join(self.dir, "empty.json")), root=self.dir)
        self.assertEqual(manager.active_path(), "history.db")

    def test_resolve(self):
        target = self.manager.resolve("my world")
        self.assertEqual(target,
                         os.path.join(self.dir, "my_world.db"))
        # absolute paths are preserved
        abs_path = os.path.join(self.dir, "other.db")
        self.assertEqual(self.manager.resolve(abs_path), abs_path)
        # empty input resolves to nothing
        self.assertEqual(self.manager.resolve("   "), "")

    def test_media_and_trash_dirs_follow_the_active_file(self):
        self.assertEqual(self.manager.media_dir(),
                         os.path.join(self.dir, "media", "base"))
        self.assertEqual(self.manager.trash_dir(),
                         os.path.join(self.dir, "db_trash"))
        self.assertEqual(self.manager.media_base_dir(),
                         os.path.join(self.dir, "media"))

    def test_known_paths_capped_at_12_and_deduped(self):
        for i in range(15):
            self.manager._remember(os.path.join(self.dir, f"w{i}.db"))
        paths = self.manager.known_paths()
        self.assertEqual(len(paths), 12)
        self.assertEqual(paths[0], os.path.join(self.dir, "w14.db"))
        self.assertEqual(len(set(paths)), 12)

    def test_list_sorts_active_first(self):
        self.cfg.set_state(db_recent=[])
        for name in ("zeta.db", "alpha.db", "base.db"):
            open(os.path.join(self.dir, name), "w").close()
        items = self.manager.list_dbs()
        self.assertEqual(items[0]["name"], "base.db", "active world first")
        self.assertEqual([i["name"] for i in items],
                         ["base.db", "alpha.db", "zeta.db"])
        self.assertTrue(all(i["can_delete"] for i in items if len(items) >= 2))
        self.assertEqual(items[0]["delete_hint"],
                         "Permanently delete this database and its media")

    def test_info_offline_reports_disk_truth(self):
        path = os.path.join(self.dir, "x.db")
        with open(path, "wb") as fh:
            fh.write(b"x" * 32)
        self.cfg.set("history", "db_path", path)
        info = asyncio.run(self.manager.info())
        self.assertFalse(info["connected"])
        self.assertTrue(info["exists"])
        self.assertEqual(info["db_bytes"], 32)
        self.assertEqual(info["persons"], 0)
        self.assertEqual(info["messages"], 0)

    def test_load_offline_persists_and_remembers(self):
        path = os.path.join(self.dir, "offline.db")
        open(path, "w").close()
        result = asyncio.run(self.manager.load(path))
        self.assertTrue(result["ok"])
        self.assertTrue(result["offline"])
        self.assertEqual(self.cfg.get("history", "db_path"), path)
        self.assertEqual(self.manager.known_paths()[0], path)

    def test_restore_backup_missing_is_error(self):
        result = asyncio.run(self.manager.restore_backup(
            os.path.join(self.dir, "nope.db")))
        self.assertFalse(result["ok"])
        self.assertIn("backup is gone", result["error"])


class RestoreCase(unittest.IsolatedAsyncioTestCase):
    """restore_backup — the undo half of clean — against a real archive."""

    async def asyncSetUp(self):
        from backend.config_manager import ConfigManager as CM
        from services.history import HistoryService
        self.dir = tempfile.mkdtemp()
        self.cfg = CM(os.path.join(self.dir, "config.json"))
        media_cfg = dict(self.cfg.get("history", "media", default={}) or {})
        media_cfg["cache_dir"] = os.path.join(self.dir, "saved_media")
        self.cfg.set("history", "media", media_cfg)
        self.service = HistoryService(
            cdp=None, config=self.cfg,
            db_path=os.path.join(self.dir, "history.db"))
        await self.service.init()
        self.manager = DbManager(config=self.cfg, service=self.service,
                                 root=self.dir)

    async def asyncTearDown(self):
        await self.service.close()

    async def seed_row(self):
        from datetime import datetime
        from stores.history_models import MessageRecord, fingerprint
        rec = MessageRecord(
            fp=fingerprint("in", "Nick", "10:00", "text", "hello", 0),
            direction="in", from_nick="Nick", kind="text", text="hello",
            media_url="", media_kind="", ts_display="10:00", occ=0, idx=0)
        await self.service.repo.append("Nick", [rec], my_nick="Me",
                                       now=datetime(2026, 9, 6, 18, 30))

    async def test_restore_connected_backup_brings_rows_back(self):
        await self.seed_row()
        # build a backup via clean
        result = await self.manager.clean()
        self.assertTrue(result["ok"], result)
        backup = result["backup"]
        self.assertTrue(backup)
        rows = await self.service.db.fetchall(
            "SELECT COUNT(*) FROM messages")
        self.assertEqual(rows[0][0], 0)
        restored = await self.manager.restore_backup(backup)
        self.assertTrue(restored["ok"], restored)
        self.assertEqual(self.manager.active_path(),
                         os.path.join(self.dir, "history.db"))
        rows = await self.service.db.fetchall(
            "SELECT COUNT(*) FROM messages")
        self.assertGreater(rows[0][0], 0, "undo of clean must restore the rows")

    async def test_restore_to_a_target_switches_the_world_to_it(self):
        target = os.path.join(self.dir, "other.db")
        source = os.path.join(self.dir, "backup.db")
        await self.service.db.close()
        import shutil
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(self.service.db.path + suffix):
                shutil.copyfile(self.service.db.path + suffix,
                                source + suffix)
        result = await self.manager.restore_backup(source, target=target)
        self.assertTrue(result["ok"], result)
        self.assertTrue(os.path.exists(target))
        # restore_backup puts the restored world LIVE and remembers it
        self.assertEqual(self.cfg.get("history", "db_path"), target)
        self.assertEqual(self.manager.active_path(), target)

    async def test_clean_failure_keeps_the_backup(self):
        class BrokenDb:
            is_open = True
            path = os.path.join(self.dir, "broken.db")
            fts_enabled = False
            async def scalar(self, *a, **kw):
                raise RuntimeError("table missing")
            async def execute(self, *a, **kw):
                raise RuntimeError("table missing")
            async def commit(self):
                raise RuntimeError("table missing")

        service = types.SimpleNamespace(
            db=BrokenDb(),
            memory=None,
            media_base_dir=lambda: os.path.join(self.dir, "media"))
        manager = DbManager(config=self.cfg, service=service, root=self.dir)
        with open(os.path.join(self.dir, "broken.db"), "wb") as fh:
            fh.write(b"x")
        result = await manager.clean()
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("backup"), "a backup must exist for a clean edit")


if __name__ == "__main__":
    unittest.main(verbosity=2)
