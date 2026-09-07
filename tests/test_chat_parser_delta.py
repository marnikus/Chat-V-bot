"""Chat parser + delta algorithm (milestone M2).

This is the heart of "do not re-parse a big chat". The parser must:

  * turn one rendered message node into one record (direction from the CSS
    class, nick, text or media, HH:MM, occurrence within the minute);
  * compute stable fingerprints so the same DOM always produces the same
    identity;
  * align a freshly read conversation against what is already stored and
    append ONLY the tail;
  * do a full bootstrap in paced chunks, honouring stop between chunks
    (AGENT_RULES RULE 7) and reporting progress as it goes (RULE 5);
  * survive the four ways the page can move underneath it: new messages at
    the bottom, older messages prepended above, the buffer being trimmed,
    and a conversation switch.

The fake page below behaves like the real one: it holds message nodes,
answers the agent probes, and can be mutated between calls.

Run with:  python3 tests/test_chat_parser_delta.py
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.chat_parser import (  # noqa: E402
    ChatParser,
    align,
    parse_records,
    sync_conversation,
)
from backend.chat_agent_js import AGENT_VERSION  # noqa: E402
from backend.history_db import HistoryDB  # noqa: E402
from backend.history_models import fingerprint  # noqa: E402
from backend.history_repo import HistoryRepo  # noqa: E402

NOW = datetime(2026, 9, 6, 18, 30, 0)


def raw(text, direction="in", from_nick="Nick", time="17:31", kind="text",
        media=None, occ=0, idx=0):
    """One record exactly as the in-page agent emits it."""
    payload = media["url"] if media else text
    return {"fp": fingerprint(direction, from_nick, time, kind, payload, occ),
            "dir": direction, "from": from_nick, "kind": kind, "text": text,
            "media": media, "time": time, "occ": occ, "idx": idx}


class FakePage:
    """A chat page the parser can talk to through CDP-style evaluates."""

    def __init__(self, messages=None, tab="private", partner="Nick",
                 me="Me", participants=2, agent=True, title=None):
        self.messages = list(messages or [])
        self.tab, self.partner, self.me = tab, partner, me
        self.title = title              # None ⇒ the tab title IS the partner
        self.participants = participants
        self.agent_version = AGENT_VERSION if agent else 0
        self.installs = 0
        self.slice_calls = []
        self.queue = []
        self.evaluates = 0
        self.scroll_top = 0
        self.scroll_height = 200
        self.client_height = 100
        self.scroll_top_calls = 0
        self.restore_calls = []
        self.prepend_on_scroll = []

    # ── page mutations used by the tests ──
    def append(self, *records):
        self.messages.extend(records)
        self.queue.extend(records)

    def prepend(self, *records):
        self.messages = list(records) + self.messages

    def trim(self, keep):
        self.messages = self.messages[-keep:]

    def _authors(self, direction):
        """Distinct nicks per direction, exactly like the in-page agent."""
        seen = []
        for m in self.messages:
            if m.get("dir") != direction:
                continue
            nick = str(m.get("from") or "").strip()
            if nick and nick not in seen:
                seen.append(nick)
        return seen

    def _reindex(self):
        for i, m in enumerate(self.messages):
            m["idx"] = i

    async def evaluate(self, expression):
        self.evaluates += 1
        if "/*CVB_INSTALL*/" in expression:
            self.installs += 1
            self.agent_version = AGENT_VERSION
            return 3
        if "/*CVB_STATE*/" in expression:
            self._reindex()
            msgs = self.messages
            return json.dumps({
                "ok": True, "agent": self.agent_version, "tab": self.tab,
                "partner": self.partner, "me": self.me,
                "title": self.partner if self.title is None else self.title,
                "participants": self.participants,
                "in_authors": self._authors("in"),
                "out_authors": self._authors("out"),
                "authors": self._authors("in") + [
                    a for a in self._authors("out")
                    if a not in self._authors("in")],
                "count": len(msgs),
                "head": msgs[0]["fp"] if msgs else "",
                "tail": msgs[-1]["fp"] if msgs else "",
                "pending": len(self.queue),
                "scroll": {"top": self.scroll_top,
                           "height": self.scroll_height,
                           "client": self.client_height,
                           "atTop": self.scroll_top <= 4,
                           "atBottom": self.scroll_top + self.client_height
                           >= self.scroll_height - 4},
            })
        if "/*CVB_SLICE*/" in expression:
            self._reindex()
            payload = json.loads(expression.split("/*ARGS*/")[1]
                                 .split("/*END*/")[0])
            a, b = payload["from"], payload["to"]
            self.slice_calls.append((a, b))
            return json.dumps(self.messages[a:b])
        if "/*CVB_DRAIN*/" in expression:
            out, self.queue = self.queue, []
            return json.dumps(out)
        if "/*CVB_SCROLL_TOP*/" in expression:
            return json.dumps(self._scroll_to_top())
        if "/*CVB_RESTORE_SCROLL*/" in expression:
            payload = json.loads(expression.split("/*ARGS*/")[1]
                                 .split("/*END*/")[0])
            top = int(payload.get("top") or 0)
            self.scroll_top = top
            self.restore_calls.append(top)
            return json.dumps({"ok": True, "top": self.scroll_top})
        return None

    def _scroll_to_top(self):
        self.scroll_top_calls += 1
        before = self.scroll_top
        if self.scroll_top_calls == 1 and self.prepend_on_scroll:
            self.prepend(*self.prepend_on_scroll)
            self.prepend_on_scroll = []
        self.scroll_top = 0
        return {"ok": True, "beforeTop": before, "top": 0, "atTop": True,
                "height": self.scroll_height, "count": len(self.messages)}


async def make_repo():
    d = tempfile.mkdtemp()
    db = HistoryDB(os.path.join(d, "history.db"))
    await db.init()
    return db, HistoryRepo(db, session_id="t")


class TestAlign(unittest.TestCase):
    """Pure suffix alignment — the resume-point finder."""

    def test_no_history_means_everything_is_new(self):
        res = align(["a", "b", "c"], [])
        self.assertEqual(res.start, 0)
        self.assertFalse(res.gap)

    def test_perfect_overlap_appends_nothing(self):
        res = align(["a", "b", "c"], ["a", "b", "c"])
        self.assertEqual(res.start, 3)
        self.assertFalse(res.gap)

    def test_partial_overlap_appends_only_the_tail(self):
        res = align(["a", "b", "c", "d"], ["x", "a", "b", "c"])
        self.assertEqual(res.start, 3)
        self.assertFalse(res.gap)

    def test_single_message_overlap_is_enough(self):
        res = align(["c", "d", "e"], ["a", "b", "c"])
        self.assertEqual(res.start, 1)
        self.assertFalse(res.gap)

    def test_no_overlap_is_reported_as_a_gap(self):
        res = align(["x", "y"], ["a", "b", "c"])
        self.assertEqual(res.start, 0)
        self.assertTrue(res.gap)

    def test_prepended_history_does_not_re_add_the_known_tail(self):
        # the user scrolled up: older nodes appeared ABOVE what we know
        res = align(["old1", "old2", "a", "b", "c"], ["a", "b", "c"])
        self.assertEqual(res.start, 5)
        self.assertFalse(res.gap)

    def test_repeated_fingerprints_pick_the_last_occurrence(self):
        res = align(["a", "a", "a"], ["a"])
        self.assertEqual(res.start, 3)


class TestRecordParsing(unittest.TestCase):
    def test_agent_records_are_normalised(self):
        recs = parse_records([
            raw("повезло ученикам))", direction="out", from_nick="HiHoney",
                time="17:31", idx=0),
            raw("", kind="gif", idx=1,
                media={"url": "https://x/y.gif", "kind": "gif"}),
        ])
        self.assertEqual(recs[0].direction, "out")
        self.assertEqual(recs[0].from_nick, "HiHoney")
        self.assertEqual(recs[0].text, "повезло ученикам))")
        self.assertEqual(recs[1].kind, "gif")
        self.assertEqual(recs[1].media_url, "https://x/y.gif")

    def test_garbage_records_are_dropped_not_crashed_on(self):
        recs = parse_records([None, {}, {"dir": "in"}, raw("ok", idx=3)])
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].text, "ok")

    def test_fingerprint_is_stable_and_occurrence_sensitive(self):
        a = fingerprint("in", "N", "17:31", "text", "ok", 0)
        b = fingerprint("in", "N", "17:31", "text", "ok", 0)
        c = fingerprint("in", "N", "17:31", "text", "ok", 1)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


class TestParserProbes(unittest.IsolatedAsyncioTestCase):
    async def test_state_is_one_small_probe(self):
        page = FakePage([raw("a", idx=0), raw("b", idx=1)])
        parser = ChatParser(page)
        st = await parser.state()
        self.assertEqual(st["tab"], "private")
        self.assertEqual(st["partner"], "Nick")
        self.assertEqual(st["count"], 2)
        self.assertEqual(page.evaluates, 1)

    async def test_agent_is_installed_only_when_missing(self):
        page = FakePage([], agent=False)
        parser = ChatParser(page)
        self.assertEqual(await parser.ensure_agent(), 3)
        self.assertEqual(page.installs, 1)
        await parser.ensure_agent()
        self.assertEqual(page.installs, 1)      # already there → no re-inject
        page.agent_version = 0                  # SPA re-render
        await parser.ensure_agent()
        self.assertEqual(page.installs, 2)

    async def test_slice_reads_only_the_requested_window(self):
        page = FakePage([raw(f"m{i}", idx=i) for i in range(10)])
        parser = ChatParser(page)
        recs = await parser.slice(7, 10)
        self.assertEqual([r.text for r in recs], ["m7", "m8", "m9"])
        self.assertEqual(page.slice_calls, [(7, 10)])

    async def test_drain_returns_and_clears_the_agent_queue(self):
        page = FakePage([])
        page.append(raw("new", idx=0))
        parser = ChatParser(page)
        recs = await parser.drain()
        self.assertEqual([r.text for r in recs], ["new"])
        self.assertEqual(await parser.drain(), [])


class TestSyncScenarios(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db, self.repo = await make_repo()

    async def asyncTearDown(self):
        await self.db.close()

    async def sync(self, parser, **kw):
        kw.setdefault("chunk_pause_ms", 0)
        kw.setdefault("now", NOW)
        return await sync_conversation(parser, self.repo, "Nick",
                                       my_nick="Me", **kw)

    async def test_bootstrap_then_delta_then_nothing(self):
        page = FakePage([raw(f"m{i}", idx=i) for i in range(10)])
        parser = ChatParser(page, chunk_size=4)
        first = await self.sync(parser)
        self.assertEqual(first.added, 10)
        self.assertFalse(first.gap)

        page.append(raw("m10", idx=10), raw("m11", idx=11))
        second = await self.sync(parser)
        self.assertEqual(second.added, 2)

        third = await self.sync(parser)
        self.assertEqual(third.added, 0)
        self.assertFalse(third.gap)
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 12)

    async def test_running_the_same_sync_twice_is_idempotent(self):
        page = FakePage([raw(f"m{i}", idx=i) for i in range(25)])
        parser = ChatParser(page, chunk_size=7)
        await self.sync(parser)
        await self.repo.reset_cursor("Nick")     # worst case: cursor lost
        again = await self.sync(parser)
        self.assertEqual(again.added, 0)
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 25)

    async def test_prepended_older_messages_are_backfilled_without_duplicates(self):
        page = FakePage([raw(f"m{i}", idx=i) for i in range(5)])
        parser = ChatParser(page, chunk_size=10)
        await self.sync(parser)
        page.prepend(raw("older1", idx=0), raw("older2", idx=1))
        res = await self.sync(parser)
        self.assertEqual(res.added, 2)
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 7)

    async def test_backfill_scrolls_to_the_first_message_and_backfills_it(self):
        # The virtualiser only kept the newest 5 lines in the DOM; the first 5
        # arrive only after the pane is scrolled to the top.
        page = FakePage([raw(f"m{i}", idx=i) for i in range(5, 10)])
        page.prepend_on_scroll = [raw(f"m{i}", idx=i) for i in range(5)]
        page.scroll_top = 150
        parser = ChatParser(page, chunk_size=4, chunk_pause_ms=0)
        res = await self.sync(parser, backfill_older=True)
        self.assertEqual(res.added, 10)
        self.assertTrue(res.backfilled)
        pid = await self.repo.ensure_person("Nick")
        cur = await self.repo.get_cursor(pid)
        self.assertTrue(cur["full_scan_complete"])
        self.assertEqual(page.scroll_top_calls, 1)
        self.assertEqual(page.restore_calls, [150], "the viewport is put back")
        texts = [r[0] for r in await self.db.fetchall(
            "SELECT text FROM messages ORDER BY ord")]
        self.assertEqual(texts, [f"m{i}" for i in range(10)])

    async def test_incremental_after_backfill_does_not_rescroll(self):
        page = FakePage([raw(f"m{i}", idx=i) for i in range(5, 10)])
        page.prepend_on_scroll = [raw(f"m{i}", idx=i) for i in range(5)]
        page.scroll_top = 150
        parser = ChatParser(page, chunk_size=10, chunk_pause_ms=0)
        await self.sync(parser, backfill_older=True)
        self.assertEqual(page.scroll_top_calls, 1)
        # the collector now sees full_scan_complete and will NOT ask again
        await self.sync(parser, backfill_older=False)
        self.assertEqual(page.scroll_top_calls, 1)
        self.assertEqual(page.restore_calls, [150])
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 10)

    async def test_an_empty_but_scrollable_pane_is_not_marked_complete(self):
        # The live report: a private tab is open but the probe found no message
        # nodes while the pane still has a scroll height. Marking it "fully
        # checked" would leave In archive at 0 forever.
        page = FakePage([])
        page.scroll_height = 400
        parser = ChatParser(page, chunk_size=10, chunk_pause_ms=0)
        result = await self.sync(parser, backfill_older=True)
        self.assertEqual(result.added, 0)
        pid = await self.repo.ensure_person("Nick")
        cur = await self.repo.get_cursor(pid)
        self.assertFalse(cur["full_scan_complete"],
                         "a scrollable-but-unread pane must be retried")
        page.scroll_height = 0
        await self.repo.reset_cursor("Nick")
        result = await self.sync(parser, backfill_older=True)
        self.assertEqual(result.added, 0)
        pid = await self.repo.ensure_person("Nick")
        cur = await self.repo.get_cursor(pid)
        self.assertTrue(cur["full_scan_complete"],
                        "a truly empty pane is safe to mark complete")

    async def test_shifted_occurrence_does_not_create_a_gap_or_a_duplicate(self):
        # Bug #2: older identical lines are prepended, so the same stored line
        # is re-read with a different occurrence number. The archive must keep
        # one row and must NOT report a bogus alignment gap.
        page = FakePage([raw("Nice", time="12:00", idx=0, occ=1)])
        parser = ChatParser(page, chunk_size=10, chunk_pause_ms=0)
        first = await self.sync(parser)
        self.assertEqual(first.added, 1)
        page.prepend(raw("Nice", time="12:00", idx=0, occ=0))
        res = await self.sync(parser)
        self.assertEqual(res.added, 0)
        self.assertFalse(res.gap)
        rows = await self.db.fetchall("SELECT COUNT(*) FROM messages")
        self.assertEqual(rows[0][0], 1)

    async def test_trimmed_buffer_with_overlap_adds_only_new_lines(self):
        page = FakePage([raw(f"m{i}", idx=i) for i in range(10)])
        parser = ChatParser(page, chunk_size=10)
        await self.sync(parser)
        page.trim(4)                       # site dropped the oldest 6 nodes
        page.append(raw("m10", idx=10))
        res = await self.sync(parser)
        self.assertEqual(res.added, 1)
        self.assertFalse(res.gap)

    async def test_completely_rolled_buffer_records_a_gap(self):
        page = FakePage([raw(f"m{i}", idx=i) for i in range(5)])
        parser = ChatParser(page, chunk_size=10)
        await self.sync(parser)
        page.messages = [raw(f"z{i}", idx=i) for i in range(3)]
        res = await self.sync(parser)
        self.assertEqual(res.added, 3)
        self.assertTrue(res.gap)
        rows = await self.db.fetchall("SELECT reason FROM gaps")
        self.assertEqual([r[0] for r in rows], ["alignment_lost"])

    async def test_chunking_paces_the_read_and_reports_progress(self):
        page = FakePage([raw(f"m{i}", idx=i) for i in range(10)])
        parser = ChatParser(page, chunk_size=3)
        seen = []
        res = await self.sync(parser, on_progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(res.added, 10)
        self.assertEqual(len(page.slice_calls), 4)          # 3+3+3+1
        self.assertGreaterEqual(len(seen), 4)
        self.assertEqual(seen[-1][0], 10)

    async def test_stop_between_chunks_is_prompt_and_not_a_failure(self):
        page = FakePage([raw(f"m{i}", idx=i) for i in range(30)])
        parser = ChatParser(page, chunk_size=5)
        calls = {"n": 0}

        def should_stop():
            calls["n"] += 1
            return calls["n"] > 2

        res = await self.sync(parser, should_stop=should_stop)
        self.assertTrue(res.stopped)
        self.assertLess(res.added, 30)
        self.assertGreater(res.added, 0)
        self.assertLess(len(page.slice_calls), 6)
        # the cursor survived, so the next sync resumes instead of restarting
        rest = await self.sync(parser)
        self.assertEqual(rest.added, 30 - res.added)

    async def test_max_messages_cap_keeps_the_newest_and_notes_the_hole(self):
        page = FakePage([raw(f"m{i}", idx=i) for i in range(50)])
        parser = ChatParser(page, chunk_size=10)
        res = await self.sync(parser, max_messages=20)
        self.assertEqual(res.added, 20)
        self.assertTrue(res.gap)
        texts = [r[0] for r in await self.db.fetchall(
            "SELECT text FROM messages ORDER BY ord")]
        self.assertEqual(texts[0], "m30")       # newest 20 kept
        self.assertEqual(texts[-1], "m49")

    async def test_steady_state_costs_no_node_reads(self):
        """The whole point of the design: an idle chat must not be parsed."""
        page = FakePage([raw(f"m{i}", idx=i) for i in range(40)])
        parser = ChatParser(page, chunk_size=40)
        await self.sync(parser)
        before = len(page.slice_calls)
        res = await self.sync(parser)
        self.assertEqual(res.added, 0)
        self.assertEqual(len(page.slice_calls), before,
                         "an unchanged conversation must not be re-read")

    async def test_media_messages_survive_the_round_trip(self):
        page = FakePage([raw("", kind="gif", idx=0,
                             media={"url": "https://x/y.gif", "kind": "gif"})])
        parser = ChatParser(page, chunk_size=10)
        res = await self.sync(parser)
        self.assertEqual(res.added, 1)
        rows = await self.db.fetchall(
            "SELECT m.kind, md.url FROM messages m JOIN media md "
            "ON md.id=m.media_id")
        self.assertEqual(rows[0], ("gif", "https://x/y.gif"))

    async def test_not_a_private_tab_is_refused_loudly(self):
        page = FakePage([raw("a", idx=0)], tab="room")
        parser = ChatParser(page, chunk_size=10)
        res = await self.sync(parser, require_private=True)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "not_private")
        self.assertEqual(res.added, 0)

    async def test_partner_mismatch_never_files_under_the_wrong_nick(self):
        page = FakePage([raw("a", idx=0)], partner="SomeoneElse")
        parser = ChatParser(page, chunk_size=10)
        res = await sync_conversation(parser, self.repo, "Nick", my_nick="Me",
                                      verify_partner=True, chunk_pause_ms=0,
                                      now=NOW)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "partner_mismatch")
        self.assertIsNone(await self.repo.get_person("Nick"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
