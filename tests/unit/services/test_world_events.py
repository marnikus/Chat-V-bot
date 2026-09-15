"""world_events — the ONE "the live world changed, reload it" broadcast.

Boot, a DB-connection switch and an undone db command all have to end the
same way: the People list, the Full User Database, the DB Connection window
and the label pills are told to reload from the world that is live *now*.
The bug this pins (2026-09-11): the page boots before the world is open, so
its first requests came back empty and only a manual refresh fixed it.

RULE 8: these tests fail if the broadcast is removed — the switch path below
runs the real `restart_world` with a real EventBus, not the emitter alone.
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.events import (EventBus, LabelsChanged, PeopleChanged,  # noqa: E402
                         UserDbChanged)
from services.undo_service import restart_world  # noqa: E402
from services.wiring_requests import RestartDeps  # noqa: E402
import services.world_events as world_events  # noqa: E402
from services.world_events import (announce_world_live,  # noqa: E402
                                   run_when_world_open, wait_for_world_open)


class FakeLabels:
    """The two methods `restart_world` touches on a label store."""

    def __init__(self, state=None, boom=False):
        self._state = state or {"assign": {}, "labels": []}
        self._boom = boom
        self.saves = 0

    def state(self):
        if self._boom:
            raise RuntimeError("label store is gone")
        return self._state


def collector(bus: EventBus):
    seen = []
    for kind in (PeopleChanged, UserDbChanged, LabelsChanged):
        bus.subscribe(kind, lambda event, k=kind: seen.append(k.__name__))
    return seen


class TestAnnounceWorldLive(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()

    def test_people_and_database_are_always_announced(self):
        seen = collector(self.bus)
        announce_world_live(self.bus, None, reason="startup")
        self.assertEqual(seen, ["PeopleChanged", "UserDbChanged"])

    def test_the_reason_travels_to_the_windows(self):
        payload = {}
        self.bus.subscribe(UserDbChanged, lambda event: payload.update(
            db=json.loads(event.payload)))
        self.bus.subscribe(PeopleChanged,
                           lambda event: payload.update(people=event.reason))
        announce_world_live(self.bus, None, reason="startup")
        self.assertEqual(payload, {"db": {"action": "startup", "ok": True},
                                   "people": "startup"})

    def test_labels_are_announced_when_a_store_is_given(self):
        seen = collector(self.bus)
        announce_world_live(self.bus, FakeLabels(), reason="db_switch")
        self.assertEqual(seen, ["PeopleChanged", "UserDbChanged",
                                "LabelsChanged"])

    def test_a_broken_label_store_costs_only_the_labels(self):
        seen = collector(self.bus)
        announce_world_live(self.bus, FakeLabels(boom=True), reason="startup")
        self.assertEqual(seen, ["PeopleChanged", "UserDbChanged"],
                         "the two lists must still reload")


class FakeMemory:
    def __init__(self):
        self.db_path = "/tmp/world.db"

    async def switch_db(self, path):            # pragma: no cover - unused
        raise AssertionError("the queue already follows that world")


class FakeUndo:
    def __init__(self):
        self.synced = 0

    async def sync_world_state(self):
        self.synced += 1


class FakeArchive:
    db = type("Db", (), {"path": "/tmp/world.db"})()
    my_nick = "me"


class TestRestartWorldUsesTheOneBroadcast(unittest.IsolatedAsyncioTestCase):
    async def test_a_world_switch_announces_the_same_events(self):
        bus = EventBus()
        seen = collector(bus)
        undo = FakeUndo()
        await restart_world(RestartDeps(memory=FakeMemory(),
                                        archive=FakeArchive(),
                                        labels=FakeLabels(), undo=undo,
                                        bus=bus), "load")
        self.assertEqual(undo.synced, 1, "the timeline is rebuilt first")
        self.assertEqual(seen, ["PeopleChanged", "UserDbChanged",
                                "LabelsChanged"])

    async def test_no_archive_means_no_broadcast(self):
        bus = EventBus()
        seen = collector(bus)
        await restart_world(RestartDeps(memory=FakeMemory(),
                                        undo=FakeUndo(), bus=bus), "load")
        self.assertEqual(seen, [], "a tear-down without a world says nothing")


class FakeStore:
    """A store that opens when told to (the app's world, in miniature)."""

    def __init__(self, open_after: int | None = 2):
        self._left = open_after
        self.checks = 0

    @property
    def is_open(self) -> bool:
        self.checks += 1
        if self._left is None:
            return False
        if self._left <= 0:
            return True
        self._left -= 1
        return False


class TestWaitForWorldOpen(unittest.IsolatedAsyncioTestCase):
    async def test_an_open_store_is_not_waited_for(self):
        store = FakeStore(open_after=0)
        started = time.monotonic()
        self.assertTrue(await wait_for_world_open(store, step=1.0))
        self.assertLess(time.monotonic() - started, 0.5,
                        "an open world is never slept on")
        # one read is the `hasattr` probe, one is the loop's own check
        self.assertEqual(store.checks, 2, "no polling once it is open")

    async def test_a_store_that_opens_later_is_waited_for(self):
        store = FakeStore(open_after=3)
        self.assertTrue(await wait_for_world_open(store, timeout=2.0))
        self.assertEqual(store.checks, 4)

    async def test_a_store_that_never_opens_gives_up_at_the_timeout(self):
        store = FakeStore(open_after=None)
        self.assertFalse(await wait_for_world_open(store, timeout=0.1,
                                                   step=0.01))

    async def test_something_that_is_not_a_store_is_never_waited_for(self):
        class NoFlag:
            pass

        self.assertFalse(await wait_for_world_open(NoFlag()))
        self.assertFalse(await wait_for_world_open(None))


class TestRunWhenWorldOpen(unittest.IsolatedAsyncioTestCase):
    """The archive's runner: wait, run, and never lose the failure."""

    async def test_the_work_runs_once_the_world_opens(self):
        store = FakeStore(open_after=2)
        done = []

        async def work():
            done.append(store.is_open)

        await run_when_world_open("userdb_page", work(), store)
        self.assertEqual(done, [True],
                         "the request must run against the open world")

    async def test_work_that_raises_reaches_the_window(self):
        store = FakeStore(open_after=0)
        seen = []

        async def work():
            raise RuntimeError("history database is not open")

        with self.assertLogs("chatbot", level="WARNING") as logged:
            await run_when_world_open("userdb_page", work(), store,
                                      lambda scope, msg: seen.append(scope))
        self.assertEqual(seen, ["userdb_page"],
                         "a failed read is still an answer for the window")
        self.assertIn("userdb_page", logged.output[0])

    async def test_a_failure_without_a_listener_is_only_logged(self):
        store = FakeStore(open_after=0)

        async def work():
            raise RuntimeError("boom")

        with self.assertLogs("chatbot", level="WARNING"):
            await run_when_world_open("stats", work(), store)

    async def test_a_world_that_never_opens_still_reports_itself(self):
        store = FakeStore(open_after=None)
        seen = []

        async def work():
            raise RuntimeError("history database is not open")

        # The real 15 s production grace, shortened — WAIT_S is read at call
        # time precisely so a test can do this instead of sleeping 15 s.
        with mock.patch.object(world_events, "WAIT_S", 0.2), \
                self.assertLogs("chatbot", level="WARNING"):
            await run_when_world_open("people", work(), store,
                                      lambda scope, msg: seen.append(msg))
        self.assertEqual(seen, ["history database is not open"],
                         "giving up must not mean silence")


if __name__ == "__main__":
    unittest.main(verbosity=2)