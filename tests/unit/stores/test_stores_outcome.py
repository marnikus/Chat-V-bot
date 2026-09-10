"""AREA B1 — `stores/outcome.py`: a Result whose truthiness means something.

Design ref: docs/archive/2026-09-09-four-area-refactor/REFACTOR_2026-09-09_AREA_B_DESIGN.md §1.2 (decision 4).

`core/result.py` (frozen for every area) has one problem for the config
stores: an `Ok(None)` is truthy and an `Err` is truthy too, so the two
callers that ask "did that change anything?" —

  * `bridge/cdp_bridge.py:87`  → `if self.ctx.config.bookmarks.add(url):`
  * `tests/test_stores_split.py::FacadeCase::test_bookmarks_dedup`

could never get a useful answer. The stores therefore wrap their `Result`
in a truthiness-aware pair that keeps every `Ok`/`Err` attribute.

Run with:  python3 tests/unit/stores/test_stores_outcome.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from stores.atomic import AtomicJsonStore  # noqa: E402
from stores.bookmark_store import DEFAULT_URLS, BookmarkStore  # noqa: E402

try:
    from stores.outcome import Outcome, Refusal  # noqa: E402
    HAVE_OUTCOME = True
except ImportError:                               # pragma: no cover - pre-B1
    Outcome = Refusal = None
    HAVE_OUTCOME = False


@unittest.skipUnless(HAVE_OUTCOME, "stores/outcome.py is AREA B1 work")
class TestOutcomeType(unittest.TestCase):
    def test_outcome_truthiness_follows_its_value(self):
        self.assertTrue(bool(Outcome(True)))
        self.assertFalse(bool(Outcome(False)))
        self.assertTrue(Outcome(True).is_ok)
        self.assertFalse(Outcome(True).is_err)
        self.assertEqual(Outcome(True).value, True)
        self.assertEqual(Outcome(False).unwrap_or("x"), False)

    def test_refusal_is_always_falsy_and_still_an_err(self):
        refusal = Refusal("duplicate", "https://a")
        self.assertFalse(bool(refusal))
        self.assertTrue(refusal.is_err)
        self.assertFalse(refusal.is_ok)
        self.assertEqual(refusal.code, "duplicate")
        self.assertEqual(refusal.detail, "https://a")
        with self.assertRaises(RuntimeError):
            refusal.unwrap()

    def test_both_are_results_of_the_same_frozen_pair(self):
        from core.result import Err, Ok
        self.assertIsInstance(Outcome(True), Ok)
        self.assertIsInstance(Refusal("x"), Err)
        # `Result` is a Union alias — a store's `-> Result[...]` annotation
        # stays honest
        self.assertIn(type(Outcome(True)).__name__,
                      ("Outcome", "Ok", "BoolOk"))


class BookmarkOutcomeCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")
        self.store = BookmarkStore(AtomicJsonStore(self.path))


class TestBookmarkTruthiness(BookmarkOutcomeCase):
    """The contract `core/interfaces.py:BookmarkStoreProto` actually promises."""

    def test_a_new_bookmark_reports_a_change(self):            # B1-30
        result = self.store.add("https://a")
        self.assertTrue(result, "an added url must be truthy for the bridge")
        self.assertTrue(result.is_ok)

    def test_a_duplicate_is_refused_loudly(self):              # B1-31
        self.store.add("https://a")
        again = self.store.add("https://a")
        self.assertFalse(again, "a duplicate must not look like a change")
        self.assertTrue(again.is_err, "and it must still read as a Result")
        self.assertEqual(self.store.all().count("https://a"), 1)

    def test_an_empty_url_is_refused(self):                    # B1-32
        for blank in ("", "   ", None):
            result = self.store.add(blank)
            self.assertFalse(result)
            self.assertTrue(result.is_err)

    def test_removing_reports_whether_it_removed(self):        # B1-33
        self.store.add("https://a")
        removed = self.store.remove("https://a")
        self.assertTrue(removed)
        self.assertTrue(removed.is_ok)
        self.assertTrue(removed.value)
        ghost = self.store.remove("https://a")
        self.assertFalse(ghost, "a no-op removal must not claim a change")
        self.assertTrue(ghost.is_ok, "…but it is not an error (BMK-03)")
        self.assertFalse(ghost.value)

    def test_defaults_survive_a_wholesale_replace(self):        # B1-34
        self.assertEqual(self.store.all(), list(DEFAULT_URLS))
        self.store.set_all([])
        self.assertEqual(self.store.all(), [])
        self.assertEqual(BookmarkStore(self.path).all(), [])

    def test_a_failed_write_reports_no_change(self):           # B1-35
        blocker = os.path.join(self.dir, "blocker")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("x")
        store = BookmarkStore(os.path.join(blocker, "bookmarks.json"))
        self.assertTrue(store.add("https://a").is_err,
                        "the save failed, so the add must not pretend "
                        "otherwise")


if __name__ == "__main__":
    unittest.main()
