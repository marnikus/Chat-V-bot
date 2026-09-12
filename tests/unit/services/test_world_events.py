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
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.events import (EventBus, LabelsChanged, PeopleChanged,  # noqa: E402
                         UserDbChanged)
from services.undo_service import restart_world  # noqa: E402
from services.world_events import announce_world_live  # noqa: E402


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
        await restart_world(FakeMemory(), FakeArchive(), FakeLabels(), undo,
                            bus, "load")
        self.assertEqual(undo.synced, 1, "the timeline is rebuilt first")
        self.assertEqual(seen, ["PeopleChanged", "UserDbChanged",
                                "LabelsChanged"])

    async def test_no_archive_means_no_broadcast(self):
        bus = EventBus()
        seen = collector(bus)
        await restart_world(FakeMemory(), None, None, FakeUndo(), bus, "load")
        self.assertEqual(seen, [], "a tear-down without a world says nothing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
