"""app.lifecycle — the boot order, and the ready broadcast at its end.

The page is up long before the backend finished opening the world, so its
first requests for the People list and the Full User Database came back
empty and stayed empty until the user pressed refresh (bug 2026-09-11).
`startup` therefore ends by announcing the live world; these tests pin both
the announcement and that it is the LAST thing before the tabs are fetched.

RULE 8: deleting that announcement fails `test_the_windows_hear_the_world_is
_open_last` — the order below is the shipped sequence, not a copy of it.
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.lifecycle import ApplicationLifecycle  # noqa: E402


class FakeApp:
    def __init__(self):
        self.quits = 0

    def quit(self):
        self.quits += 1


class FakeMemory:
    def __init__(self, order):
        self._order = order

    async def init(self):
        self._order.append("memory.init")


class FakeHistory:
    def __init__(self, order, boom=False):
        self._order = order
        self._boom = boom

    async def init(self):
        if self._boom:
            raise RuntimeError("archive unavailable")
        self._order.append("history.init")

    def start(self):
        self._order.append("history.start")


class FakeBridge:
    """Records the boot calls in the order the lifecycle makes them."""

    def __init__(self, order, announce_boom=False):
        self._order = order
        self._announce_boom = announce_boom

    async def sync_world_state(self):
        self._order.append("undo.sync")

    async def announce_world_ready(self):
        if self._announce_boom:
            raise RuntimeError("no bus")
        self._order.append("announce")

    def get_tabs(self):
        self._order.append("get_tabs")


def make_lifecycle(order, announce_boom=False, history_boom=False):
    return ApplicationLifecycle(
        app=FakeApp(), cdp=None, memory=FakeMemory(order),
        engine=None, history=FakeHistory(order, boom=history_boom),
        bridge=FakeBridge(order, announce_boom=announce_boom))


class TestStartupAnnouncesTheReadyWorld(unittest.IsolatedAsyncioTestCase):
    async def test_the_windows_hear_the_world_is_open_last(self):
        order: list[str] = []
        await make_lifecycle(order).startup()
        self.assertEqual(order, ["memory.init", "history.init",
                                 "history.start", "undo.sync", "announce",
                                 "get_tabs"])

    async def test_a_failed_broadcast_never_stops_the_boot(self):
        order: list[str] = []
        await make_lifecycle(order, announce_boom=True).startup()
        self.assertEqual(order[-1], "get_tabs",
                         "the tabs are still fetched after a failed announce")

    async def test_an_unavailable_archive_still_announces_the_people_list(self):
        order: list[str] = []
        await make_lifecycle(order, history_boom=True).startup()
        self.assertIn("announce", order,
                      "the queue can be read even without the archive")
        self.assertNotIn("history.start", order)


if __name__ == "__main__":
    unittest.main(verbosity=2)
