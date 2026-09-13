"""services/collector_service — tick phase contract (AREA C).

test_collector_state.py and test_services_collector_gaps.py pin the status
vocabulary, push channel, throttling, reset and backfill seams. This file
pins the _tick PHASE MATRIX the refactor must preserve verbatim
(docs/archive/2026-09-09-four-area-refactor/REFACTOR_2026-09-09_AREA_C_DESIGN.md §3.3):

  probe phase   — agent self-heal, last_probe payload, refusal gates;
  nick phase    — My-Nick adoption (single author, stale saved nick);
  gate phase    — the two-step private-chat gate through tick();
  archive phase — rename continuation, person rows, cursor/unchanged,
                  backfill planning, sync outcomes (added / not-ok / none),
                  media repair counters, the COLLECTED / NO_NEW statuses.

Every test drives the PUBLIC `Collector.tick()` — the refactor is only
allowed to move code, not to change any of these observables.

Run with:  python3 -m pytest tests/integration/services/test_collector_tick_phases.py
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from backend.chat_parser import ChatParser  # noqa: E402
from backend.history_db import HistoryDB  # noqa: E402
from backend.history_repo import HistoryRepo  # noqa: E402
from services.collector_service import Collector, CollectorState  # noqa: E402
from stores.history_models import SyncResult  # noqa: E402
from stores.user_memory import UserMemory, UserRecord  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "tests"))
from test_chat_parser_delta import FakePage, raw  # noqa: E402

NOW = datetime(2026, 9, 6, 18, 30, 0)


class ConnectedPage(FakePage):
    is_connected = True


class FakeMedia:
    """Media drain recorder — enough of MediaStore for the tick paths."""

    def __init__(self):
        self.pending_calls = 0
        self.evict_calls = 0

    async def process_pending(self):
        self.pending_calls += 1

    async def evict_if_needed(self):
        self.evict_calls += 1


class TickCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = HistoryDB(os.path.join(self.dir, "history.db"))
        await self.db.init()
        self.repo = HistoryRepo(self.db, session_id="s")
        self.memory = UserMemory(os.path.join(self.dir, "users.db"))
        await self.memory.init()
        self.media = FakeMedia()
        self.page = ConnectedPage([raw(f"m{i}", from_nick="Nick", idx=i)
                                   for i in range(3)])
        self.parser = ChatParser(self.page, chunk_size=10, chunk_pause_ms=0)
        self.col = Collector(cdp=self.page, repo=self.repo,
                             parser=self.parser, media=self.media,
                             settings={"heartbeat_ms": 1000,
                                       "idle_heartbeat_ms": 3000,
                                       "throttle_factor": 4,
                                       "my_nick": "Me",
                                       "require_two_participants": True,
                                       "require_private": True,
                                       "download_media": True},
                             memory=self.memory)
        self.col.now = lambda: NOW
        self.logs = []
        self.col.collector_log.connect(lambda p: self.logs.append(json.loads(p)))

    async def asyncTearDown(self):
        await self.memory.close()
        await self.db.close()

    async def collect_all(self):
        """A normal pass: 3 lines from Nick."""
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.assertEqual(self.col._added, 3)
        self.assertEqual(self.col._total, 3)
        self.assertEqual(self.col._nick, "Nick")

    def log_lines(self, contains=""):
        return [p["message"] for p in self.logs if contains in p["message"]]


# ══════════════════════════════════════════════════════════════════
# probe phase
# ══════════════════════════════════════════════════════════════════
class TestProbePhase(TickCase):
    async def test_stale_agent_is_reinstalled_and_self_heal_counted(self):
        self.page.agent_version = 0
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.assertEqual(self.page.installs, 1)
        self.assertEqual(self.col._self_heals, 1)
        self.assertTrue(self.log_lines("Re-installed the in-page agent"))

    async def test_last_probe_payload_is_captured(self):
        await self.collect_all()
        probe = self.col._last_probe
        self.assertEqual(probe["count"], 3)
        self.assertEqual(probe["participants"], 2)
        self.assertEqual(probe["partner"], "Nick")
        self.assertIn("in_authors", probe)
        self.assertIn("out_authors", probe)
        self.assertIn("panes", probe)

    async def test_not_ok_state_is_refused(self):
        async def broken(_expr):
            return json.dumps({"ok": False, "agent": 99})

        good = self.page.evaluate
        self.page.evaluate = broken
        self.assertEqual(await self.col.tick(), CollectorState.NOT_PRIVATE)
        self.assertEqual(self.col._text, "Not in private tab now")
        self.page.evaluate = good
        await self.collect_all()

    async def test_group_tab_is_refused(self):
        self.page.tab = "group"
        self.assertEqual(await self.col.tick(), CollectorState.NOT_PRIVATE)

    async def test_three_participants_are_refused_as_group(self):
        self.page.participants = 3
        self.assertEqual(await self.col.tick(), CollectorState.GROUP_TAB)
        self.assertIn("Group tab", self.col._text)

    async def test_any_participant_count_is_allowed_when_requirement_off(self):
        self.col.configure(require_two_participants=False)
        self.page.participants = 3
        state = await self.col.tick()
        self.assertNotEqual(state, CollectorState.GROUP_TAB)

    async def test_empty_partner_nick_is_refused(self):
        self.page.partner = ""
        self.assertEqual(await self.col.tick(), CollectorState.NOT_PRIVATE)


# ══════════════════════════════════════════════════════════════════
# nick phase
# ══════════════════════════════════════════════════════════════════
class TestNickPhase(TickCase):
    async def test_partner_equal_to_my_nick_is_refused(self):
        self.page.partner = "Me"
        self.assertEqual(await self.col.tick(), CollectorState.NOT_PRIVATE)
        self.assertIn("ambiguous", self.col._text)

    async def test_single_out_author_is_adopted_as_my_nick(self):
        self.col.configure(my_nick="")
        self.page.me = ""
        # outbound messages from "Alice" while the pane has no `me`:
        # the single out author who is not the partner becomes My Nick
        self.page.messages = [
            raw("x", from_nick="Alice", direction="out", idx=0)] + [
            raw(f"m{i}", from_nick="Nick", idx=i) for i in range(3)]
        state = await self.col.tick()
        self.assertIn(state, (CollectorState.COLLECTED, CollectorState.NO_NEW))
        self.assertEqual(self.col.my_nick, "Alice")
        self.assertTrue(self.log_lines("Detected My Nick"))

    async def test_stale_saved_nick_is_replaced_when_page_differs(self):
        self.col.configure(my_nick="OldName")
        self.page.me = "NewName"
        await self.collect_all()
        self.assertEqual(self.col.my_nick, "NewName")
        self.assertTrue(self.log_lines("My Nick changed"))


# ══════════════════════════════════════════════════════════════════
# gate phase
# ══════════════════════════════════════════════════════════════════
class TestGatePhase(TickCase):
    async def test_strangers_refuse_as_group_tab(self):
        self.page.messages = [raw("m0", from_nick="Nick", direction="in",
                                  idx=0),
                              raw("m1", from_nick="Stranger",
                                  direction="in", idx=1)]
        self.assertEqual(await self.col.tick(), CollectorState.GROUP_TAB)
        self.assertIn("write here too", self.col._text)

    async def test_title_mismatch_is_refused(self):
        self.page.title = "Somebody Else"
        self.assertEqual(await self.col.tick(), CollectorState.NOT_PRIVATE)
        self.assertIn("does not match", self.col._text)


# ══════════════════════════════════════════════════════════════════
# archive phase
# ══════════════════════════════════════════════════════════════════
class TestArchivePhase(TickCase):
    async def test_rename_continues_the_history(self):
        await self.collect_all()
        # the site re-renders the same rows under the new nick (the
        # author-agnostic fingerprints stay identical): a rename, not a new
        # person — the archive continues under the new nick
        self.page.partner = "Nicky"
        self.page.title = None
        self.page.pane_same = True
        self.page.messages = [raw(f"m{i}", from_nick="Nicky", idx=i)
                              for i in range(3)]
        state = await self.col.tick()
        self.assertIn(state, (CollectorState.COLLECTED, CollectorState.NO_NEW))
        self.assertEqual(self.col._nick, "Nicky")
        self.assertTrue(self.log_lines("the history continues"))
        person = await self.repo.get_person("Nicky")
        self.assertEqual(person["message_count"], 3)

    async def test_unchanged_cursor_returns_no_new_and_still_drains_media(self):
        await self.collect_all()
        drains = self.media.pending_calls
        self.assertEqual(await self.col.tick(), CollectorState.NO_NEW)
        self.assertEqual(self.col._last_sync_reason, "unchanged_cursor")
        self.assertEqual(self.col._added, 0)
        self.assertGreater(self.media.pending_calls, drains)
        self.assertGreater(self.media.evict_calls, 0)

    async def test_new_messages_emit_history_appended(self):
        await self.collect_all()
        payloads = []
        self.col.history_appended.connect(lambda p: payloads.append(p))
        self.page.messages.append(raw("m3", from_nick="Nick", idx=3))
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.assertEqual(self.col._added, 1)
        self.assertEqual(self.col._total, 4)
        self.assertEqual(len(payloads), 1)
        payload = json.loads(payloads[0])
        self.assertEqual(payload["nick"], "Nick")
        self.assertEqual(payload["added"], 1)
        self.assertEqual(payload["total"], 4)
        self.assertTrue(payload["items"])

    async def test_bootstrap_and_backfill_planning(self):
        """A fresh repo: bootstrap pass with auto-backfill requested."""
        syncs = []

        async def fake_sync(parser, repo, nick, **kwargs):
            syncs.append((nick, kwargs))
            return SyncResult(ok=True, added=0, total=0, count=3,
                              reason="bootstrap", records=[])

        with mock.patch("services.collector_service.sync_conversation",
                        fake_sync):
            state = await self.col.tick()
        self.assertEqual(state, CollectorState.NO_NEW)
        nick, kwargs = syncs[0]
        self.assertEqual(nick, "Nick")
        self.assertTrue(kwargs["backfill_older"])
        self.assertIsNone(kwargs["max_messages"])   # max_bootstrap=0 → no cap

    async def test_sync_failure_returns_not_private(self):
        await self.collect_all()
        self.page.messages.append(raw("m3", from_nick="Nick", idx=3))
        with mock.patch(
                "services.collector_service.sync_conversation",
                new=lambda *a, **k: _coro(SyncResult(ok=False, added=0,
                                                     reason="boom",
                                                     count=4, total=3,
                                                     records=[]))):
            self.assertEqual(await self.col.tick(),
                             CollectorState.NOT_PRIVATE)
        self.assertTrue(self.log_lines("Sync failed"))

    async def test_media_repair_counters_reach_the_status_payload(self):
        await self.collect_all()
        self.page.messages.append(raw("m3", from_nick="Nick", idx=3))
        with mock.patch(
                "services.collector_service.sync_conversation",
                new=lambda *a, **k: _coro(
                    SyncResult(ok=True, added=0, total=3, count=4,
                               reason="media", records=[],
                               media_repaired=2, media_requeued=3))):
            await self.col.tick()
        self.assertEqual(self.col._last_media_repaired, 2)
        self.assertEqual(self.col._last_media_requeued, 3)
        payload = self.col.state_payload()
        self.assertEqual(payload["media_repaired"], 2)
        self.assertEqual(payload["media_requeued"], 3)
        self.assertTrue(self.log_lines("Media recovery"))


# ══════════════════════════════════════════════════════════════════
# throttling surface
# ══════════════════════════════════════════════════════════════════
class TestIntervals(TickCase):
    async def test_idle_interval_differs_from_active_and_throttle_applies(self):
        idle = self.col.next_interval_ms()
        await self.collect_all()
        active = self.col.next_interval_ms()
        self.assertNotEqual(idle, active)
        self.col.on_run_started()
        self.assertEqual(self.col.next_interval_ms(), active * 4)

    async def test_probe_penalty_scales_the_interval(self):
        await self.collect_all()
        base = self.col.next_interval_ms()
        self.col.note_probe_duration(0.4)     # 4× penalty (capped at 4.0)
        self.assertEqual(self.col.next_interval_ms(), base * 4)
        self.col.note_probe_duration(2.0)
        self.assertEqual(self.col.next_interval_ms(), base * 4)
        self.col.note_probe_duration(0.05)
        self.assertEqual(self.col.next_interval_ms(), base)


def _coro(result):
    async def inner():
        return result

    return inner()


if __name__ == "__main__":
    unittest.main(verbosity=2)
