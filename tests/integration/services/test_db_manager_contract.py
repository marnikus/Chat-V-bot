"""services/db_service — registry / lifecycle / containment contract (AREA C).

test_db_manager.py (534 lines) pins the lifecycle and window behaviour;
test_db_manager_corrupt.py pins corruption handling and create()
containment. This file pins the seams the AREA C split extracts
(docs/REFACTOR_2026-09-09_AREA_C_DESIGN.md §5):

  * DbRegistry: resolve() matrix (plain / suffix / inside-root paths /
    the containment refusal for traversal and absolute escapes),
    remember/prune/list_dbs/info;
  * DbLifecycle: create → connect, create refusal, load unchanged-active,
    delete a non-active world, restore_backup without a source, clean
    without a service.

The two resolve() refusal tests are behaviour-changing: they fail before
the AREA C containment fix and pass after it.

Run with:  python3 -m pytest tests/integration/services/test_db_manager_contract.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from backend.config_manager import ConfigManager  # noqa: E402
from backend.db_manager import DbManager  # noqa: E402
from backend.history_service import HistoryService  # noqa: E402
from test_chat_parser_delta import FakePage, raw  # noqa: E402


class ConnectedPage(FakePage):
    is_connected = True


class DbCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        media_cfg = dict(self.cfg.get("history", "media", default={}) or {})
        media_cfg["cache_dir"] = os.path.join(self.dir, "saved_media")
        self.cfg.set("history", "media", media_cfg)
        self.page = ConnectedPage([raw(f"m{i}", idx=i) for i in range(4)])
        self.db_path = os.path.join(self.dir, "history.db")
        self.service = HistoryService(cdp=self.page, config=self.cfg,
                                      db_path=self.db_path)
        await self.service.init()
        self.manager = DbManager(config=self.cfg, service=self.service,
                                 root=self.dir)

    async def asyncTearDown(self):
        try:
            await self.service.close()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
# DbRegistry — resolve() matrix
# ══════════════════════════════════════════════════════════════════
class TestResolveMatrix(DbCase):
    async def test_plain_name_joins_next_to_the_active_db(self):
        target = self.manager.resolve("work")
        self.assertEqual(os.path.dirname(os.path.abspath(target)),
                         os.path.abspath(self.dir))
        self.assertTrue(target.endswith("work.db"))

    async def test_name_with_suffix_is_kept(self):
        self.assertTrue(self.manager.resolve("work.db").endswith("work.db"))

    async def test_empty_input_resolves_to_empty(self):
        self.assertEqual(self.manager.resolve(""), "")
        self.assertEqual(self.manager.resolve("   "), "")

    async def test_absolute_path_inside_the_root_is_allowed(self):
        inside = os.path.join(self.dir, "inside.db")
        self.assertEqual(os.path.abspath(self.manager.resolve(inside)),
                         os.path.abspath(inside))

    async def test_traversal_name_is_refused(self):
        """AREA C containment fix: names that would escape the app folder
        resolve to '' (a loud refusal at the create/load/delete gates)."""
        self.assertEqual(self.manager.resolve("../evil"), "")

    async def test_absolute_path_outside_the_root_is_refused(self):
        outside = os.path.join(self.dir, "..", "escape.db")
        self.assertEqual(self.manager.resolve(outside), "")

    async def test_deep_relative_path_inside_root_is_allowed(self):
        os.makedirs(os.path.join(self.dir, "sub"), exist_ok=True)
        inside = os.path.join("sub", "nested.db")
        self.assertTrue(self.manager.resolve(inside))

    async def test_media_and_trash_dirs_derive_from_the_active_path(self):
        self.assertEqual(
            self.manager.media_dir(),
            os.path.join(self.dir, "saved_media", "history"))
        self.assertEqual(self.manager.trash_dir(),
                         os.path.join(self.dir, "db_trash"))


# ══════════════════════════════════════════════════════════════════
# DbRegistry — remember / prune / list / info
# ══════════════════════════════════════════════════════════════════
class TestRegistrySeams(DbCase):
    async def test_remember_caps_the_recent_list(self):
        for i in range(15):
            self.manager._remember(os.path.join(self.dir, f"w{i}.db"))
        self.assertEqual(len(self.manager.known_paths()), 12)

    async def test_prune_drops_ghost_paths(self):
        self.cfg.set_state(db_recent=[os.path.join(self.dir, "gone.db"),
                                      self.db_path])
        self.manager._prune_remembered()
        self.assertEqual(self.manager.known_paths(), [self.db_path])

    async def test_existing_worlds_scans_and_includes_active(self):
        open(os.path.join(self.dir, "neighbour.db"), "wb").close()
        worlds = self.manager.existing_worlds()
        abspaths = [os.path.abspath(p) for p in worlds]
        self.assertIn(os.path.abspath(self.db_path), abspaths)
        self.assertIn(os.path.abspath(os.path.join(self.dir, "neighbour.db")),
                      abspaths)

    async def test_list_dbs_shape_and_sort(self):
        open(os.path.join(self.dir, "aaa.db"), "wb").close()
        items = self.manager.list_dbs()
        self.assertTrue(items)
        for item in items:
            for key in ("path", "name", "bytes", "exists", "active",
                        "can_delete", "delete_hint"):
                self.assertIn(key, item)
        self.assertTrue(items[0]["active"], "the active world sorts first")

    async def test_info_reports_paths_and_counts(self):
        info = await self.manager.info()
        self.assertEqual(os.path.abspath(info["path"]),
                         os.path.abspath(self.db_path))
        for key in ("db_bytes", "media_bytes", "media_files", "persons",
                    "messages", "connected", "trash_dir", "total_bytes"):
            self.assertIn(key, info)
        self.assertTrue(info["connected"])


# ══════════════════════════════════════════════════════════════════
# DbLifecycle seams
# ══════════════════════════════════════════════════════════════════
class TestLifecycleSeams(DbCase):
    async def test_create_makes_a_new_world_and_connects(self):
        result = await self.manager.create("second")
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result["op"], "create")
        self.assertTrue(os.path.exists(
            os.path.join(self.dir, "second.db")))
        self.assertEqual(os.path.abspath(self.manager.active_path()),
                         os.path.abspath(os.path.join(self.dir,
                                                      "second.db")))

    async def test_create_refuses_traversal_names(self):
        """AREA C containment fix (red before the fix): no world may be
        created outside the app folder, loudly refused."""
        old = os.getcwd()
        tmp = tempfile.mkdtemp()
        os.chdir(tmp)
        try:
            result = await self.manager.create("../evil")
            self.assertFalse(result.get("ok"),
                             "a traversal name must be refused")
        finally:
            os.chdir(old)
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.unlink(os.path.join(tmp, "..", "evil" + suffix))
                except OSError:
                    pass

    async def test_create_refuses_absolute_names_outside_the_root(self):
        outside = os.path.join(self.dir, "..", "absolute_evil.db")
        try:
            result = await self.manager.create(outside)
            if result.get("ok"):
                self.assertTrue(
                    os.path.abspath(result["path"]).startswith(
                        os.path.abspath(self.dir) + os.sep),
                    "create accepted an absolute path outside the root")
        finally:
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.unlink(outside + suffix)
                except OSError:
                    pass

    async def test_load_the_active_world_is_unchanged(self):
        result = await self.manager.load(self.db_path)
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("unchanged"))

    async def test_delete_a_non_active_world(self):
        neighbour = os.path.join(self.dir, "neighbour.db")
        open(neighbour, "wb").close()
        result = await self.manager.delete(neighbour)
        self.assertTrue(result.get("ok"), result)
        self.assertFalse(os.path.exists(neighbour))

    async def test_delete_a_missing_file_reports_an_error(self):
        result = await self.manager.delete(
            os.path.join(self.dir, "never.db"))
        self.assertFalse(result.get("ok"))

    async def test_restore_backup_without_a_source_fails(self):
        result = await self.manager.restore_backup(
            os.path.join(self.dir, "gone.db"))
        self.assertFalse(result.get("ok"))
        self.assertIn("backup", result["error"])

    async def test_clean_without_a_service_fails(self):
        manager = DbManager(config=self.cfg, service=None, root=self.dir)
        result = await manager.clean()
        self.assertFalse(result.get("ok"))

    async def test_offline_load_persists_and_remembers(self):
        manager = DbManager(config=self.cfg, service=None, root=self.dir)
        target = os.path.join(self.dir, "offline.db")
        open(target, "wb").close()
        result = await manager.load(target)
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("offline"))
        self.assertEqual(self.cfg.get("history", "db_path", default=""),
                         target)


if __name__ == "__main__":
    unittest.main(verbosity=2)
