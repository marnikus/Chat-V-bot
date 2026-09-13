"""The shipped boot order, end to end: the DB list fills itself on startup.

Bug (2026-09-11, second report): “the list of persons still not visible as I
run app … it forces me to press refresh first”. `main.py` builds the window
BEFORE `ApplicationLifecycle.startup` opens the world, so the window's first
`userdb_page` request reached a closed `HistoryDB` and was answered only with
`history_error` — never with `userdb_page_ready`. The table waited for a reply
that had already died, and only ↻ (a brand-new request) filled it.

`tests/unit/bridge_safety/test_boot_race.py` pins the wait on the bridge; this
file pins the same promise through the SHIPPED wiring: a REAL `Router`, the
REAL `ApplicationLifecycle`, the REAL `HistoryService`/`UserMemory` — one
closed world, one request before it opens, zero refresh calls.

RULE 8: with `wait_for_world_open` removed from the run path the answer never
arrives (`pages` stays empty) and these tests fail; they do not pass on a fake
that outlives the real bridge.
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

from app.lifecycle import ApplicationLifecycle  # noqa: E402
from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from services.history import HistoryService  # noqa: E402
from stores.user_memory import UserMemory, UserRecord  # noqa: E402
from tests.unit.bridge_safety.helpers import drain  # noqa: E402

NICKS = ("Mloni", "Bea", "Cy")


class FakeCdp:
    connected = None
    disconnected = None
    lease = None

    async def disconnect(self):                     # pragma: no cover - unused
        pass


class FakeApp:
    def quit(self):                                 # pragma: no cover - unused
        pass


async def seed_world(path: str) -> None:
    """People in BOTH halves of the world: the queue and the archive."""
    memory = UserMemory(path)
    await memory.init()
    for nick in NICKS:
        await memory.upsert_user(UserRecord(nick=nick))
    await memory.close()
    archive = HistoryService(cdp=FakeCdp(), db_path=path)
    await archive.db.init()
    for nick in NICKS:                              # the real write path
        await archive.repo.ensure_person(nick)
    await archive.db.close()


class BootChainCase(unittest.IsolatedAsyncioTestCase):
    """The state `main.py` leaves behind when the page has already loaded."""

    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        world = os.path.join(self._tmp.name, "world.db")
        await seed_world(world)
        self.world = world
        self.bridge = Bridge(config=ConfigManager(
            os.path.join(self._tmp.name, "config.json")))
        self.memory = UserMemory(world)             # both stores exist,
        self.archive = HistoryService(cdp=FakeCdp(), db_path=world,
                                      memory=self.memory)
        self.bridge._memory = self.memory           # ...and are CLOSED
        self.bridge.attach_history(self.archive)
        self.pages, self.errors, self.changes = [], [], []
        self.bridge.userdb_page_ready.connect(
            lambda req_id, payload: self.pages.append(json.loads(payload)))
        self.bridge.history_error.connect(
            lambda scope, msg: self.errors.append((scope, msg)))
        self.bridge.userdb_changed.connect(self.changes.append)

    async def asyncTearDown(self):
        await self.archive.close()
        await self.memory.close()
        self._tmp.cleanup()

    async def run_startup(self):
        """The real `startup`, on the real objects — no fakes in the path."""
        lifecycle = ApplicationLifecycle(app=FakeApp(), cdp=None,
                                         memory=self.memory, engine=None,
                                         history=self.archive, bridge=self.bridge)
        await lifecycle.startup()
        await drain()

    def nicks(self, page: dict):
        return sorted(row["nick"] for row in page["items"])


class TestTheBootFillsTheDatabaseWindow(BootChainCase):
    async def test_the_first_request_sent_before_startup_is_answered(self):
        self.bridge.userdb_page("boot-1", json.dumps({"limit": 50,
                                                      "offset": 0}))
        self.assertEqual(self.pages, [], "the world is still closed here")
        await self.run_startup()
        self.assertEqual(self.errors, [], "the boot request must not fail")
        self.assertEqual(len(self.pages), 1,
                         "one request, one answer — ↻ must not be needed")
        self.assertEqual(self.nicks(self.pages[0]), sorted(NICKS))

    async def test_the_same_holds_for_the_stats_line(self):
        self.bridge.userdb_stats("boot-stats")
        await self.run_startup()
        answers = [page for page in self.pages if page.get("persons")]
        self.assertEqual(len(answers), 1, "the footer stats arrive as well")
        self.assertEqual(answers[0]["persons"], len(NICKS))

    async def test_the_people_list_is_filled_by_the_boot_alone(self):
        users = []
        self.bridge.users_updated.connect(
            lambda payload: users.append(json.loads(payload)))
        await self.run_startup()
        self.assertTrue(users, "the People list was never filled")
        self.assertEqual(sorted(row["nick"] for row in users[-1]),
                         sorted(NICKS))

    async def test_the_window_is_told_the_live_world_changed(self):
        await self.run_startup()
        self.assertTrue(self.changes, "the DB window never heard the world live")
        self.assertEqual(json.loads(self.changes[-1])["action"], "startup")


if __name__ == "__main__":
    unittest.main(verbosity=2)
