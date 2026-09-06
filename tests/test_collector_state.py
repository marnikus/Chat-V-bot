"""Passive collector — detection, statuses, throttling (milestone M3).

The collector is a supervisor: every tick it takes ONE cheap heartbeat
probe, decides what changed, and does the smallest amount of work that
keeps the archive correct. These tests drive `tick()` directly so the state
machine is deterministic — no sleeping, no real loop.

Covered:
  * the detection table (disconnected / room tab / group tab / private);
  * the exact status vocabulary the request asked for ("Collecting",
    "Collected"/"No new messages", "Not in private tab now");
  * live push handling (the in-page agent hands us new lines);
  * throttling while an action-stack run is active (decision D-3);
  * self-healing after the page re-renders and the agent disappears;
  * the supervisor never dies: an exploding probe becomes an ERROR status
    and the next tick recovers.

Run with:  python3 tests/test_collector_state.py
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.chat_parser import ChatParser  # noqa: E402
from backend.collector import Collector, CollectorState  # noqa: E402
from backend.history_db import HistoryDB  # noqa: E402
from backend.history_models import fingerprint  # noqa: E402
from backend.history_repo import HistoryRepo  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_chat_parser_delta import FakePage, raw  # noqa: E402

NOW = datetime(2026, 9, 6, 18, 30, 0)


class ConnectedPage(FakePage):
    is_connected = True


class CollectorCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = HistoryDB(os.path.join(self.dir, "history.db"))
        await self.db.init()
        self.repo = HistoryRepo(self.db, session_id="s")
        self.page = ConnectedPage([raw(f"m{i}", idx=i) for i in range(4)])
        self.parser = ChatParser(self.page, chunk_size=10, chunk_pause_ms=0)
        self.col = Collector(cdp=self.page, repo=self.repo,
                             parser=self.parser, media=None,
                             settings={"heartbeat_ms": 1000,
                                       "idle_heartbeat_ms": 3000,
                                       "throttle_factor": 4,
                                       "my_nick": "Me"})
        self.col.now = lambda: NOW
        self.statuses = []
        self.col.status_changed.connect(
            lambda payload: self.statuses.append(json.loads(payload)["state"]))

    async def asyncTearDown(self):
        await self.db.close()


class TestDetection(CollectorCase):
    async def test_disconnected(self):
        self.page.is_connected = False
        self.assertEqual(await self.col.tick(), CollectorState.DISCONNECTED)
        self.assertEqual(self.page.slice_calls, [])

    async def test_disabled(self):
        self.col.configure(enabled=False)
        self.assertEqual(await self.col.tick(), CollectorState.OFF)
        self.assertEqual(self.page.evaluates, 0)

    async def test_paused(self):
        self.col.pause()
        self.assertEqual(await self.col.tick(), CollectorState.PAUSED)
        self.col.resume()
        self.assertNotEqual(await self.col.tick(), CollectorState.PAUSED)

    async def test_main_room_tab_is_not_collected(self):
        self.page.tab = "room"
        self.assertEqual(await self.col.tick(), CollectorState.NOT_PRIVATE)
        self.assertEqual(self.col.state_payload()["text"],
                         "Not in private tab now")
        self.assertEqual(self.page.slice_calls, [])

    async def test_group_tab_is_not_collected(self):
        self.page.participants = 3
        self.assertEqual(await self.col.tick(), CollectorState.GROUP_TAB)
        self.assertEqual(self.page.slice_calls, [])

    async def test_group_guard_can_be_switched_off(self):
        self.page.participants = 3
        self.col.configure(require_two_participants=False)
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)

    async def test_partner_equal_to_my_nick_is_refused(self):
        self.page.partner = "Me"
        state = await self.col.tick()
        self.assertEqual(state, CollectorState.NOT_PRIVATE)
        self.assertIn("ambiguous", self.col.state_payload()["text"].lower())


class TestCollectionFlow(CollectorCase):
    async def test_first_tick_bootstraps_and_reports_collected(self):
        state = await self.col.tick()
        self.assertEqual(state, CollectorState.COLLECTED)
        payload = self.col.state_payload()
        self.assertEqual(payload["nick"], "Nick")
        self.assertEqual(payload["added"], 4)
        self.assertEqual(payload["total"], 4)
        self.assertIn(CollectorState.BOOTSTRAPPING, self.statuses)
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 4)

    async def test_idle_tick_says_no_new_messages_and_reads_nothing(self):
        await self.col.tick()
        reads = len(self.page.slice_calls)
        self.assertEqual(await self.col.tick(), CollectorState.NO_NEW)
        self.assertEqual(self.col.state_payload()["text"], "No new messages")
        self.assertEqual(len(self.page.slice_calls), reads)

    async def test_new_messages_are_appended_on_the_next_tick(self):
        await self.col.tick()
        self.page.append(raw("m4", idx=4), raw("m5", idx=5))
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.assertEqual(self.col.state_payload()["added"], 2)
        self.assertIn(CollectorState.COLLECTING, self.statuses)
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 6)

    async def test_switching_conversation_starts_a_new_archive(self):
        await self.col.tick()
        self.page.partner = "Other"
        self.page.messages = [raw("hi", from_nick="Other", idx=0)]
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.assertEqual(self.col.state_payload()["nick"], "Other")
        self.assertEqual((await self.repo.get_person("Nick"))["message_count"], 4)
        self.assertEqual((await self.repo.get_person("Other"))["message_count"], 1)

    async def test_my_nick_is_recorded_and_a_missing_one_warns(self):
        await self.col.tick()
        rows = await self.db.fetchall("SELECT DISTINCT my_nick FROM messages")
        self.assertEqual([r[0] for r in rows], ["Me"])
        self.col.configure(my_nick="")
        self.page.append(raw("later", idx=4))
        await self.col.tick()
        self.assertIn("My Nick", self.col.state_payload()["warning"])

    async def test_status_is_only_emitted_when_it_changes(self):
        await self.col.tick()
        await self.col.tick()
        before = len(self.statuses)
        await self.col.tick()
        self.assertEqual(len(self.statuses), before,
                         "an unchanged status must not spam the UI")


class TestLivePush(CollectorCase):
    async def test_pushed_records_are_appended_without_a_tick(self):
        await self.col.tick()
        appended = []
        self.col.history_appended.connect(
            lambda p: appended.append(json.loads(p)))
        payload = json.dumps([raw("pushed", idx=4)])
        added = await self.col.handle_push(payload)
        self.assertEqual(added, 1)
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 5)
        self.assertEqual(appended[0]["nick"], "Nick")
        self.assertEqual(len(appended[0]["items"]), 1)

    async def test_push_before_any_conversation_is_ignored(self):
        added = await self.col.handle_push(json.dumps([raw("stray", idx=0)]))
        self.assertEqual(added, 0)

    async def test_malformed_push_cannot_kill_the_collector(self):
        await self.col.tick()
        self.assertEqual(await self.col.handle_push("{not json"), 0)
        self.assertEqual(await self.col.handle_push(json.dumps({"x": 1})), 0)
        self.assertEqual(await self.col.tick(), CollectorState.NO_NEW)

    async def test_a_push_and_a_tick_never_double_store(self):
        await self.col.tick()
        extra = raw("both", idx=4)
        self.page.append(extra)
        await self.col.handle_push(json.dumps([extra]))
        await self.col.tick()
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 5)


class TestThrottleAndPacing(CollectorCase):
    async def test_run_active_marks_the_status_and_slows_the_loop(self):
        base = self.col.next_interval_ms()
        self.col.on_run_started()
        self.assertTrue(self.col.state_payload()["throttled"])
        self.assertEqual(self.col.next_interval_ms(), base * 4)
        self.col.on_run_finished()
        self.assertFalse(self.col.state_payload()["throttled"])
        self.assertEqual(self.col.next_interval_ms(), base)

    async def test_collection_continues_while_throttled(self):
        self.col.on_run_started()
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.assertIn("throttled", self.col.state_payload()["text"])
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 4)

    async def test_idle_states_back_off(self):
        self.page.tab = "room"
        await self.col.tick()
        self.assertEqual(self.col.next_interval_ms(), 3000)

    async def test_a_slow_page_backs_off_further(self):
        await self.col.tick()
        self.col.note_probe_duration(0.9)
        self.assertGreater(self.col.next_interval_ms(), 1000)


class TestResilience(CollectorCase):
    async def test_agent_loss_is_healed(self):
        await self.col.tick()
        self.page.agent_version = 0            # Angular re-rendered
        self.page.append(raw("after rerender", idx=4))
        state = await self.col.tick()
        self.assertEqual(self.page.installs, 1)
        self.assertEqual(state, CollectorState.COLLECTED)
        self.assertEqual(self.col.state_payload()["self_heals"], 1)

    async def test_probe_failure_becomes_an_error_and_then_recovers(self):
        async def boom(_expr):
            raise RuntimeError("page went away")

        good = self.page.evaluate
        self.page.evaluate = boom
        self.assertEqual(await self.col.tick(), CollectorState.ERROR)
        self.assertIn("page went away", self.col.state_payload()["error"])
        self.page.evaluate = good
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.assertEqual(self.col.state_payload()["error"], "")

    async def test_stop_ends_the_loop_without_losing_the_archive(self):
        await self.col.tick()
        self.col.stop()
        self.assertFalse(self.col.running)
        self.assertEqual(await self.col.tick(), CollectorState.OFF)
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 4)

    async def test_run_loop_starts_and_stops_cleanly(self):
        task = asyncio.ensure_future(self.col.run())
        await asyncio.sleep(0.05)
        self.col.stop()
        await asyncio.wait_for(task, timeout=2)
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 4)


class TestSettings(CollectorCase):
    async def test_settings_round_trip(self):
        self.col.configure(heartbeat_ms=2500, my_nick="Другой",
                           require_two_participants=False)
        settings = self.col.settings()
        self.assertEqual(settings["heartbeat_ms"], 2500)
        self.assertEqual(settings["my_nick"], "Другой")
        self.assertFalse(settings["require_two_participants"])

    async def test_unknown_settings_are_ignored_not_fatal(self):
        self.col.configure(nonsense=True)
        self.assertNotIn("nonsense", self.col.settings())

    async def test_state_payload_shape(self):
        await self.col.tick()
        payload = self.col.state_payload()
        for key in ("state", "text", "nick", "my_nick", "added", "total",
                    "throttled", "error", "warning", "self_heals", "agent"):
            self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
