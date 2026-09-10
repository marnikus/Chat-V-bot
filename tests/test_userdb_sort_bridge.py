"""Sortable columns of the Full User Database — the QWebChannel half.

`HistoryDb` sends `{q, limit, offset, sort, dir}` to the `userdb_page` slot
and paints whatever comes back, in the order it comes back. These tests drive
the REAL `Bridge` (bridge/router.py + bridge/history_bridge.py) over the real
request-id/signal protocol and pin:

  * `dir` actually reaches the query and the answer echoes it;
  * a payload without `dir` keeps the historical order, so an older page or a
    saved setting cannot change what the user sees;
  * a hostile `sort` / `dir` string is data, never SQL.

Design: docs/archive/2026-09-10-history-push-and-sort/SORTABLE_DATABASE_COLUMNS_DESIGN_2026-09-10.md §3.1 / §6.4

Run with:  python3 tests/test_userdb_sort_bridge.py
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_history_bridge import BridgeCase  # noqa: E402


class TestUserDbSortOverTheBridge(BridgeCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        # Two people with different message counts, so every column that can
        # be sorted on has something to distinguish.
        await self.seed("Aaron", 2)
        await self.seed("Zoe", 6)

    async def ask_page(self, **options):
        _req, payload = await self.ask(
            self.bridge.userdb_page, "u-sort",
            json.dumps(options), signal=self.bridge.userdb_page_ready)
        return json.loads(payload)

    async def test_the_direction_reaches_the_database(self):
        up = await self.ask_page(sort="nick", dir="asc", limit=10)
        down = await self.ask_page(sort="nick", dir="desc", limit=10)
        self.assertEqual([p["nick"] for p in up["items"]], ["Aaron", "Zoe"])
        self.assertEqual([p["nick"] for p in down["items"]], ["Zoe", "Aaron"])

    async def test_the_answer_echoes_what_was_asked(self):
        data = await self.ask_page(sort="msgs", dir="asc", limit=10)
        self.assertEqual(data["sort"], "msgs")
        self.assertEqual(data["dir"], "asc")
        self.assertEqual([p["nick"] for p in data["items"]], ["Aaron", "Zoe"],
                         "fewest messages first")

    async def test_a_payload_without_a_direction_keeps_the_old_order(self):
        # Before the feature the window always sent {"sort": "recent"} — that
        # request must still mean "newest activity first".
        legacy = await self.ask_page(sort="recent", limit=10)
        self.assertEqual(legacy["dir"], "desc")
        explicit = await self.ask_page(sort="last", dir="desc", limit=10)
        self.assertEqual([p["nick"] for p in legacy["items"]],
                         [p["nick"] for p in explicit["items"]])

    async def test_no_options_at_all_still_answers(self):
        data = await self.ask_page(limit=10)
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["sort"], "recent")
        self.assertEqual(data["dir"], "desc")

    async def test_a_hostile_sort_or_dir_is_data_not_syntax(self):
        for payload in ({"sort": "nick; DROP TABLE persons--", "dir": "asc"},
                        {"sort": "nick", "dir": "asc; DELETE FROM persons"},
                        {"sort": "(SELECT nick FROM persons)",
                         "dir": "desc --"}):
            data = await self.ask_page(limit=10, **payload)
            self.assertEqual(data["total"], 2, f"{payload} broke the query")
        self.assertEqual(self.errors, [], "the bridge must not report a failure")
        after = await self.ask_page(sort="nick", dir="asc", limit=10)
        self.assertEqual([p["nick"] for p in after["items"]], ["Aaron", "Zoe"],
                         "both people are still in the archive")

    async def test_paging_a_sort_never_serves_a_person_twice(self):
        seen = []
        offset = 0
        while True:
            data = await self.ask_page(sort="msgs", dir="asc", limit=1,
                                   offset=offset)
            if not data["items"]:
                break
            seen.extend(p["nick"] for p in data["items"])
            if not data["has_more"]:
                break
            offset += 1
        self.assertEqual(sorted(seen), ["Aaron", "Zoe"],
                         "one row per page, every person exactly once")


if __name__ == "__main__":
    unittest.main(verbosity=2)
