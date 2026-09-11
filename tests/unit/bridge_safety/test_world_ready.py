"""The boot broadcast: the windows receive the world's users by themselves.

Bug (2026-09-11): after a restart the Full User Database and the People list
stayed empty until the refresh button was pressed, because the page boots
while `main.py` is still opening the world — the first requests hit a closed
database and nothing asked again.

The fix is one announcement at the end of `ApplicationLifecycle.startup`
(`Router.announce_world_ready`). These tests run that method on a REAL
router, a REAL `UserMemory` and the REAL `PeopleService`, and read the JS
signals the windows listen to — so they fail if the announcement (or its
wiring) disappears, not if a fake drifts (RULE 8).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from stores.user_memory import UserMemory, UserRecord  # noqa: E402
from tests.unit.bridge_safety.helpers import drain  # noqa: E402

NICKS = ("Mloni", "Bea", "Cy")


class WorldReadyCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        world = os.path.join(self._tmp.name, "world.db")
        self.memory = UserMemory(world)
        await self.memory.init()
        for nick in NICKS:
            await self.memory.upsert_user(UserRecord(nick=nick))
        self.bridge = Bridge(config=ConfigManager(
            os.path.join(self._tmp.name, "config.json")))
        self.bridge._memory = self.memory        # write-through rebind
        self.users, self.changed = [], []
        self.bridge.users_updated.connect(self.users.append)
        self.bridge.userdb_changed.connect(self.changed.append)

    async def asyncTearDown(self):
        await self.memory.close()
        self._tmp.cleanup()


class TestWorldReadyAnnouncesEveryUser(WorldReadyCase):
    async def test_the_people_window_is_handed_every_user(self):
        await self.bridge.announce_world_ready()
        await drain()
        self.assertTrue(self.users,
                        "the People window was never told to load")
        rows = json.loads(self.users[-1])
        self.assertEqual(sorted(row["nick"] for row in rows), sorted(NICKS))

    async def test_the_database_window_is_told_to_reload_too(self):
        await self.bridge.announce_world_ready()
        await drain()
        self.assertTrue(self.changed, "userdb_changed never reached the DB window")
        self.assertEqual(json.loads(self.changed[-1])["action"], "startup")

    async def test_the_stats_travel_with_the_users(self):
        stats = []
        self.bridge.stats_updated.connect(stats.append)
        await self.bridge.announce_world_ready()
        await drain()
        self.assertTrue(stats, "the stats line never refreshed")
        self.assertGreaterEqual(json.loads(stats[-1]).get("total", 0),
                                len(NICKS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
