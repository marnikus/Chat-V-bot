"""Ghost-file regression: real SQLite/filesystem -> manager -> Bridge -> panel.

The exact b.db/m.db mismatch, safe diagnostics, non-overwrite races and native
file reveal. No user's database or native desktop is touched by these tests.
"""

import asyncio
import copy
import json
import ntpath
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import closing
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QObject
from backend.bridge import Bridge
from backend.config_manager import ConfigManager
from backend.db_inventory import ALIAS_DATABASE, SUFFIXES, existing_group
from backend.db_manager import DbManager, LAST_DATABASE
from backend.db_paths import PROTECTED_DATABASE
from backend.file_reveal import _start_detached, reveal_file
from backend.history_db import HistoryDB, INCOMPATIBLE_SCHEMA, inspect_archive, inspect_archive_details
from test_db_connection_safety import SafetyCase


class InventoryCase(SafetyCase):
    database_name = "b.db"

    def mpath(self, name="m.db"):
        return os.path.join(self.root, name)

    def entry(self, path, items=None):
        return next(i for i in (self.manager.list_dbs() if items is None else items)
                    if i["path"] == path)

    async def independent(self, path):
        db = HistoryDB(path)
        try:
            await db.init()
        finally:
            await db.close()
        return path

    async def assert_conflict(self, path, status):
        await self.seed()
        original = self.service.db
        messages = await self.contents()
        settings = self.service.settings()
        collector = self.service.collector.state_payload()
        result = await self.manager.create(path)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["path"], path)
        self.assertEqual(result["conflict"]["status"], status)
        row = self.entry(path, result["items"])
        self.assertTrue(row["blocking"])
        self.assertTrue(row["can_reveal"])
        self.assertFalse(row["can_load"])
        self.assertFalse(row["can_delete"])
        self.assertFalse(row["manageable"])
        self.assertFalse(self.entry(self.path, result["items"])["can_delete"])
        self.assertEqual(self.entry(path)["status"], status, "refresh must not re-hide the file")
        self.assertIs(self.service.db, original)
        self.assertEqual(await self.contents(), messages)
        self.assertEqual(self.service.settings(), settings)
        self.assertEqual(self.service.collector.state_payload(), collector)
        self.assertEqual(self.cfg.get("history", "db_path"), self.path)
        return result


class TestVisibleConflicts(InventoryCase):
    async def test_empty_m_is_visible_while_b_stays_connected(self):
        path = self.mpath()
        Path(path).touch()
        self.assertEqual(self.names(), ["b.db", "m.db"])
        result = await self.assert_conflict(path, "empty")
        self.assertIn("m.db already exists", result["error"])
        self.assertIn("0 bytes", result["detail"])
        self.assertEqual(Path(path).read_bytes(), b"")
        self.assertEqual((await self.manager.load(path))["error"], INCOMPATIBLE_SCHEMA)
        self.assertEqual((await self.manager.delete(path))["error"], INCOMPATIBLE_SCHEMA)
        self.assertEqual((await self.manager.delete(self.path))["error"], LAST_DATABASE)

    async def test_old_foreign_schema_is_visible_not_reinitialized_or_loaded(self):
        path = self.mpath()
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY, user_id INTEGER, text TEXT)")
            db.execute("INSERT INTO messages VALUES(1,42,'preserve this old conversation')")
            db.commit()
        original = Path(path).read_bytes()
        result = await self.assert_conflict(path, "incompatible")
        self.assertTrue(result["detail"])
        self.assertEqual((await self.manager.load(path))["error"], INCOMPATIBLE_SCHEMA)
        self.assertEqual((await self.manager.delete(path))["error"], INCOMPATIBLE_SCHEMA)
        self.assertEqual(Path(path).read_bytes(), original)

    async def test_corrupt_bytes_are_visible_and_untouched(self):
        path = self.mpath()
        content = b"This is not SQLite; it must never be overwritten.\x00\xff"
        Path(path).write_bytes(content)
        result = await self.assert_conflict(path, "incompatible")
        self.assertIn("not a database", result["detail"])
        self.assertEqual(Path(path).read_bytes(), content)

    async def test_each_orphan_sidecar_reserves_a_visible_name_without_a_main_db(self):
        path = self.mpath()
        for suffix in SUFFIXES[1:]:
            with self.subTest(suffix=suffix):
                member = path + suffix
                Path(member).write_bytes(b"potentially recoverable data")
                result = await self.assert_conflict(path, "sidecars")
                self.assertFalse(result["conflict"]["main_exists"])
                self.assertEqual(result["conflict"]["files"], [member])
                self.assertIn("database file itself is missing", result["error"])
                self.assertIn("m.db" + suffix, result["error"])
                self.assertNotIn("m.db already exists", result["error"])
                self.assertEqual(self.manager.reveal_target(path)["reveal_path"], member)
                self.assertFalse(os.path.lexists(path), "discovery must not initialize m.db")
                self.assertEqual(Path(member).read_bytes(), b"potentially recoverable data")
                os.unlink(member)
        self.assertEqual(self.names(), ["b.db"])
        self.assertNotIn(path, self.manager.known_paths())
        self.assertTrue((await self.manager.create("m"))["ok"])

    async def test_multiple_sidecars_are_one_diagnostic_row(self):
        path = self.mpath()
        for suffix in SUFFIXES[1:]:
            Path(path + suffix).write_bytes(suffix.encode())
        result = await self.assert_conflict(path, "sidecars")
        self.assertEqual(self.names(), ["b.db", "m.db"])
        self.assertEqual(result["conflict"]["files"], [path + s for s in SUFFIXES[1:]])
        self.assertFalse(os.path.exists(path))

    async def test_directory_with_db_name_is_visible_and_never_touched(self):
        path = self.mpath()
        os.mkdir(path)
        Path(path, "valuable.txt").write_text("preserved")
        await self.assert_conflict(path, "not_file")
        self.assertEqual(Path(path, "valuable.txt").read_text(), "preserved")
        self.assertFalse((await self.manager.delete(path))["ok"])

    async def test_broken_link_blocks_its_lexical_name_not_its_missing_target(self):
        path = self.mpath()
        target = self.mpath("never-create-this.db")
        os.symlink(target, path)
        result = await self.assert_conflict(path, "broken_link")
        self.assertEqual(result["path"], path)
        self.assertEqual(self.manager.reveal_target(path)["reveal_path"], path)
        self.assertTrue(os.path.islink(path))
        self.assertFalse(os.path.lexists(target))
        self.assertEqual((await self.manager.load(path))["error"], ALIAS_DATABASE)
        self.assertEqual((await self.manager.delete(path))["error"], ALIAS_DATABASE)

    async def test_active_symlink_alias_is_visible_but_not_a_second_database(self):
        path = self.mpath()
        os.symlink(self.path, path)
        await self.assert_conflict(path, "alias")
        self.assertEqual(self.entry(path)["alias_of"], self.path)
        self.assertEqual((await self.manager.load(path))["error"], ALIAS_DATABASE)
        self.assertEqual((await self.manager.delete(path))["error"], ALIAS_DATABASE)
        self.assertEqual((await self.manager.delete(self.path))["error"], LAST_DATABASE)
        self.assertTrue(os.path.exists(path))

    async def test_active_hardlink_alias_is_visible_but_cannot_delete_the_live_file(self):
        path = self.mpath()
        os.link(self.path, path)
        await self.assert_conflict(path, "alias")
        self.assertEqual((await self.manager.delete(path))["error"], ALIAS_DATABASE)
        self.assertEqual((await self.manager.load(path))["error"], ALIAS_DATABASE)
        self.assertEqual((await self.manager.delete(self.path))["error"], LAST_DATABASE)
        self.assertTrue(os.path.samefile(path, self.path))

    async def test_unaccounted_external_hardlink_is_read_only_not_an_independent_archive(self):
        with tempfile.TemporaryDirectory() as outside:
            original = await self.independent(str(Path(outside, "external.db")))
            path = self.mpath()
            os.link(original, path)
            await self.assert_conflict(path, "alias")
            self.assertIn("outside this inventory", self.entry(path)["detail"])
            self.assertEqual((await self.manager.load(path))["error"], ALIAS_DATABASE)
            self.assertEqual((await self.manager.delete(path))["error"], ALIAS_DATABASE)
            self.assertTrue(os.path.samefile(path, original))

    async def test_alias_order_is_stable_when_a_duplicate_is_remembered(self):
        primary = await self.make("c")
        alias = self.mpath()
        os.link(primary, alias)
        self.assertEqual(self.entry(alias)["status"], "alias")
        result = await self.manager.create(alias)
        self.assertEqual(self.entry(alias, result["items"])["status"], "alias")
        self.assertEqual(self.entry(alias)["alias_of"], primary)
        self.assertEqual(sum(i["manageable"] for i in result["items"]), 2)
        self.assertFalse((await self.manager.delete(alias))["ok"])

    async def test_temporarily_locked_archive_stays_visible_and_not_a_fallback(self):
        path = await self.make("m")
        with closing(sqlite3.connect(path, timeout=0.1)) as db:
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("BEGIN EXCLUSIVE")
            try:
                result = await self.assert_conflict(path, "unavailable")
                self.assertIn("locked", result["detail"])
                self.assertEqual((await self.manager.delete(self.path))["error"], LAST_DATABASE)
            finally:
                db.rollback()
        self.assertEqual(self.entry(path)["status"], "ready")
        self.assertTrue(self.entry(path)["can_load"])

    async def test_valid_unregistered_archive_is_discovered_and_duplicate_is_visible(self):
        path = await self.independent(self.mpath())
        self.assertNotIn(path, self.manager.known_paths())
        self.assertTrue(self.entry(path)["can_load"])
        result = await self.manager.create("m")
        self.assertFalse(result["ok"])
        self.assertTrue(result["conflict"]["compatible"])
        self.assertEqual([i["name"] for i in result["items"]], ["b.db", "m.db"])
        self.assertEqual(self.manager.active_path(), self.path)
        self.assertTrue((await self.manager.load(path))["ok"])

    async def test_safe_legacy_discovery_does_not_perform_the_migration(self):
        path = await self.make("m")
        with closing(sqlite3.connect(path)) as db:
            db.execute("UPDATE schema_meta SET value='4' WHERE key='schema_version'")
            db.commit()
        before = Path(path).read_bytes()
        row = self.entry(path)
        self.assertEqual(row["status"], "legacy")
        self.assertTrue(row["can_load"])
        self.assertEqual(inspect_archive_details(path, full=True)["schema_version"], "4")
        self.assertTrue(inspect_archive(path, full=True))
        self.assertEqual(Path(path).read_bytes(), before)
        self.assertTrue((await self.manager.load(path))["ok"])
        self.assertEqual(await self.service.db.get_meta("schema_version"), "5")

    async def test_known_reserved_stores_sidecars_aliases_and_staging_remain_excluded(self):
        undo_wal = self.mpath("undo_history.db-wal")
        staging = self.mpath(".cvb-private.db")
        link = self.mpath("queue-link.db")
        for path in (undo_wal, staging):
            Path(path).write_bytes(b"internal state")
        os.link(self.memory._db_path, link)
        self.cfg.set_state(db_recent=[link, staging, self.mpath("undo_history.db")])
        self.assertEqual(self.names(), ["b.db"])
        self.assertEqual(self.manager.known_paths(), [])
        for path in (link, staging, self.mpath("undo_history.db")):
            self.assertEqual((await self.manager.create(path))["error"], PROTECTED_DATABASE)
        self.assertEqual(Path(undo_wal).read_bytes(), b"internal state")
        self.assertEqual(Path(staging).read_bytes(), b"internal state")

    async def test_lexical_trash_boundary_cannot_be_escaped_through_a_link(self):
        with tempfile.TemporaryDirectory() as outside:
            trash = Path(self.root, "db_trash")
            trash.mkdir()
            (trash / "outside").symlink_to(outside, target_is_directory=True)
            result = await self.manager.create(str(trash / "outside" / "m.db"))
            self.assertEqual(result["error"], PROTECTED_DATABASE)
            self.assertFalse(Path(outside, "m.db").exists())


class TestInventoryLifecycle(InventoryCase):
    async def test_missing_recent_is_pruned_on_disk_and_does_not_reserve_the_name(self):
        path = self.mpath()
        self.cfg.set_state(db_recent=[path])
        self.assertEqual(self.names(), ["b.db"])
        self.assertEqual(self.manager.known_paths(), [])
        reload = ConfigManager(self.cfg._path)
        self.assertEqual(reload.get_state("db_recent"), [])
        result = await self.manager.create("m")
        self.assertTrue(result["ok"])
        self.assertEqual([i["name"] for i in result["items"]], ["b.db", "m.db"])
        self.assertEqual(result["active_path"], self.path)

    async def test_existing_external_invalid_hint_survives_refresh_and_restart(self):
        with tempfile.TemporaryDirectory() as outside:
            path = str(Path(outside, "m.db"))
            Path(path).touch()
            result = await self.assert_conflict(path, "empty")
            self.assertIn(path, self.manager.known_paths())
            restarted = DbManager(ConfigManager(self.cfg._path), root=self.root)
            self.assertEqual(self.entry(path, restarted.list_dbs())["status"], "empty")
            self.assertEqual(self.entry(path, result["items"])["reveal_path"], path)
            os.unlink(path)
            self.assertEqual([i["name"] for i in restarted.list_dbs()], ["b.db"])
            self.assertEqual(restarted.known_paths(), [])
            self.assertTrue((await self.manager.create(path))["ok"])
            self.assertEqual(self.manager.active_path(), self.path)

    async def test_external_orphan_hint_is_retained_until_the_actual_sidecar_disappears(self):
        with tempfile.TemporaryDirectory() as outside:
            path = str(Path(outside, "m.db"))
            Path(path + "-shm").write_bytes(b"shared memory")
            self.cfg.set_state(db_recent=[path])
            row = self.entry(path)
            self.assertEqual(row["status"], "sidecars")
            self.assertIn(path, self.manager.known_paths())
            os.unlink(path + "-shm")
            self.assertNotIn(path, [i["path"] for i in self.manager.list_dbs()])
            self.assertEqual(self.manager.known_paths(), [])

    async def test_create_delete_and_same_name_recreate_have_immediate_truthful_snapshots(self):
        made = await self.manager.create("m")
        self.assertTrue(self.entry(made["path"], made["items"])["can_load"])
        original = self.service.db
        deleted = await self.manager.delete(made["path"])
        self.assertTrue(deleted["ok"], deleted)
        self.assertEqual([i["name"] for i in deleted["items"]], ["b.db"])
        self.assertEqual(existing_group(made["path"]), [])
        self.assertNotIn(made["path"], self.manager.known_paths())
        self.assertTrue(os.path.exists(deleted["backup"]))
        self.assertFalse(deleted["items"][0]["can_delete"])
        again = await self.manager.create("m")
        self.assertTrue(again["ok"], again)
        self.assertEqual([i["name"] for i in again["items"]], ["b.db", "m.db"])
        self.assertIs(self.service.db, original)

    async def test_delete_moves_broken_sidecar_links_too_so_the_name_is_truly_free(self):
        path = await self.make("m")
        missing = self.mpath("missing-journal-target")
        os.symlink(missing, path + "-journal")
        self.assertTrue(inspect_archive(path, full=True))
        deleted = await self.manager.delete(path)
        self.assertTrue(deleted["ok"], deleted)
        self.assertEqual(existing_group(path), [])
        self.assertTrue(os.path.islink(deleted["backup"] + "-journal"))
        self.assertFalse(os.path.exists(missing))
        self.assertEqual([i["name"] for i in deleted["items"]], ["b.db"])
        self.assertTrue((await self.manager.create("m"))["ok"])

    async def test_link_left_after_active_delete_cannot_mutate_the_undo_backup(self):
        await self.seed()
        await self.make("m")
        alias = self.mpath("old-b-link.db")
        os.link(self.path, alias)
        deleted = await self.manager.delete(self.path)
        self.assertTrue(deleted["ok"], deleted)
        self.assertEqual(self.entry(alias, deleted["items"])["status"], "alias")
        self.assertFalse(self.entry(alias, deleted["items"])["can_load"])
        self.assertTrue(os.path.samefile(alias, deleted["backup"]))
        before = Path(deleted["backup"]).read_bytes()
        self.assertEqual((await self.manager.load(alias))["error"], ALIAS_DATABASE)
        self.assertEqual(Path(deleted["backup"]).read_bytes(), before)
        self.assertEqual((await self.manager.delete(self.mpath()))["error"], LAST_DATABASE)

    async def test_restore_refuses_an_alias_planted_at_the_original_name(self):
        await self.seed()
        made = await self.make("m")
        deleted = await self.manager.delete(made)
        os.symlink(self.path, made)
        original = self.service.db
        before = await self.contents()
        restored = await self.manager.restore_backup(deleted["backup"], made)
        self.assertFalse(restored["ok"])
        self.assertEqual(restored["error"], ALIAS_DATABASE)
        self.assertIs(self.service.db, original)
        self.assertEqual(await self.contents(), before)
        self.assertTrue(os.path.islink(made))

    async def test_publication_race_reports_the_winner_without_overwriting_it(self):
        path = self.mpath()
        publish = self.manager._publish
        def race(stage, destination):
            Path(destination).write_bytes(b"another creator won")
            publish(stage, destination)
        with patch.object(self.manager, "_publish", side_effect=race):
            result = await self.manager.create("m")
        self.assertFalse(result["ok"])
        self.assertEqual(result["conflict"]["status"], "incompatible")
        self.assertIn("m.db already exists", result["error"])
        self.assertEqual(self.entry(path, result["items"])["path"], path)
        self.assertEqual(Path(path).read_bytes(), b"another creator won")
        self.assertEqual(list(Path(self.root).glob(".cvb-*")), [])
        self.assertEqual(self.manager.active_path(), self.path)

    async def test_sidecar_appearing_at_publication_is_not_overwritten_or_hidden(self):
        path = self.mpath()
        publish = self.manager._publish
        def race(stage, destination):
            Path(destination + "-wal").write_bytes(b"do not discard this WAL")
            publish(stage, destination)
        with patch.object(self.manager, "_publish", side_effect=race):
            result = await self.manager.create("m")
        self.assertFalse(result["ok"])
        self.assertEqual(result["conflict"]["status"], "sidecars")
        self.assertFalse(os.path.exists(path))
        self.assertEqual(Path(path + "-wal").read_bytes(), b"do not discard this WAL")
        self.assertEqual(list(Path(self.root).glob(".cvb-*")), [])

    async def test_atomic_main_file_link_still_refuses_a_winner_after_the_group_check(self):
        path = self.mpath()
        original_link = os.link
        def late_winner(source, destination):
            if destination == path:
                Path(path).write_bytes(b"won just before the atomic link")
            return original_link(source, destination)
        with patch("backend.db_manager.os.link", side_effect=late_winner):
            result = await self.manager.create("m")
        self.assertFalse(result["ok"])
        self.assertIn("m.db already exists", result["error"])
        self.assertEqual(Path(path).read_bytes(), b"won just before the atomic link")
        self.assertEqual(self.entry(path, result["items"])["status"], "incompatible")

    async def test_first_snapshot_accounts_for_sidecars_created_by_sqlite_read_only_inspection(self):
        made = await self.manager.create("m")
        for row in made["items"]:
            self.assertEqual(row["files"], existing_group(row["path"]))
            self.assertEqual(row["bytes"], sum(os.path.getsize(p) for p in row["files"]))
        self.assertEqual(made["items"], self.manager.list_dbs())

    async def test_disappearance_during_inspection_drops_missing_groups_and_disables_orphans(self):
        for keep_sidecars in (True, False):
            with self.subTest(keep_sidecars=keep_sidecars):
                path = await self.make("m")
                def disappear(candidate, **kwargs):
                    result = inspect_archive_details(candidate, **kwargs)
                    if candidate == path:
                        for member in ([path] if keep_sidecars else existing_group(path)):
                            os.unlink(member)
                    return result
                with patch("backend.db_inventory.inspect_archive_details", side_effect=disappear):
                    items = self.manager.list_dbs()
                if keep_sidecars:
                    row = self.entry(path, items)
                    self.assertFalse(row["main_exists"])
                    self.assertFalse(row["manageable"])
                    self.assertFalse(row["can_load"])
                    self.assertFalse(row["can_delete"])
                    self.assertEqual(row["files"], existing_group(path))
                    self.assertEqual(self.entry(path)["status"], "sidecars")
                    for member in existing_group(path):
                        os.unlink(member)
                else:
                    self.assertNotIn(path, [i["path"] for i in items])
                    self.assertNotIn(path, self.manager.known_paths())
                self.assertEqual((await self.manager.delete(self.path))["error"], LAST_DATABASE)

    async def test_info_and_direct_list_share_the_same_capabilities(self):
        path = self.mpath()
        Path(path).touch()
        info = await self.manager.info()
        self.assertEqual(info["inventory_folder"], self.root)
        self.assertEqual(info["items"], self.manager.list_dbs())
        self.assertTrue(info["connected"])
        self.assertFalse(self.entry(path, info["items"])["can_load"])

    async def test_missing_file_probe_never_creates_a_database_or_sidecar(self):
        path = self.mpath()
        result = inspect_archive_details(path, full=True)
        self.assertFalse(result["compatible"])
        self.assertEqual(result["status"], "missing")
        self.assertFalse(inspect_archive(path))
        self.assertEqual(existing_group(path), [])


class TestNativeReveal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name, "m & other; Пошлый01.db"))
        Path(self.path).touch()

    def test_windows_selects_exact_filename_using_arguments_not_a_shell(self):
        with patch("backend.file_reveal.sys.platform", "win32"), \
                patch("backend.file_reveal._start_detached", return_value=True) as start:
            result = reveal_file(self.path)
        self.assertTrue(result["ok"])
        start.assert_called_once_with("explorer.exe", ["/select,", ntpath.normpath(self.path)])

    def test_macos_selects_the_file_not_its_associated_application(self):
        with patch("backend.file_reveal.sys.platform", "darwin"), \
                patch("backend.file_reveal._start_detached", return_value=True) as start:
            self.assertTrue(reveal_file(self.path)["ok"])
        start.assert_called_once_with("/usr/bin/open", ["-R", self.path])

    def test_other_desktops_open_only_the_containing_folder(self):
        with patch("backend.file_reveal.sys.platform", "linux"), \
                patch("backend.file_reveal._open_folder", return_value=True) as open_folder:
            self.assertTrue(reveal_file(self.path)["ok"])
        open_folder.assert_called_once_with(self.tmp.name)

    def test_qprocess_false_pid_tuple_is_not_reported_as_success(self):
        with patch("PySide6.QtCore.QProcess.startDetached", return_value=(False, 0)):
            self.assertFalse(_start_detached("explorer.exe", ["/select,", self.path]))

    def test_launcher_refusal_and_exception_are_visible_failures(self):
        for outcome in (False, OSError("launcher missing")):
            with self.subTest(outcome=outcome), \
                    patch("backend.file_reveal.sys.platform", "linux"), \
                    patch("backend.file_reveal._open_folder", return_value=outcome,
                          side_effect=outcome if isinstance(outcome, Exception) else None):
                result = reveal_file(self.path)
                self.assertFalse(result["ok"])
                self.assertTrue(result["error"])

    def test_disappearing_file_never_launches_a_file_manager(self):
        os.unlink(self.path)
        with patch("backend.file_reveal._start_detached") as start, \
                patch("backend.file_reveal._open_folder") as open_folder:
            self.assertFalse(reveal_file(self.path)["ok"])
        start.assert_not_called()
        open_folder.assert_not_called()

    def test_broken_link_can_be_revealed_without_creating_its_target(self):
        os.unlink(self.path)
        target = str(Path(self.tmp.name, "missing.db"))
        os.symlink(target, self.path)
        with patch("backend.file_reveal.sys.platform", "linux"), \
                patch("backend.file_reveal._open_folder", return_value=True):
            self.assertTrue(reveal_file(self.path)["ok"])
        self.assertFalse(os.path.exists(target))


class TestBridgeInventory(InventoryCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        bridge = Bridge.__new__(Bridge)
        QObject.__init__(bridge)
        bridge._config, bridge._memory, bridge._presets = self.cfg, self.memory, None
        bridge._engine = types.SimpleNamespace(load_stack=lambda _b: None)
        bridge._dbs = self.manager
        bridge.attach_history(self.service)
        self.bridge = bridge
        self.changes, self.resets, self.infos = [], [], []
        self.completed, self.measured = asyncio.Event(), asyncio.Event()
        def changed(raw):
            self.changes.append(json.loads(raw))
            self.completed.set()
        def info(_req, raw):
            self.infos.append(json.loads(raw))
            self.measured.set()
        bridge.db_changed.connect(changed)
        bridge.db_info_ready.connect(info)
        bridge.history_reset.connect(lambda raw: self.resets.append(json.loads(raw)))

    async def command(self, name, *args):
        self.completed.clear()
        getattr(self.bridge, name)(*args)
        await asyncio.wait_for(self.completed.wait(), 5)
        return self.changes[-1]

    async def info(self):
        self.measured.clear()
        self.bridge.db_info("test-request")
        await asyncio.wait_for(self.measured.wait(), 5)
        return self.infos[-1]

    def panel(self, events, reveal_results=None):
        node = shutil.which("node")
        have_dom = node and subprocess.run(
            [node, "-e", "require('jsdom')"], cwd=ROOT / "tests", timeout=10,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not have_dom:
            if os.environ.get("REQUIRE_DOM_TESTS"):
                self.fail("Node/jsdom is required for the real DB panel regression")
            self.skipTest("Install development DOM dependency: npm ci --prefix tests")
        result = subprocess.run([node, str(ROOT / "tests/db_inventory_panel_harness.js")],
                                input=json.dumps({"events": events, "reveal_results": reveal_results or {}}),
                                text=True, capture_output=True, cwd=ROOT, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    async def test_ghost_error_adds_the_actual_file_before_stats_and_ignores_stale_info(self):
        before = await self.info()
        path = self.mpath()
        Path(path).touch()  # appeared since the previous panel read
        timeline = copy.deepcopy(self.bridge._get_global_history())
        error = await self.command("db_create", "m")
        after = await self.info()
        snapshots = self.panel([
            {"type": "info", "payload": before},
            {"type": "remember_request"},
            {"type": "create", "name": "m"},
            {"type": "change", "payload": error},
            {"type": "stale_info", "payload": before},
            {"type": "info", "payload": after},
        ])
        for snapshot in snapshots[3:]:
            self.assertEqual([r["name"] for r in snapshot["rows"]], ["b.db", "m.db"])
            conflict = snapshot["rows"][1]
            self.assertIn("Empty file", conflict["detail"])
            self.assertEqual(conflict["buttons"], [])
            self.assertEqual(conflict["filename_tag"], "BUTTON")
            self.assertIn(path, conflict["title"])
            self.assertTrue(snapshot["rows"][0]["buttons"][0]["disabled"])
            self.assertIn("m.db already exists", snapshot["status"])
            self.assertEqual(snapshot["active"], self.path)
        self.assertEqual(self.bridge._get_global_history(), timeline)
        self.assertEqual(self.resets, [])

    async def test_sidecar_error_renders_real_reason_and_click_reveals_the_sidecar_only(self):
        before = await self.info()
        path = self.mpath()
        Path(path + "-wal").write_bytes(b"preserve pending data")
        error = await self.command("db_create", "m")
        with patch("backend.file_reveal.sys.platform", "win32"), \
                patch("backend.file_reveal._start_detached", return_value=True) as start:
            revealed = json.loads(self.bridge.db_reveal(path))
        snapshots = self.panel([
            {"type": "info", "payload": before},
            {"type": "change", "payload": error},
            {"type": "click_name", "path": path},
        ], {path: revealed})
        row = snapshots[1]["rows"][1]
        self.assertIn("Sidecar files only", row["detail"])
        self.assertIn("m.db-wal", row["detail"])
        self.assertIn(path + "-wal", row["title"])
        self.assertEqual(snapshots[-1]["calls"][-1], ["db_reveal", path])
        self.assertFalse(any(c[0] == "db_load" for c in snapshots[-1]["calls"]))
        start.assert_called_once_with("explorer.exe", ["/select,", ntpath.normpath(path + "-wal")])
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.resets, [])
        self.assertEqual(self.manager.active_path(), self.path)

    async def test_create_delete_recreate_snapshots_render_without_waiting_for_info(self):
        before = await self.info()
        made = await self.command("db_create", "m")
        deleted = await self.command("db_delete", made["path"])
        again = await self.command("db_create", "m")
        snapshots = self.panel([
            {"type": "info", "payload": before},
            {"type": "change", "payload": made},
            {"type": "change", "payload": deleted},
            {"type": "change", "payload": again},
        ])
        self.assertEqual([[r["name"] for r in s["rows"]] for s in snapshots],
                         [["b.db"], ["b.db", "m.db"], ["b.db"], ["b.db", "m.db"]])
        self.assertIn("Click Load", snapshots[-1]["status"])
        self.assertTrue(all(s["active"] == self.path for s in snapshots))
        self.assertEqual(self.resets, [])

    async def test_undo_and_redo_also_publish_authoritative_inventories(self):
        made = await self.command("db_create", "m")
        undone = await self.command("undo")
        redone = await self.command("redo")
        self.assertEqual([i["name"] for i in undone["items"]], ["b.db"])
        self.assertEqual([i["name"] for i in redone["items"]], ["b.db", "m.db"])
        self.assertTrue(self.entry(made["path"], redone["items"])["can_load"])
        self.assertEqual(self.manager.active_path(), self.path)

    async def test_db_list_info_and_error_event_agree(self):
        Path(self.mpath()).write_bytes(b"unknown file")
        changed = await self.command("db_create", "m")
        listed = json.loads(self.bridge.db_list())
        info = await self.info()
        self.assertEqual(changed["items"], listed["items"])
        self.assertEqual(listed["items"], info["items"])
        self.assertEqual(listed["inventory_folder"], self.root)

    async def test_revealing_valid_inactive_database_keeps_connection_collection_and_undo(self):
        path = await self.make("m")
        await self.seed()
        old = self.service.db
        contents = await self.contents()
        timeline = copy.deepcopy(self.bridge._get_global_history())
        with patch("backend.file_reveal.sys.platform", "linux"), \
                patch("backend.file_reveal._open_folder", return_value=True):
            result = json.loads(self.bridge.db_reveal(path))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["reveal_path"], path)
        self.assertIs(self.service.db, old)
        self.assertEqual(await self.contents(), contents)
        self.assertEqual(self.bridge._get_global_history(), timeline)
        self.assertEqual(self.changes, [])
        self.assertEqual(self.resets, [])

    async def test_reveal_rejects_missing_protected_and_unknown_external_paths(self):
        with tempfile.TemporaryDirectory() as outside:
            arbitrary = str(Path(outside, "secret.db"))
            Path(arbitrary).touch()
            with patch("backend.file_reveal.reveal_file") as launch:
                for path in (self.mpath(), self.memory._db_path, arbitrary, "https://example.test/m.db"):
                    self.assertFalse(json.loads(self.bridge.db_reveal(path))["ok"], path)
            launch.assert_not_called()

    async def test_native_reveal_failure_reaches_the_real_panel(self):
        info = await self.info()
        with patch("backend.file_reveal.sys.platform", "linux"), \
                patch("backend.file_reveal._open_folder", return_value=False):
            result = json.loads(self.bridge.db_reveal(self.path))
        self.assertFalse(result["ok"])
        snapshots = self.panel([
            {"type": "info", "payload": info},
            {"type": "click_name", "path": self.path},
        ], {self.path: result})
        self.assertIn("could not be opened", snapshots[-1]["status"])
        self.assertFalse(snapshots[-1]["busy"])
        self.assertEqual(self.resets, [])


if __name__ == "__main__":
    unittest.main()
