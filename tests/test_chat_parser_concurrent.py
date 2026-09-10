"""backend/chat_parser — concurrency and payload-shape contracts.

Design refs: docs/BACKEND_TESTS_DESIGN_2026-09-09.md §CP#1–3.

The existing delta suite (test_chat_parser_delta.py) covers alignment,
backfill, trimming and sequential idempotence. The gaps this file fills:

  * TWO overlapping syncs against the SAME conversation (the collector
    heartbeat + a user pressing "Collect" can genuinely race) must leave
    the archive EXACTLY as one sync would — no duplicate rows, no ghost
    gap rows, message_count truthful;
  * concurrent syncs of DIFFERENT persons sharing one database must
    never cross-file rows (identity comes from the archive, not from
    call order);
  * the agent answer SHAPES the wild page can produce — `{ok:true}`
    without items, ok:false, items as a string, items as None — must
    parse to "nothing new", never raise.

Run with:  python3 tests/test_chat_parser_concurrent.py
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.chat_parser import (  # noqa: E402
    ChatParser,
    parse_records,
    sync_conversation,
)
from stores.history_db import HistoryDB  # noqa: E402
from stores.history_repo import HistoryRepo  # noqa: E402
from test_chat_parser_delta import FakePage, NOW, raw  # noqa: E402


async def make_repo():
    d = tempfile.mkdtemp()
    db = HistoryDB(os.path.join(d, "history.db"))
    await db.init()
    return db, HistoryRepo(db, session_id="t")


class ConcurrencyCase(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.db, self.repo = await make_repo()

    async def asyncTearDown(self):
        await self.db.close()

    async def sync(self, parser, nick, **kw):
        kw.setdefault("chunk_pause_ms", 0)
        kw.setdefault("now", NOW)
        return await sync_conversation(parser, self.repo, nick,
                                       my_nick="Me", **kw)

    async def rows_of(self, nick):
        person = await self.repo.get_person(nick)
        if not person:
            return []
        return await self.db.fetchall(
            "SELECT fp, text FROM messages WHERE person_id=? "
            "ORDER BY ord", (person["id"],))


# ══════════════════════════════════════════════════════════════════
# CP#1 — two overlapping syncs, same conversation
# ══════════════════════════════════════════════════════════════════
class TestOverlappingSyncs(ConcurrencyCase):

    async def test_two_racing_syncs_leave_exactly_one_copy(self):
        page = FakePage([raw(f"m{i}", idx=i) for i in range(10)])
        parser = ChatParser(page, chunk_size=4)

        results = await asyncio.gather(self.sync(parser, "Nick"),
                                       self.sync(parser, "Nick"))

        rows = await self.rows_of("Nick")
        self.assertEqual(len(rows), 10,
                         f"racing syncs duplicated or lost rows: "
                         f"{len(rows)} stored")
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 10,
                         "message_count must tell the truth after a race")
        gaps = await self.db.fetchall(
            "SELECT COUNT(*) FROM gaps WHERE person_id=?",
            (person["id"],))
        self.assertEqual(gaps[0][0], 0, "a race must not record gap rows")
        total_added = sum(r.added for r in results)
        self.assertEqual(total_added, 10,
                         "the two syncs together must add each line once")

    async def test_a_sync_following_a_race_still_aligns(self):
        page = FakePage([raw(f"m{i}", idx=i) for i in range(8)])
        parser = ChatParser(page, chunk_size=8)
        await asyncio.gather(self.sync(parser, "Nick"),
                             self.sync(parser, "Nick"))
        page.append(raw("m8", idx=8), raw("m9", idx=9))
        tail = await self.sync(parser, "Nick")
        self.assertEqual(tail.added, 2,
                         "a race must not poison the resume cursor")
        rows = await self.rows_of("Nick")
        self.assertEqual(len(rows), 10)


# ══════════════════════════════════════════════════════════════════
# CP#2 — different persons, one database, in parallel
# ══════════════════════════════════════════════════════════════════
class TestParallelPersons(ConcurrencyCase):

    async def test_concurrent_persons_never_cross_file(self):
        anna_page = FakePage([raw(f"m{i}", from_nick="Anna", idx=i)
                              for i in range(6)])
        belle_page = FakePage([raw(f"m{i}", from_nick="Belle", idx=i)
                               for i in range(9)])
        anna_parser = ChatParser(anna_page, chunk_size=5)
        belle_parser = ChatParser(belle_page, chunk_size=5)

        await asyncio.gather(self.sync(anna_parser, "Anna"),
                             self.sync(belle_parser, "Belle"))

        anna_rows = await self.rows_of("Anna")
        belle_rows = await self.rows_of("Belle")
        self.assertEqual(len(anna_rows), 6)
        self.assertEqual(len(belle_rows), 9)
        for fp, _text in anna_rows:
            self.assertNotIn(fp, {f for f, _ in belle_rows},
                             "the same line got filed under two persons")
        persons = await self.repo.possible_duplicates()
        self.assertEqual(
            [p for p in persons if p.get("nick") in ("Anna", "Belle")],
            [], "distinct partners must not look like duplicates")


# ══════════════════════════════════════════════════════════════════
# CP#3 — agent payload shapes the page can produce
# ══════════════════════════════════════════════════════════════════
class TestPayloadShapes(unittest.TestCase):

    def test_ok_without_items_means_nothing_new(self):
        self.assertEqual(parse_records({"ok": True}), [])
        self.assertEqual(parse_records({}), [])

    def test_ok_false_with_items_still_unwraps_items(self):
        """Decided contract: `ok` is informational; the agent never sends
        items alongside a failure, so _payload unwraps whatever items are
        present and lets normalisation decide. (An assertion that
        ok:false must DISCARD items would break the bare-list parity.)"""
        items = [raw("x", idx=0)]
        self.assertEqual([r.text for r in
                          parse_records({"ok": False, "items": items})],
                         ["x"])
        self.assertEqual(parse_records({"ok": False}), [])

    def test_non_list_items_are_refused_not_crashed_on(self):
        self.assertEqual(parse_records({"ok": True, "items": "boo"}), [])
        self.assertEqual(parse_records({"ok": True, "items": None}), [])
        self.assertEqual(parse_records({"ok": True, "items": 7}), [])

    def test_a_bare_list_still_parses(self):
        recs = parse_records([raw("hello", idx=0)])
        self.assertEqual([r.text for r in recs], ["hello"])

    def test_garbage_inside_ok_items_is_dropped(self):
        recs = parse_records({"ok": True,
                              "items": [None, {"dir": "in"},
                                        raw("real", idx=2), 42]})
        self.assertEqual([r.text for r in recs], ["real"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
