"""Sortable columns of the Full User Database — the SQL half.

The BD table (`#userdbTable`) is server-paged, so the order MUST be decided in
the database; sorting the loaded page in JavaScript would order only the rows
that happen to be in memory (design §1.1). These tests drive the real
`HistoryQuery.list_persons()` over a real SQLite file and pin:

  * what each sort key means, in both directions;
  * that an absent `dir` reproduces the historical order, so every existing
    caller and every saved setting keeps behaving exactly as before;
  * that the ORDER BY is TOTAL, so `LIMIT/OFFSET` paging can neither repeat
    nor drop a row when the primary columns tie;
  * that the nick search keeps its prefix boost on top of the column order;
  * that tombstones stay hidden under every sort (RULE 14);
  * that neither `sort` nor `dir` can reach SQL as text.

Design: docs/archive/2026-09-10-history-push-and-sort/SORTABLE_DATABASE_COLUMNS_DESIGN_2026-09-10.md §3 / §6.3

Run with:  python3 tests/test_userdb_sort_query.py
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.history_db import HistoryDB  # noqa: E402
from backend.history_models import MessageRecord, fingerprint  # noqa: E402
from backend.history_query import HistoryQuery, PersonPageRequest  # noqa: E402
from backend.history_repo import HistoryRepo  # noqa: E402

NOW = datetime(2026, 9, 10, 12, 0, 0)


def rec(text="hi", direction="in", from_nick="Nick", time="17:31", idx=0):
    payload = text
    return MessageRecord(
        fp=fingerprint(direction, from_nick, time, "text", payload, 0),
        direction=direction, from_nick=from_nick, kind="text", text=text,
        media_url="", media_kind="", ts_display=time, occ=0, idx=idx)


class SortCase(unittest.IsolatedAsyncioTestCase):
    """A database whose `persons` rows are written directly, so every test
    controls the counters and the timestamps — including the ties that make
    paging unstable."""

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = HistoryDB(os.path.join(self.dir, "history.db"))
        await self.db.init()
        self.repo = HistoryRepo(self.db, session_id="s1")
        self.q = HistoryQuery(self.db)

    async def asyncTearDown(self):
        await self.db.close()

    async def person(self, nick, messages=0, media=0, first="", last="",
                     my_nicks=None, deleted=False):
        await self.db.execute(
            "INSERT INTO persons(nick, nick_lc, first_seen, last_seen, "
            "message_count, media_count, my_nicks, created_at, deleted_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (nick, nick.lower(), first, last, messages, media,
             json.dumps(my_nicks or [], ensure_ascii=False),
             NOW.isoformat(timespec="seconds"),
             NOW.isoformat(timespec="seconds") if deleted else None))
        await self.db.commit()

    async def nicks(self, **kwargs):
        out = await self.q.list_persons(PersonPageRequest(limit=500, **kwargs))
        return [item["nick"] for item in out["items"]]

    async def raw_count(self):
        return int(await self.db.scalar("SELECT COUNT(*) FROM persons", (), 0))


class TestSortKeys(SortCase):
    """Every column the header offers has a defined meaning, both ways."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.person("alice", messages=5, media=1,
                          first="2026-01-05 10:00:00",
                          last="2026-09-01 10:00:00", my_nicks=["Zed"])
        await self.person("boris", messages=50, media=9,
                          first="2026-03-05 10:00:00",
                          last="2026-07-01 10:00:00", my_nicks=["Me"])
        await self.person("cara", messages=9, media=0,
                          first="2026-02-05 10:00:00",
                          last="2026-08-01 10:00:00", my_nicks=["Me", "Old"])

    async def test_nick_sorts_alphabetically_in_both_directions(self):
        self.assertEqual(await self.nicks(sort="nick", dir="asc"),
                         ["alice", "boris", "cara"])
        self.assertEqual(await self.nicks(sort="nick", dir="desc"),
                         ["cara", "boris", "alice"])

    async def test_message_count_sorts_busiest_first_then_quietest(self):
        self.assertEqual(await self.nicks(sort="msgs", dir="desc"),
                         ["boris", "cara", "alice"])
        self.assertEqual(await self.nicks(sort="msgs", dir="asc"),
                         ["alice", "cara", "boris"])

    async def test_media_count_sorts_its_own_column(self):
        self.assertEqual(await self.nicks(sort="media", dir="desc"),
                         ["boris", "alice", "cara"])
        self.assertEqual(await self.nicks(sort="media", dir="asc"),
                         ["cara", "alice", "boris"])

    async def test_first_seen_sorts_chronologically(self):
        self.assertEqual(await self.nicks(sort="first", dir="asc"),
                         ["alice", "cara", "boris"])
        self.assertEqual(await self.nicks(sort="first", dir="desc"),
                         ["boris", "cara", "alice"])

    async def test_last_seen_sorts_chronologically(self):
        self.assertEqual(await self.nicks(sort="last", dir="desc"),
                         ["alice", "cara", "boris"])
        self.assertEqual(await self.nicks(sort="last", dir="asc"),
                         ["boris", "cara", "alice"])

    async def test_my_nick_sorts_by_the_stored_identity_list(self):
        # `my_nicks` is a JSON array stored as text, and the column shows it
        # joined. Ordering the stored text needs no JSON extension and cannot
        # fail on a hand-edited row; the only wrinkle is that a person with
        # several identities sorts just before one sharing the same first
        # identity (`["Me", "Old"]` < `["Me"]`, because "," < "]").
        self.assertEqual(await self.nicks(sort="my_nick", dir="asc"),
                         ["cara", "boris", "alice"])
        self.assertEqual(await self.nicks(sort="my_nick", dir="desc"),
                         ["alice", "boris", "cara"])

    async def test_direction_is_reported_back_to_the_ui(self):
        page = await self.q.list_persons(PersonPageRequest(sort="media", dir="asc"))
        self.assertEqual(page["sort"], "media")
        self.assertEqual(page["dir"], "asc")
        page = await self.q.list_persons(PersonPageRequest(sort="nick"))
        self.assertEqual(page["sort"], "nick")
        self.assertEqual(page["dir"], "asc", "the natural direction of nick")


class TestBackwardsCompatibility(SortCase):
    """Callers that predate the feature send no `dir` at all."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.person("alice", messages=5, media=1,
                          first="2026-01-05 10:00:00",
                          last="2026-09-01 10:00:00")
        await self.person("boris", messages=50, media=9,
                          first="2026-03-05 10:00:00",
                          last="2026-07-01 10:00:00")
        await self.person("cara", messages=9, media=4,
                          first="2026-02-05 10:00:00",
                          last="2026-08-01 10:00:00")

    async def test_an_empty_direction_means_the_natural_one(self):
        cases = {
            "nick": ["alice", "boris", "cara"],
            "msgs": ["boris", "cara", "alice"],
            "media": ["boris", "cara", "alice"],   # 9, 4, 1
            "first": ["alice", "cara", "boris"],
            "last": ["alice", "cara", "boris"],
        }
        for key, want in cases.items():
            self.assertEqual(await self.nicks(sort=key, dir=""), want, key)
            self.assertEqual(await self.nicks(sort=key), want, key + " (no dir)")

    async def test_the_legacy_aliases_keep_their_historical_order(self):
        # `recent` was "last_seen DESC, message_count DESC" before the feature
        self.assertEqual(await self.nicks(sort="recent"),
                         ["alice", "cara", "boris"])
        # `messages` was "message_count DESC, last_seen DESC"
        self.assertEqual(await self.nicks(sort="messages"),
                         ["boris", "cara", "alice"])
        # `nick` was ascending, `first` ascending — unchanged
        self.assertEqual(await self.nicks(sort="nick"),
                         ["alice", "boris", "cara"])
        self.assertEqual(await self.nicks(sort="first"),
                         ["alice", "cara", "boris"])

    async def test_an_unknown_direction_falls_back_to_natural(self):
        self.assertEqual(await self.nicks(sort="nick", dir="sideways"),
                         ["alice", "boris", "cara"])
        self.assertEqual(await self.nicks(sort="msgs", dir="DESCENDING"),
                         ["boris", "cara", "alice"])


class TestUnknownInput(SortCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.person("alice", messages=5, last="2026-09-01 10:00:00")
        await self.person("boris", messages=50, last="2026-07-01 10:00:00")

    async def test_an_unknown_key_falls_back_to_the_default_order(self):
        self.assertEqual(await self.nicks(sort="nope"),
                         await self.nicks(sort="recent"))

    async def test_no_key_at_all_uses_the_default(self):
        self.assertEqual(await self.nicks(), await self.nicks(sort="recent"))


class TestPagingIsStable(SortCase):
    """A sortable, paged list needs a TOTAL order. With ties on the primary
    columns SQLite is free to re-shuffle between two `LIMIT/OFFSET` queries,
    so a row can be served twice or never — the classic "I scrolled and a
    person disappeared" bug."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        # 25 people, only five distinct (message_count, last_seen) pairs and
        # one shared first_seen: ties on every sortable column.
        for i in range(25):
            await self.person(
                f"p{i:02d}",
                messages=(i % 5) + 1,
                media=i % 2,
                first="2026-01-01 00:00:00",
                last=f"2026-0{(i % 5) + 1}-01 00:00:00")

    async def walk(self, **kwargs):
        seen, offset = [], 0
        while True:
            page = await self.q.list_persons(PersonPageRequest(limit=5, offset=offset, **kwargs))
            if not page["items"]:
                break
            seen.extend(item["nick"] for item in page["items"])
            if not page["has_more"]:
                break
            offset += 5
        return seen

    async def test_every_person_appears_exactly_once_per_sort(self):
        full = sorted(await self.nicks(sort="nick", dir="asc"))
        self.assertEqual(len(full), 25)
        for key in ("nick", "msgs", "media", "first", "last", "my_nick"):
            for direction in ("asc", "desc"):
                walked = await self.walk(sort=key, dir=direction)
                self.assertEqual(sorted(walked), full,
                                 f"paging {key}/{direction} lost or repeated "
                                 "rows")
                self.assertEqual(len(walked), 25,
                                 f"{key}/{direction} served a row twice")

    async def test_the_paged_walk_reproduces_the_single_query_order(self):
        whole = await self.nicks(sort="msgs", dir="desc")
        self.assertEqual(await self.walk(sort="msgs", dir="desc"), whole)

    async def test_the_default_sort_pages_stably_too(self):
        whole = await self.nicks(sort="recent")
        self.assertEqual(await self.walk(sort="recent"), whole)


class TestSearchInteraction(SortCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        # "Ангел" / "Ангелина" START with the needle; "Мой Ангел" only
        # contains it, yet has by far the most messages. The two "… Ангел"
        # rows are the same length, so nothing but the chosen column can
        # separate them.
        await self.person("Ангел", messages=2, last="2026-09-01 10:00:00")
        await self.person("Ангелина", messages=3, last="2026-08-01 10:00:00")
        await self.person("Мой Ангел", messages=900, last="2026-09-09 10:00:00")
        # Same length as "Мой Ангел" (9 chars) so that inside this tier
        # nothing but the chosen column can separate them.
        await self.person("Bbb Ангел", messages=700, last="2026-09-08 10:00:00")
        await self.person("Aaa Ангел", messages=1, last="2026-09-07 10:00:00")

    async def test_a_prefix_match_still_outranks_the_column_order(self):
        page = await self.q.list_persons(PersonPageRequest(q="ангел", sort="msgs", dir="desc",
                                         limit=10))
        self.assertEqual(page["total"], 5)
        self.assertEqual([i["nick"] for i in page["items"][:2]],
                         ["Ангел", "Ангелина"],
                         "the prefix boost must survive a column sort")
        self.assertNotIn("Мой Ангел", [i["nick"] for i in page["items"][:2]],
                         "900 messages must not outrank relevance")

    async def test_the_closest_match_leads_its_tier(self):
        # Inside the boosted tier the existing relevance rule (shorter nick =
        # closer match) still decides; the column order must not overturn it.
        page = await self.q.list_persons(PersonPageRequest(q="ангел", sort="msgs", dir="desc",
                                         limit=10))
        self.assertEqual([i["nick"] for i in page["items"][:2]],
                         ["Ангел", "Ангелина"],
                         "5 letters before 8, even with fewer messages")

    async def test_the_column_order_decides_outside_the_relevance_tier(self):
        down = await self.q.list_persons(PersonPageRequest(q="ангел", sort="msgs", dir="desc",
                                         limit=10))
        self.assertEqual([i["nick"] for i in down["items"][2:]],
                         ["Мой Ангел", "Bbb Ангел", "Aaa Ангел"],
                         "900, 700, 1 messages")
        up = await self.q.list_persons(PersonPageRequest(q="ангел", sort="msgs", dir="asc",
                                       limit=10))
        self.assertEqual([i["nick"] for i in up["items"][2:]],
                         ["Aaa Ангел", "Bbb Ангел", "Мой Ангел"],
                         "the same tier reversed")


class TestArchiveRules(SortCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.person("alive", messages=5, last="2026-09-01 10:00:00")
        await self.person("gone", messages=50, last="2026-09-02 10:00:00",
                          deleted=True)

    async def test_tombstones_stay_hidden_under_every_sort(self):
        for key in ("nick", "msgs", "media", "first", "last", "my_nick"):
            for direction in ("asc", "desc"):
                got = await self.nicks(sort=key, dir=direction)
                self.assertEqual(got, ["alive"], f"{key}/{direction}")

    async def test_include_deleted_still_works_with_a_sort(self):
        got = await self.nicks(sort="nick", dir="desc", include_deleted=True)
        self.assertEqual(got, ["gone", "alive"])


class TestNoSqlInjection(SortCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.person("alice", messages=5, last="2026-09-01 10:00:00")
        await self.person("boris", messages=50, last="2026-07-01 10:00:00")

    async def test_hostile_sort_and_dir_are_data_not_syntax(self):
        hostile = [
            ("last_seen; DROP TABLE persons--", "asc"),
            ("nick", "asc; DELETE FROM persons"),
            ("(SELECT nick FROM persons)", "desc"),
            ("nick ASC --", "asc"),
        ]
        for sort, direction in hostile:
            page = await self.q.list_persons(PersonPageRequest(sort=sort, dir=direction))
            self.assertEqual(len(page["items"]), 2, f"payload {sort!r}")
        self.assertEqual(await self.raw_count(), 2,
                         "the persons table survived a hostile sort/dir")

    async def test_the_order_by_never_contains_user_text(self):
        # The whitelist is the mechanism; this pins it from the outside.
        page = await self.q.list_persons(PersonPageRequest(sort="message_count DESC; --",
                                         dir="asc"))
        self.assertEqual(page["sort"], "message_count DESC; --",
                         "the request is echoed verbatim …")
        self.assertEqual([i["nick"] for i in page["items"]],
                         await self.nicks(sort="recent", dir="asc"),
                         "… but it is ordered by the default key, not by SQL")


class TestRealRepositoryPath(SortCase):
    """One end-to-end case through the collector's own write path, so the
    fixture style above cannot hide a mismatch with real data."""

    async def test_the_archive_written_by_the_repo_sorts_as_promised(self):
        await self.repo.append("Nick", [rec(text=f"m{i}", idx=i)
                                        for i in range(4)], my_nick="Me",
                               now=NOW)
        await self.repo.append("Other", [rec(text="x", idx=0)], my_nick="Me",
                               now=NOW)
        busiest = await self.q.list_persons(PersonPageRequest(sort="msgs", dir="desc"))
        self.assertEqual(busiest["items"][0]["nick"], "Nick")
        quietest = await self.q.list_persons(PersonPageRequest(sort="msgs", dir="asc"))
        self.assertEqual(quietest["items"][0]["nick"], "Other")
        alpha = await self.q.list_persons(PersonPageRequest(sort="nick", dir="asc"))
        self.assertEqual([i["nick"] for i in alpha["items"]],
                         ["Nick", "Other"])


class TestResponseEnvelope(SortCase):
    """The paging envelope the UI reads, pinned key by key.

    Mutation testing found these unpinned: renaming the payload key `"limit"`
    to `"LIMIT"`, flipping `total > offset + len(items)` to `>=`, and dropping
    the `my_nicks` argument all survived, because the sort tests only ever read
    `item["nick"]` to check ordering and `page["total"]` once.
    """

    async def test_the_envelope_has_exactly_these_keys(self):
        await self.person("Ann")
        page = await self.q.list_persons(PersonPageRequest())
        self.assertEqual(
            set(page),
            {"items", "total", "has_more", "offset", "limit", "query",
             "sort", "dir"})

    async def test_the_requested_limit_is_honoured_and_echoed(self):
        for n in ("A", "B", "C", "D", "E"):
            await self.person(n)
        page = await self.q.list_persons(PersonPageRequest(limit=2))
        self.assertEqual(page["limit"], 2)
        self.assertEqual(len(page["items"]), 2)

    async def test_the_offset_is_echoed_and_applied(self):
        for n in ("A", "B", "C"):
            await self.person(n)
        page = await self.q.list_persons(PersonPageRequest(limit=2, offset=1))
        self.assertEqual(page["offset"], 1)
        self.assertEqual(len(page["items"]), 2)

    async def test_has_more_is_false_on_exactly_the_last_page(self):
        """`total > offset + len(items)`. At exactly the end it must be False —
        mutating `>` to `>=` makes the UI scroll for a page that is empty."""
        for n in ("A", "B", "C"):
            await self.person(n)
        page = await self.q.list_persons(PersonPageRequest(limit=3))
        self.assertEqual(page["total"], 3)
        self.assertFalse(page["has_more"])

    async def test_has_more_is_true_while_rows_remain(self):
        for n in ("A", "B", "C"):
            await self.person(n)
        page = await self.q.list_persons(PersonPageRequest(limit=2))
        self.assertTrue(page["has_more"])

    async def test_the_query_is_echoed_verbatim(self):
        await self.person("Ann")
        page = await self.q.list_persons(PersonPageRequest(q=" Ann "))
        self.assertEqual(page["query"], " Ann ",
                         "echoed as sent, not normalised")

    async def test_my_nicks_reach_the_payload(self):
        """`_person_item(row, self._my_nicks(row))` — passing None instead
        survived mutation testing, so the wiring is asserted here."""
        await self.person("Ann", my_nicks=["Me", "Me2"])
        page = await self.q.list_persons(PersonPageRequest())
        self.assertEqual(page["items"][0]["my_nicks"], ["Me", "Me2"])

    async def test_an_empty_database_still_reports_a_total(self):
        page = await self.q.list_persons(PersonPageRequest())
        self.assertEqual(page["total"], 0)
        self.assertEqual(page["items"], [])
        self.assertFalse(page["has_more"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
