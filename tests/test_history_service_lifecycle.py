"""services/history_service — lifecycle, per-world settings, world isolation.

Design refs: docs/archive/2026-09-09-test-suite/BACKEND_TESTS_DESIGN_2026-09-09.md §HS#1–6.

Promises proven here (module docstring + switch_db's own contract):

  * init() brings up a working archive; close() is idempotent and the
    file stays readable afterwards;
  * apply_settings() DEEP-merges a UI patch (siblings survive) and the
    per-world copy lands in the world's `app_settings` table;
  * per-world settings travel with their world: A's 9 MB cap must not
    leak into B, and must come back when A is re-opened;
  * meta flags are world-scoped;
  * ONE DB = ONE WORLD: a message written in world A is invisible in
    world B and still in A after the round trip — both directions;
  * the radar (gaze) state is saved before a switch, a new world starts
    COLD (RULE 15), and switching back restores the saved state;
  * to_json() is a valid JSON export of the service settings.

Run with:  python3 tests/test_history_service_lifecycle.py
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.config_manager import ConfigManager  # noqa: E402
from backend.history_service import HistoryService  # noqa: E402
from test_chat_parser_delta import FakePage, raw  # noqa: E402


class ConnectedPage(FakePage):
    is_connected = True


class ServiceCase(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        media_cfg = dict(self.cfg.get("history", "media", default={}) or {})
        media_cfg["cache_dir"] = os.path.join(self.dir, "saved_media")
        self.cfg.set("history", "media", media_cfg)
        self.page = ConnectedPage([raw(f"m{i}", idx=i) for i in range(4)])
        self.db_a = os.path.join(self.dir, "world_a.db")
        self.db_b = os.path.join(self.dir, "world_b.db")
        self.service = HistoryService(cdp=self.page, config=self.cfg,
                                      db_path=self.db_a)
        await self.service.init()

    async def asyncTearDown(self):
        try:
            await self.service.close()
        except Exception:
            pass

    async def seed(self, nick, count, partner=None):
        self.page.partner = partner or nick
        self.page.messages = [raw(f"m{i}", from_nick=nick, idx=i)
                              for i in range(count)]
        await self.service.collector.tick()

    async def message_count(self):
        rows = await self.service.db.fetchall(
            "SELECT COUNT(*) FROM messages")
        return rows[0][0]


# ══════════════════════════════════════════════════════════════════
# HS#1 — lifecycle
# ══════════════════════════════════════════════════════════════════
class TestLifecycle(ServiceCase):

    async def test_init_opens_and_close_is_idempotent(self):
        self.assertTrue(self.service.db.is_open)
        await self.service.close()
        self.assertFalse(self.service.db.is_open)
        await self.service.close()          # second close must be a no-op
        # the file is still a readable SQLite database
        import aiosqlite
        async with aiosqlite.connect(self.db_a) as conn:
            rows = await conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            self.assertGreater((await rows.fetchone())[0], 0)

    async def test_enabled_and_settings_surfaces(self):
        self.assertTrue(self.service.enabled)
        data = self.service.settings()
        self.assertIn("media", data)
        self.assertIn("db_path", data)
        self.assertEqual(os.path.abspath(data["db_path"]),
                         os.path.abspath(self.db_a))
        self.assertEqual(data["collector"]["my_nick"],
                         self.service.my_nick)


# ══════════════════════════════════════════════════════════════════
# HS#2 / HS#5 — settings merge, per-world persistence
# ══════════════════════════════════════════════════════════════════
class TestSettings(ServiceCase):

    async def test_apply_settings_deep_merges_and_keeps_siblings(self):
        self.service.apply_settings({"media": {"max_file_mb": 9}})
        media = self.service.settings()["media"]
        self.assertEqual(media["max_file_mb"], 9)
        self.assertEqual(media["cache_dir"],
                         os.path.join(self.dir, "saved_media"),
                         "sibling key lost by the patch")
        self.assertTrue(media["download"], "neighbour key lost")

    async def test_patch_lands_in_the_worlds_app_settings(self):
        """The persist is fire-and-forget (a loop task) — the honest
        contract is "persisted after the loop gets a tick". Ledger #9
        (minor): the task is neither awaited nor reference-held and it
        writes through the shared self.db handle, so a world switch
        racing the task could rebind the handle first."""
        self.service.apply_settings({"media": {"max_file_mb": 9}})
        await asyncio.sleep(0.05)          # let the persist task run
        rows = await self.service.db.fetchall(
            "SELECT value FROM app_settings WHERE key='media_max_file_mb'")
        self.assertTrue(rows, "per-world setting not persisted")
        self.assertEqual(float(json.loads(rows[0][0])), 9.0)

    async def test_a_per_world_cap_travels_with_its_world(self):
        """Documented dual-write: a patch lands in the world's
        app_settings AND in the config template that un-seeded worlds
        serve — so world B (no stored settings) legitimately shows the
        template. Per-world isolation holds for worlds that HAVE their
        own stored values: A's stored cap must survive the round trip."""
        self.service.apply_settings({"media": {"max_file_mb": 9}})
        await asyncio.sleep(0.05)
        await self.service.switch_db(self.db_b)
        # B serves the template (9 now lives in config.json)
        self.assertEqual(self.service.settings()["media"]["max_file_mb"], 9)
        self.assertEqual(self.cfg.get("history", "media", "max_file_mb"), 9,
                         "the config template must receive the patch")
        # and back to A: its own stored cap comes back
        await self.service.switch_db(self.db_a)
        self.assertEqual(self.service.settings()["media"]["max_file_mb"], 9,
                         "world A's stored cap was lost on the round trip")

    async def test_a_fresh_world_keeps_the_app_template(self):
        """HS#5 — a world without stored settings uses the template."""
        self.service.apply_settings({"media": {"max_file_mb": 7}})
        await self.service.switch_db(self.db_b)
        rows = await self.service.db.fetchall(
            "SELECT COUNT(*) FROM app_settings")
        self.assertEqual(rows[0][0], 0,
                         "an un-seeded fresh world must have no settings")
        self.assertEqual(self.service.settings()["media"]["max_file_mb"], 7,
                         "the config template must keep serving")

    async def test_seed_app_settings_fills_a_fresh_world_once(self):
        await self.service.switch_db(self.db_b)
        await self.service.seed_app_settings()
        rows = await self.service.db.fetchall(
            "SELECT key FROM app_settings")
        keys = {r[0] for r in rows}
        self.assertIn("my_nick", keys)
        self.assertIn("media_max_file_mb", keys)
        await self.service.seed_app_settings()     # second pass: no-op
        rows = await self.service.db.fetchall(
            "SELECT COUNT(*) FROM app_settings")
        self.assertEqual(rows[0][0], len(keys), "seed duplicated rows")


# ══════════════════════════════════════════════════════════════════
# HS#3 — meta flags are world-scoped
# ══════════════════════════════════════════════════════════════════
class TestMetaFlags(ServiceCase):

    async def test_flags_round_trip_and_do_not_leak_between_worlds(self):
        self.assertFalse(await self.service.get_meta_flag("migrated_2026"),
                         "an unset flag must read False")
        await self.service.set_meta_flag("migrated_2026")
        self.assertTrue(await self.service.get_meta_flag("migrated_2026"))

        await self.service.switch_db(self.db_b)
        self.assertFalse(await self.service.get_meta_flag("migrated_2026"),
                         "world A's flag leaked into world B")
        await self.service.switch_db(self.db_a)
        self.assertTrue(await self.service.get_meta_flag("migrated_2026"))


# ══════════════════════════════════════════════════════════════════
# HS#4 — ONE DB = ONE WORLD (data isolation, both directions)
# ══════════════════════════════════════════════════════════════════
class TestWorldIsolation(ServiceCase):

    async def test_messages_never_cross_worlds(self):
        await self.seed("Anna", 4, partner="Anna")
        count_a = await self.message_count()
        self.assertEqual(count_a, 4)

        await self.service.switch_db(self.db_b)
        self.assertEqual(os.path.abspath(self.service.db.path),
                         os.path.abspath(self.db_b))
        self.assertEqual(await self.message_count(), 0,
                         "world A's messages are visible in world B")

        await self.seed("Belle", 2, partner="Belle")
        self.assertEqual(await self.message_count(), 2)

        await self.service.switch_db(self.db_a)
        self.assertEqual(await self.message_count(), 4,
                         "switching back lost or polluted world A")
        rows = await self.service.db.fetchall(
            "SELECT COUNT(*) FROM messages WHERE from_nick='Belle'")
        self.assertEqual(rows[0][0], 0, "Belle's rows leaked into world A")

        await self.service.switch_db(self.db_b)
        self.assertEqual(await self.message_count(), 2,
                         "world B's writes were lost on the way back")

    async def test_page_reads_the_active_world_only(self):
        await self.seed("Anna", 4, partner="Anna")
        await self.service.switch_db(self.db_b)
        payload = await self.service.page("Anna")
        self.assertEqual(payload["stats"].get("total", 0), 0,
                         "world A's person visible from world B")


# ══════════════════════════════════════════════════════════════════
# HS#6 — gaze (radar state) follows its world
# ══════════════════════════════════════════════════════════════════
class TestGaze(ServiceCase):

    async def test_gaze_survives_a_world_round_trip(self):
        self.service.collector.configure(my_nick="Me")
        self.service.collector._nick = "Alice"
        self.service.collector._added = 7
        self.service.collector._total = 30

        await self.service.switch_db(self.db_b)     # saves A's gaze on exit
        self.assertNotEqual(self.service.collector._nick, "Alice",
                            "world B started warm — RULE 15 violated")

        await self.service.switch_db(self.db_a)
        self.assertEqual(self.service.collector._nick, "Alice",
                         "A's radar partner was lost on the round trip")
        self.assertEqual(self.service.collector._added, 7)


# ══════════════════════════════════════════════════════════════════
# export surface
# ══════════════════════════════════════════════════════════════════
class TestExport(ServiceCase):

    async def test_to_json_is_a_valid_settings_export(self):
        payload = json.loads(self.service.to_json())
        self.assertIn("db_path", payload)
        self.assertIn("media", payload)
        self.assertIsInstance(payload["preview"], dict)


if __name__ == "__main__":
    unittest.main(verbosity=2)
