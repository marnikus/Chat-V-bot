"""`_person_item` — the row → payload projection the Full User Database renders.

This file exists because mutation testing found a real hole. `_person_item`
survived 52 of 65 mutants: renaming the payload key `"message_count"` to
`"XXmessage_countXX"`, or turning `or 0` into `and 0`, broke nothing any test
could see — the sort suites only ever read `item["nick"]` to check ordering.

Coverage said 100%. The lines were executed; their *values* were never
asserted. That is exactly the gap a mutation score catches and a coverage
percentage hides, so the whole projection is pinned here, key by key.

`_person_item` is a pure module-level function, so these need no database.

Run with:  python3 tests/test_person_item.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.history_query import _person_item  # noqa: E402


def row(**over):
    """A `persons` row as SQLite would return it (schema defaults included)."""
    base = {
        "id": 7,
        "nick": "Ann",
        "nick_lc": "ann",
        "first_seen": "2026-01-02 03:04:05",
        "last_seen": "2026-09-07 10:00:00",
        "message_count": 12,
        "in_count": 8,
        "out_count": 4,
        "media_count": 3,
        "last_ord": 99,
        "my_nicks": '["Me", "Me2"]',
        "note": "",
        "created_at": "2026-01-02 03:04:05",
        "deleted_at": None,
    }
    base.update(over)
    return base


class TestEveryFieldIsProjected(unittest.TestCase):
    def test_the_full_row_becomes_the_exact_payload(self):
        self.assertEqual(
            _person_item(row(), ["Me", "Me2"]),
            {"id": 7,
             "nick": "Ann",
             "message_count": 12,
             "in_count": 8,
             "out_count": 4,
             "media_count": 3,
             "first_seen": "2026-01-02 03:04:05",
             "last_seen": "2026-09-07 10:00:00",
             "my_nicks": ["Me", "Me2"],
             "deleted": False})

    def test_no_extra_keys_leak_into_the_payload(self):
        """`last_ord`, `note`, `nick_lc` and `created_at` are storage details —
        the UI must not receive them."""
        self.assertEqual(
            set(_person_item(row(), [])),
            {"id", "nick", "message_count", "in_count", "out_count",
             "media_count", "first_seen", "last_seen", "my_nicks", "deleted"})

    def test_the_directional_counters_stay_separate(self):
        """A swap between `in_count` and `out_count` must be visible; they are
        distinct numbers on purpose."""
        item = _person_item(row(in_count=5, out_count=9), [])
        self.assertEqual(item["in_count"], 5)
        self.assertEqual(item["out_count"], 9)


class TestAbsentValuesBecomeNeutral(unittest.TestCase):
    """`or 0` / `or ""` — a NULL column must not reach the UI as None, and
    `int(None)` would raise. Mutating `or` to `and` breaks exactly this."""

    def test_null_counters_project_to_zero(self):
        item = _person_item(row(message_count=None, in_count=None,
                                out_count=None, media_count=None), [])
        self.assertEqual((item["message_count"], item["in_count"],
                          item["out_count"], item["media_count"]),
                         (0, 0, 0, 0))

    def test_null_timestamps_project_to_empty_strings(self):
        item = _person_item(row(first_seen=None, last_seen=None), [])
        self.assertEqual(item["first_seen"], "")
        self.assertEqual(item["last_seen"], "")

    def test_columns_missing_from_the_row_entirely(self):
        bare = {"id": 1, "nick": "Bo"}
        item = _person_item(bare, [])
        self.assertEqual(item["message_count"], 0)
        self.assertEqual(item["media_count"], 0)
        self.assertEqual(item["first_seen"], "")
        self.assertEqual(item["last_seen"], "")
        self.assertFalse(item["deleted"])


class TestDeletedFlag(unittest.TestCase):
    def test_a_tombstone_timestamp_sets_the_flag(self):
        self.assertTrue(_person_item(
            row(deleted_at="2026-09-07 10:00:00"), [])["deleted"])

    def test_no_tombstone_means_not_deleted(self):
        self.assertFalse(_person_item(row(deleted_at=None), [])["deleted"])

    def test_the_flag_is_a_real_bool_not_the_timestamp(self):
        item = _person_item(row(deleted_at="2026-09-07 10:00:00"), [])
        self.assertIs(item["deleted"], True)


class TestTypesAreJsonReady(unittest.TestCase):
    """The payload is json.dumps'd straight to the WebChannel, so SQLite's
    loose typing must be normalised before it leaves."""

    def test_counters_are_ints_even_when_sqlite_returns_strings(self):
        item = _person_item(row(message_count="12", media_count="3"), [])
        self.assertIs(type(item["message_count"]), int)
        self.assertIs(type(item["media_count"]), int)
        self.assertEqual(item["message_count"], 12)

    def test_the_id_is_an_int(self):
        self.assertIs(type(_person_item(row(id="7"), [])["id"]), int)

    def test_my_nicks_is_passed_through_untouched(self):
        """Parsing the JSON is `_my_nicks`'s job, not the projection's."""
        sent = ["Me", "Me2"]
        self.assertIs(_person_item(row(), sent)["my_nicks"], sent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
