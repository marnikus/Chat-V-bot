"""The DB Connection window: create / load / delete / clean, and the sizes.

The promises this proves:

  * **nothing is ever unlinked.** "Delete DB" and "Clean DB" move or copy the
    file into `db_trash/` first, so one Ctrl+Z brings the data back
    (AGENT_RULES RULE 12);
  * **the app stays connected.** Switching databases closes the live handle
    and, if the new file cannot be opened, re-opens the previous one;
  * **the read-out is the truth**: full database size (file + WAL), text size
    and the images-folder size come from the real files on disk;
  * every action is one entry on the ONE global undo timeline.

Per AGENT_RULES RULE 8 this drives the REAL HistoryService and the REAL
Bridge slots against real SQLite files in a temp folder.

Run with:  python3 tests/test_db_manager.py
"""

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject  # noqa: E402

from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from backend.db_manager import (DbManager, file_group_size,  # noqa: E402
                                folder_size, safe_db_name)
from backend.history_service import HistoryService  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_chat_parser_delta import FakePage, raw  # noqa: E402


class ConnectedPage(FakePage):
    is_connected = True


async def wait_for(box, timeout=3.0):
    step, waited = 0.01, 0.0
    while not box and waited < timeout:
        await asyncio.sleep(step)
        waited += step
    return box


# ═════════════════════════════════════════════════════════════════
# pure helpers
# ═════════════════════════════════════════════════════════════════
class TestNameSafety(unittest.TestCase):
    def test_a_plain_name_gets_the_db_suffix(self):
        self.assertEqual(safe_db_name("work"), "work.db")

    def test_an_existing_suffix_is_kept_once(self):
        self.assertEqual(safe_db_name("work.db"), "work.db")

    def test_path_separators_cannot_escape_the_folder(self):
        for hostile in ("../../etc/passwd", "/etc/passwd", "..\\..\\x"):
            self.assertNotIn("/", safe_db_name(hostile))
            self.assertNotIn("\\", safe_db_name(hostile))

    def test_an_empty_name_still_produces_a_file(self):
        self.assertTrue(safe_db_name("   ").endswith(".db"))


class TestSizeHelpers(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_folder_size_counts_bytes_and_files(self):
        os.makedirs(os.path.join(self.dir, "images"))
        for i in range(3):
            with open(os.path.join(self.dir, "images", f"{i}.bin"), "wb") as fh:
                fh.write(b"x" * 100)
        size, files = folder_size(self.dir)
        self.assertEqual(files, 3)
        self.assertEqual(size, 300)

    def test_a_missing_folder_is_zero_not_an_error(self):
        self.assertEqual(folder_size(os.path.join(self.dir, "nope")), (0, 0))

    def test_the_db_size_includes_the_wal_sibling(self):
        path = os.path.join(self.dir, "history.db")
        with open(path, "wb") as fh:
            fh.write(b"a" * 10)
        with open(path + "-wal", "wb") as fh:
            fh.write(b"b" * 5)
        self.assertEqual(file_group_size(path), 15)


# ═════════════════════════════════════════════════════════════════
# the manager against a live archive
# ═════════════════════════════════════════════════════════════════
class DbCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        self.page = ConnectedPage([raw(f"m{i}", idx=i) for i in range(4)])
        self.db_path = os.path.join(self.dir, "history.db")
        self.service = HistoryService(cdp=self.page, config=self.cfg,
                                      db_path=self.db_path)
        await self.service.init()
        self.service.collector.configure(my_nick="Me")
        self.manager = DbManager(config=self.cfg, service=self.service,
                                 root=self.dir)

    async def asyncTearDown(self):
        await self.service.close()

    async def seed(self, nick="Nick", count=4):
        self.page.partner = nick
        self.page.messages = [raw(f"m{i}", from_nick=nick, idx=i)
                              for i in range(count)]
        await self.service.collector.tick()

    async def messages(self):
        rows = await self.service.db.fetchall("SELECT COUNT(*) FROM messages")
        return rows[0][0]


class TestInfo(DbCase):
    async def test_it_reports_the_three_sizes_the_window_shows(self):
        await self.seed()
        info = await self.manager.info()
        self.assertTrue(info["connected"])
        self.assertGreater(info["db_bytes"], 0, "full DB size")
        self.assertGreater(info["text_bytes"], 0, "text size")
        self.assertIn("media_bytes", info, "images folder size")
        self.assertEqual(info["total_bytes"],
                         info["db_bytes"] + info["media_bytes"])

    async def test_the_images_folder_is_measured_on_disk(self):
        media_dir = self.manager.media_dir()
        os.makedirs(os.path.join(media_dir, "Nick", "images"), exist_ok=True)
        with open(os.path.join(media_dir, "Nick", "images", "a.jpg"),
                  "wb") as fh:
            fh.write(b"x" * 2048)
        info = await self.manager.info()
        self.assertEqual(info["media_files"], 1)
        self.assertEqual(info["media_bytes"], 2048)

    async def test_the_counts_match_the_archive(self):
        await self.seed(count=4)
        info = await self.manager.info()
        self.assertEqual(info["messages"], 4)
        self.assertEqual(info["persons"], 1)

    async def test_the_list_marks_the_connected_file(self):
        items = self.manager.list_dbs()
        self.assertTrue(items, "the active file must always be listed")
        self.assertTrue(items[0]["active"])
        self.assertEqual(items[0]["path"], self.db_path)


class TestLifecycle(DbCase):
    async def test_create_makes_a_new_empty_database_and_connects(self):
        await self.seed()
        result = await self.manager.create("work")
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(os.path.exists(result["path"]))
        self.assertEqual(await self.messages(), 0, "a new DB starts empty")
        self.assertEqual(self.manager.active_path(), result["path"])

    async def test_create_refuses_to_overwrite(self):
        first = await self.manager.create("work")
        again = await self.manager.create("work")
        self.assertTrue(first["ok"])
        self.assertFalse(again["ok"])
        self.assertIn("exists", again["error"])

    async def test_load_switches_back_with_the_data_intact(self):
        await self.seed(count=4)
        made = await self.manager.create("work")
        self.assertEqual(await self.messages(), 0)
        back = await self.manager.load(self.db_path)
        self.assertTrue(back["ok"], back.get("error"))
        self.assertEqual(await self.messages(), 4,
                         "the original database still holds its messages")
        self.assertNotEqual(made["path"], self.manager.active_path())

    async def test_loading_a_missing_file_changes_nothing(self):
        before = self.manager.active_path()
        result = await self.manager.load(os.path.join(self.dir, "ghost.db"))
        self.assertFalse(result["ok"])
        self.assertEqual(self.manager.active_path(), before)
        self.assertTrue(self.service.db.is_open, "we stay connected")

    async def test_the_chosen_database_is_remembered_in_the_config(self):
        made = await self.manager.create("work")
        self.assertEqual(self.cfg.get("history", "db_path"), made["path"])

    async def test_delete_moves_the_file_to_the_trash(self):
        made = await self.manager.create("work")
        await self.manager.load(self.db_path)
        result = await self.manager.delete(made["path"])
        self.assertTrue(result["ok"], result.get("error"))
        self.assertFalse(os.path.exists(made["path"]))
        self.assertTrue(os.path.exists(result["backup"]),
                        "the file must survive inside db_trash")
        self.assertTrue(result["backup"].startswith(self.manager.trash_dir()))

    async def test_deleting_the_connected_database_reconnects_elsewhere(self):
        await self.seed()
        other = await self.manager.create("work")     # now connected to work
        result = await self.manager.delete(other["path"])
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(self.service.db.is_open,
                        "the app must never end up without a database")
        self.assertNotEqual(self.manager.active_path(), other["path"])

    async def test_a_deleted_database_can_be_restored(self):
        made = await self.manager.create("work")
        await self.manager.load(self.db_path)
        deleted = await self.manager.delete(made["path"])
        restored = await self.manager.restore_backup(deleted["backup"],
                                                     made["path"])
        self.assertTrue(restored["ok"], restored.get("error"))
        self.assertTrue(os.path.exists(made["path"]))

    async def test_clean_empties_the_tables_but_keeps_the_file(self):
        await self.seed(count=4)
        result = await self.manager.clean()
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(os.path.exists(self.db_path), "the file stays")
        self.assertEqual(await self.messages(), 0)
        persons = await self.service.db.fetchall("SELECT COUNT(*) FROM persons")
        self.assertEqual(persons[0][0], 0)

    async def test_clean_keeps_a_full_backup_in_the_trash(self):
        await self.seed(count=4)
        result = await self.manager.clean()
        self.assertTrue(os.path.exists(result["backup"]))
        restored = await self.manager.restore_backup(result["backup"],
                                                     self.db_path)
        self.assertTrue(restored["ok"], restored.get("error"))
        self.assertEqual(await self.messages(), 4,
                         "cleaning must be reversible")

    async def test_the_archive_keeps_working_after_a_switch(self):
        await self.seed(count=4)
        await self.manager.create("work")
        await self.seed(nick="Other", count=2)
        self.assertEqual(await self.messages(), 2,
                         "collecting continues into the new database")


class TestSwitchFailsClosed(DbCase):
    async def test_a_broken_target_leaves_the_old_database_open(self):
        await self.seed(count=4)
        broken = os.path.join(self.dir, "broken.db")
        with open(broken, "wb") as fh:
            fh.write(b"this is definitely not a sqlite file" * 10)
        result = await self.manager.load(broken)
        self.assertFalse(result.get("ok"), "a corrupt file must be refused")
        self.assertTrue(self.service.db.is_open)
        self.assertEqual(await self.messages(), 4,
                         "the previous database is still the live one")


# ═════════════════════════════════════════════════════════════════
# the bridge slots + undo
# ═════════════════════════════════════════════════════════════════
class TestDbBridge(DbCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        br = Bridge.__new__(Bridge)
        QObject.__init__(br)
        br._config = self.cfg
        br._engine = types.SimpleNamespace(load_stack=lambda _b: None)
        br._memory = None
        br._presets = None
        br._dbs = self.manager
        br.attach_history(self.service)
        self.bridge = br
        self.changes = []
        br.db_changed.connect(lambda p: self.changes.append(json.loads(p)))

    async def test_db_info_answers_on_the_request_id(self):
        box = []
        self.bridge.db_info_ready.connect(lambda *a: box.append(a))
        self.bridge.db_info("i1")
        await wait_for(box)
        req, payload = box[-1]
        self.assertEqual(req, "i1")
        data = json.loads(payload)
        self.assertIn("total_bytes", data)
        self.assertIn("items", data)

    async def test_db_list_names_the_active_database(self):
        data = json.loads(self.bridge.db_list())
        self.assertEqual(data["active"], self.db_path)

    async def test_create_is_one_undo_step(self):
        self.assertTrue(self.bridge.db_create("work"))
        await wait_for(self.changes)
        history, index = self.bridge._get_global_history()
        self.assertEqual([e["kind"] for e in history], ["dbconn"])
        self.assertEqual(index, 0)
        self.assertEqual(history[0]["value"]["op"], "create")

    async def test_undoing_a_load_reconnects_the_previous_database(self):
        await self.seed(count=4)
        self.assertTrue(self.bridge.db_create("work"))
        await wait_for(self.changes)
        self.assertEqual(await self.messages(), 0)
        result = json.loads(self.bridge.undo())
        self.assertEqual(result["kind"], "dbconn")
        self.changes.clear()
        await wait_for(self.changes)
        self.assertEqual(self.manager.active_path(), self.db_path)
        self.assertEqual(await self.messages(), 4)

    async def test_undoing_a_clean_brings_the_messages_back(self):
        await self.seed(count=4)
        self.assertTrue(self.bridge.db_clean())
        await wait_for(self.changes)
        self.assertEqual(await self.messages(), 0)
        self.changes.clear()
        self.bridge.undo()
        await wait_for(self.changes)
        self.assertEqual(await self.messages(), 4,
                         "Ctrl+Z must restore a cleaned database")

    async def test_undoing_a_delete_puts_the_file_back(self):
        made = await self.manager.create("work")
        await self.manager.load(self.db_path)
        self.assertTrue(self.bridge.db_delete(made["path"]))
        await wait_for(self.changes)
        self.assertFalse(os.path.exists(made["path"]))
        self.changes.clear()
        self.bridge.undo()
        await wait_for(self.changes)
        self.assertTrue(os.path.exists(made["path"]),
                        "Ctrl+Z must bring the database file back")

    async def test_a_failed_action_is_not_recorded(self):
        self.bridge.db_load(os.path.join(self.dir, "ghost.db"))
        await asyncio.sleep(0.2)
        history, _index = self.bridge._get_global_history()
        self.assertEqual(history, [], "a refused action is not an undo step")


class TestUiWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = os.path.join(os.path.dirname(__file__), "..", "ui")
        with open(os.path.join(base, "index.html"), encoding="utf-8") as fh:
            cls.html = fh.read()
        with open(os.path.join(base, "js", "db-panel.js"), encoding="utf-8") as fh:
            cls.js = fh.read()

    def test_db_connection_is_a_normal_grid_window(self):
        self.assertIn('data-window="dbconn"', self.html)
        self.assertIn('id="winDbconn"', self.html)

    def test_it_offers_the_four_actions(self):
        for anchor in ("dbCreateBtn", "dbCleanBtn", "dbFileList",
                       "dbNewNameInput"):
            self.assertIn(anchor, self.html, anchor + " is missing")
        for call in ("db_create", "db_load", "db_delete", "db_clean"):
            self.assertIn(call, self.js, call + " is not wired")

    def test_it_shows_the_three_sizes(self):
        self.assertIn("Full DB size", self.js)
        self.assertIn("Text size", self.js)
        self.assertIn("Images folder", self.js)

    def test_destructive_actions_are_confirmed_and_explained(self):
        self.assertIn("PresetsUI.confirm", self.js)
        self.assertIn("db_trash", self.js)


if __name__ == "__main__":
    unittest.main(verbosity=2)
