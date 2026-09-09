"""ONE database file = ONE fully self-contained world.

The unified single-DB contract (docs/DB_CREATION_DELETION_REDESIGN_DESIGN_
2026-09-08.md, phase 1) proven here against REAL SQLite files:

  * a newly created world contains the full v6 schema — all 12 tables, so
    messages, people queue, labels, undo, gaze and per-world settings all
    live in the SAME file (the chat.db/history.db/chatbot.db split is
    over);
  * writes for each world-bound surface (queue, labels, undo, settings)
    land in the world's own file, verified with an independent
    read-only connection — not the service's;
  * the media cache is per world: `<media root>/<world stem>`;
  * two world files carry nothing of each other (strict isolation).

Per AGENT_RULES RULE 8 this drives the REAL HistoryService, UserMemory,
LabelStore and DbManager against real files in a temp folder.

Run with:  python3 tests/test_db_unified_world.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config_manager import ConfigManager  # noqa: E402
from backend.db_manager import DbManager  # noqa: E402
from backend.history_service import HistoryService  # noqa: E402
from backend.label_store import LabelStore  # noqa: E402
from backend.user_memory import UserMemory, UserRecord  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_chat_parser_delta import FakePage, raw  # noqa: E402

#: the full v6 table set — one file, one world
WORLD_TABLES = {
    "app_settings", "cursors", "gaps", "gaze_data", "label_assigns",
    "labels", "media", "messages", "persons", "schema_meta",
    "undo_history", "users",
}


class ConnectedPage(FakePage):
    is_connected = True


class WorldCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        # the media root lives INSIDE the temp dir so per-world folders
        # (saved_media/<stem>) never touch the checkout
        media_cfg = dict(self.cfg.get("history", "media", default={}) or {})
        media_cfg["cache_dir"] = os.path.join(self.dir, "saved_media")
        self.cfg.set("history", "media", media_cfg)
        self.page = ConnectedPage([raw(f"m{i}", idx=i) for i in range(4)])
        self.db_path = os.path.join(self.dir, "history.db")
        # the people queue travels WITH the world file (v6)
        self.memory = UserMemory(self.db_path)
        await self.memory.init()
        self.service = HistoryService(cdp=self.page, config=self.cfg,
                                      db_path=self.db_path, memory=self.memory)
        await self.service.init()
        self.manager = DbManager(config=self.cfg, service=self.service,
                                 root=self.dir)

    async def asyncTearDown(self):
        await self.service.close()
        await self.memory.close()

    async def seed(self, nick="Nick", count=4):
        self.page.partner = nick
        self.page.messages = [raw(f"m{i}", from_nick=nick, idx=i)
                              for i in range(count)]
        await self.service.collector.tick()

    async def read_world(self, path, sql, args=()):
        """An INDEPENDENT read-only view of a world file on disk."""
        import aiosqlite
        async with aiosqlite.connect(f"file:{os.path.abspath(path)}?mode=ro",
                                     uri=True) as conn:
            cur = await conn.execute(sql, args)
            return await cur.fetchall()


class TestUnifiedSchema(WorldCase):
    async def test_a_newly_created_world_has_all_twelve_tables(self):
        made = await self.manager.create("work")
        self.assertTrue(made["ok"], made.get("error"))
        rows = await self.read_world(
            made["path"],
            "SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in rows}
        missing = WORLD_TABLES - tables
        self.assertFalse(missing, f"the new world is missing {missing}")

    async def test_the_new_world_is_a_version_six_file(self):
        made = await self.manager.create("work")
        rows = await self.read_world(
            made["path"],
            "SELECT value FROM schema_meta WHERE key='schema_version'")
        self.assertEqual(rows, [("6",)])

    async def test_the_new_world_is_seeded_from_the_app_template(self):
        made = await self.manager.create("work")
        rows = dict(await self.read_world(
            made["path"], "SELECT key, value FROM app_settings"))
        for key in ("my_nick", "media_max_file_mb",
                    "media_max_cache_mb", "preview"):
            self.assertIn(key, rows,
                          f"a fresh world must be seeded with {key}")


class TestWritesLandInTheWorldFile(WorldCase):
    async def test_queue_rows_land_in_the_world_file(self):
        await self.memory.upsert_user(UserRecord(nick="Ann", registered=True))
        rows = await self.read_world(
            self.db_path, "SELECT nick FROM users WHERE nick='Ann'")
        self.assertEqual(rows, [("Ann",)])
        self.assertEqual(self.memory.db_path, self.db_path,
                         "the queue connection must sit in the world file")

    async def test_the_queue_follows_the_world_on_switch(self):
        await self.memory.upsert_user(UserRecord(nick="Ann"))
        made = await self.manager.create("work")
        self.assertEqual(os.path.abspath(self.memory.db_path),
                         os.path.abspath(made["path"]),
                         "the queue connection must travel with the world")
        beta = await self.read_world(made["path"], "SELECT COUNT(*) FROM users")
        self.assertEqual(beta[0][0], 0, "a new world starts with an empty queue")
        alpha = await self.read_world(self.db_path, "SELECT nick FROM users")
        self.assertEqual([r[0] for r in alpha], ["Ann"],
                         "the world left behind keeps its own people")

    async def test_label_rows_land_in_the_world_tables(self):
        store = LabelStore(self.cfg, db=self.service.db)
        self.service.bind_labels(store)
        label = store.create("VIP", "#ff0000")
        self.assertIsNotNone(label)
        self.assertTrue(store.assign("Ann", label["id"]))
        await store.flush_to_db()
        rows = await self.read_world(self.db_path, "SELECT name FROM labels")
        self.assertEqual([r[0] for r in rows], ["VIP"])
        rows = await self.read_world(
            self.db_path, "SELECT nick, label_id FROM label_assigns")
        self.assertEqual(rows, [("Ann", label["id"])])

    async def test_world_undo_round_trips_through_the_file(self):
        entries = [
            {"seq": 1, "kind": "people", "value": {"before": [],
                                                   "after": []}},
            {"seq": 2, "kind": "archive", "value": {"op": "clear"}},
        ]
        await self.service.save_world_undo(entries)
        rows = await self.read_world(
            self.db_path, "SELECT seq, kind FROM undo_history ORDER BY seq")
        self.assertEqual(rows, [(1, "people"), (2, "archive")])
        loaded = await self.service.load_world_undo()
        self.assertEqual([e["seq"] for e in loaded], [1, 2])
        self.assertEqual(loaded[0]["kind"], "people")
        self.assertEqual(loaded[1]["value"], {"op": "clear"})


class TestPerWorldMedia(WorldCase):
    async def test_every_world_has_its_own_media_folder(self):
        made = await self.manager.create("work")
        self.assertEqual(self.manager.media_dir(),
                         os.path.join(self.dir, "saved_media", "work"))
        self.assertEqual(self.manager.media_dir(self.db_path),
                         os.path.join(self.dir, "saved_media", "history"))
        self.assertEqual(self.service.world_media_dir(),
                         self.manager.media_dir())
        # the live media cache follows the ACTIVE world
        self.assertEqual(os.path.abspath(self.service.media.cache_dir),
                         os.path.abspath(self.manager.media_dir()))

    async def test_the_media_cache_points_back_to_the_right_world(self):
        made = await self.manager.create("work")
        self.assertEqual(os.path.abspath(self.service.media.cache_dir),
                         os.path.abspath(
                             os.path.join(self.dir, "saved_media", "work")))
        back = await self.manager.load(self.db_path)
        self.assertTrue(back["ok"], back.get("error"))
        self.assertEqual(os.path.abspath(self.service.media.cache_dir),
                         os.path.abspath(
                             os.path.join(self.dir, "saved_media", "history")))


class TestStrictIsolation(WorldCase):
    async def test_two_world_files_carry_nothing_of_each_other(self):
        await self.seed("Nick", count=4)
        await self.memory.upsert_user(UserRecord(nick="Ann", registered=True))
        store = LabelStore(self.cfg, db=self.service.db)
        self.service.bind_labels(store)
        label = store.create("VIP", "#ff0000")
        self.assertTrue(store.assign("Ann", label["id"]))
        await store.flush_to_db()
        await self.service.save_world_undo(
            [{"seq": 1, "kind": "people", "value": {"before": [],
                                                    "after": []}}])
        made = await self.manager.create("beta")
        self.assertTrue(made["ok"], made.get("error"))
        # the new world's tables are all empty of the old world's data
        self.assertEqual(
            (await self.read_world(made["path"],
                                   "SELECT COUNT(*) FROM users"))[0][0], 0,
            "no people from the old world in the new file")
        self.assertEqual(
            (await self.read_world(made["path"],
                                   "SELECT COUNT(*) FROM messages"))[0][0], 0,
            "no messages from the old world in the new file")
        self.assertEqual(
            (await self.read_world(made["path"],
                                   "SELECT COUNT(*) FROM labels"))[0][0], 0,
            "no labels from the old world in the new file")
        self.assertEqual(
            (await self.read_world(made["path"],
                                   "SELECT COUNT(*) FROM undo_history"
                                   ))[0][0], 0,
            "no undo from the old world in the new file")
        # and the old world still holds everything, untouched
        self.assertEqual(
            (await self.read_world(self.db_path,
                                   "SELECT COUNT(*) FROM messages"
                                   ))[0][0], 4)
        self.assertEqual(
            [r[0] for r in await self.read_world(
                self.db_path, "SELECT nick FROM users ORDER BY nick")],
            sorted(["Ann"] + ["Nick"]))
        self.assertEqual(
            [r[0] for r in await self.read_world(
                self.db_path, "SELECT name FROM labels")], ["VIP"])

    async def test_no_world_references_the_others_file(self):
        await self.seed("Nick", count=2)
        made = await self.manager.create("beta")
        # neither file may hold a path pointing at the other's database
        for path, other in ((self.db_path, os.path.basename(made["path"])),
                            (made["path"], os.path.basename(self.db_path))):
            rows = await self.read_world(
                path, "SELECT name FROM sqlite_master")
            text = " ".join(str(r) for r in rows)
            self.assertNotIn(other, text,
                             f"{os.path.basename(path)} references {other}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
