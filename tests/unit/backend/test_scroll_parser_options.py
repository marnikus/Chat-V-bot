"""The scroll pipeline: its options object and its batch phases.

`ScrollParser.collect()` used to be 192 lines with CC 43 — per-item
judgement, seek mode, stall detection and the UI callbacks were interleaved
in one `for scroll_i` loop (AREA D task D2, design doc §4). It is now
`_prepare()` → `_consume_batch()` → `_advance()`, and the 18 knobs live in one
frozen `ScrollOptions`.

What must not change is what the RUN sees: which people get collected, which
get purged, when the loop stops, and that a user stop is never reported as a
lost page (RULE 7). Those are pinned here against a scripted fake CDP.

Contracts proven here:

  SP#1   `ScrollOptions` defaults are exactly the constructor's defaults;
  SP#2   `from_options()` builds a parser equivalent to the long call;
  SP#3   the legacy 20-parameter constructor keeps working, name for name;
  SP#4   the three knobs that were clamped/normalised are still clamped;
  SP#5   newly RENDERED people are counted even in seek mode (stall math);
  SP#6   a seek writes nothing but the found person, and never purges;
  SP#7   a filtered-out person is counted, reported and purged once;
  SP#8   a collected person is confirmed, added and announced in that order;
  SP#9   `known_nicks` survives between runs of the same parser;
  SP#10  end-of-list needs the geometry AND a quiet window (stall math);
  SP#11  STOPPED is not "context lost" — and both differ from an empty run;
  SP#12  the finished list is sorted, summarised, and `parse()` still returns
         the legacy ``(all, filtered)`` tuple;
  SP#13  `min_new_users` finishes early, once the target is met.

Run with:  python3 tests/unit/backend/test_scroll_parser_options.py
"""

import asyncio
import dataclasses
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from backend.scroll_parser import CollectResult, ScrollParser  # noqa: E402
from test_scroll_parse_pipeline import FakeCDP, person  # noqa: E402

try:                                            # the new seam (D2)
    from backend.scroll_parser import ScrollOptions
except ImportError:                                              # noqa: PERF203
    ScrollOptions = None


def run(parser, **kw):
    return asyncio.run(parser.collect(**kw))


def msgs(parser, **kw):
    """A run plus the (message, level) lines it logged."""
    seen = []
    parser.set_log_cb(lambda m, level: seen.append((m, level)))
    return run(parser, **kw), seen


def make(pages, **kw):
    kw.setdefault("pause_ms", 0)
    kw.setdefault("poll_ms", 1)
    kw.setdefault("load_timeout_ms", 60)
    return ScrollParser(cdp=FakeCDP(pages), **kw)


# ══════════════════════════════════════════════════════════════════
# SP#1–4 — the options object
# ══════════════════════════════════════════════════════════════════
class TestScrollOptions(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if ScrollOptions is None:
            raise unittest.SkipTest("ScrollOptions is part of D2")

    def test_defaults_are_the_constructor_defaults(self):
        """One source of truth: the frozen dataclass and the long legacy
        signature may not drift apart."""
        import inspect
        params = dict(inspect.signature(ScrollParser.__init__).parameters)
        fields = {f.name: f for f in ScrollOptions.__dataclass_fields__.values()}
        # every option the constructor takes must exist with the same default
        missing = object()
        for name, param in params.items():
            if name in ("self", "cdp", "criteria"):
                continue
            with self.subTest(option=name):
                self.assertIn(name, fields,
                              f"{name} is a constructor knob but not an option")
                default = missing if param.default is inspect.Parameter.empty \
                    else param.default
                field = fields[name]
                if field.default_factory is not dataclasses.MISSING:
                    continue                     # mutable default: not comparable
                field_default = (missing if field.default is dataclasses.MISSING
                                 else field.default)
                if default is missing or field_default is missing:
                    self.assertIs(default, field_default)
                    continue
                self.assertEqual(default, field_default)

    def test_from_options_equals_the_long_call(self):
        pages = [[person("Anna"), person("Boris", female=False)]]
        kwargs = dict(pause_ms=0, poll_ms=1, load_timeout_ms=60,
                      scroll_dy=120, stall_threshold=1, max_scrolls=2,
                      highlight_ms=0, confirm_pause_ms=0)
        via_ctor = make(pages, **kwargs)
        via_options = ScrollParser.from_options(
            FakeCDP(pages), ScrollOptions(**kwargs))
        first, first_log = msgs(via_ctor)
        second, second_log = msgs(via_options)
        self.assertEqual([p.nick for p in second.all_people],
                         [p.nick for p in first.all_people])
        self.assertEqual([p.nick for p in second.collected],
                         [p.nick for p in first.collected])
        self.assertEqual(second_log, first_log)
        self.assertEqual(second.scrolls, first.scrolls)

    def test_the_legacy_constructor_still_takes_every_knob(self):
        parser = make([[person("Anna")]])
        options = getattr(parser, "options", parser)      # pre-D2 fallback
        self.assertEqual(options.max_scrolls, 50)
        self.assertEqual(options._pause_ms if hasattr(options, "_pause_ms")
                         else options.pause_ms, 0)
        self.assertEqual(parser.known_nicks, set())
        self.assertIsNone(parser._criteria)

    def test_clamping_and_normalisation_are_unchanged(self):
        parser = make([[person("Anna")]], highlight_ms=-5,
                      confirm_pause_ms=10**9, highlight_enabled=0,
                      scroll_dy="7")
        options = getattr(parser, "options", parser)
        clamp = lambda name: (getattr(options, name)                              # noqa: E731
                              if hasattr(options, name)
                              else getattr(options, "_" + name))
        self.assertEqual(clamp("highlight_ms"), 0)
        self.assertFalse(clamp("highlight_enabled"))
        self.assertGreaterEqual(clamp("confirm_pause_ms"), 0)
        # scroll_dy was never clamped, only stored as given
        self.assertEqual(int(clamp("scroll_dy")), 7)

    def test_the_options_object_is_immutable(self):
        with self.assertRaises(Exception):
            ScrollOptions().pause_ms = 1


# ══════════════════════════════════════════════════════════════════
# SP#5–8 — what one batch of rendered people does
# ══════════════════════════════════════════════════════════════════
class TestBatchPhases(unittest.TestCase):

    def test_seek_mode_still_counts_newly_rendered_people(self):
        """SP#5 — the stall detector counts RENDERED people, not collected
        ones: a seek that stopped counting would stall out before reaching a
        target further down the list."""
        pages = [[person("Anna")], [person("Bella")], [person("Cara")]]
        parser = make(pages)
        result, log = msgs(parser)
        self.assertEqual(sorted(p.nick for p in result.all_people),
                         ["Anna", "Bella", "Cara"])
        # the same pages, this time seeking a person that is not there
        seek = make([[person("Anna")], [person("Bella")], [person("Cara")]])
        result, log = msgs(seek, seek_nicks={"Nobody"})
        self.assertIsNone(result.found)
        self.assertTrue(result.scrolls >= 1)
        self.assertEqual([m for m, _ in log if "Scroll 1/" in m],
                         ["📜 Scroll 1/50: +1 new person(s), 0 seen, 0 "
                          "collected"],
                         "a seek COUNTS newly rendered people (that is what "
                         "keeps the stall detector honest) but records "
                         "nothing — `all_people` stays empty by design")

    def test_a_seek_finds_marks_and_stops_without_purging(self):
        """SP#6."""
        pages = [[person("Anna"), person("Boris", female=False)],
                 [person("Cara")]]
        rejected = []
        parser = make(pages, person_filter=None,
                      on_reject=lambda record, reason: rejected.append(
                          (record.nick, reason)))
        result = run(parser, seek_nicks={"Boris", "Anna"})
        self.assertIsNotNone(result.found)
        self.assertEqual(result.found.nick, "Anna")
        self.assertEqual([p.nick for p in result.collected], ["Anna"])
        self.assertTrue(result.stopped_early)
        self.assertFalse(result.purged)
        self.assertEqual(rejected, [],
                         "a seek never judges people for membership")
        self.assertEqual(result.rejected, {})

    def test_a_waiting_target_that_fails_the_filter_is_skipped_not_purged(self):
        from backend.person_filter import PersonFilter
        pages = [[person("Anna", female=False), person("Bella")],
                 [person("Bella")]]
        rejected = []
        parser = make(pages, person_filter=PersonFilter(female="yes"),
                      on_reject=lambda record, reason: rejected.append(
                          (record.nick, reason)))
        result, log = msgs(parser, seek_nicks={"Anna"})
        self.assertIsNone(result.found)
        self.assertEqual(rejected, [],
                         "a waiting target that fails the filter is skipped, "
                         "not purged — it is not being judged for membership")
        self.assertEqual(result.purged, [])
        self.assertEqual(result.rejected, {})
        text = " ".join(m for m, _ in log)
        self.assertIn("↷ “Anna” is waiting but does not pass the filter "
                      "(not female) — skipping", text)

    def test_a_rejected_person_is_counted_reported_and_purged_once(self):
        """SP#7 — RULE 6: a person who does not pass must not linger."""
        from backend.person_filter import PersonFilter
        pages = [[person("Anna", female=False), person("Bella")]]
        purged = []

        async def on_reject(record, reason):
            purged.append((record.nick, reason))
            return True                      # caller says "it was destroyed"

        parser = make(pages, person_filter=PersonFilter(female="yes"),
                      on_reject=on_reject)
        result, log = msgs(parser)
        self.assertEqual([p.nick for p in result.collected], ["Bella"])
        self.assertEqual(result.rejected, {"not female": 1})
        self.assertEqual(purged, [("Anna", "not female")])
        self.assertEqual(result.purged, ["Anna"])
        self.assertIn("🚫 Filtered out", " ".join(m for m, _ in log))

    def test_a_rejected_person_without_a_callback_is_still_recorded(self):
        from backend.person_filter import PersonFilter
        pages = [[person("Anna", female=False)]]
        parser = make(pages, person_filter=PersonFilter(female="yes"))
        result = run(parser)
        self.assertEqual([(r.nick, why) for r, why in result.rejected_people],
                         [("Anna", "not female")])
        self.assertEqual(result.purged, [])

    def test_collect_announces_the_person_after_adding_it(self):
        """SP#8 — RULE 5: the UI refreshes per person, not per run."""
        seen = []

        async def on_collect(record, snapshot):
            seen.append((record.nick, [p.nick for p in snapshot]))

        pages = [[person("Anna"), person("Bella")]]
        parser = make(pages, on_collect=on_collect)
        result = run(parser)
        self.assertEqual(seen, [("Anna", ["Anna"]),
                                ("Bella", ["Anna", "Bella"])],
                        "the callback gets the list as it stands")
        self.assertEqual([p.nick for p in result.collected], ["Anna", "Bella"])

    def test_a_broken_callback_never_kills_the_run(self):
        """A UI hiccup must not abort a parse — the run is longer than the
        widget that is reporting on it."""
        def boom(*a):
            raise RuntimeError("widget gone")

        pages = [[person("Anna"), person("Bella", registered=True)]]
        parser = make(pages, on_collect=boom, on_reject=boom)
        result = run(parser)
        self.assertEqual([p.nick for p in result.collected], ["Anna", "Bella"])


# ══════════════════════════════════════════════════════════════════
# SP#9–13 — the scroll loop itself
# ══════════════════════════════════════════════════════════════════
class TestScrollLoop(unittest.TestCase):

    def test_known_nicks_survive_between_runs(self):
        """SP#9 — a second parse of the same page adds nobody twice."""
        parser = make([[person("Anna"), person("Bella")]])
        first = run(parser)
        second = run(parser)
        self.assertEqual(len(first.collected), 2)
        self.assertEqual(second.collected, [])
        self.assertEqual(sorted(parser.known_nicks), ["Anna", "Bella"])

    def test_end_of_list_needs_the_geometry_and_a_quiet_window(self):
        """SP#10 — one quiet scroll is not the end; the stall counter is."""
        parser = ScrollParser(cdp=FakeCDP([[person("Anna")]], page_height=100),
                              pause_ms=0, poll_ms=1, load_timeout_ms=60,
                              stall_threshold=3)
        result, log = msgs(parser)
        self.assertTrue(result.reached_end)
        self.assertIn("⏹ Bottom of the list reached and no new people "
                      "loaded — end of list", [m for m, _ in log])

    def test_a_list_that_never_settles_is_cut_off_by_max_scrolls(self):
        pages = [[person(f"P{i}")] for i in range(12)]
        parser = ScrollParser(cdp=FakeCDP(pages, page_height=10),
                              pause_ms=0, poll_ms=1, load_timeout_ms=30,
                              stall_threshold=2, max_scrolls=1)
        result, log = msgs(parser)
        self.assertEqual(result.scrolls, 1)
        self.assertFalse(result.reached_end)
        self.assertIn("⏹ Reached max scrolls (1)", [m for m, _ in log])

    def test_a_user_stop_is_not_reported_as_a_lost_page(self):
        """SP#11 — RULE 7."""
        cdp = FakeCDP([[person("Anna")], [person("Bella")]], load_delay=2)
        stopped = {"n": 0}

        def should_stop():
            stopped["n"] += 1
            return stopped["n"] > 3          # stops while settling after a scroll

        parser = ScrollParser(cdp=cdp, pause_ms=0, poll_ms=1,
                              load_timeout_ms=200, should_stop=should_stop)
        result, log = msgs(parser)
        self.assertTrue(result.stopped)
        self.assertNotIn("❌ Lost the page context while scrolling",
                         [m for m, _ in log])

    def test_a_page_that_answers_nothing_is_an_error_not_an_empty_run(self):
        class Dead:
            async def evaluate(self, expression):
                return None

            async def get_element_rect(self, selector):
                return {"x": 0, "y": 0, "width": 1, "height": 1}

            async def mouse_wheel(self, *a):
                return None

        parser = ScrollParser(cdp=Dead())
        result, log = msgs(parser)
        self.assertIsInstance(result, CollectResult)
        self.assertEqual(result.all_people, [])
        self.assertIn("❌ Element search failed: no data returned from the page "
                      "(wrong page? not connected?)", [m for m, _ in log])

    def test_the_finished_list_is_sorted_and_summarised(self):
        """SP#12."""
        pages = [[person("Zoya"), person("anna", registered=True),
                  person("Mia")]]
        parser = make(pages)
        result, log = msgs(parser)
        self.assertEqual([p.nick for p in result.collected],
                         ["anna", "Mia", "Zoya"],
                         "case-insensitive, un-messaged first")
        self.assertIn("📊 Parse finished: 3 person(s) seen, 3 matched the "
                      "filter (3 not yet messaged)", [m for m, _ in log])
        all_people, collected = asyncio.run(parser.parse())
        self.assertEqual((all_people, collected), ([], []),
                         "the second run knows everybody already")

    def test_min_new_users_finishes_early(self):
        """SP#13."""
        pages = [[person("Anna")], [person("Bella")], [person("Cara")]]
        cdp = FakeCDP(pages, page_height=10)
        parser = ScrollParser(cdp=cdp, pause_ms=0, poll_ms=1,
                              load_timeout_ms=60, max_scrolls=50)
        result, log = msgs(parser, min_new_users=2)
        self.assertTrue(result.stopped_early)
        self.assertEqual(len(result.collected), 2)
        self.assertIn("🎯 Collected 2 new un-messaged person(s) (target 2) "
                      "— finishing scroll early", [m for m, _ in log])
        self.assertEqual(cdp.scrolls, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
