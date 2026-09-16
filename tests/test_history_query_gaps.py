"""Round F step F6 — the mutation survivors in `backend/history_query.py`.

The configured mutation job (`setup.cfg [mutmut]`, mutmut 3.7.0, scored in
reports/CODE_QUALITY_METRICS_2026-09-12.md §3) generated 1,141 mutants of
`backend/history_query.py` and left **9 survivors**. This file closes eight of
them; the ninth is an equivalent mutant and is recorded at the bottom rather
than chased.

The nine turned out to be two different kinds of gap, so they are tested at two
different levels:

* **The call `list_persons` makes** (4 mutants: the COUNT's fallback argument
  ×3 and the page SQL's spelling). Nothing in the selected suites could see
  these. Over a real SQLite file `SELECT COUNT(*)` always returns exactly one
  non-NULL row, so the fallback argument is unreachable by construction, and no
  suite read the SQL text — the real-database suites assert the *order of the
  nicks that came back*, which is the same order under every one of these
  mutants. A recording stand-in for `HistoryDB` makes both visible.
* **The values the helpers guarantee** (backslash escaping, the limit floor).
  Here the repo was NOT missing tests: `tests/test_history_query_edges.py`
  already asserts `_like_escape("back\\slash") == "back\\\\slash"` and
  `_clamp(-5) == 1` / `_clamp("garbage") == 50`, and all four of those mutants
  die there — measured by running each mutant against that file one at a time.
  They survived the *job* because the job does not select that file. Widening
  the selection was measured and rejected: that one file executes all 29
  functions of the module, which makes 910 of its 1,141 mutants reachable
  instead of 159, and the narrow job's ~25 seconds become something else (the
  reachable count is measured; the runtime was not run, so it is not quoted).
  So the same two guarantees are pinned here at the level the job measures — a
  page the UI actually asked for — and the duplication is named instead of left
  for the next reader to rediscover.

One trap, because it decides whether any of this reproduces: mutmut reads a
non-zero pytest exit as a kill, so where `tests/conftest.py` cannot import
PySide6 the job reports **159/159 killed, 0 survivors** — a false 100% that
looks like success. `pytest_add_cli_args = --noconftest` in `setup.cfg` makes
that impossible and is neutral where PySide6 does import.

Design/outcome: docs/archive/2026-09-12-round-f-size-tail/ROUND_F_DESIGN_2026-09-12.md §9

Run with:  python3 tests/test_history_query_gaps.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.history_db import HistoryDB  # noqa: E402
from backend.history_query import (  # noqa: E402
    DEFAULT_LIMIT, HistoryQuery, PersonPageRequest,
)
from backend import history_query as hq_mod  # noqa: E402

#: What the default request must send the engine, verbatim. Written out rather
#: than assembled from `req.where()` / `req.order()`: assembling it would
#: re-derive the mutant from the mutant's own source and could not fail.
COUNT_SQL = "SELECT COUNT(*) FROM persons WHERE deleted_at IS NULL"
PAGE_SQL = ("SELECT * FROM persons WHERE deleted_at IS NULL ORDER BY "
            "last_seen DESC, message_count DESC, nick_lc ASC, id ASC "
            "LIMIT ? OFFSET ?")


def row(nick="Ann", **over):
    """One `persons` row as `fetchdicts` would return it."""
    base = {"id": 1, "nick": nick, "nick_lc": nick.lower(), "message_count": 3,
            "in_count": 2, "out_count": 1, "media_count": 0,
            "first_seen": "2026-01-01 00:00:00",
            "last_seen": "2026-09-01 00:00:00", "my_nicks": '["Me"]',
            "deleted_at": None}
    base.update(over)
    return base


class RecordingDB:
    """A `HistoryDB` stand-in that records what `list_persons` asks it for.

    Two properties are deliberate:

    * `scalar`'s `default` is a **required positional**. The real signature is
      `scalar(sql, params=(), default=0)` — the same `0` `list_persons` passes —
      so *dropping* the argument is invisible against the real engine and that
      one mutant stays equivalent (see `TestTheSqlItSends`). What the stand-in
      pins is the call convention: the count's fallback belongs to the caller,
      not to whichever default the engine happens to carry today.
    * `count=None` means "the count query yielded nothing", the only situation
      in which that fallback is observable at all — and one a real SQLite file
      cannot produce, which is exactly why three mutants sat on that argument
      unnoticed while coverage of the line read 100%.
    """

    def __init__(self, rows=(), count=0):
        self.rows = [dict(r) for r in rows]
        self.count = count
        self.calls = []

    async def scalar(self, sql, params, default):
        self.calls.append(("count", sql, list(params), default))
        return default if self.count is None else self.count

    async def fetchdicts(self, sql, params=()):
        self.calls.append(("page", sql, list(params)))
        return list(self.rows)


class TestTheCountFallback(unittest.IsolatedAsyncioTestCase):
    """`list_persons` mutants 18 (`0` → `None`) and 22 (`0` → `1`)."""

    async def test_a_count_that_yields_nothing_still_reports_total_zero(self):
        db = RecordingDB(rows=[], count=None)
        page = await HistoryQuery(db).list_persons(PersonPageRequest())
        self.assertEqual(page["total"], 0)
        self.assertEqual(page["items"], [])
        self.assertFalse(page["has_more"])

    async def test_the_envelope_stays_json_ready_when_the_count_is_missing(self):
        """`total` is an int on the way in and crosses the QWebChannel as JSON
        on the way out, and `has_more` is computed from it. A `None` there is a
        `TypeError` raised inside a bridge slot: the user's list simply stops
        paging, with the explanation in a log nobody is reading. A `1` is worse
        — it is a plausible number, so the grid offers a next page that is
        empty."""
        db = RecordingDB(rows=[row()], count=None)
        page = await HistoryQuery(db).list_persons(PersonPageRequest())
        self.assertIsInstance(page["total"], int)
        self.assertEqual(page["total"], 0)
        json.dumps(page)                              # must not raise


class TestTheSqlItSends(unittest.IsolatedAsyncioTestCase):
    """`list_persons` mutants 21 (fallback argument dropped) and 29
    (`LIMIT ? OFFSET ?` lower-cased), plus the binding order the function's own
    docstring promises: COUNT binds `where()` only, the page binds `where()` +
    `order()` + limit/offset, in that order.

    A mis-bind is silent — the engine happily runs it and returns the wrong
    people — so the statements are pinned as text at the call site, which is
    the one place the existing suites cannot see: `test_person_page_request.py`
    pins the fragments the request builds, `test_userdb_sort_query.py` pins the
    order that comes back, and neither observes what is actually sent.
    """

    async def test_the_count_binds_only_the_where_parameters(self):
        db = RecordingDB()
        await HistoryQuery(db).list_persons(
            PersonPageRequest(q="ангел", sort="nick", limit=5, offset=10))
        kind, sql, params, default = db.calls[0]
        self.assertEqual(kind, "count")
        self.assertEqual(sql, "SELECT COUNT(*) FROM persons WHERE "
                              "deleted_at IS NULL AND nick_lc LIKE ? "
                              "ESCAPE '\\'")
        self.assertEqual(params, ["%ангел%"], "no relevance parameter here")
        self.assertEqual(default, 0, "the caller owns the fallback")

    async def test_the_page_binds_where_then_order_then_limit_offset(self):
        db = RecordingDB()
        await HistoryQuery(db).list_persons(
            PersonPageRequest(q="ангел", sort="nick", limit=5, offset=10))
        kind, sql, params = db.calls[1]
        self.assertEqual(kind, "page")
        self.assertEqual(params, ["%ангел%", "ангел%", 5, 10],
                         "substring filter, prefix boost, then limit/offset")
        self.assertEqual(sql.count("?"), len(params),
                         "every placeholder has exactly one bound value")

    async def test_the_default_request_sends_the_documented_statements(self):
        """Mutant 29 wrote `limit ? offset ?` and nothing noticed, because
        SQLite folds the case of its keywords: the behaviour really is
        identical, and this is the one assertion here that pins a statement
        rather than an outcome. It is kept because the statement IS the
        contract — the module docstring quotes it, the paging invariant
        (a TOTAL order under `LIMIT/OFFSET`) depends on it, and a rewrite
        should be a decision somebody makes on purpose."""
        db = RecordingDB()
        await HistoryQuery(db).list_persons(PersonPageRequest())
        self.assertEqual(db.calls[0][1], COUNT_SQL)
        self.assertEqual(db.calls[1][1], PAGE_SQL)


class RealDBCase(unittest.IsolatedAsyncioTestCase):
    """A real SQLite file, so what follows is observed through the engine."""

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = HistoryDB(os.path.join(self.dir, "history.db"))
        await self.db.init()
        self.q = HistoryQuery(self.db)

    async def asyncTearDown(self):
        await self.db.close()

    async def person(self, nick, messages=1, my_nicks=None):
        await self.db.execute(
            "INSERT INTO persons(nick, nick_lc, first_seen, last_seen, "
            "message_count, media_count, my_nicks, created_at, deleted_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (nick, nick.lower(), "2026-01-01 00:00:00",
             "2026-09-01 00:00:00", messages, 0,
             json.dumps(my_nicks or [], ensure_ascii=False),
             "2026-09-01 00:00:00", None))
        await self.db.commit()

    async def nicks(self, **kwargs):
        page = await self.q.list_persons(PersonPageRequest(**kwargs))
        return [item["nick"] for item in page["items"]]


class TestTheLimitFloorOnItsWayToTheEngine(RealDBCase):
    """`_clamp` mutants 4 (the `except` branch assigning `None`) and 9
    (`max(1, …)` → `max(2, …)`).

    Both already die in `tests/test_history_query_edges.py`, which pins the
    helper directly; the job does not select that file, so the same two rules
    are pinned here through a page request, which is how they reach a user.
    """

    async def test_a_limit_of_one_really_returns_one_row(self):
        for nick in ("A", "B", "C"):
            await self.person(nick)
        page = await self.q.list_persons(PersonPageRequest(limit=1))
        self.assertEqual(page["limit"], 1, "the floor is 1, not 2")
        self.assertEqual(len(page["items"]), 1)
        self.assertTrue(page["has_more"])

    async def test_a_limit_the_engine_cannot_use_falls_back_to_the_default(self):
        """`req.limit` arrives from a JSON blob the UI built, so a hand-edited
        or truncated payload can put anything in it. `_clamp` catches both
        `int()` failures; assigning `None` in the handler instead turns a
        recoverable page into a `TypeError` two lines later."""
        for nick in ("A", "B"):
            await self.person(nick)
        for bad in ("garbage", [3]):
            page = await self.q.list_persons(PersonPageRequest(limit=bad))
            self.assertEqual(page["limit"], DEFAULT_LIMIT, repr(bad))
            self.assertEqual(len(page["items"]), 2, repr(bad))


class TestABackslashInANickFilter(RealDBCase):
    """`_like_escape` mutants 13 and 14 — the two halves of the backslash
    doubling, the search string and the replacement.

    `tests/test_history_query_edges.py` pins the helper's output and kills both;
    no suite had put a backslash through the *filter*. With `ESCAPE '\\'` an
    un-doubled backslash swallows the character after it, so the search finds a
    different person and reports a confident total for them.
    """

    async def test_a_backslash_nick_is_found_and_only_it(self):
        await self.person("a\\b")
        await self.person("ab")
        page = await self.q.list_persons(PersonPageRequest(q="a\\b"))
        self.assertEqual([item["nick"] for item in page["items"]], ["a\\b"],
                         "un-doubled, `\\b` means a literal b")
        self.assertEqual(page["total"], 1)

    async def test_a_lone_backslash_still_matches_the_nick_containing_it(self):
        await self.person("a\\b")
        await self.person("ab")
        self.assertEqual(await self.nicks(q="\\"), ["a\\b"])


class TestTheIdentityListFallback(RealDBCase):
    """`_my_nicks` mutant 7 — an **equivalent mutant**, recorded not chased.

    `json.loads(v or "[]")` and `json.loads(v or "XX[]XX")` cannot be told
    apart by any input: a truthy `v` short-circuits the `or` in both, and a
    falsy one parses to `[]` in the original and raises into the `except` —
    which also returns `[]` — in the mutant. Same value, same type, every time.
    Killing it would require spying on the argument `json.loads` receives, i.e.
    pinning a string literal instead of a behaviour, so it is reported as
    equivalent and left alive. What both paths share is pinned here.

    The schema makes the falsy branch narrower than it looks: `my_nicks` is
    `TEXT NOT NULL DEFAULT '[]'` (stores/history_schema.py:55), so a stored
    NULL is impossible and only a hand-emptied string, a non-JSON string, or a
    row that omits the column altogether can reach it.
    """

    async def test_a_blank_or_broken_identity_list_reads_as_empty(self):
        await self.person("Ann", my_nicks=["Me"])
        self.assertEqual((await self.q.list_persons(
            PersonPageRequest()))["items"][0]["my_nicks"], ["Me"])
        for stored in ("", "not json", "[]"):
            await self.db.execute(
                "UPDATE persons SET my_nicks=? WHERE nick='Ann'", (stored,))
            await self.db.commit()
            page = await self.q.list_persons(PersonPageRequest())
            self.assertEqual(page["items"][0]["my_nicks"], [], repr(stored))


class TestTheIdentityListIsReadDefensively(unittest.TestCase):
    """The same fallback, on rows that never reached a database."""

    def test_a_row_without_the_column_reads_as_empty(self):
        for absent in ({}, {"my_nicks": None}, {"my_nicks": ""}):
            # the helper moved from a classmethod to the projection module,
            # re-exported at history_query top level (drift, 2026-09-16)
            self.assertEqual(hq_mod._my_nicks(absent), [], repr(absent))

    def test_a_stored_list_comes_back_as_a_list(self):
            self.assertEqual(hq_mod._my_nicks({"my_nicks": '["Me","Me2"]'}),
                         ["Me", "Me2"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
