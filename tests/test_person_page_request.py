"""`PersonPageRequest` — the Full User Database page request, in isolation.

The request object carries the six options the UI sends as one JSON blob and
owns the SQL fragments built from them. Testing it apart from the database
pins the two things a SQL test cannot see clearly:

  * the ORDER BY body is assembled ONLY from the whitelist, in the documented
    order, with a total-order tiebreaker;
  * the parameter lists line up with the placeholders — COUNT binds the WHERE
    parameters, SELECT binds WHERE + ORDER BY + limit/offset. Getting that
    wrong is a silent mis-binding, not an exception.

Design: docs/RULE16_SIZE_COMPLEXITY_FIT_2026-09-10.md §2.1

Run with:  python3 tests/test_person_page_request.py
"""

import dataclasses
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.history_query import (  # noqa: E402
    DEFAULT_SORT, SORT_COLUMNS, SORT_TIEBREAK, PersonPageRequest,
)


class TestNaturalOrder(unittest.TestCase):
    """No `dir` ⇒ the key's own natural direction (backwards compatible)."""

    def test_the_default_request_is_the_historical_recent_order(self):
        req = PersonPageRequest()
        self.assertEqual(req.sort, DEFAULT_SORT)
        self.assertEqual(req.resolved_dir(), "desc")
        self.assertEqual(req.columns(),
                         "last_seen DESC, message_count DESC, "
                         "nick_lc ASC, id ASC")

    def test_every_key_has_a_documented_natural_direction(self):
        natural = {"nick": "asc", "first": "asc", "my_nick": "asc",
                   "msgs": "desc", "media": "desc", "last": "desc",
                   "messages": "desc", "recent": "desc"}
        self.assertEqual(set(natural), set(SORT_COLUMNS),
                         "the whitelist and the UI's NATURAL map must agree")
        for key, want in natural.items():
            self.assertEqual(PersonPageRequest(sort=key).resolved_dir(), want,
                             key)

    def test_the_tiebreaker_makes_the_order_total(self):
        for key in SORT_COLUMNS:
            body = PersonPageRequest(sort=key).columns()
            for column in SORT_TIEBREAK:
                self.assertIn(column, body, f"{key} lost the {column} tiebreak")
            self.assertEqual(body.count("nick_lc"), 1,
                             f"{key} mentions nick_lc twice: {body}")
            self.assertEqual(body.count("id"), 1,
                             f"{key} mentions id twice: {body}")

    def test_the_secondary_column_follows_the_primary_one(self):
        # `msgs` descending = busiest first, and among equals the OLDEST
        # activity last — both columns flip together.
        self.assertEqual(PersonPageRequest(sort="msgs").columns(),
                         "message_count DESC, last_seen DESC, "
                         "nick_lc ASC, id ASC")
        self.assertEqual(PersonPageRequest(sort="msgs", dir="asc").columns(),
                         "message_count ASC, last_seen ASC, "
                         "nick_lc ASC, id ASC")


class TestDirectionOverride(unittest.TestCase):
    def test_an_explicit_direction_flips_every_column(self):
        self.assertEqual(PersonPageRequest(sort="nick", dir="desc").columns(),
                         "nick_lc DESC, id ASC")
        self.assertEqual(PersonPageRequest(sort="nick", dir="asc").columns(),
                         "nick_lc ASC, id ASC")
        self.assertEqual(PersonPageRequest(sort="first", dir="desc").columns(),
                         "first_seen DESC, nick_lc ASC, id ASC")

    def test_the_resolved_direction_is_echoed_for_the_header_arrow(self):
        self.assertEqual(PersonPageRequest(sort="nick").resolved_dir(), "asc")
        self.assertEqual(
            PersonPageRequest(sort="nick", dir="desc").resolved_dir(), "desc")

    def test_an_unusable_direction_falls_back_to_natural(self):
        for bad in ("", "  ", "sideways", "DESCENDING", None):
            req = PersonPageRequest(sort="nick", dir=bad)
            self.assertEqual(req.resolved_dir(), "asc", repr(bad))
            self.assertEqual(req.columns(),
                             PersonPageRequest(sort="nick").columns(),
                             repr(bad))

    def test_the_direction_is_case_insensitive(self):
        self.assertEqual(PersonPageRequest(sort="nick", dir="DESC").columns(),
                         PersonPageRequest(sort="nick", dir="desc").columns())


class TestUnknownSortKey(unittest.TestCase):
    def test_an_unknown_key_falls_back_to_the_default(self):
        for bad in ("nope", "", None, "message_count DESC; --",
                    "(SELECT nick FROM persons)"):
            req = PersonPageRequest(sort=bad)
            self.assertEqual(req.spec(), SORT_COLUMNS[DEFAULT_SORT], repr(bad))
            self.assertEqual(req.columns(),
                             PersonPageRequest().columns(), repr(bad))

    def test_no_user_text_reaches_the_order_by(self):
        hostile = "last_seen; DROP TABLE persons--"
        req = PersonPageRequest(sort=hostile, dir="asc; DELETE FROM persons")
        body = req.columns()
        for token in ("DROP", "DELETE", ";", "--"):
            self.assertNotIn(token, body, body)


class TestWhereClause(unittest.TestCase):
    def test_live_people_only_by_default(self):
        clause, params = PersonPageRequest().where()
        self.assertEqual(clause, "deleted_at IS NULL")
        self.assertEqual(params, [])

    def test_tombstones_can_be_asked_for(self):
        clause, params = PersonPageRequest(include_deleted=True).where()
        self.assertEqual(clause, "1=1")
        self.assertEqual(params, [])

    def test_a_nick_filter_adds_one_escaped_parameter(self):
        clause, params = PersonPageRequest(q=" Ангел ").where()
        self.assertEqual(clause, "deleted_at IS NULL AND nick_lc LIKE ? "
                                 "ESCAPE '\\'")
        self.assertEqual(params, ["%ангел%"], "trimmed and lower-cased")

    def test_wildcards_in_a_nick_are_literal(self):
        # the needle is lower-cased because it is matched against `nick_lc`,
        # so the search is case-insensitive; the point here is that `%` and
        # `_` arrive escaped and therefore act as literals.
        _clause, params = PersonPageRequest(q="Ann%").where()
        self.assertEqual(params, ["%ann\\%%"], "% must not act as a wildcard")
        _clause, params = PersonPageRequest(q="Ann_").where()
        self.assertEqual(params, ["%ann\\_%"])

    def test_a_blank_query_is_no_filter(self):
        for blank in ("", "   ", None):
            self.assertEqual(PersonPageRequest(q=blank).where(),
                             ("deleted_at IS NULL", []), repr(blank))


class TestOrderClause(unittest.TestCase):
    def test_without_a_query_there_are_no_order_parameters(self):
        body, params = PersonPageRequest(sort="nick").order()
        self.assertEqual(body, "nick_lc ASC, id ASC")
        self.assertEqual(params, [])

    def test_a_query_puts_relevance_first_and_binds_one_parameter(self):
        body, params = PersonPageRequest(q="ангел", sort="msgs").order()
        self.assertTrue(body.startswith("(nick_lc LIKE ? ESCAPE '\\') DESC, "
                                        "LENGTH(nick_lc) ASC, "), body)
        self.assertTrue(body.endswith("message_count DESC, last_seen DESC, "
                                      "nick_lc ASC, id ASC"), body)
        self.assertEqual(params, ["ангел%"], "a prefix match, not a substring")

    def test_the_placeholders_line_up_with_the_parameters(self):
        """COUNT binds only the WHERE parameter; SELECT binds WHERE + ORDER BY
        + limit/offset. A mis-bind here is silent, so it is pinned."""
        req = PersonPageRequest(q="ангел", sort="nick", limit=5, offset=10)
        where, where_params = req.where()
        order, order_params = req.order()
        self.assertEqual(where.count("?"), len(where_params),
                         "the WHERE clause and its parameters must match")
        self.assertEqual(order.count("?"), len(order_params),
                         "the ORDER BY and its parameters must match")
        self.assertEqual(where_params + order_params, ["%ангел%", "ангел%"])


class TestRequestIsImmutable(unittest.TestCase):
    def test_the_request_cannot_be_mutated_on_its_way_to_the_database(self):
        req = PersonPageRequest(sort="nick")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            req.sort = "msgs"

    def test_equal_requests_compare_equal(self):
        self.assertEqual(PersonPageRequest(sort="nick", dir="asc"),
                         PersonPageRequest(sort="nick", dir="asc"))
        self.assertNotEqual(PersonPageRequest(sort="nick"),
                            PersonPageRequest(sort="msgs"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
