"""A world switch is a FULL restart — nothing from the old world survives.

Phase 3 of the redesign (docs/DB_CREATION_DELETION_REDESIGN_DESIGN_2026-
09-08.md, D7): creating/loading/switching databases must restart every
world-bound surface fresh, so no stale data from world A can ever be seen
from world B — and world A must come back exactly as it was left:

  * no people-queue bleed in either direction (the queue connection
    travels with the file);
  * no message bleed;
  * labels reload from the switched-into world's own tables;
  * the volatile radar/collector state (partner, counters, collected
    markers) is wiped, then the new world's own persistent state loaded;
  * per-world settings follow the world — the switched-into world applies
    its OWN stored settings, and the world left behind gets its back;
  * a switch that cannot open the new file re-opens the previous one
    (fail closed) — the app is never left without a world, and never with
    a mix of two;
  * the undo timeline is world-bound: world A's entries are invisible
    from world B and come back with A (one global timeline, split by
    ownership), and the UI is told a world switched via
    `db_changed` + `switched: true`.

Per AGENT_RULES RULE 8 this drives the REAL HistoryService, UserMemory,
LabelStore and Bridge against real SQLite files in a temp folder.

Run with:  python3 tests/test_db_switch_restart.py
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
from backend.db_manager import DbManager  # noqa: E402
from backend.history_service import HistoryService  # noqa: E402
from backend.label_store import LabelStore  # noqa: E402
from backend.user_memory import UserMemory, UserRecord  # noqa: E402

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


class RestartCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        media_cfg = dict(self.cfg.get("history", "media", default={}) or {})
        media_cfg["cache_dir"] = os.path.join(self.dir, "saved_media")
        self.cfg.set("history", "media", media_cfg)
        self.page = ConnectedPage([raw(f"m{i}", idx=i) for i in range(4)])
        self.db_path = os.path.join(self.dir, "history.db")
        self.memory = UserMemory(self.db_path)
        await self.memory.init()
        self.service = HistoryService(cdp=self.page, config=self.cfg,
                                      db_path=self.db_path, memory=self.memory)
        self.store = LabelStore(self.cfg, db=self.service.db)
        self.service.bind_labels(self.store)
        await self.service.init()
        self.manager = DbManager(config=self.cfg, service=self.service,
                                 root=self.dir)

    async def asyncTearDown(self):
        await self.service.close()
        await self.memory.close()

    async def seed(self, nick="Nick", count=4, user="Ann"):
        self.page.partner = nick
        self.page.messages = [raw(f"m{i}", from_nick=nick, idx=i)
                              for i in range(count)]
        await self.service.collector.tick()
        await self.memory.upsert_user(UserRecord(nick=user, registered=True))

    async def count_messages(self):
        rows = await self.service.db.fetchall(
            "SELECT COUNT(*) FROM messages WHERE deleted_at=''")
        return rows[0][0]

    async def write_setting(self, key, value):
        """Persist one per-world setting straight into the world file."""
        await self.service.db.execute(
            "INSERT INTO app_settings(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value), ""))
        await self.service.db.commit()


class TestNoBleed(RestartCase):
    async def test_no_people_bleed_between_worlds(self):
        await self.seed(user="Ann")
        made = await self.manager.create("work")
        self.assertTrue(made["ok"], made.get("error"))
        self.assertEqual(await self.memory.get_all(), [],
                         "the new world must start with an empty queue")
        # write a person into world B…
        await self.memory.upsert_user(UserRecord(nick="Bob"))
        back = await self.manager.load(self.db_path)
        self.assertTrue(back["ok"], back.get("error"))
        nicks = {u.nick for u in await self.memory.get_all()}
        self.assertIn("Ann", nicks,
                      "the old world comes back with its own people")
        self.assertNotIn("Bob", nicks,
                         "a person made in world B must not appear in A")

    async def test_no_messages_bleed_between_worlds(self):
        await self.seed(count=4)
        made = await self.manager.create("work")
        self.assertEqual(await self.count_messages(), 0,
                         "world B starts with no messages from A")
        back = await self.manager.load(self.db_path)
        self.assertEqual(await self.count_messages(), 4,
                         "world A still holds its messages after the round trip")

    async def test_labels_reload_per_world(self):
        label = self.store.create("VIP", "#ff0000")
        self.assertTrue(self.store.assign("Ann", label["id"]))
        await self.store.flush_to_db()
        made = await self.manager.create("work")
        self.assertEqual(self.store.defs(), [],
                         "world B has no labels of its own yet")
        back = await self.manager.load(self.db_path)
        self.assertTrue(back["ok"], back.get("error"))
        self.assertEqual([d["id"] for d in self.store.defs()],
                         [label["id"]],
                         "world A's labels come back with world A")
        self.assertEqual(self.store.ids_for("Ann"), [label["id"]])


class TestRadarReset(RestartCase):
    async def test_switching_forgets_everything_about_the_old_conversation(self):
        await self.seed(count=4)
        self.assertEqual(self.service.collector._nick, "Nick",
                         "the old world had a live partner")
        self.assertGreater(self.service.collector._total, 0)
        self.assertGreater(self.service.collector._added, 0)
        made = await self.manager.create("work")
        self.assertTrue(made["ok"], made.get("error"))
        collector = self.service.collector
        self.assertEqual(collector._nick, "",
                         "the old partner must not survive a world switch")
        self.assertEqual(collector._total, 0,
                         "session totals are per-conversation, not per-app")
        self.assertEqual(collector._added, 0,
                         "the 'already collected' markers reset with the world")
        self.assertEqual(collector._verified, False,
                         "the private-chat gate is re-verified per world")

    async def test_the_old_world_is_unchanged_after_the_round_trip(self):
        await self.seed(count=4, user="Ann")
        label = self.store.create("VIP", "#ff0000")
        self.assertTrue(self.store.assign("Ann", label["id"]))
        await self.store.flush_to_db()
        made = await self.manager.create("work")
        back = await self.manager.load(self.db_path)
        self.assertTrue(back["ok"], back.get("error"))
        self.assertEqual(await self.count_messages(), 4)
        nicks = {u.nick for u in await self.memory.get_all()}
        self.assertIn("Ann", nicks)
        self.assertEqual([d["id"] for d in self.store.defs()], [label["id"]])


class TestSettingsFollowTheWorld(RestartCase):
    async def test_per_world_settings_do_not_bleed(self):
        await self.write_setting("media_max_cache_mb", 77)   # world A's own
        made = await self.manager.create("work")
        self.assertTrue(made["ok"], made.get("error"))
        self.assertEqual(
            self.service.media.max_cache_bytes, 200 * 1024 * 1024,
            "world B is seeded from the app template — NOT from A's 77")
        await self.write_setting("media_max_cache_mb", 11)   # world B's own
        back = await self.manager.load(self.db_path)
        self.assertEqual(
            self.service.media.max_cache_bytes, 77 * 1024 * 1024,
            "switching back into A applies A's own stored setting")
        again = await self.manager.load(made["path"])
        self.assertEqual(
            self.service.media.max_cache_bytes, 11 * 1024 * 1024,
            "B's setting follows B, not whatever world was active before")


class TestFailClosed(RestartCase):
    async def test_a_broken_file_cannot_leave_the_app_without_a_world(self):
        await self.seed(count=4, user="Ann")
        broken = os.path.join(self.dir, "broken.db")
        with open(broken, "wb") as fh:
            fh.write(b"this is definitely not a sqlite database" * 8)
        with self.assertRaises(Exception):
            await self.service.switch_db(broken)
        self.assertTrue(self.service.db.is_open,
                        "the previous world must be re-opened after a failed swap")
        self.assertEqual(os.path.abspath(self.service.db.path),
                         os.path.abspath(self.db_path))
        self.assertEqual(os.path.abspath(self.memory.db_path),
                         os.path.abspath(self.db_path),
                         "the queue connection comes back with the world")
        self.assertEqual(await self.count_messages(), 4,
                         "the old world's data is untouched by the failed swap")
        self.assertIn("Ann", {u.nick for u in await self.memory.get_all()})

    async def test_a_failed_switch_does_not_mix_the_two_worlds(self):
        await self.seed(count=4, user="Ann")
        other = os.path.join(self.dir, "other.db")
        probe = HistoryService(cdp=ConnectedPage([]), config=None,
                               db_path=other)
        await probe.init()                      # a perfectly good world B
        await probe.close()
        with open(other, "r+b") as fh:          # now corrupt its header
            fh.write(b"not-sqlite" + b"\x00" * 90)
        with self.assertRaises(Exception):
            await self.service.switch_db(other)
        # nothing from B may have leaked into A, and A is fully live
        self.assertEqual(await self.count_messages(), 4)
        self.assertIn("Ann", {u.nick for u in await self.memory.get_all()})


class TestUndoNeverCrossesAWorldSwitch(RestartCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        br = Bridge.__new__(Bridge)
        QObject.__init__(br)
        br._config = self.cfg
        br._engine = types.SimpleNamespace(load_stack=lambda _b: None)
        br._memory = self.memory
        br._presets = None
        br._dbs = self.manager
        br._labels = self.store
        br.attach_history(self.service)
        self.bridge = br
        self.changes = []
        br.db_changed.connect(lambda p: self.changes.append(json.loads(p)))

    async def drain_world_undo(self):
        """Wait until every scheduled world-undo save has hit the file."""
        for _ in range(300):
            if not getattr(self.bridge, "_undo_pendings", None):
                return
            await asyncio.sleep(0.01)
        self.fail("a world undo save never finished")

    async def bridge_load(self, path):
        """Switch through the BRIDGE: pushes the undo step, rebuilds the
        timeline and signals the UI with `switched: true`."""
        self.changes.clear()
        self.assertTrue(self.bridge.db_load(path))
        await wait_for(self.changes)
        self.assertTrue(self.changes, "a world switch must signal the UI")
        return self.changes[-1]

    async def test_world_undo_is_invisible_from_the_other_world(self):
        await self.seed(count=4, user="Ann")
        made = await self.manager.create("work")
        self.assertTrue(made["ok"], made.get("error"))
        # back into A through the bridge (world A is now "the other world")
        await self.bridge_load(self.db_path)
        people = {"before": [],
                  "after": [{"nick": "Ann", "gender": "unknown",
                             "registered": True, "messaged": False}]}
        self.bridge._push_global("people", people)
        await self.drain_world_undo()
        loaded = await self.service.load_world_undo()
        self.assertIn("people", [e["kind"] for e in loaded],
                      "world A's undo entry lives in A's own file")

        change = await self.bridge_load(made["path"])
        self.assertTrue(change.get("switched"),
                        "the payload must say a FRESH world is live")
        history, _index = self.bridge._get_global_history()
        self.assertNotIn("people", [e["kind"] for e in history],
                         "world A's undo must be invisible from world B")

        await self.bridge_load(self.db_path)
        history, _index = self.bridge._get_global_history()
        self.assertIn("people", [e["kind"] for e in history],
                      "world A's undo comes back when A comes back")
        entry = [e for e in history if e["kind"] == "people"][0]
        self.assertEqual(entry["value"], people)

    async def test_app_level_undo_survives_the_switch(self):
        # stack entries are APP data, not world data — they must survive
        self.bridge._push_global("stack", {"layout": "a"})
        await self.drain_world_undo()
        made = await self.manager.create("work")
        self.assertTrue(made["ok"], made.get("error"))
        await self.bridge_load(self.db_path)
        history, _index = self.bridge._get_global_history()
        self.assertIn("stack", [e["kind"] for e in history],
                      "app-level undo survives a world switch (into A)")
        await self.bridge_load(made["path"])
        history, _index = self.bridge._get_global_history()
        self.assertIn("stack", [e["kind"] for e in history],
                      "app-level undo survives a world switch (into B)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
