"""services/history_service — the world owner: settings, world state,
migration, gaze, world-undo table, fail-closed `switch_db`.

HistoryService is driven against a REAL HistoryDB/HistoryRepo and a REAL
ConfigManager in temp dirs (AGENT_RULES RULE 8); only CDP is faked
(FakePage). The read paths (page/search/stats) are already covered by
tests/test_history_query.py — here we cover the SERVICE seams.

Run with:  python3 tests/integration/services/test_services_history.py
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from backend.config_manager import ConfigManager  # noqa: E402
from backend.history_models import MessageRecord, fingerprint  # noqa: E402
from services.history import (HistoryService,  # noqa: E402
                                      HISTORY_DEFAULTS, MAX_FILE_MB_DEFAULT,
                                      OLD_MAX_FILE_MB, _merge, _db_stem)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "tests"))
from test_chat_parser_delta import FakePage, raw  # noqa: E402

NOW = datetime(2026, 9, 6, 18, 30, 0)


def rec(text="hi", direction="in", from_nick="Nick", time="17:31"):
    return MessageRecord(
        fp=fingerprint(direction, from_nick, time, "text", text, 0),
        direction=direction, from_nick=from_nick, kind="text", text=text,
        media_url="", media_kind="", ts_display=time, occ=0, idx=0)


class AddBindingCdp:
    """FakePage + the binding surface HistoryService.init() probes."""

    def __init__(self, *args, **kw):
        self.page = FakePage(*args, **kw)
        self.binding_installs = []
        self.events = {}

    def __getattr__(self, name):
        return getattr(self.page, name)

    async def add_binding(self, name):
        self.binding_installs.append(name)
        return True

    def on_event(self, method, callback):
        self.events[method] = callback


class ServiceCase(unittest.IsolatedAsyncioTestCase):
    USE_FTS = True

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        media_cfg = dict(self.cfg.get("history", "media", default={}) or {})
        media_cfg["cache_dir"] = os.path.join(self.dir, "saved_media")
        self.cfg.set("history", "media", media_cfg)
        self.page = AddBindingCdp([raw(f"m{i}", idx=i) for i in range(4)])
        self.db_path = os.path.join(self.dir, "history.db")
        self.service = HistoryService(cdp=self.page, config=self.cfg,
                                      db_path=self.db_path)
        await self.service.init()

    async def asyncTearDown(self):
        await self.service.close()

    async def seed_messages(self, nick="Nick", n=6, my_nick="Me"):
        batch = [rec(text=f"line {i}", direction="in" if i % 2 else "out",
                     from_nick=my_nick if i % 2 else nick,
                     time=f"1{i}:0{i}") for i in range(n)]
        await self.service.repo.append(nick, batch, my_nick=my_nick, now=NOW)

    async def world_undo_rows(self):
        if not self.service.db.is_open:
            return []
        rows = await self.service.db.fetchall(
            "SELECT seq, kind, value FROM undo_history ORDER BY seq")
        return rows


class TestSettings(ServiceCase):
    async def test_defaults_merge_with_stored(self):
        self.assertEqual(self.service.enabled, True)
        settings = self.service.settings()
        self.assertEqual(settings["db_path"], self.db_path)
        self.assertEqual(settings["media"]["max_file_mb"], MAX_FILE_MB_DEFAULT)
        self.assertIn("collector", settings)
        self.assertEqual(settings["fts"], self.service.db.fts_enabled)

    async def test_stored_values_override_defaults(self):
        cfg = ConfigManager(os.path.join(self.dir, "cfg2.json"))
        cfg.set("history", {"enabled": False, "media": {"max_file_mb": 50}})
        service = HistoryService(cdp=self.page, config=cfg,
                                 db_path=os.path.join(self.dir, "h2.db"))
        await service.init()
        self.assertFalse(service.enabled)
        self.assertEqual(service.settings()["media"]["max_file_mb"], 50)
        await service.close()

    async def test_old_2mb_cap_is_migrated_up(self):
        cfg = ConfigManager(os.path.join(self.dir, "cfg3.json"))
        cfg.set("history", {"media": {"max_file_mb": OLD_MAX_FILE_MB}})
        service = HistoryService(cdp=self.page, config=cfg,
                                 db_path=os.path.join(self.dir, "h3.db"))
        await service.init()
        self.assertEqual(service.settings()["media"]["max_file_mb"],
                         MAX_FILE_MB_DEFAULT)
        await service.close()

    async def test_larger_cap_is_kept(self):
        cfg = ConfigManager(os.path.join(self.dir, "cfg4.json"))
        cfg.set("history", {"media": {"max_file_mb": 44}})
        service = HistoryService(cdp=self.page, config=cfg,
                                 db_path=os.path.join(self.dir, "h4.db"))
        await service.init()
        self.assertEqual(service.settings()["media"]["max_file_mb"], 44)
        await service.close()

    async def test_apply_settings_live_and_persists(self):
        before = self.service.media.max_file_bytes
        settings = self.service.apply_settings({
            "media": {"max_file_mb": 30},
            "preview": {"page_size": 99},
            "collector": {"heartbeat_ms": 2222},
        })
        self.assertEqual(settings["media"]["max_file_mb"], 30)
        self.assertEqual(settings["preview"]["page_size"], 99)
        self.assertEqual(self.service.media.max_file_bytes,
                         30 * 1024 * 1024)
        self.assertGreater(self.service.media.max_file_bytes, before)
        self.assertEqual(self.service.collector.settings()["heartbeat_ms"],
                         2222)
        stored = self.cfg.get("history", default={})
        self.assertEqual(stored["media"]["max_file_mb"], 30)
        # per-world half is written to the open database (async task)
        await asyncio.sleep(0.05)
        rows = await self.service.db.fetchdicts(
            "SELECT key, value FROM app_settings")
        data = {r["key"]: r["value"] for r in rows}
        self.assertEqual(json.loads(data["media_max_file_mb"]), 30)
        self.assertEqual(json.loads(data["preview"])["page_size"], 99)

    async def test_set_my_nick_trims_and_persists(self):
        clean = self.service.set_my_nick("  Аня  Ивановна  ")
        self.assertEqual(clean, "Аня Ивановна")
        self.assertEqual(self.service.my_nick, "Аня Ивановна")
        await asyncio.sleep(0.05)   # let the async app_settings write land
        rows = await self.service.db.fetchdicts(
            "SELECT key, value FROM app_settings")
        data = {r["key"]: r["value"] for r in rows}
        self.assertEqual(json.loads(data["my_nick"]), "Аня Ивановна")


class TestWorldSettings(ServiceCase):
    async def test_seed_fills_missing_keys_only(self):
        self.service.collector.configure(my_nick="SeedMe")
        await self.service.seed_app_settings()
        rows = await self.service.db.fetchdicts(
            "SELECT key, value FROM app_settings")
        data = {r["key"]: r["value"] for r in rows}
        self.assertEqual(json.loads(data["my_nick"]), "SeedMe")
        # seed again with different values — existing keys are untouched
        self.service.set_my_nick("Changed")
        await asyncio.sleep(0.05)   # let the async app_settings write land
        await self.service.seed_app_settings()
        rows = await self.service.db.fetchdicts(
            "SELECT key, value FROM app_settings")
        data = {r["key"]: r["value"] for r in rows}
        self.assertEqual(json.loads(data["my_nick"]), "Changed")

    async def test_load_app_settings_world_wins_over_template(self):
        self.service.set_my_nick("WorldNick")
        await asyncio.sleep(0.05)   # let the async app_settings write land
        await self.service.db.commit()
        # a NEW service on the same world must restore the world's nick
        service2 = HistoryService(cdp=self.page, config=self.cfg,
                                  db_path=self.db_path)
        await service2.init()
        self.assertEqual(service2.my_nick, "WorldNick")
        await service2.close()

    async def test_malformed_world_settings_are_ignored(self):
        await self.service.db.execute(
            "INSERT INTO app_settings(key, value, updated_at) "
            "VALUES('my_nick', '{broken', '2026-01-01')")
        await self.service.db.execute(
            "INSERT INTO app_settings(key, value, updated_at) "
            "VALUES('media_max_file_mb', 'NaN', '2026-01-01')")
        await self.service.db.commit()
        # reload — must not raise and must keep defaults
        service2 = HistoryService(cdp=self.page, config=self.cfg,
                                  db_path=self.db_path)
        await service2.init()
        self.assertNotEqual(service2.my_nick, None)
        await service2.close()


class TestMediaDirs(ServiceCase):
    def test_world_media_dir_uses_the_db_stem(self):
        base = self.service.media_base_dir()
        self.assertEqual(base, os.path.join(self.dir, "saved_media"))
        self.assertEqual(self.service.world_media_dir(),
                         os.path.join(base, "history"))
        self.assertEqual(self.service.world_media_dir("/x/work.db"),
                         os.path.join(base, "work"))

    def test_db_stem_helpers(self):
        self.assertEqual(_db_stem("work.db"), "work")
        self.assertEqual(_db_stem("/a/b/my world 2.db"), "my_world_2")
        self.assertEqual(_db_stem(""), "world")

    def test_merge_is_deep(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        out = _merge(base, {"a": {"y": 9}, "c": 4})
        self.assertEqual(out["a"], {"x": 1, "y": 9})
        self.assertEqual(out["c"], 4)
        self.assertEqual(base["a"]["y"], 2, "base must not be mutated")


class TestGaze(ServiceCase):
    async def test_save_load_round_trip(self):
        self.service.collector._nick = "Partner"
        self.service.collector._added = 7
        self.service.collector._total = 40
        self.service.collector._last_sync_reason = "scroll"
        self.service.collector._last_sync_added = 2
        self.service.collector._last_sync_count = 3
        await self.service.save_gaze()

        service2 = HistoryService(cdp=self.page, config=self.cfg,
                                  db_path=self.db_path)
        await service2.init()
        self.assertEqual(service2.collector._nick, "Partner")
        self.assertEqual(service2.collector._added, 7)
        self.assertEqual(service2.collector._total, 40)
        self.assertEqual(service2.collector._last_sync_reason, "scroll")
        # the verified private-chat gate fails closed: not restored
        self.assertFalse(service2.collector._verified)
        await service2.close()

    async def test_save_with_no_partner_is_a_noop(self):
        self.service.collector._nick = ""
        await self.service.save_gaze()
        rows = await self.service.db.fetchall("SELECT COUNT(*) FROM gaze_data")
        self.assertEqual(rows[0][0], 0)

    async def test_load_empty_table_is_idempotent(self):
        await self.service.load_gaze()
        self.assertEqual(self.service.collector._nick, "")


class TestMigration(ServiceCase):
    async def test_clean_install_is_idempotent(self):
        report = await self.service.migrate_install()
        self.assertFalse(any(report.values()), report)
        report2 = await self.service.migrate_install()
        self.assertFalse(any(report2.values()))

    async def test_prunes_ghost_recent_paths(self):
        self.cfg.set_state(db_recent=[os.path.join(self.dir, "gone.db"),
                                      self.db_path])
        service2 = HistoryService(cdp=self.page, config=self.cfg,
                                  db_path=self.db_path)
        await service2.db.init()      # NOT full init: init() runs migrate_install
        report = await service2.migrate_install()
        self.assertTrue(report["recent_pruned"])
        recent = self.cfg.get_state("db_recent", [])
        self.assertEqual(recent, [self.db_path])
        # second run is a no-op (the ghost is already gone)
        self.assertFalse((await service2.migrate_install())["recent_pruned"])
        await service2.db.close()

    async def test_rehomes_world_undo_entries(self):
        self.cfg.set_state(undo_history=[
            {"kind": "stack", "value": [{"block_id": "PAUSE"}]},
            {"kind": "people", "value": {"before": [], "after": []}, "seq": 2},
        ])
        report = await self.service.migrate_install()
        self.assertTrue(report["undo_rehomed"])
        rows = await self.world_undo_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "people")
        left = self.cfg.get_state("undo_history", [])
        self.assertEqual([e["kind"] for e in left], ["stack"],
                         "config keeps the app half only")
        # second run: flag set → no double work
        report2 = await self.service.migrate_install()
        self.assertFalse(report2["undo_rehomed"])
        self.assertEqual(len(await self.world_undo_rows()), 1)

    async def test_merges_a_legacy_queue_file(self):
        import aiosqlite
        legacy = os.path.join(self.dir, "chatbot.db")
        async with aiosqlite.connect(legacy) as src:
            await src.execute(
                "CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "nick TEXT, gender TEXT, registered INT, "
                "anonymous INT, guest INT, first_seen TEXT, last_seen TEXT, "
                "messaged INT, message_count INT, last_messaged TEXT, notes TEXT)")
            await src.execute(
                "INSERT INTO users(nick, gender, registered, anonymous, guest, "
                "first_seen, last_seen, messaged, message_count, "
                "last_messaged, notes) "
                "VALUES('Old', 'male', 0, 0, 0, "
                "'2026-01-01', '2026-01-02', 1, 3, NULL, 'note')")
            await src.commit()
        from stores.user_memory import UserMemory, UserRecord
        memory = UserMemory(legacy)
        await memory.init()
        await memory.upsert_user(UserRecord(nick="New"))
        service2 = HistoryService(cdp=self.page, config=self.cfg,
                                  db_path=self.db_path)
        service2.memory = memory
        await service2.init()          # init() runs migrate_install()
        # world row wins on conflict; legacy-only row added; file renamed
        rows = await service2.memory.get_all()
        nicks = {u.nick for u in rows}
        self.assertEqual(nicks, {"New", "Old"})
        legacy_files = [f for f in os.listdir(self.dir)
                        if f.startswith("chatbot.db.migrated-")]
        self.assertTrue(legacy_files, "legacy file must be renamed out")
        # a second migrate has nothing left to merge
        self.assertFalse((await service2.migrate_install())["queue_merged"])
        await service2.close()


class TestWorldUndo(ServiceCase):
    async def test_save_world_undo_is_transactional_and_ordered(self):
        await self.service.save_world_undo([
            {"seq": 2, "kind": "grid", "value": {"v": 2}},
            {"seq": 1, "kind": "stack", "value": []},
        ])
        rows = await self.world_undo_rows()
        self.assertEqual([r[0] for r in rows], [1, 2])
        self.assertEqual(rows[0][1], "stack")
        # saved on a closed db is a no-op, not a crash
        await self.service.db.close()
        await self.service.save_world_undo([{"seq": 9, "kind": "x", "value": {}}])

    async def test_load_world_undo_skips_corrupt_rows(self):
        await self.service.db.execute(
            "INSERT INTO undo_history(seq, kind, value, created_at) "
            "VALUES(1,'stack','[]','2026-01-01')")
        await self.service.db.execute(
            "INSERT INTO undo_history(seq, kind, value, created_at) "
            "VALUES(2,'people','{bad json','2026-01-01')")
        await self.service.db.commit()
        entries = await self.service.load_world_undo()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "stack")


class TestConvenience(ServiceCase):
    async def test_page_wrapper_carries_stats_and_my_nick(self):
        await self.seed_messages()
        self.service.set_my_nick("Me")
        await asyncio.sleep(0)   # let the async app_settings write land
        page = await self.service.page("Nick")
        self.assertEqual(page["nick"], "Nick")
        self.assertEqual(len(page["items"]), 6)
        self.assertEqual(page["my_nick"], "Me")
        self.assertIn("message_count", page["stats"])

    async def test_page_unknown_person(self):
        page = await self.service.page("Ghost")
        self.assertTrue(page["missing"])
        self.assertEqual(page["items"], [])

    def test_preview_settings_and_to_json(self):
        self.assertEqual(self.service.preview_settings(),
                         HISTORY_DEFAULTS["preview"])
        data = json.loads(self.service.to_json())
        self.assertEqual(data["db_path"], self.db_path)
        self.assertIn("collector", data)


class TestLifecycle(ServiceCase):
    async def test_close_stops_task_and_persists_gaze(self):
        self.service.collector._nick = "Ally"
        await self.service.save_gaze()
        self.service.start()
        task = self.service._task
        self.assertIsNotNone(task)
        await self.service.close()
        self.assertTrue(task.done())
        self.assertFalse(self.service.db.is_open)

    async def test_start_is_idempotent_and_respects_disabled(self):
        self.service.start()
        first = self.service._task
        self.service.start()
        self.assertIs(self.service._task, first, "no second task")
        await self.service.close()
        # disabled
        cfg = ConfigManager(os.path.join(self.dir, "cfg5.json"))
        cfg.set("history", {"enabled": False})
        service2 = HistoryService(cdp=self.page, config=cfg,
                                  db_path=os.path.join(self.dir, "h5.db"))
        await service2.init()
        service2.start()
        self.assertIsNone(service2._task)
        await service2.close()

    async def test_push_binding_ignores_other_bindings(self):
        self.assertTrue(self.service._binding)
        self.assertEqual(self.page.binding_installs, ["__cvbPush"])
        # bindings for other names go to the collector only via __cvbPush
        self.assertIsNone(self.service._on_binding({"name": "other"}))
        result = self.service._on_binding({"name": "__cvbPush", "payload": "[]"})
        self.assertIsNotNone(result)

    async def test_reconnect_rebinds(self):
        self.assertEqual(self.service._binding, True)
        await self.service._rebind()
        self.assertEqual(self.service._binding, True)
        self.service._on_disconnected()
        self.assertFalse(self.service._binding)
        await self.service._rebind()
        self.assertTrue(self.service._binding)


class TestSwitchDb(ServiceCase):
    async def test_switch_to_a_new_world_starts_cold(self):
        self.service.set_my_nick("WorldA")
        await self.seed_messages("Anna")
        await self.service.db.commit()
        warm_nick = self.service.collector._nick
        self.service.collector._nick = "Anna"

        target = os.path.join(self.dir, "world_b.db")
        settings = await self.service.switch_db(target)
        self.assertEqual(self.service.db.path, target)
        self.assertEqual(settings["db_path"], target)
        # volatile state reset: the new world is cold (RULE 15)
        self.assertEqual(self.service.collector._nick, "")
        rows = await self.service.db.fetchall("SELECT COUNT(*) FROM messages")
        self.assertEqual(rows[0][0], 0)
        # old world on disk untouched
        self.assertTrue(os.path.exists(self.db_path))

    async def test_switch_fail_closed_reopens_previous(self):
        await self.seed_messages("Anna")
        old_path = self.service.db.path
        before = await self.service.db.fetchall(
            "SELECT COUNT(*) FROM messages")
        before_count = before[0][0]
        target = os.path.join(self.dir, "locked.db")
        # a target that cannot open: lock it by pointing at a directory
        os.makedirs(target, exist_ok=True)
        with self.assertRaises(Exception):
            await self.service.switch_db(target)
        self.assertEqual(self.service.db.path, old_path,
                         "a failed swap must reopen the previous world")
        self.assertTrue(self.service.db.is_open)
        rows = await self.service.db.fetchall(
            "SELECT COUNT(*) FROM messages")
        self.assertEqual(rows[0][0], before_count)
        self.assertFalse(os.path.exists(target + ".db"))

    async def test_switch_empty_path_is_a_programmer_error(self):
        with self.assertRaises(ValueError):
            await self.service.switch_db("   ")


class TestCollectorIntegration(ServiceCase):
    async def test_collector_tick_writes_through_the_service(self):
        self.page.is_connected = True
        self.page.partner = "Nick"
        self.service.collector.configure(my_nick="Me")
        await self.service.collector.tick()
        rows = await self.service.db.fetchall("SELECT COUNT(*) FROM messages")
        self.assertGreaterEqual(rows[0][0], 4)
        stats = await self.service.query.db_stats()
        self.assertEqual(stats["persons"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
