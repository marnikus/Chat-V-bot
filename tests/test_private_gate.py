"""Bug #1 — the two-step private-chat gate.

The archive may only grow when BOTH checks pass:

  STEP 1  the conversation on screen contains exactly two nicks — mine and
          the partner's. A third author means it is not a private chat
          (the main room, a group tab, a pane that was mixed in…).
  STEP 2  the ACTIVE tab title names that same partner.

Any failure ⇒ nothing is written, for the tick path *and* for the live push
path (the in-page observer). The bug report shows what happens otherwise:
main-room lines from `Макс__Б` archived inside «Ански»'s private history.

Run with:  python3 tests/test_private_gate.py
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.chat_agent_js import AGENT_VERSION  # noqa: E402
from backend.chat_parser import (  # noqa: E402
    ChatParser,
    sync_conversation,
    verify_private,
)
from services.collector_service import Collector, CollectorState  # noqa: E402
from stores.history_db import HistoryDB  # noqa: E402
from stores.history_repo import HistoryRepo  # noqa: E402
from stores.user_memory import UserMemory  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_chat_parser_delta import FakePage, raw  # noqa: E402

NOW = datetime(2026, 9, 7, 12, 0, 0)
PARTNER = "Ански"
ME = "Хорошо Все"
STRANGER = "Макс__Б"


def state(**over):
    base = {"ok": True, "agent": AGENT_VERSION, "tab": "private",
            "partner": PARTNER, "title": PARTNER, "me": ME,
            "participants": 2, "count": 2,
            "in_authors": [PARTNER], "out_authors": [ME],
            "authors": [PARTNER, ME]}
    base.update(over)
    return base


# ── the pure gate ────────────────────────────────────────────────

class TestVerifyPrivate(unittest.TestCase):
    def test_a_clean_private_chat_passes(self):
        check = verify_private(state(), PARTNER, ME)
        self.assertTrue(check.ok)
        self.assertEqual(check.reason, "ok")
        self.assertEqual(check.strangers, [])

    def test_the_main_room_tab_is_refused(self):
        check = verify_private(state(tab="room"), PARTNER, ME)
        self.assertFalse(check.ok)
        self.assertEqual(check.reason, "not_private")

    def test_a_third_author_is_refused(self):
        check = verify_private(
            state(in_authors=[PARTNER, STRANGER],
                  authors=[PARTNER, STRANGER, ME], count=3), PARTNER, ME)
        self.assertFalse(check.ok)
        self.assertEqual(check.reason, "strangers")
        self.assertEqual(check.strangers, [STRANGER])
        self.assertIn(STRANGER, check.detail)

    def test_a_room_full_of_people_is_refused_even_on_a_private_tab(self):
        check = verify_private(
            state(in_authors=[STRANGER, "Lizalo4ka", PARTNER],
                  authors=[STRANGER, "Lizalo4ka", PARTNER, ME]), PARTNER, ME)
        self.assertFalse(check.ok)
        self.assertEqual(check.reason, "strangers")
        self.assertEqual(check.strangers, [STRANGER, "Lizalo4ka"])

    def test_the_tab_title_must_name_the_partner(self):
        check = verify_private(state(title="Lizalo4ka", partner="Lizalo4ka"),
                               PARTNER, ME)
        self.assertFalse(check.ok)
        self.assertEqual(check.reason, "title_mismatch")

    def test_a_trailing_space_in_the_tab_title_is_tolerated(self):
        self.assertTrue(verify_private(state(title=PARTNER + " "),
                                       PARTNER, ME).ok)

    def test_case_and_inner_spacing_are_normalised(self):
        self.assertTrue(
            verify_private(state(title="хорошо  ВСЕ", partner="хорошо  ВСЕ",
                                 in_authors=["Хорошо Все"],
                                 out_authors=["Ански"],
                                 authors=["Хорошо Все", "Ански"]),
                           "Хорошо Все", "Ански").ok)

    def test_a_title_that_contains_the_nick_still_counts(self):
        # some skins add an unread badge or a status suffix to the title
        self.assertTrue(verify_private(state(title=PARTNER + " (2)"),
                                       PARTNER, ME).ok)

    def test_an_empty_tab_title_is_refused(self):
        check = verify_private(state(title="", partner=""), PARTNER, ME)
        self.assertFalse(check.ok)
        self.assertEqual(check.reason, "no_partner")

    def test_saving_under_my_own_nick_is_refused(self):
        check = verify_private(state(title=ME, partner=ME), ME, ME)
        self.assertFalse(check.ok)
        self.assertEqual(check.reason, "self_chat")

    def test_a_foreign_outbound_author_is_a_stranger(self):
        check = verify_private(state(out_authors=["SomeoneElse"],
                                     authors=[PARTNER, "SomeoneElse"]),
                               PARTNER, ME)
        self.assertFalse(check.ok)
        self.assertEqual(check.reason, "strangers")

    def test_without_my_nick_the_single_outbound_author_is_adopted(self):
        check = verify_private(state(), PARTNER, "")
        self.assertTrue(check.ok)
        self.assertEqual(check.me, ME)

    def test_without_my_nick_two_outbound_authors_are_still_refused(self):
        check = verify_private(state(out_authors=[ME, STRANGER],
                                     authors=[PARTNER, ME, STRANGER]),
                               PARTNER, "")
        self.assertFalse(check.ok)
        self.assertEqual(check.reason, "strangers")

    def test_an_empty_conversation_passes_the_author_check(self):
        check = verify_private(state(count=0, in_authors=[], out_authors=[],
                                     authors=[]), PARTNER, ME)
        self.assertTrue(check.ok)

    def test_an_agent_that_reports_no_authors_at_all_is_refused(self):
        blind = state()
        for key in ("in_authors", "out_authors", "authors"):
            blind.pop(key)
        check = verify_private(blind, PARTNER, ME)
        self.assertFalse(check.ok)
        self.assertEqual(check.reason, "no_author_data")

    def test_the_gate_also_accepts_a_list_of_records(self):
        items = [{"dir": "in", "from": PARTNER}, {"dir": "out", "from": ME},
                 {"dir": "in", "from": STRANGER}]
        check = verify_private(state(), PARTNER, ME, items=items)
        self.assertFalse(check.ok)
        self.assertEqual(check.strangers, [STRANGER])


# ── the collector ────────────────────────────────────────────────

class ConnectedPage(FakePage):
    is_connected = True


class GateCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = HistoryDB(os.path.join(self.dir, "history.db"))
        await self.db.init()
        self.repo = HistoryRepo(self.db, session_id="gate")
        self.page = ConnectedPage(
            [raw("привет", from_nick=PARTNER, time="11:55", idx=0),
             raw("привет :)", direction="out", from_nick=ME, time="11:58",
                 idx=1)],
            partner=PARTNER, me=ME)
        self.parser = ChatParser(self.page, chunk_size=10, chunk_pause_ms=0)
        self.col = Collector(cdp=self.page, repo=self.repo,
                             parser=self.parser, media=None,
                             settings={"my_nick": ME})
        self.col.now = lambda: NOW

    async def asyncTearDown(self):
        await self.db.close()

    async def stored(self, nick=PARTNER):
        person = await self.repo.get_person(nick)
        return int((person or {}).get("message_count") or 0)


class TestCollectorGate(GateCase):
    async def test_a_verified_private_chat_is_collected(self):
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.assertEqual(await self.stored(), 2)

    async def test_a_stranger_in_the_pane_blocks_the_save(self):
        self.page.messages.insert(1, raw("всем привет", from_nick=STRANGER,
                                         time="11:57", idx=1))
        self.assertEqual(await self.col.tick(), CollectorState.GROUP_TAB)
        self.assertEqual(await self.stored(), 0)
        self.assertIn(STRANGER, self.col.state_payload()["text"])
        self.assertEqual(self.page.slice_calls, [],
                         "a refused chat must not even be sliced")

    async def test_the_stranger_check_survives_the_next_ticks(self):
        self.page.messages.append(raw("ку", from_nick=STRANGER, time="11:59",
                                      idx=2))
        for _ in range(3):
            self.assertEqual(await self.col.tick(), CollectorState.GROUP_TAB)
        self.assertEqual(await self.stored(), 0)

    async def test_a_tab_title_naming_somebody_else_blocks_the_save(self):
        self.page.title = "Lizalo4ka"
        self.assertEqual(await self.col.tick(), CollectorState.NOT_PRIVATE)
        self.assertEqual(await self.stored(), 0)
        self.assertEqual(await self.stored("Lizalo4ka"), 0)

    async def test_the_room_tab_is_never_archived(self):
        self.page.tab = "room"
        self.page.messages = [raw("всем привет", from_nick=STRANGER, idx=0),
                              raw("ку", from_nick="Lizalo4ka", idx=1)]
        self.assertEqual(await self.col.tick(), CollectorState.NOT_PRIVATE)
        self.assertEqual(self.col.state_payload()["text"],
                         "Not in private tab now")
        self.assertEqual(await self.stored(STRANGER), 0)

    async def test_recovery_once_the_stranger_pane_is_gone(self):
        self.page.messages.append(raw("ку", from_nick=STRANGER, idx=2))
        self.assertEqual(await self.col.tick(), CollectorState.GROUP_TAB)
        self.page.messages.pop()
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.assertEqual(await self.stored(), 2)

    async def test_an_old_agent_is_re_installed_before_anything_is_saved(self):
        self.page.agent_version = 3
        await self.col.tick()
        self.assertGreaterEqual(self.page.installs, 1)
        self.assertEqual(self.col.state_payload()["agent"], AGENT_VERSION)

    async def test_manual_backfill_scrolls_even_when_auto_backfill_is_off(self):
        self.col.configure(auto_backfill=False)
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.page.prepend_on_scroll = [
            raw("самое первое", from_nick=PARTNER, time="11:55", idx=0),
            raw("затем моё", direction="out", from_nick=ME, time="11:58",
                idx=1)]
        self.page.scroll_top = 120
        self.assertEqual(await self.col.backfill_older(),
                         CollectorState.COLLECTED)
        self.assertEqual(self.page.scroll_top_calls, 1)
        self.assertEqual(await self.stored(), 4)

    async def test_an_unknown_partner_is_added_to_both_the_archive_and_people(self):
        memory = UserMemory(os.path.join(self.dir, "people.db"))
        await memory.init()
        self.col.memory = memory
        seen = []
        self.col.people_changed.connect(lambda j: seen.append(j))
        try:
            self.page.messages = [
                raw("ты тут?", from_nick=PARTNER, time="11:55", idx=0),
                raw("да", direction="out", from_nick=ME, time="11:58", idx=1)]
            self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
            person = await self.repo.get_person(PARTNER)
            self.assertEqual(person["message_count"], 2)
            user = await memory.get_user(PARTNER)
            self.assertIsNotNone(user)
            self.assertFalse(user.messaged,
                             "discovery must not mark the person messaged")
            self.assertEqual(len(seen), 1)
            self.assertEqual(json.loads(seen[0])["nick"], PARTNER)
            # a second tick must not emit another people_changed
            self.assertEqual(await self.col.tick(), CollectorState.NO_NEW)
            self.assertEqual(len(seen), 1)
        finally:
            await memory.close()

    async def test_my_nick_is_adopted_from_the_single_outbound_author(self):
        self.col.configure(my_nick="")
        self.page.me = ""
        self.page.messages = [
            raw("ты тут?", from_nick=PARTNER, time="11:55", idx=0),
            raw("да", direction="out", from_nick=ME, time="11:58", idx=1)]
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.assertEqual(self.col.my_nick, ME,
                         "the single outbound author is adopted as me")
        payload = self.col.state_payload()
        self.assertEqual(payload["warning"], "")
        self.assertEqual(await self.stored(), 2)

    async def test_first_tick_backfills_older_and_marks_the_full_scan(self):
        self.page.messages = [
            raw("мне привет", from_nick=PARTNER, time="12:00", idx=0),
            raw("привет :)", direction="out", from_nick=ME, time="12:01",
                idx=1)]
        self.page.prepend_on_scroll = [
            raw("самое первое", from_nick=PARTNER, time="11:55", idx=0),
            raw("затем моё", direction="out", from_nick=ME, time="11:58",
                idx=1)]
        self.page.scroll_top = 120
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        pid = await self.repo.ensure_person(PARTNER)
        cur = await self.repo.get_cursor(pid)
        self.assertTrue(cur["full_scan_complete"])
        self.assertEqual(self.page.scroll_top_calls, 1)
        before = self.page.scroll_top_calls
        self.assertEqual(await self.col.tick(), CollectorState.NO_NEW)
        self.assertEqual(self.page.scroll_top_calls, before,
                         "once complete, the heart beat must not re-scroll")
        self.assertEqual(await self.stored(), 4)


class TestPushGate(GateCase):
    def push(self, items, **over):
        payload = {"kind": "append", "agent": AGENT_VERSION, "tab": "private",
                   "partner": PARTNER, "title": PARTNER, "me": ME,
                   "count": len(items), "items": items}
        payload.update(over)
        return json.dumps(payload, ensure_ascii=False)

    async def test_a_verified_push_is_stored(self):
        await self.col.tick()
        added = await self.col.handle_push(
            self.push([raw("ты тут?", from_nick=PARTNER, time="12:01",
                           idx=2)]))
        self.assertEqual(added, 1)
        self.assertEqual(await self.stored(), 3)

    async def test_a_push_carrying_a_stranger_is_dropped_whole(self):
        await self.col.tick()
        items = [raw("всем привет", from_nick=STRANGER, time="12:01", idx=2),
                 raw("ты тут?", from_nick=PARTNER, time="12:02", idx=3)]
        self.assertEqual(await self.col.handle_push(self.push(items)), 0)
        self.assertEqual(await self.stored(), 2)

    async def test_a_push_from_the_room_tab_is_dropped(self):
        await self.col.tick()
        items = [raw("всем привет", from_nick=STRANGER, time="12:01", idx=2)]
        self.assertEqual(
            await self.col.handle_push(self.push(items, tab="room")), 0)
        self.assertEqual(await self.stored(), 2)
        self.assertEqual(await self.stored(STRANGER), 0)

    async def test_a_push_for_another_partner_is_dropped(self):
        await self.col.tick()
        items = [raw("ку", from_nick="Lizalo4ka", time="12:01", idx=2)]
        self.assertEqual(
            await self.col.handle_push(
                self.push(items, partner="Lizalo4ka", title="Lizalo4ka")), 0)
        self.assertEqual(await self.stored(), 2)
        self.assertEqual(await self.stored("Lizalo4ka"), 0)

    async def test_pushes_are_ignored_until_a_tick_verified_the_chat(self):
        items = [raw("ты тут?", from_nick=PARTNER, time="12:01", idx=2)]
        self.assertEqual(await self.col.handle_push(self.push(items)), 0)
        self.assertEqual(await self.stored(), 0)

    async def test_a_refused_tick_disarms_the_push_channel(self):
        await self.col.tick()                       # verified
        self.page.tab = "room"                      # the user switches away
        await self.col.tick()
        items = [raw("ты тут?", from_nick=PARTNER, time="12:01", idx=2)]
        self.assertEqual(await self.col.handle_push(self.push(items)), 0)
        self.assertEqual(await self.stored(), 2)


# ── the shared sync entry point (used by the COLLECT_HISTORY block) ──

class TestSyncConversationGate(GateCase):
    async def test_sync_refuses_a_pane_with_a_third_author(self):
        self.page.messages.append(raw("ку", from_nick=STRANGER, idx=2))
        result = await sync_conversation(self.parser, self.repo, PARTNER,
                                         my_nick=ME, require_private=True,
                                         verify_partner=True, now=NOW)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "strangers")
        self.assertEqual(result.added, 0)
        self.assertEqual(await self.stored(), 0)

    async def test_sync_still_stores_a_clean_private_chat(self):
        result = await sync_conversation(self.parser, self.repo, PARTNER,
                                         my_nick=ME, require_private=True,
                                         verify_partner=True, now=NOW)
        self.assertTrue(result.ok)
        self.assertEqual(result.added, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
