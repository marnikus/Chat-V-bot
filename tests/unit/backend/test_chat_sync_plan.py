"""The read-decision half of a conversation sync — pure, no page, no DB.

`sync_conversation()` used to make these decisions inline across 295 lines and
46 nesting levels (AREA D task D1, docs/REFACTOR_2026-09-09_AREA_D_DESIGN.md §3).
The decisions now live in two objects that can be driven from a table:

  * `SyncOptions`  — the 11 optional knobs of the public call, one place;
  * `SyncPlanner`  — (state, cursor, options) → `ReadPlan`.

Contracts proven here (ids from the design doc):

  SY#1  every legacy keyword keeps its documented default, and the façade
         builds the same options object the algorithm reads;
  SY#2  an empty conversation is EMPTY (never "unchanged");
  SY#3  the nothing-moved fast path needs bootstrapped + same count + same
         head + same tail (all four, or we read again);
  SY#4  a grown tail with an unchanged head is a DELTA starting at the stored
         dom_count — that is the whole point of the design;
  SY#5  anything else (head moved, shorter list, no cursor) is a FULL read
         from 0;
  SY#6  `max_messages` trims the window from the NEWEST end and records a gap;
  SY#7  streaming vs buffer-then-align is decided by the stored tail
         fingerprints, not by the mode;
  SY#8  the signature helpers normalise the agent's lists the way the
         archive's cursor stores them;
  SY#9  `pause_seconds`/`stopping`/`progress` never raise on hostile input
         (a UI callback must not kill a sync — RULE 5);
  SY#10 the cursor signature set is what a plan carries for the final
         `repo.append(...)` bookkeeping call.

Run with:  python3 tests/unit/backend/test_chat_sync_plan.py
"""

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from backend.chat_parser import sync_conversation  # noqa: E402,F401
from backend.chat_sync import (  # noqa: E402
    MODE_DELTA,
    MODE_EMPTY,
    MODE_FULL,
    MODE_UNCHANGED,
    SyncOptions,
    SyncPlanner,
)


def cursor(**kw) -> dict:
    """A stored cursor, shaped exactly like HistoryRepo.get_cursor()."""
    base = {"person_id": 1, "last_ord": 0, "dom_count": 0, "head_sig": "",
            "tail_sig": "", "head_any": "", "tail_any": "", "tail_fps": [],
            "tail_keys": [], "bootstrapped": False,
            "full_scan_complete": False, "full_scan_at": ""}
    base.update(kw)
    return base


def state(**kw) -> dict:
    base = {"ok": True, "agent": 10, "tab": "private", "partner": "Nick",
            "me": "Me", "count": 10, "head": "h", "tail": "t",
            "head_any": "Ha", "tail_any": "Ta",
            "scroll": {"top": 0, "height": 100, "client": 50,
                       "atTop": True, "atBottom": False}}
    base.update(kw)
    return base


# ══════════════════════════════════════════════════════════════════
# SY#1 / SY#9 — the options object
# ══════════════════════════════════════════════════════════════════
class TestSyncOptions(unittest.TestCase):

    def test_defaults_match_the_public_call(self):
        opts = SyncOptions()
        self.assertEqual(opts.my_nick, "")
        self.assertFalse(opts.require_private)
        self.assertFalse(opts.verify_partner)
        self.assertIsNone(opts.max_messages)
        self.assertIsNone(opts.chunk_pause_ms)
        self.assertIsNone(opts.should_stop)
        self.assertIsNone(opts.on_progress)
        self.assertIsNone(opts.now)
        self.assertFalse(opts.backfill_older)
        self.assertEqual(opts.backfill_wait_s, 2.0)
        self.assertIsNone(opts.media)

    def test_from_kwargs_accepts_exactly_the_legacy_names(self):
        stop = lambda: False                                     # noqa: E731
        opts = SyncOptions.from_kwargs(my_nick="Me", require_private=True,
                                       verify_partner=True, max_messages=50,
                                       chunk_pause_ms=25, should_stop=stop,
                                       on_progress=None, now=None,
                                       backfill_older=True,
                                       backfill_wait_s=3.5, media="MEDIA")
        self.assertTrue(opts.require_private and opts.verify_partner)
        self.assertEqual((opts.max_messages, opts.chunk_pause_ms), (50, 25))
        self.assertIs(opts.should_stop, stop)
        self.assertTrue(opts.backfill_older)
        self.assertEqual(opts.backfill_wait_s, 3.5)
        self.assertEqual(opts.media, "MEDIA")

    def test_unknown_keywords_are_dropped_not_raised(self):
        """`load_stack` hands blocks arbitrary keys; a stale caller must not
        explode inside the collector."""
        opts = SyncOptions.from_kwargs(my_nick="Me", legacy_flag=1)
        self.assertEqual(opts.my_nick, "Me")
        self.assertFalse(hasattr(opts, "legacy_flag"))

    def test_the_object_is_immutable(self):
        opts = SyncOptions()
        with self.assertRaises(Exception):
            opts.my_nick = "someone else"

    def test_pause_seconds_uses_the_parser_when_unset(self):
        class Parser:
            chunk_pause_ms = 77

        self.assertEqual(SyncOptions().pause_seconds(Parser()), 0.077)
        self.assertEqual(SyncOptions(chunk_pause_ms=5).pause_seconds(Parser()),
                         0.005)
        # an explicit 0 must NOT fall back to the parser's value
        self.assertEqual(SyncOptions(chunk_pause_ms=0).pause_seconds(Parser()), 0)
        self.assertEqual(SyncOptions(chunk_pause_ms=None).pause_seconds(None), 0)
        self.assertEqual(SyncOptions(chunk_pause_ms=-100).pause_seconds(None), 0)

    def test_for_parser_freezes_pacing_and_timestamp(self):
        class Parser:
            chunk_pause_ms = 40

        fixed = datetime(2026, 9, 9, 12, 0, 0)
        opts = SyncOptions().for_parser(Parser(), now=fixed)
        self.assertEqual(opts.chunk_pause_ms, 40)
        self.assertEqual(opts.now, fixed)
        self.assertTrue(isinstance(opts.now, datetime))
        # already-set values win
        kept = SyncOptions(chunk_pause_ms=1, now=fixed).for_parser(Parser(),
                                                                    now=None)
        self.assertEqual(kept.chunk_pause_ms, 1)
        self.assertEqual(kept.now, fixed)

    def test_stopping_swallows_a_broken_predicate(self):
        self.assertFalse(SyncOptions().stopping())
        self.assertTrue(SyncOptions(should_stop=lambda: True).stopping())
        self.assertFalse(SyncOptions(should_stop="not callable").stopping())

        def boom():
            raise RuntimeError("page gone")

        self.assertFalse(SyncOptions(should_stop=boom).stopping(),
                         "a raising stop predicate must not kill the sync")

    def test_progress_callback_never_raises(self):
        seen = []
        SyncOptions(on_progress=lambda d, t: seen.append((d, t))) \
            .progress(3, 10)
        self.assertEqual(seen, [(3, 10)])
        SyncOptions().progress(1, 2)                       # no callback

        def boom(done, total):
            raise ValueError("widget is gone")

        SyncOptions(on_progress=boom).progress(1, 2)       # must not raise


# ══════════════════════════════════════════════════════════════════
# SY#8 — signature helpers
# ══════════════════════════════════════════════════════════════════
class TestSignatures(unittest.TestCase):

    def test_lists_join_in_order(self):
        self.assertEqual(SyncPlanner.signature(["x", "y"]), "x|y")
        self.assertEqual(SyncPlanner.signature(("x", "y")), "x|y")

    def test_scalars_and_empties(self):
        self.assertEqual(SyncPlanner.signature("solo"), "solo")
        self.assertEqual(SyncPlanner.signature(None), "")
        self.assertEqual(SyncPlanner.signature([]), "")
        # characterisation of the shipped helper: `str(value or "")` means a
        # falsy scalar collapses to "" — pinned, because a cursor written with
        # "" is what makes the next tick read again
        self.assertEqual(SyncPlanner.signature(0), "")

    def test_signatures_of_a_state_are_the_four_cursor_columns(self):
        sigs = SyncPlanner.signatures(state(head=["h1", "h2"], tail="t"))
        self.assertEqual(sigs, {"head_sig": "h1|h2", "tail_sig": "t",
                                "head_any": "Ha", "tail_any": "Ta"})
        self.assertEqual(SyncPlanner.signatures({}),
                         {"head_sig": "", "tail_sig": "",
                          "head_any": "", "tail_any": ""})


# ══════════════════════════════════════════════════════════════════
# SY#2–SY#7 — the plan
# ══════════════════════════════════════════════════════════════════
class TestSyncPlanner(unittest.TestCase):

    def plan(self, st=None, cur=None, **opts):
        # `state=`/`cursor=` are spelled as keywords by the cases below
        st = opts.pop("state", None) or st
        cur = opts.pop("cursor", None) or cur
        return SyncPlanner.plan(st or state(), cur or cursor(),
                                SyncOptions(**opts))

    def test_six_is_empty_not_unchanged(self):
        p = self.plan(state(count=0))
        self.assertEqual(p.mode, MODE_EMPTY)
        self.assertEqual(p.count, 0)
        self.assertEqual(p.start, 0)

    def test_nothing_moved_is_unchanged(self):
        cur = cursor(bootstrapped=True, dom_count=10, head_sig="h",
                     tail_sig="t")
        self.assertEqual(self.plan(cursor=cur).mode, MODE_UNCHANGED)

    def test_each_of_the_four_guards_must_hold(self):
        good = dict(bootstrapped=True, dom_count=10, head_sig="h", tail_sig="t")
        for broken in ("bootstrapped", "dom_count", "head_sig", "tail_sig"):
            cur = cursor(**{**good, broken: False if broken == "bootstrapped"
                            else ("" if broken.endswith("_sig") else 0)})
            with self.subTest(broken=broken):
                self.assertNotEqual(self.plan(cursor=cur).mode,
                                    MODE_UNCHANGED)

    def test_an_empty_tail_sig_never_matches(self):
        """A fresh row has no tail; `tail_sig == ""` must not read as
        'the tail is unchanged'. The head still lines up, so this is the
        delta path — append what arrived since the stored count."""
        cur = cursor(bootstrapped=True, dom_count=10, head_sig="h", tail_sig="")
        p = self.plan(state(count=10, tail=""), cursor=cur)
        self.assertNotEqual(p.mode, MODE_UNCHANGED)
        self.assertEqual(p.mode, MODE_DELTA)
        self.assertEqual(p.start, 10)

    def test_grown_tail_with_same_head_is_a_delta_from_the_stored_count(self):
        cur = cursor(bootstrapped=True, dom_count=10, head_sig="h",
                     tail_sig="t", tail_fps=["a", "b"])
        p = self.plan(state(count=13), cursor=cur)
        self.assertEqual(p.mode, MODE_DELTA)
        self.assertEqual(p.start, 10)
        self.assertEqual(p.count, 13)
        self.assertTrue(p.streaming)

    def test_a_shrunk_list_is_never_a_delta(self):
        cur = cursor(bootstrapped=True, dom_count=10, head_sig="h", tail_sig="t")
        p = self.plan(state(count=8), cursor=cur)
        self.assertEqual(p.mode, MODE_FULL)
        self.assertEqual(p.start, 0)

    def test_head_change_means_the_whole_visible_range_is_reread(self):
        cur = cursor(bootstrapped=True, dom_count=10, head_sig="other",
                     tail_sig="t", tail_fps=["a"])
        p = self.plan(state(count=11), cursor=cur)
        self.assertEqual(p.mode, MODE_FULL)
        self.assertEqual(p.start, 0)
        self.assertFalse(p.gap)

    def test_first_ever_read_streams_because_there_is_no_stored_tail(self):
        p = self.plan(state(count=4), cursor=cursor(bootstrapped=False))
        self.assertEqual(p.mode, MODE_FULL)
        self.assertTrue(p.streaming,
                        "with no stored tail there is nothing to align")

    def test_a_stored_tail_defers_the_write_until_alignment(self):
        cur = cursor(bootstrapped=True, dom_count=4, head_sig="moved",
                     tail_fps=["a", "b"])
        p = self.plan(state(count=6, head="new"), cursor=cur)
        self.assertFalse(p.streaming,
                         "a full re-read with a stored tail must be aligned "
                         "first, or the archive duplicates everything")

    def test_max_messages_keeps_the_newest_window_and_records_a_gap(self):
        p = self.plan(state(count=100), max_messages=30)
        self.assertEqual(p.start, 70)
        self.assertEqual(p.count, 100)
        self.assertTrue(p.gap)

    def test_max_messages_below_the_stored_count_does_not_gap(self):
        cur = cursor(bootstrapped=True, dom_count=10, head_sig="h",
                     tail_sig="t", tail_fps=["a"])
        p = self.plan(state(count=12), cursor=cur, max_messages=30)
        self.assertFalse(p.gap)
        self.assertEqual(p.start, 10)

    def test_max_messages_zero_or_negative_is_no_cap(self):
        for cap in (0, None):
            with self.subTest(cap=cap):
                p = self.plan(state(count=100), max_messages=cap)
                self.assertEqual(p.start, 0)
                self.assertFalse(p.gap)

    def test_the_plan_carries_the_cursor_signatures_it_was_read_with(self):
        st = state(head=["h1", "h2"], tail="t9", head_any="ha", tail_any="ta")
        p = self.plan(st)
        self.assertEqual(p.cursor_kwargs(p.count),
                         {"dom_count": 10, "head_sig": "h1|h2",
                          "tail_sig": "t9", "head_any": "ha",
                          "tail_any": "ta"})
        # an incomplete read must not claim the tail is settled, or the next
        # tick's "nothing moved" check would skip messages that never arrived
        self.assertEqual(p.cursor_kwargs(4, complete=False),
                         {"dom_count": 4, "head_sig": "h1|h2",
                          "tail_sig": "", "head_any": "ha", "tail_any": ""})

    def test_count_may_be_overridden_after_a_viewport_change(self):
        """A virtualised pane can regain nodes between the settle probe and
        the read — the session re-runs the planner with the fresh count, and
        the decision must depend on THAT count only, not on the stale probe."""
        cur = cursor(bootstrapped=True, dom_count=10, head_sig="h", tail_sig="t")
        by_override = SyncPlanner.plan(state(count=10), cur, SyncOptions(),
                                       count=14)
        by_state = SyncPlanner.plan(state(count=14), cur, SyncOptions())
        self.assertEqual(by_override.count, 14)
        self.assertEqual(by_override.mode, by_state.mode)
        self.assertEqual(by_override.start, by_state.start)
        # 14 > the stored 10 with the same head: a delta from dom_count
        self.assertEqual(by_override.mode, MODE_DELTA)
        self.assertEqual(by_override.start, 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
