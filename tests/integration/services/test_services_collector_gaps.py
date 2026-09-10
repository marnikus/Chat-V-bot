"""services/collector_service — the gaps beyond test_collector_state.py.

test_collector_state.py (31 tests) already pins the detection table, the
status vocabulary, live push, throttling, self-healing and probe failure.
This file covers the remaining seams (docs/archive/2026-09-09-test-suite/SERVICES_TEST_DESIGN_2026-09-09.md §2.8): timeouts, volatile-state reset, person_cleared,
manual backfill and the memory-queue bridge in `_remember_partner`.

Run with:  python3 tests/integration/services/test_services_collector_gaps.py
"""

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from backend.chat_parser import ChatParser  # noqa: E402
from backend.history_db import HistoryDB  # noqa: E402
from backend.history_repo import HistoryRepo  # noqa: E402
from services.collector_service import Collector, CollectorState  # noqa: E402
from stores.user_memory import UserMemory, UserRecord  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "tests"))
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
        self.memory = UserMemory(os.path.join(self.dir, "users.db"))
        await self.memory.init()
        self.col = Collector(cdp=self.page, repo=self.repo,
                             parser=self.parser, media=None,
                             settings={"heartbeat_ms": 1000,
                                       "idle_heartbeat_ms": 3000,
                                       "throttle_factor": 4,
                                       "my_nick": "Me"},
                             memory=self.memory)
        self.col.now = lambda: NOW

    async def asyncTearDown(self):
        await self.memory.close()
        await self.db.close()


class TestTimeout(CollectorCase):
    async def test_timeout_becomes_error_then_recovers(self):
        async def hang(_expr):
            raise asyncio.TimeoutError("probe timed out")

        good = self.page.evaluate
        self.page.evaluate = hang
        state = await self.col.tick()
        self.assertEqual(state, CollectorState.ERROR)
        self.assertIn("probe timed out", self.col.state_payload()["error"])
        self.page.evaluate = good
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)


class TestResetState(CollectorCase):
    async def test_reset_state_forgets_everything_volatile(self):
        await self.col.tick()
        self.assertNotEqual(self.col._nick, "")
        self.assertGreater(self.col._total, 0)
        self.col._verified = True
        self.col._probe_penalty = 7.0
        self.col.reset_state()
        self.assertEqual(self.col._nick, "")
        self.assertEqual(self.col._text, "")
        self.assertFalse(self.col._verified)
        self.assertEqual(self.col._added, 0)
        self.assertEqual(self.col._total, 0)
        self.assertEqual(self.col._error, "")
        # the probe penalty describes CDP reliability, NOT the conversation —
        # a DB swap must not forget how flaky the connection is
        self.assertEqual(self.col._probe_penalty, 7.0)
        self.assertEqual(self.col._last_probe, {})
        self.assertEqual(self.col._last_emitted, ())
        # after reset a tick re-detects the partner; the DB cursor still
        # knows the 4 lines, so nothing is duplicated (no_new is fine)
        self.assertIn(await self.col.tick(),
                      (CollectorState.COLLECTED, CollectorState.NO_NEW))
        self.assertEqual(self.col._added, 0)
        self.assertEqual(self.col._total, 4)
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 4)


class TestPersonCleared(CollectorCase):
    async def test_clearing_the_current_partner_zeroes_totals(self):
        await self.col.tick()
        self.assertEqual(self.col._nick, "Nick")
        self.assertEqual(self.col._total, 4)
        self.col.person_cleared("Nick")
        self.assertEqual(self.col._total, 0)
        self.assertEqual(self.col._added, 0)
        self.assertEqual(self.col._last_sync_reason, "history_cleared")
        self.assertEqual(self.col._last_sync_count, 0)

    async def test_clearing_another_partner_is_a_noop(self):
        await self.col.tick()
        before = (self.col._total, self.col._added)
        self.col.person_cleared("Other")
        self.col.person_cleared("")
        self.assertEqual((self.col._total, self.col._added), before)

    async def test_nick_is_normalized_before_compare(self):
        await self.col.tick()
        self.assertEqual(self.col._total, 4)
        self.col.person_cleared("  Nick  ")      # trimmed + collapsed
        self.assertEqual(self.col._total, 0, "whitespace-padded nick must match")


class TestBackfill(CollectorCase):
    async def test_backfill_without_partner_warns(self):
        state = await self.col.backfill_older()
        self.assertEqual(state, self.col._state)
        self.assertEqual(self.col._force_backfill, False)

    async def test_backfill_resets_cursor_and_forces_a_pass(self):
        await self.col.tick()
        self.assertEqual(self.col._total, 4)
        state = await self.col.backfill_older()
        self.assertIn(state, (CollectorState.COLLECTED, CollectorState.NO_NEW,
                              CollectorState.BOOTSTRAPPING))
        # the force flag is consumed by the pass it triggered
        self.assertFalse(self.col._force_backfill)
        # replay must never duplicate rows
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 4)


class TestRememberPartner(CollectorCase):
    async def test_archive_only_when_no_memory_store(self):
        self.col.memory = None
        result = await self.col._remember_partner("Nick")
        self.assertEqual(result, "archive_only")
        person = await self.repo.get_person("Nick")
        self.assertIsNotNone(person)

    async def test_new_partner_is_notified_once(self):
        notified = []
        self.col.people_changed.connect(
            lambda p: notified.append(p))
        result = await self.col._remember_partner("Nick")
        self.assertEqual(result, "new")
        self.assertEqual(len(notified), 1)
        # second time — known, no second notification
        result = await self.col._remember_partner("Nick")
        self.assertEqual(result, "known")
        self.assertEqual(len(notified), 1)

    async def test_memory_failure_returns_error_not_raise(self):
        class BoomMemory:
            async def get_user(self, nick):
                raise RuntimeError("queue down")

        self.col.memory = BoomMemory()
        result = await self.col._remember_partner("Nick")
        self.assertEqual(result, "error")

    async def test_existing_messaged_flag_is_kept(self):
        await self.memory.upsert_user(UserRecord(nick="Nick"))
        await self.memory.mark_messaged("Nick")   # seed the Done flag
        result = await self.col._remember_partner("Nick")
        self.assertEqual(result, "known")
        row = await self.memory.get_user("Nick")
        self.assertTrue(row.messaged, "a refresh must not clear the flag")
        self.assertEqual(row.message_count, 1)


class TestSettingsSurface(CollectorCase):
    async def test_configure_ignores_unknown_keys(self):
        self.col.configure(nonsense=True, my_nick="Alice")
        settings = self.col.settings()
        self.assertNotIn("nonsense", settings)
        self.assertEqual(settings["my_nick"], "Alice")

    async def test_state_payload_has_the_full_vocabulary(self):
        self.col.on_run_started()
        payload = self.col.state_payload()
        for key in ("state", "text", "nick", "my_nick", "added", "total",
                    "throttled", "error", "warning", "self_heals", "agent"):
            self.assertIn(key, payload)
        self.assertTrue(payload["throttled"])

    async def test_run_loop_exits_promptly_on_stop(self):
        task = asyncio.ensure_future(self.col.run())
        await asyncio.sleep(0.1)
        self.assertTrue(self.col.running)
        self.col.stop()
        await asyncio.wait_for(task, timeout=3)
        self.assertFalse(self.col.running)

    async def test_pause_resume_round_trip(self):
        self.col.pause()
        self.assertEqual(await self.col.tick(), CollectorState.PAUSED)
        self.col.resume()
        self.assertNotEqual(await self.col.tick(), CollectorState.PAUSED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
