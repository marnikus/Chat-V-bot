"""Live people-status refresh, undo timestamp erase, and the Order (#) column.

BUG A  — After a run marked people messaged nothing emitted users_updated,
         so the table kept showing “New” until an app restart. The engine now
         emits person_marked per person and the bridge refreshes (plus a
         final stack_complete refresh).
BUG B  — Reset Messaged left last_messaged behind, so a “New” person kept a
         message time; undoing a messaged status must clear flag AND
         timestamp.
FEATURE — the People table gets a sortable “#” column: processing order as
         the selector algorithm builds it (A–Z under an enabled Scroll &
         Parse block, newest-discovered first otherwise). Only un-messaged
         people are numbered.

Run with:  python3 tests/test_live_status_and_order.py
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject, Signal  # noqa: E402

from actions.base_action import BaseAction, ActionResult  # noqa: E402
from backend.action_engine import ActionEngine  # noqa: E402
from backend.bridge import Bridge  # noqa: E402
from backend.cdp_client import CDPClient  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from backend.criteria_engine import CriteriaEngine  # noqa: E402
from backend.user_memory import UserMemory, UserRecord  # noqa: E402

UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")


def run_with_settle(coro, settle: float = 0.15):
    """Run `coro` and let asyncio.ensure_future() tasks it scheduled finish
    on the SAME event loop (asyncio.run would strand them)."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(coro)
        loop.run_until_complete(asyncio.sleep(settle))
    finally:
        loop.close()


class RecordingClick(BaseAction):
    """Stands in for CLICK_USER: OK per user, records the call."""
    block_id = "CLICK_USER"
    name = "Click User"
    icon = "👤"

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        return ActionResult.OK


class FullHarness:
    """Real UserMemory + ActionEngine + Bridge (the real __init__ wiring)."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = self._tmp.name
        self.memory = UserMemory(os.path.join(base, "users.db"))
        self.config = ConfigManager(os.path.join(base, "config.json"))
        self.cdp = CDPClient()
        self.engine = ActionEngine(cdp=self.cdp, memory=self.memory,
                                   criteria=CriteriaEngine())
        self.bridge = Bridge(cdp=self.cdp, memory=self.memory,
                             criteria=CriteriaEngine(), engine=self.engine,
                             config=self.config)
        self.user_payloads = []      # every users_updated emission
        self.stat_payloads = []
        self.bridge.users_updated.connect(
            lambda j: self.user_payloads.append(json.loads(j)))
        self.bridge.stats_updated.connect(
            lambda j: self.stat_payloads.append(json.loads(j)))

    async def __aenter__(self):
        await self.memory.init()
        return self

    async def __aexit__(self, *exc):
        await self.memory.close()
        self._tmp.cleanup()

    async def seed(self, *people):
        for p in people:
            await self.memory.upsert_user(p)

    async def pin_first_seen(self, nick, iso):
        await self.memory._db.execute(
            "UPDATE users SET first_seen=? WHERE nick=?", (iso, nick))
        await self.memory._db.commit()

    def by_nick(self, payload=None):
        payload = payload if payload is not None else self.user_payloads[-1]
        return {u["nick"]: u for u in payload}

    @property
    def last_stats(self):
        return self.stat_payloads[-1]


def rec(nick, messaged=False):
    return UserRecord(nick=nick, gender="female", guest=True,
                      messaged=messaged)


class TestLiveRefresh(unittest.TestCase):
    def test_engine_run_flips_rows_to_done_without_restart(self):
        async def go():
            async with FullHarness() as h:
                await h.seed(rec("Anna"), rec("Bella"))
                click = RecordingClick()
                h.engine._stack = [click]
                marked = []
                h.engine.person_marked.connect(lambda n: marked.append(n))
                # Run from the harness tmp dir so run-trace files stay out of
                # the repo, on the SAME loop the bridge tasks are scheduled on
                # (go() itself runs on that loop via run_with_settle).
                cwd = os.getcwd()
                os.chdir(h._tmp.name)
                try:
                    await h.engine.execute(None)
                    await asyncio.sleep(0.2)   # let queued refreshes land
                finally:
                    os.chdir(cwd)

                self.assertEqual(sorted(marked), ["Anna", "Bella"],
                                 "engine must announce each person it marked")
                self.assertEqual(sorted(click.calls), ["Anna", "Bella"])
                # The bridge re-emitted the list DURING/after the run — no
                # manual refresh_users() call happened anywhere.
                self.assertTrue(h.user_payloads,
                                "run must produce users_updated emissions")
                last = h.by_nick()
                self.assertTrue(last["Anna"]["messaged"])
                self.assertTrue(last["Bella"]["messaged"])
                self.assertTrue(all(u["order"] is None for u in last.values()),
                                "messaged people have no # order")
                stats = h.last_stats
                self.assertEqual((stats["total"], stats["queued"], stats["done"]),
                                 (2, 0, 2))
        run_with_settle(go())

    def test_person_marked_signal_triggers_an_immediate_refresh(self):
        async def go():
            async with FullHarness() as h:
                await h.seed(rec("Anna"))
                await h.memory.mark_messaged("Anna")   # engine-path write
                h.user_payloads.clear()
                # what the bridge __init__ wiring does on engine.person_marked
                h.engine.person_marked.emit("Anna")
                await asyncio.sleep(0.05)
                self.assertTrue(h.user_payloads,
                                "person_marked must refresh the people list")
                self.assertTrue(h.by_nick()["Anna"]["messaged"])
        run_with_settle(go())

    def test_stack_complete_triggers_a_final_refresh(self):
        async def go():
            async with FullHarness() as h:
                await h.seed(rec("Anna"))
                await h.memory.mark_messaged("Anna")
                h.user_payloads.clear()
                h.engine.stack_complete.emit()
                await asyncio.sleep(0.05)
                self.assertTrue(h.user_payloads)
                self.assertTrue(h.by_nick()["Anna"]["messaged"])
        run_with_settle(go())


class TestTimestampErase(unittest.TestCase):
    def test_reset_messaged_erases_the_timestamp(self):
        async def go():
            async with FullHarness() as h:
                await h.seed(rec("Anna"), rec("Cara", messaged=True))
                await h.memory.mark_messaged("Cara")     # gives a timestamp
                await h.bridge._do_reset()
                rows = {u.nick: u for u in await h.memory.get_all()}
                for u in rows.values():
                    self.assertFalse(u.messaged)
                    self.assertIsNone(u.last_messaged,
                                      "a New person must have no message time")
                # and the UI payload agrees + Cara now ranks in the order
                ui = h.by_nick()
                self.assertIsNone(ui["Cara"]["last_messaged"])
                self.assertIsNotNone(ui["Cara"]["order"])
        run_with_settle(go())

    def test_undo_of_done_clears_flag_and_timestamp(self):
        async def go():
            async with FullHarness() as h:
                await h.seed(rec("Anna"))
                # user clicks ✔ Done
                await h.bridge._do_set_messaged("Anna", True)
                anna = await h.memory.get_user("Anna")
                self.assertTrue(anna.messaged)
                self.assertIsNotNone(anna.last_messaged)
                # Ctrl+Z
                h.bridge.undo()
                await asyncio.sleep(0.05)
                anna = await h.memory.get_user("Anna")
                self.assertFalse(anna.messaged, "undo must clear the flag")
                self.assertIsNone(anna.last_messaged,
                                  "undo must erase the timestamp")
                ui = h.by_nick()["Anna"]
                self.assertFalse(ui["messaged"])
                self.assertEqual(ui["last_messaged"], None)
        run_with_settle(go())

    def test_per_row_new_again_erases_the_timestamp(self):
        async def go():
            async with FullHarness() as h:
                await h.seed(rec("Anna"))
                await h.memory.mark_messaged("Anna")
                await h.bridge._do_set_messaged("Anna", False)  # row ↩ Undo
                anna = await h.memory.get_user("Anna")
                self.assertFalse(anna.messaged)
                self.assertIsNone(anna.last_messaged)
        run_with_settle(go())


class TestOrderColumn(unittest.TestCase):
    async def _seed_ranks(self, h, scroll_parse: bool):
        """Four people: Bella already messaged; timestamps spaced so the
        newest-first order is deterministic."""
        for nick in ("Anna", "Cara", "Dasha", "Bella"):
            await h.seed(rec(nick))
        await h.memory.mark_messaged("Bella")
        for i, nick in enumerate(("Anna", "Cara", "Dasha"), start=1):
            await h.pin_first_seen(nick, f"2026-09-0{i}T10:00:00")
        if scroll_parse:
            h.engine.load_stack([{"block_id": "SCROLL_PARSE", "enabled": True}])
        else:
            h.engine.load_stack([])
        await h.bridge._refresh_users()
        return h.by_nick()

    def test_order_is_a_z_under_a_scroll_parse_block(self):
        async def go():
            async with FullHarness() as h:
                ui = await self._seed_ranks(h, scroll_parse=True)
                self.assertEqual(ui["Anna"]["order"], 1)
                self.assertEqual(ui["Cara"]["order"], 2)
                self.assertEqual(ui["Dasha"]["order"], 3)
                self.assertIsNone(ui["Bella"]["order"],
                                  "messaged person is not in the order list")
        run_with_settle(go())

    def test_order_is_newest_first_without_a_scroll_parse_block(self):
        async def go():
            async with FullHarness() as h:
                ui = await self._seed_ranks(h, scroll_parse=False)
                self.assertEqual(ui["Dasha"]["order"], 1)  # newest (09-03)
                self.assertEqual(ui["Cara"]["order"], 2)
                self.assertEqual(ui["Anna"]["order"], 3)
                self.assertIsNone(ui["Bella"]["order"])
        run_with_settle(go())

    def test_order_updates_dynamically_as_statuses_change(self):
        async def go():
            async with FullHarness() as h:
                await h.seed(rec("Anna"), rec("Cara"))
                h.engine.load_stack([{"block_id": "SCROLL_PARSE",
                                      "enabled": True}])
                await h.bridge._refresh_users()
                ui = h.by_nick()
                self.assertEqual(ui["Anna"]["order"], 1)
                self.assertEqual(ui["Cara"]["order"], 2)
                # Cara gets messaged (engine-style write) → drops out, Anna
                # becomes #1 and Cara is no longer numbered.
                await h.memory.mark_messaged("Cara")
                await h.bridge._refresh_users()
                ui = h.by_nick()
                self.assertEqual(ui["Anna"]["order"], 1)
                self.assertIsNone(ui["Cara"]["order"])
        run_with_settle(go())

    def test_stack_edit_changes_the_ranking(self):
        async def go():
            async with FullHarness() as h:
                await h.seed(rec("Anna"), rec("Cara"))
                await h.pin_first_seen("Anna", "2026-09-01T10:00:00")
                await h.pin_first_seen("Cara", "2026-09-03T10:00:00")
                # no Scroll & Parse → newest first: Cara #1
                h.engine.load_stack([])
                await h.bridge._refresh_users()
                self.assertEqual(h.by_nick()["Cara"]["order"], 1)
                # adding a Scroll & Parse block switches the selector to A–Z
                h.engine.load_stack([{"block_id": "SCROLL_PARSE",
                                      "enabled": True}])
                await h.bridge._refresh_users()
                self.assertEqual(h.by_nick()["Anna"]["order"], 1)
                self.assertEqual(h.by_nick()["Cara"]["order"], 2)
        run_with_settle(go())


class TestOrderUiContract(unittest.TestCase):
    def test_table_offers_a_sortable_order_column(self):
        with open(os.path.join(UI_DIR, "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('data-sort="order"', html)
        self.assertIn('title="Processing order', html)

    def test_user_table_renders_and_sorts_the_order(self):
        with open(os.path.join(UI_DIR, "js", "user-table.js"),
                  encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn('class="col-order"', js)
        self.assertIn("colspan=\"9\"", js)
        self.assertIn("Number.isInteger(user.order)", js)
        self.assertIn("No processing order", js)
        # a New person must never show a message time even with stale data
        self.assertIn("(!u.messaged || !u.last_messaged)", js)

    def test_css_styles_the_order_cell(self):
        with open(os.path.join(UI_DIR, "css", "table.css"),
                  encoding="utf-8") as fh:
            css = fh.read()
        self.assertIn("th.col-order", css)
        self.assertIn("td.col-order", css)


if __name__ == "__main__":
    unittest.main(verbosity=2)
