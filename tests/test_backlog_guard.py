"""Tests for the backlog guard.

Feature: Scroll & Parse must not add NEW people while at least X people with a
not-messaged status already exist in the list.

The guard is checked before any scrolling (the point is to avoid the work), and
a skipped run still hands the existing backlog to the rest of the stack — the
people already waiting must still be worked through.

Run with:  python3 tests/test_backlog_guard.py
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.base_action import ActionResult  # noqa: E402
from actions.scroll_parse import ScrollParse  # noqa: E402
from backend.action_engine import ActionEngine, RunTracer  # noqa: E402
from backend.user_memory import UserMemory, UserRecord  # noqa: E402
from tests.test_collect_visual_and_live_refresh import HighlightCDP  # noqa: E402
from tests.test_scroll_parse_pipeline import person  # noqa: E402


def run(coro):
    return asyncio.run(coro)


PEOPLE = [[person("Anna"), person("Bella")], [person("Cara"), person("Dana")]]


class Eng:
    """Minimal engine stand-in exposing the hooks the block discovers."""

    criteria = None

    def __init__(self, backlog=0, fail=False):
        self._backlog = backlog
        self._fail = fail
        self.msgs = []
        self.calls = 0

    def report(self, m, level="info"):
        self.msgs.append((m, level))

    def is_stopping(self):
        return False

    async def backlog_count(self):
        self.calls += 1
        if self._fail:
            raise RuntimeError("count exploded")
        return self._backlog

    @property
    def text(self):
        return " ".join(m for m, _ in self.msgs)


def block(**over):
    cfg = dict(scroll_pause_ms=0, load_timeout_ms=20, min_new_users=0,
               pre_delay_ms=0, confirm_pause_ms=0, highlight_enabled=False)
    cfg.update(over)
    return ScrollParse(**cfg)


class TestGuardDecision(unittest.TestCase):
    def test_guard_off_by_default_always_collects(self):
        b = block()
        self.assertFalse(b.skip_if_backlog)
        cdp = HighlightCDP(PEOPLE, page_height=100)
        eng = Eng(backlog=999)
        res = run(b.run_pipeline(cdp, eng))
        self.assertFalse(res.skipped)
        self.assertTrue(res.collected)
        self.assertEqual(eng.calls, 0, "the count must not even be requested")

    def test_skips_when_backlog_meets_the_threshold(self):
        cdp = HighlightCDP(PEOPLE, page_height=100)
        eng = Eng(backlog=5)
        res = run(block(skip_if_backlog=True,
                        backlog_threshold=5).run_pipeline(cdp, eng))
        self.assertTrue(res.skipped)
        self.assertEqual(res.backlog, 5)
        self.assertEqual(res.collected, [], "nobody may be added")
        self.assertEqual(cdp.scrolls, 0, "no scrolling work may happen")
        self.assertIn("Backlog guard", eng.text)

    def test_at_least_x_means_greater_or_equal(self):
        """Boundary: exactly X already waiting must skip."""
        for backlog, expect_skip in ((4, False), (5, True), (6, True)):
            cdp = HighlightCDP(PEOPLE, page_height=100)
            res = run(block(skip_if_backlog=True, backlog_threshold=5)
                      .run_pipeline(cdp, Eng(backlog=backlog)))
            self.assertEqual(res.skipped, expect_skip,
                             f"backlog={backlog} threshold=5")

    def test_collects_when_backlog_is_below_the_threshold(self):
        cdp = HighlightCDP(PEOPLE, page_height=100)
        eng = Eng(backlog=2)
        res = run(block(skip_if_backlog=True,
                        backlog_threshold=5).run_pipeline(cdp, eng))
        self.assertFalse(res.skipped)
        self.assertEqual([p.nick for p in res.collected],
                         ["Anna", "Bella", "Cara", "Dana"])
        self.assertIn("< threshold", eng.text)

    def test_explicit_backlog_argument_wins(self):
        cdp = HighlightCDP(PEOPLE, page_height=100)
        eng = Eng(backlog=0)
        res = run(block(skip_if_backlog=True, backlog_threshold=3)
                  .run_pipeline(cdp, eng, backlog=10))
        self.assertTrue(res.skipped)
        self.assertEqual(eng.calls, 0, "no need to ask when told")

    def test_counting_failure_fails_open(self):
        """A counting problem must never silently stop collection."""
        cdp = HighlightCDP(PEOPLE, page_height=100)
        res = run(block(skip_if_backlog=True, backlog_threshold=1)
                  .run_pipeline(cdp, Eng(fail=True)))
        self.assertFalse(res.skipped)
        self.assertTrue(res.collected)

    def test_no_engine_means_no_backlog(self):
        cdp = HighlightCDP(PEOPLE, page_height=100)
        res = run(block(skip_if_backlog=True,
                        backlog_threshold=1).run_pipeline(cdp, None))
        self.assertFalse(res.skipped)

    def test_guard_is_loud_about_what_to_do(self):
        eng = Eng(backlog=7)
        run(block(skip_if_backlog=True, backlog_threshold=5)
            .run_pipeline(HighlightCDP(PEOPLE, page_height=100), eng))
        self.assertIn("7", eng.text)
        self.assertIn("threshold 5", eng.text)
        self.assertIn("backlog", eng.text.lower())
        self.assertTrue(any(lvl == "warn" for _, lvl in eng.msgs))

    def test_skipped_run_purges_nobody(self):
        """Nothing is evaluated, so nothing is purged — by design."""
        purged = []

        class E(Eng):
            async def person_rejected(self, rec, why):
                purged.append(rec.nick)
                return True

        res = run(block(skip_if_backlog=True, backlog_threshold=1)
                  .run_pipeline(HighlightCDP(PEOPLE, page_height=100),
                                E(backlog=9)))
        self.assertTrue(res.skipped)
        self.assertEqual(purged, [])


class TestThresholdValidation(unittest.TestCase):
    def test_non_positive_threshold_is_clamped(self):
        """A threshold of 0 with the guard on would block every run forever."""
        for raw in (0, -3, None):
            self.assertEqual(ScrollParse(backlog_threshold=raw).backlog_threshold,
                             1, f"threshold {raw!r} must clamp to 1")

    def test_clamped_threshold_still_lets_an_empty_list_collect(self):
        cdp = HighlightCDP(PEOPLE, page_height=100)
        res = run(block(skip_if_backlog=True,
                        backlog_threshold=0).run_pipeline(cdp, Eng(backlog=0)))
        self.assertFalse(res.skipped, "an empty list must always collect")


class TestEngineBacklogCount(unittest.TestCase):
    def test_counts_only_unmessaged_people(self):
        async def go():
            with tempfile.TemporaryDirectory() as tmp:
                mem = UserMemory(os.path.join(tmp, "t.db"))
                await mem.init()
                for nick in ("a", "b", "c"):
                    await mem.upsert_user(UserRecord(nick=nick))
                await mem.mark_messaged("a")
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                count = await eng.backlog_count()
                direct = await mem.count_unmessaged()
                await mem.close()
                return count, direct

        count, direct = run(go())
        self.assertEqual(count, 2, "messaged people are history, not backlog")
        self.assertEqual(direct, 2)

    def test_falls_back_when_memory_lacks_the_fast_count(self):
        class Old:
            async def get_all(self):
                return [UserRecord(nick="a"), UserRecord(nick="b", messaged=True)]

        eng = ActionEngine(cdp=None, memory=Old(), criteria=None)
        self.assertEqual(run(eng.backlog_count()), 1)

    def test_engine_count_fails_open(self):
        class Broken:
            async def count_unmessaged(self): raise RuntimeError("db down")

        eng = ActionEngine(cdp=None, memory=Broken(), criteria=None)
        self.assertEqual(run(eng.backlog_count()), 0)


class TestEngineIntegration(unittest.TestCase):
    """The guard must not stall the stack: the backlog still gets worked."""

    def _run_stack(self, seed_unmessaged, **over):
        async def go():
            with tempfile.TemporaryDirectory() as tmp:
                mem = UserMemory(os.path.join(tmp, "t.db"))
                await mem.init()
                for i in range(seed_unmessaged):
                    await mem.upsert_user(
                        UserRecord(nick=f"Waiting{i}", gender="female",
                                   guest=True))
                cdp = HighlightCDP(PEOPLE, page_height=100)
                eng = ActionEngine(cdp=cdp, memory=mem, criteria=None)
                cfg = {"block_id": "SCROLL_PARSE", "scroll_pause_ms": 0,
                       "load_timeout_ms": 20, "min_new_users": 0,
                       "pre_delay_ms": 0, "confirm_pause_ms": 0,
                       "highlight_enabled": False}
                cfg.update(over)
                eng.load_stack([cfg])
                eng._tracer = RunTracer("test")
                queue = await eng._run_collect_phase(eng._stack[0])
                eng._tracer.close()
                names = sorted(u.nick for u in await mem.get_all())
                await mem.close()
                return queue, names, cdp.scrolls

        cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        try:
            return run(go())
        finally:
            os.chdir(cwd)

    def test_backlog_blocks_new_people_but_queue_still_served(self):
        queue, names, scrolls = self._run_stack(
            6, skip_if_backlog=True, backlog_threshold=5)
        self.assertEqual(scrolls, 0, "no scrolling")
        self.assertNotIn("Anna", names, "no new person may be added")
        self.assertEqual(len(queue), 6,
                         "the waiting people must still be worked through")

    def test_small_backlog_lets_collection_proceed(self):
        queue, names, scrolls = self._run_stack(
            2, skip_if_backlog=True, backlog_threshold=5)
        self.assertIn("Anna", names)
        self.assertGreater(scrolls, 0)
        # A normal (non-skipped) run queues the people it just collected —
        # that is the pre-existing contract, unchanged by the guard.
        self.assertEqual(len(queue), 4)
        self.assertEqual(sorted(q.nick for q in queue),
                         ["Anna", "Bella", "Cara", "Dana"])
        # …and the 2 already waiting are still in the list, untouched.
        for i in range(2):
            self.assertIn(f"Waiting{i}", names)

    def test_guard_off_ignores_a_huge_backlog(self):
        _, names, scrolls = self._run_stack(50, skip_if_backlog=False)
        self.assertIn("Anna", names)
        self.assertGreater(scrolls, 0)

    def test_messaged_people_do_not_hold_collection_back(self):
        async def go():
            with tempfile.TemporaryDirectory() as tmp:
                mem = UserMemory(os.path.join(tmp, "t.db"))
                await mem.init()
                for i in range(9):                    # all already messaged
                    await mem.upsert_user(UserRecord(nick=f"Done{i}"))
                    await mem.mark_messaged(f"Done{i}")
                cdp = HighlightCDP(PEOPLE, page_height=100)
                eng = ActionEngine(cdp=cdp, memory=mem, criteria=None)
                eng.load_stack([{"block_id": "SCROLL_PARSE",
                                 "scroll_pause_ms": 0, "load_timeout_ms": 20,
                                 "min_new_users": 0, "pre_delay_ms": 0,
                                 "confirm_pause_ms": 0,
                                 "highlight_enabled": False,
                                 "skip_if_backlog": True,
                                 "backlog_threshold": 3}])
                eng._tracer = RunTracer("test")
                await eng._run_collect_phase(eng._stack[0])
                eng._tracer.close()
                names = sorted(u.nick for u in await mem.get_all())
                await mem.close()
                return names, cdp.scrolls

        cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        try:
            names, scrolls = run(go())
        finally:
            os.chdir(cwd)
        self.assertIn("Anna", names, "9 messaged people are not a backlog")
        self.assertGreater(scrolls, 0)


class TestBlockContract(unittest.TestCase):
    def test_skipped_run_is_a_success_not_a_failure(self):
        outcome = run(block(skip_if_backlog=True, backlog_threshold=1)
                      .execute("—", HighlightCDP(PEOPLE, page_height=100),
                               Eng(backlog=5)))
        self.assertEqual(outcome, ActionResult.OK)

    def test_params_round_trip_through_presets(self):
        b = ScrollParse(skip_if_backlog=True, backlog_threshold=12)
        d = b.to_dict()
        schema = b.config_schema()
        for key in ("skip_if_backlog", "backlog_threshold"):
            self.assertIn(key, d, f"{key} must be preset-storable")
            self.assertIn(key, schema, f"{key} must be editable in the UI")
        clone = ScrollParse(**{k: v for k, v in d.items() if k != "block_id"})
        self.assertTrue(clone.skip_if_backlog)
        self.assertEqual(clone.backlog_threshold, 12)
        self.assertEqual(schema["skip_if_backlog"]["type"], "checkbox")

    def test_legacy_presets_are_unaffected(self):
        b = ScrollParse(**{"max_scrolls": 20, "scroll_pause_ms": 500})
        self.assertFalse(b.skip_if_backlog, "opt-in only")
        self.assertEqual(b.backlog_threshold, 5)

    def test_guard_is_independent_of_min_new_users(self):
        """Two different questions: whether to start vs when to stop."""
        cdp = HighlightCDP(PEOPLE, page_height=100)
        res = run(block(skip_if_backlog=True, backlog_threshold=5,
                        min_new_users=1).run_pipeline(cdp, Eng(backlog=1)))
        self.assertFalse(res.skipped, "guard passed")
        self.assertTrue(res.stopped_early, "min_new_users still applies")
        self.assertGreaterEqual(len(res.new_unmessaged), 1)
        self.assertLess(len(res.collected), 4,
                        "must stop before walking the whole list")

    def test_ui_exposes_both_settings(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "ui", "js", "stack-dnd.js"),
                   encoding="utf-8").read()
        self.assertIn("skip_if_backlog:false", src)
        self.assertIn("backlog_threshold:5", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
