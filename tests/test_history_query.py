"""Message archive — READ path (milestone M1).

Everything the two new windows need: chronological paging that stays
stable while the collector appends, search inside one conversation and
across the whole archive, nick search for the master list, and the counters
in the headers.

Two search back-ends must behave identically from the caller's point of
view: FTS5 when SQLite provides it, a `text_lc LIKE` fallback when it does
not. Cyrillic case-insensitivity is asserted on BOTH paths — SQLite's
built-in LIKE folds ASCII only, which is exactly the trap this feature
would otherwise fall into.

Run with:  python3 tests/test_history_query.py
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
from backend.history_query import HistoryQuery  # noqa: E402
from backend.history_repo import HistoryRepo  # noqa: E402

NOW = datetime(2026, 9, 6, 18, 30, 0)


def rec(text="hi", direction="in", from_nick="Nick", time="17:31",
        kind="text", media=None, occ=0, idx=0):
    payload = media["url"] if media else text
    return MessageRecord(
        fp=fingerprint(direction, from_nick, time, kind, payload, occ),
        direction=direction, from_nick=from_nick, kind=kind, text=text,
        media_url=(media or {}).get("url", ""),
        media_kind=(media or {}).get("kind", ""),
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

    async def seed(self, nick="Nick", n=10, my_nick="Me", start=0):
        batch = [rec(text=f"line {i}", idx=i,
                     direction="out" if i % 2 else "in",
                     from_nick=my_nick if i % 2 else nick,
                     time="1%d:%02d" % (i // 60, i % 60))
                 for i in range(start, start + n)]
        await self.repo.append(nick, batch, my_nick=my_nick, now=NOW)


class TestPaging(QueryCase):
    async def test_opens_at_the_newest_end(self):
        await self.seed(n=120)
        page = await self.q.page("Nick", limit=50)
        self.assertEqual(len(page["items"]), 50)
        self.assertEqual(page["items"][-1]["ord"], 120)   # newest last
        self.assertEqual(page["items"][0]["ord"], 71)
        self.assertTrue(page["has_more"])                 # older rows exist
        self.assertFalse(page["has_newer"])
        self.assertEqual(page["total"], 120)

    async def test_older_page_walks_backwards_without_overlap(self):
        await self.seed(n=120)
        first = await self.q.page("Nick", limit=50)
        older = await self.q.page("Nick", before_ord=first["items"][0]["ord"],
                                  limit=50)
        self.assertEqual(older["items"][-1]["ord"], 70)
        self.assertEqual(older["items"][0]["ord"], 21)
        self.assertTrue(older["has_more"])
        self.assertTrue(older["has_newer"])

    async def test_last_page_reports_no_more(self):
        await self.seed(n=30)
        page = await self.q.page("Nick", limit=50)
        self.assertEqual(len(page["items"]), 30)
        self.assertFalse(page["has_more"])

    async def test_after_ord_fetches_what_the_collector_just_added(self):
        await self.seed(n=10)
        newest = await self.q.page("Nick", limit=5)
        await self.seed(n=3, start=10)
        fresh = await self.q.page("Nick", after_ord=newest["items"][-1]["ord"])
        self.assertEqual([i["ord"] for i in fresh["items"]], [11, 12, 13])

    async def test_around_centres_on_a_search_hit(self):
        await self.seed(n=100)
        page = await self.q.around("Nick", 50, radius=5)
        ords = [i["ord"] for i in page["items"]]
        self.assertEqual(ords[0], 45)
        self.assertEqual(ords[-1], 55)
        self.assertEqual(page["anchor_ord"], 50)

    async def test_unknown_person_returns_an_empty_page_not_an_error(self):
        page = await self.q.page("Ghost", limit=10)
        self.assertEqual(page["items"], [])
        self.assertEqual(page["total"], 0)
        self.assertFalse(page["has_more"])
        self.assertTrue(page["missing"])

    async def test_message_items_carry_both_nicks_and_media(self):
        await self.repo.append("Nick", [
            rec(text="", kind="gif", idx=0,
                media={"url": "https://x/y.gif", "kind": "gif"})],
            my_nick="Me", now=NOW)
        item = (await self.q.page("Nick"))["items"][0]
        self.assertEqual(item["from_nick"], "Nick")
        self.assertEqual(item["my_nick"], "Me")
        self.assertEqual(item["kind"], "gif")
        self.assertEqual(item["media"]["url"], "https://x/y.gif")
        self.assertEqual(item["media"]["state"], "pending")

    async def test_gaps_are_reported_with_the_page(self):
        await self.seed(n=5)
        await self.repo.append("Nick", [rec(text="after the hole", idx=99)],
                               now=NOW)
        page = await self.q.page("Nick")
        self.assertEqual(len(page["gaps"]), 1)
        self.assertEqual(page["gaps"][0]["after_ord"], 5)


class TestSearch(QueryCase):
    async def seed_text(self):
        batch = [rec(text="Привет, как дела?", idx=0),
                 rec(text="ПРИВЕТ ещё раз", idx=1),
                 rec(text="nothing to see", idx=2),
                 rec(text="", kind="gif", idx=3,
                     media={"url": "https://x/cat.gif", "kind": "gif"})]
        await self.repo.append("Nick", batch, my_nick="Me", now=NOW)
        await self.repo.append("Other", [rec(text="привет from Other", idx=0,
                                             from_nick="Other")], now=NOW)

    async def test_search_in_one_conversation_is_case_insensitive_cyrillic(self):
        await self.seed_text()
        res = await self.q.search_person("Nick", "привет")
        self.assertEqual(res["total"], 2)
        self.assertEqual(sorted(i["ord"] for i in res["items"]), [1, 2])
        self.assertIn("Привет", res["items"][0]["text"])

    async def test_search_is_scoped_to_the_person(self):
        await self.seed_text()
        res = await self.q.search_person("Nick", "Other")
        self.assertEqual(res["total"], 0)
        self.assertEqual(res["items"], [])

    async def test_global_search_groups_by_person(self):
        await self.seed_text()
        res = await self.q.search_global("привет")
        nicks = {g["nick"] for g in res["groups"]}
        self.assertEqual(nicks, {"Nick", "Other"})
        self.assertEqual(res["total"], 3)
        hit = res["groups"][0]["items"][0]
        self.assertIn("ord", hit)
        self.assertIn("snippet", hit)

    async def test_empty_query_returns_nothing_rather_than_everything(self):
        await self.seed_text()
        self.assertEqual((await self.q.search_person("Nick", "   "))["total"], 0)
        self.assertEqual((await self.q.search_global(""))["total"], 0)

    async def test_search_clamps_and_says_so(self):
        batch = [rec(text=f"needle {i}", idx=i) for i in range(30)]
        await self.repo.append("Nick", batch, now=NOW)
        res = await self.q.search_person("Nick", "needle", limit=10)
        self.assertEqual(len(res["items"]), 10)
        self.assertEqual(res["total"], 30)
        self.assertTrue(res["has_more"])

    async def test_wildcards_and_quotes_do_not_break_the_query(self):
        await self.seed_text()
        for hostile in ("100%", "_", "'", '"', "*", "AND OR", "привет'"):
            res = await self.q.search_person("Nick", hostile)
            self.assertIsInstance(res["total"], int)


class TestSearchWithoutFts(TestSearch):
    """Same expectations with FTS5 switched off (LIKE fallback path)."""
    USE_FTS = False

    async def test_fallback_is_reported(self):
        self.assertFalse(self.db.fts_enabled)


class TestUserDatabase(QueryCase):
    async def test_lists_every_person_with_counters(self):
        await self.seed("Nick", n=4)
        await self.seed("Other", n=2)
        res = await self.q.list_persons()
        self.assertEqual(res["total"], 2)
        by_nick = {p["nick"]: p for p in res["items"]}
        self.assertEqual(by_nick["Nick"]["message_count"], 4)
        self.assertEqual(by_nick["Other"]["message_count"], 2)
        self.assertIn("my_nicks", by_nick["Nick"])

    async def test_lazy_paging_of_the_master_list(self):
        for i in range(25):
            await self.seed(f"P{i:02d}", n=1)
        first = await self.q.list_persons(limit=10)
        self.assertEqual(len(first["items"]), 10)
        self.assertTrue(first["has_more"])
        last = await self.q.list_persons(offset=20, limit=10)
        self.assertEqual(len(last["items"]), 5)
        self.assertFalse(last["has_more"])

    async def test_nick_search_prefers_prefix_matches(self):
        for nick in ("Ангел", "Мой Ангел", "Ангелина"):
            await self.seed(nick, n=1)
        res = await self.q.list_persons(q="ангел")
        self.assertEqual(res["total"], 3)
        self.assertIn(res["items"][0]["nick"], ("Ангел", "Ангелина"))
        exact = await self.q.list_persons(q="Ангелина")
        self.assertEqual(exact["total"], 1)

    async def test_sorting_options(self):
        await self.seed("Few", n=1)
        await self.seed("Many", n=9)
        by_count = await self.q.list_persons(sort="messages")
        self.assertEqual(by_count["items"][0]["nick"], "Many")
        by_nick = await self.q.list_persons(sort="nick")
        self.assertEqual([p["nick"] for p in by_nick["items"]], ["Few", "Many"])

    async def test_tombstoned_people_are_hidden_unless_asked_for(self):
        await self.seed("Nick", n=2)
        await self.seed("Gone", n=2)
        await self.repo.delete_person("Gone")
        self.assertEqual((await self.q.list_persons())["total"], 1)
        withdel = await self.q.list_persons(include_deleted=True)
        self.assertEqual(withdel["total"], 2)
        gone = [p for p in withdel["items"] if p["nick"] == "Gone"][0]
        self.assertTrue(gone["deleted"])

    async def test_db_stats_feed_the_window_header(self):
        await self.seed("Nick", n=3)
        stats = await self.q.db_stats()
        self.assertEqual(stats["persons"], 1)
        self.assertEqual(stats["messages"], 3)
        self.assertIn("media_bytes", stats)
        self.assertIn("fts", stats)

    async def test_person_stats_expose_both_identities(self):
        await self.seed("Nick", n=3, my_nick="Me1")
        await self.repo.reset_cursor("Nick")
        await self.seed("Nick", n=2, my_nick="Me2", start=50)
        stats = await self.q.person_stats("Nick")
        self.assertEqual(stats["nick"], "Nick")
        self.assertEqual(sorted(stats["my_nicks"]), ["Me1", "Me2"])
        self.assertEqual(stats["message_count"], 5)
        self.assertIn("first_seen", stats)
        self.assertIn("last_seen", stats)


if __name__ == "__main__":
    unittest.main(verbosity=2)
