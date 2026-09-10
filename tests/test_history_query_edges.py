"""backend/history_query — adversarial input, pagination edges, empty DB.

Design refs: docs/archive/2026-09-09-test-suite/BACKEND_TESTS_DESIGN_2026-09-09.md §HQ#1–5.

The existing read-path suite (test_history_query.py) covers the happy
paging/search behaviour on both back-ends. This file attacks the seams:

  * FTS5: user search text is DATA, never MATCH syntax — operators,
    unbalanced quotes, CJK, emoji must return a result or an empty one,
    never an sqlite OperationalError escaping to the UI;
  * LIKE: % and _ in a nick filter must not act as wildcards;
  * pagination edges: out-of-range cursors, clamped limits, offsets past
    the end, missing persons;
  * counters on an EMPTY database (zeros, no None leaks);
  * soft-deleted rows are invisible to every read but counted as hidden.

Run with:  python3 tests/test_history_query_edges.py
"""

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.history_db import HistoryDB  # noqa: E402
from backend.history_models import MessageRecord, fingerprint  # noqa: E402
from backend.history_query import (  # noqa: E402
    MAX_LIMIT,
    _fts_query,
    _like_escape,
    HistoryQuery,
    PersonPageRequest,
)
from backend.history_repo import HistoryRepo  # noqa: E402

NOW = datetime(2026, 9, 6, 18, 30, 0)


def rec(text="hi", direction="in", from_nick="Nick", time="17:31",
        occ=0, idx=0):
    return MessageRecord(
        fp=fingerprint(direction, from_nick, time, "text", text, occ),
        direction=direction, from_nick=from_nick, kind="text", text=text,
        ts_display=time, occ=occ, idx=idx)


class QueryCase(unittest.IsolatedAsyncioTestCase):
    USE_FTS = True

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = HistoryDB(os.path.join(self.dir, "history.db"),
                            use_fts=self.USE_FTS)
        await self.db.init()
        self.repo = HistoryRepo(self.db, session_id="s1")
        self.q = HistoryQuery(self.db)

    async def asyncTearDown(self):
        await self.db.close()

    async def seed(self, nick="Nick", n=10):
        batch = [rec(text=f"line {i}", idx=i, from_nick=nick,
                     time="1%d:%02d" % (i // 60, i % 60))
                 for i in range(n)]
        await self.repo.append(nick, batch, my_nick="Me", now=NOW)


class TestFtsSafety(QueryCase):

    async def test_fts_operators_are_data_not_syntax(self):
        """Every token of user input is quoted before MATCH — `AND`, `OR`,
        `NOT`, `NEAR`, `*`, quotes, parentheses are search terms."""
        for expr in ('"unbalanced', "a AND b", "NOT x", "NEAR(a b)",
                     "col:near", "(parenthesised", "a OR b OR c",
                     "^start", "star*", 'quo"te'):
            self.assertTrue(_fts_query(expr) or expr.strip() == "",
                            f"_fts_query emptied a real query: {expr!r}")

    async def test_hostile_searches_return_not_raise(self):
        await self.seed(n=5)
        for query in ('"unbalanced', "a AND b", "NOT x", "*", "(",
                      "🤖👍", "日本語", "''", '"""', "a" * 500):
            person = await self.q.search_person("Nick", query)
            self.assertIsInstance(person["items"], list, repr(query))
            self.assertIsInstance(person["total"], int, repr(query))
            global_ = await self.q.search_global(query)
            self.assertIsInstance(global_["groups"], list, repr(query))

    async def test_empty_and_whitespace_queries_are_empty_results(self):
        await self.seed(n=3)
        for query in ("", "   ", "!!!", "…"):
            person = await self.q.search_person("Nick", query)
            self.assertEqual(person["items"], [])
            self.assertEqual(person["total"], 0)

    async def test_real_text_still_matches_through_the_quoter(self):
        await self.seed(n=10)
        person = await self.q.search_person("Nick", "line 5")
        self.assertGreaterEqual(person["total"], 1)
        texts = [i["text"] for i in person["items"]]
        self.assertTrue(any("line 5" in t for t in texts))

    async def test_cyrillic_case_folds_in_search(self):
        batch = [rec(text="Привет МИР", idx=0),
                 rec(text="пока друг", idx=1)]
        await self.repo.append("Nick", batch, my_nick="Me", now=NOW)
        person = await self.q.search_person("Nick", "привет мир")
        self.assertEqual(person["total"], 1)


class TestLikeEscape(QueryCase):

    def test_wildcards_and_backslash_are_escaped(self):
        self.assertEqual(_like_escape("100%"), "100\\%")
        self.assertEqual(_like_escape("under_score"), "under\\_score")
        self.assertEqual(_like_escape("back\\slash"), "back\\\\slash")
        self.assertEqual(_like_escape(""), "")

    async def test_percent_in_nick_filter_is_literal(self):
        for nick in ("Ann", "Anndrea", "Ann%100", "Ann_200"):
            await self.repo.append(nick, [rec(text="x", idx=0)],
                                   my_nick="Me", now=NOW)
        # "Ann%" must find only the nick literally containing "Ann%" —
        # as a wildcard it would also return plain "Ann" and "Anndrea"
        out = await self.q.list_persons(PersonPageRequest(q="Ann%"))
        self.assertEqual([i["nick"] for i in out["items"]], ["Ann%100"],
                         "% acted as a wildcard in the nick filter")
        out = await self.q.list_persons(PersonPageRequest(q="Ann_"))
        self.assertEqual(sorted(i["nick"] for i in out["items"]),
                         ["Ann_200"], "_ acted as a wildcard")
        out = await self.q.list_persons(PersonPageRequest(q="Ann"))
        self.assertEqual(sorted(i["nick"] for i in out["items"]),
                         ["Ann", "Ann%100", "Ann_200", "Anndrea"])


class TestPaginationEdges(QueryCase):

    async def test_missing_person_is_missing_not_crash(self):
        page = await self.q.page("Ghost")
        self.assertEqual(page["items"], [])
        self.assertTrue(page["missing"])
        stats = await self.q.person_stats("Ghost")
        self.assertTrue(stats["missing"])
        self.assertEqual(stats["message_count"], 0)

    async def test_out_of_range_cursors_return_sane_pages(self):
        await self.seed(n=10)
        page = await self.q.page("Nick", before_ord=0)      # before the head
        self.assertEqual(page["items"], [])
        self.assertFalse(page["has_more"])
        page = await self.q.page("Nick", before_ord=10 ** 9)
        self.assertEqual(len(page["items"]), 10, "far cursor returns all")
        page = await self.q.page("Nick", after_ord=10 ** 9)  # past the tail
        self.assertEqual(page["items"], [])

    async def test_limit_is_clamped_both_ways(self):
        await self.seed(n=5)
        page = await self.q.page("Nick", limit=0)
        self.assertEqual(len(page["items"]), 5,
                         "limit 0 is falsy → the default page size")
        page = await self.q.page("Nick", limit=10 ** 6)
        self.assertEqual(len(page["items"]), 5)
        self.assertEqual(HistoryQuery._clamp(None), 50)
        self.assertEqual(HistoryQuery._clamp("garbage"), 50)
        self.assertEqual(HistoryQuery._clamp(-5), 1,
                         "a negative limit clamps to 1")
        self.assertEqual(HistoryQuery._clamp(10 ** 9), MAX_LIMIT)

    async def test_offset_beyond_end_is_empty_not_error(self):
        await self.seed(n=5)
        person = await self.q.search_person("Nick", "line", offset=100)
        self.assertEqual(person["items"], [])
        self.assertFalse(person["has_more"])
        out = await self.q.list_persons(PersonPageRequest(offset=100))
        self.assertEqual(out["items"], [])

    async def test_around_an_ord_of_a_missing_person(self):
        out = await self.q.around("Ghost", 5)
        self.assertTrue(out["missing"])
        self.assertEqual(out["items"], [])

    async def test_deleted_rows_are_invisible_but_counted(self):
        await self.seed(n=4)
        person = await self.repo.get_person("Nick")
        token = HistoryRepo.new_op_token()
        rows = await self.repo.deleted_count("Nick")
        self.assertEqual(rows, 0)
        await self.repo.soft_delete_history("Nick", token)
        page = await self.q.page("Nick")
        self.assertEqual(page["items"], [], "hidden rows leaked into a page")
        self.assertEqual(page["total"], 0)
        stats = await self.q.person_stats("Nick")
        self.assertEqual(stats["hidden"], 4)
        db = await self.q.db_stats()
        self.assertEqual(db["messages_hidden"], 4)
        self.assertEqual(db["messages"], 0)


class TestEmptyDatabaseCounters(QueryCase):

    async def test_stats_on_an_empty_db_are_zeros(self):
        stats = await self.q.db_stats()
        for key in ("persons", "persons_deleted", "messages",
                    "messages_hidden", "media", "media_cached", "gaps"):
            self.assertEqual(stats[key], 0, key)
        self.assertEqual(stats["text_bytes"], 0)
        self.assertIsInstance(stats["db_bytes"], int)
        self.assertGreater(stats["db_bytes"], 0, "the file itself exists")

    async def test_list_persons_on_an_empty_db(self):
        out = await self.q.list_persons(PersonPageRequest())
        self.assertEqual(out["items"], [])
        self.assertEqual(out["total"], 0)
        self.assertFalse(out["has_more"])

    async def test_sort_modes_and_q_filter(self):
        await self.repo.append("b", [rec(text="x", idx=0)],
                               my_nick="Me", now=NOW)
        await self.repo.append("a", [rec(text="x", idx=0), rec(text="y",
                                     idx=1, occ=1)],
                               my_nick="Me", now=NOW)
        by_nick = await self.q.list_persons(PersonPageRequest(sort="nick"))
        self.assertEqual([i["nick"] for i in by_nick["items"]], ["a", "b"])
        by_messages = await self.q.list_persons(PersonPageRequest(sort="messages"))
        self.assertEqual([i["nick"] for i in by_messages["items"]], ["a", "b"])
        filtered = await self.q.list_persons(PersonPageRequest(q="A"))
        self.assertEqual([i["nick"] for i in filtered["items"]], ["a"])
        unknown_sort = await self.q.list_persons(PersonPageRequest(sort="??"))
        self.assertEqual(len(unknown_sort["items"]), 2,
                         "an unknown sort must fall back, not fail")

    async def test_search_global_groups_by_person(self):
        await self.repo.append("Ann", [rec(text="apple pie", idx=0),
                                       rec(text="apple juice", idx=1)],
                               my_nick="Me", now=NOW)
        await self.repo.append("Bea", [rec(text="apple tart", idx=0)],
                               my_nick="Me", now=NOW)
        out = await self.q.search_global("apple")
        self.assertEqual(out["persons"], 2)
        self.assertEqual(out["groups"][0]["nick"], "Ann",
                         "the busiest conversation leads")
        self.assertLessEqual(len(out["groups"][0]["items"]), 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
