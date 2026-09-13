"""The boot race: a request that arrives before the world is open is ANSWERED.

Bug (2026-09-11, second report): “the list of persons still not visible as I
run app … it forces me to press refresh first”. The page is built before
`ApplicationLifecycle.startup` opens the world, so the window's first request
reached the archive while `HistoryDB` was still closed and died with
“history database is not open”. The reply never came, the table stayed empty,
and only ↻ (a fresh request, now against an open world) filled it.

The fix: the bridge waits for the world before it runs that work
(`services.world_events.wait_for_world_open`), so the SAME request answers.
These tests run the REAL `HistoryBridge`/`PeopleBridge` over a REAL world
file: the window asks once, the world opens later, the list arrives.

RULE 8: they fail on the pre-fix code (the answer never comes), not on a
fake drifting away from the real bridge.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.events import EventBus  # noqa: E402
from bridge.context import BridgeContext  # noqa: E402
from bridge.history_bridge import HistoryBridge  # noqa: E402
from bridge.people_bridge import PeopleBridge  # noqa: E402
from services.history import HistoryService  # noqa: E402
from services.history import HistoryDeps  # noqa: E402
from stores.user_memory import UserMemory, UserRecord  # noqa: E402

PEOPLE = ("Mloni", "Bea", "Cy")


class FakeCdp:
    connected = None
    disconnected = None
    lease = None


async def seed_world(path: str) -> None:
    """A world with people in BOTH halves: the queue and the archive."""
    memory = UserMemory(path)
    await memory.init()
    for nick in PEOPLE:
        await memory.upsert_user(UserRecord(nick=nick))
    await memory.close()
    archive = HistoryService(HistoryDeps(cdp=FakeCdp(), db_path=path))
    await archive.db.init()
    for nick in PEOPLE:                       # the real write path
        await archive.repo.ensure_person(nick)
    await archive.db.close()


class BootRaceCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "world.db")
        await seed_world(self.path)
        # Both stores exist but are CLOSED — exactly the state the page sees.
        self.memory = UserMemory(self.path)
        self.archive = HistoryService(HistoryDeps(cdp=FakeCdp(), db_path=self.path, memory=self.memory))
        self.ctx = BridgeContext(memory=self.memory, bus=EventBus())
        self.ctx.archive = self.archive

    async def asyncTearDown(self):
        try:
            await self.archive.db.close()
        except Exception:                               # noqa: BLE001
            pass
        try:
            await self.memory.close()
        except Exception:                               # noqa: BLE001
            pass
        self._tmp.cleanup()

    async def _open_world_later(self) -> None:
        """What `lifecycle.startup` does — after the page already asked."""
        await asyncio.sleep(0.05)
        await self.memory.init()
        await self.archive.db.init()


class TestDatabaseWindowAnswersTheBootRequest(BootRaceCase):
    async def test_the_first_page_request_survives_the_boot_race(self):
        bridge = HistoryBridge(self.ctx)
        pages, errors = [], []
        bridge.userdb_page_ready.connect(
            lambda req_id, payload: pages.append(json.loads(payload)))
        bridge.history_error.connect(lambda scope, msg: errors.append(msg))

        bridge.userdb_page("u1", json.dumps({"limit": 50, "offset": 0}))
        await self._open_world_later()
        await asyncio.sleep(0.3)

        self.assertEqual(errors, [], "the boot request must not fail")
        self.assertEqual(len(pages), 1, "one request, one answer")
        self.assertEqual(sorted(row["nick"] for row in pages[0]["items"]),
                         sorted(PEOPLE))

    async def test_the_stats_request_survives_it_too(self):
        bridge = HistoryBridge(self.ctx)
        pages = []
        bridge.userdb_page_ready.connect(
            lambda req_id, payload: pages.append(json.loads(payload)))

        bridge.userdb_stats("s1")
        await self._open_world_later()
        await asyncio.sleep(0.3)

        self.assertEqual(len(pages), 1, "the footer stats arrive as well")
        self.assertEqual(pages[0]["persons"], len(PEOPLE))

    async def test_a_world_that_never_opens_still_reports_the_error(self):
        """The wait is bounded: a broken boot must not hang the window."""
        bridge = HistoryBridge(self.ctx)
        errors = []
        bridge.history_error.connect(
            lambda scope, msg: errors.append((scope, msg)))

        with mock.patch("services.world_events.WAIT_S", 0.05):
            bridge.userdb_page("u1", json.dumps({"limit": 5}))
            await asyncio.sleep(0.3)
        self.assertEqual(errors[0][0], "userdb_page",
                         "the window is told WHICH read failed")
        self.assertIn("not open", errors[0][1])


class TestPeopleWindowAnswersTheBootRequest(BootRaceCase):
    async def test_refresh_users_before_the_queue_is_open(self):
        bridge = PeopleBridge(self.ctx)
        users = []
        bridge.users_updated.connect(lambda payload: users.append(
            json.loads(payload)))

        await self._ask_then_open(bridge)
        self.assertTrue(users, "the People list was never filled")
        self.assertEqual(sorted(row["nick"] for row in users[-1]),
                         sorted(PEOPLE))

    async def _ask_then_open(self, bridge) -> None:
        asker = asyncio.ensure_future(bridge._refresh_users_async())
        await self._open_world_later()
        await asyncio.wait_for(asker, timeout=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
