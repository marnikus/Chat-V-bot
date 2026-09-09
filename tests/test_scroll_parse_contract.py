"""`actions.scroll_parse` — filter/parser plumbing and mode decision (P1).

SPEC-FIRST (docs/ACTIONS_TEST_DESIGN_2026-09-09.md §9).

`tests/test_scroll_parse_pipeline.py` drives the real scroll loop against a
fake page; this file pins the block's own contract instead:

  * `build_filter(panel_criteria)` — "accepted for call-compatibility and
    IGNORED. The four selects below are now the only ones."
  * `build_parser` — panel criteria are "intentionally not applied";
    `on_reject` is only wired when `purge_rejected` is on, because it
    DESTROYS stored records;
  * `_read_unmessaged` — "Fails open (empty set -> normal collection)";
  * the scroll-only mode decision (STEP 0) and the `execute` outcome mapping;
  * RULE 3 — every setting round-trips, and the stack must stay JSON-safe
    (`bridge/stack_bridge.get_stack_json()` = `json.dumps(engine.get_stack())`).

Run with:  python3 tests/test_scroll_parse_contract.py
"""

import asyncio
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions.scroll_parse as sp  # noqa: E402
from actions.base_action import ActionResult  # noqa: E402
from actions.scroll_parse import ScrollParse  # noqa: E402
from backend.person_filter import ANY, NO, YES  # noqa: E402
from backend.scroll_parser import CollectResult  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class Person:
    def __init__(self, nick, messaged=False):
        self.nick = nick
        self.messaged = messaged


class FakeEngine:
    def __init__(self, unmessaged=None, criteria=None, raise_on_read=False):
        self.lines = []
        self.criteria = criteria
        self.collected = []
        self.rejected = []
        self.stopping = False
        self._unmessaged = unmessaged
        self._raise = raise_on_read

    def report(self, message, level="info"):
        self.lines.append((level, message))

    def text(self):
        return " | ".join(m for _lvl, m in self.lines)

    async def unmessaged_nicks(self):
        if self._raise:
            raise RuntimeError("db locked")
        return self._unmessaged

    async def person_collected(self, record, result=None):
        self.collected.append(record)

    async def person_rejected(self, record, reason, result=None):
        self.rejected.append((record, reason))

    def is_stopping(self):
        return self.stopping


class StubParser:
    """Records what the block asked for and returns a canned result."""

    def __init__(self, result=None, **kwargs):
        self.kwargs = kwargs
        self.result = result or CollectResult()
        self.collect_args = None

    async def collect(self, **kwargs):
        self.collect_args = kwargs
        return self.result


class PipelineCase(unittest.TestCase):
    """Swaps the real ScrollParser for a recorder."""

    def setUp(self):
        self.created = []

        def factory(**kwargs):
            parser = StubParser(result=self.result, **kwargs)
            self.created.append(parser)
            return parser

        self.result = CollectResult()
        patcher = mock.patch.object(sp, "ScrollParser",
                                    side_effect=lambda **kw: factory(**kw))
        patcher.start()
        self.addCleanup(patcher.stop)

    def pipeline(self, block, engine=None, **kwargs):
        return run(block.run_pipeline(object(), engine, **kwargs))

    @property
    def parser(self):
        return self.created[-1]


class TestFilterRules(unittest.TestCase):
    """SP-01, SP-02."""

    def test_the_four_block_rules_are_the_only_source_of_truth(self):
        """SP-01: panel_criteria is documented as IGNORED."""
        block = ScrollParse(filter_female=ANY, filter_registered=YES,
                            filter_guest=NO, filter_anonymous=ANY)
        panel = object()
        flt = block.build_filter(panel)
        self.assertEqual(flt.female, ANY)
        self.assertEqual(flt.registered, YES)
        self.assertEqual(flt.guest, NO)
        self.assertEqual(flt.anonymous, ANY)
        self.assertIsNone(flt.panel_criteria)

    def test_the_defaults_are_female_yes_guest_yes_others_no(self):
        block = ScrollParse()
        flt = block.build_filter()
        self.assertEqual((flt.female, flt.registered, flt.guest,
                          flt.anonymous), (YES, NO, YES, NO))

    def test_an_invalid_rule_value_falls_back_to_the_default(self):
        """SP-02: a hand-edited preset must not produce a broken filter."""
        block = ScrollParse(filter_female="maybe", filter_guest="")
        flt = block.build_filter()
        self.assertEqual(flt.female, YES)
        self.assertEqual(flt.guest, YES)


class TestParserWiring(unittest.TestCase):
    """SP-03, SP-04."""

    def test_panel_criteria_never_reach_the_parser(self):
        """SP-03."""
        block = ScrollParse()
        parser = block.build_parser(object(), panel_criteria=object())
        self.assertIsNone(parser._criteria)
        self.assertIsNone(parser._filter.panel_criteria)

    def test_every_scroll_knob_is_forwarded(self):
        block = ScrollParse(max_scrolls=7, scroll_pause_ms=11,
                            scroll_delta_y=13,
                            viewport_selector="div.vp", load_timeout_ms=17,
                            stall_threshold=19, person_selector="li.p",
                            nick_selector=".nick", highlight_enabled=False,
                            highlight_ms=23, confirm_pause_ms=29)
        parser = block.build_parser(object())
        self.assertEqual(parser.max_scrolls, 7)
        self.assertEqual(parser._pause_ms, 11)
        self.assertEqual(parser._scroll_dy, 13)
        self.assertEqual(parser._vp_sel, "div.vp")
        self.assertEqual(parser._load_timeout_ms, 17)
        self.assertEqual(parser._stall, 19)
        self.assertEqual(parser._person_sel, "li.p")
        self.assertEqual(parser._nick_sel, ".nick")
        self.assertIs(parser._highlight_enabled, False)
        self.assertEqual(parser._highlight_ms, 23)
        self.assertEqual(parser._confirm_pause_ms, 29)

    def test_reject_hook_is_wired_only_when_purging_is_on(self):
        """SP-04: on_reject DESTROYS stored records — opt-in only."""
        async def on_reject(record, reason, result=None):
            return None

        wired = ScrollParse(purge_rejected=True).build_parser(
            object(), on_reject=on_reject)
        self.assertIs(wired._on_reject, on_reject)

        muted = ScrollParse(purge_rejected=False).build_parser(
            object(), on_reject=on_reject)
        self.assertIsNone(muted._on_reject)

    def test_collect_hook_is_always_wired(self):
        async def on_collect(record, result=None):
            return None

        parser = ScrollParse(purge_rejected=False).build_parser(
            object(), on_collect=on_collect)
        self.assertIs(parser._on_collect, on_collect)


class TestSettings(unittest.TestCase):
    """SP-05, SP-06, RULE 3."""

    def test_retired_settings_are_dropped_from_attributes_and_to_dict(self):
        """SP-05."""
        block = ScrollParse(use_panel_filters=True, skip_if_backlog=1,
                            backlog_threshold=5)
        for dead in ("use_panel_filters", "skip_if_backlog",
                     "backlog_threshold"):
            self.assertFalse(hasattr(block, dead))
            self.assertNotIn(dead, block.to_dict())

    def test_negative_min_new_users_is_clamped_to_zero(self):
        """SP-06: 0 means "scroll to the end", a negative is meaningless."""
        self.assertEqual(ScrollParse(min_new_users=-3).min_new_users, 0)

    def test_negative_timings_are_clamped(self):
        block = ScrollParse(highlight_ms=-1, confirm_pause_ms=-1)
        self.assertEqual(block.highlight_ms, 0)
        self.assertEqual(block.confirm_pause_ms, 0)

    def test_settings_round_trip_and_stay_json_safe(self):
        block = ScrollParse(max_scrolls=3, scroll_only=True,
                            filter_female=ANY, min_new_users=2,
                            pre_delay_ms=0)
        data = block.to_dict()
        json.dumps(data, ensure_ascii=False)
        clone = ScrollParse(**{k: v for k, v in data.items()
                               if k != "block_id"})
        self.assertEqual(clone.to_dict(), data)

    def test_schema_exposes_every_setting(self):
        schema = ScrollParse().config_schema()
        for key in ("max_scrolls", "scroll_pause_ms", "scroll_delta_y",
                    "viewport_selector", "load_timeout_ms",
                    "stall_threshold", "min_new_users", "person_selector",
                    "nick_selector", "highlight_enabled", "highlight_ms",
                    "confirm_pause_ms", "purge_rejected", "scroll_only",
                    "filter_female", "filter_registered", "filter_guest",
                    "filter_anonymous", "pre_delay_ms"):
            self.assertIn(key, schema, f"{key} missing from the schema")

    def test_the_filter_selects_offer_the_three_documented_choices(self):
        schema = ScrollParse().config_schema()
        for key in ("filter_female", "filter_registered", "filter_guest",
                    "filter_anonymous"):
            self.assertEqual(sorted(schema[key]["options"]),
                             sorted([ANY, YES, NO]))


class TestUnmessagedRead(unittest.TestCase):
    """SP-07 — "Fails open ... so a read problem can never leave the block
    doing nothing at all"."""

    def test_without_an_engine(self):
        self.assertEqual(run(ScrollParse()._read_unmessaged(None)), set())

    def test_without_a_reader(self):
        self.assertEqual(run(ScrollParse()._read_unmessaged(object())), set())

    def test_a_raising_reader_falls_back_to_normal_collection(self):
        engine = FakeEngine(raise_on_read=True)
        self.assertEqual(run(ScrollParse()._read_unmessaged(engine)), set())

    def test_a_list_is_normalised_to_a_set(self):
        engine = FakeEngine(unmessaged=["Ann", "Bob", "Ann"])
        self.assertEqual(run(ScrollParse()._read_unmessaged(engine)),
                         {"Ann", "Bob"})


class TestModeDecision(PipelineCase):
    """SP-08 .. SP-11, SP-14 — STEP 0."""

    def test_scroll_only_seeks_the_un_messaged_people(self):
        """SP-08."""
        engine = FakeEngine(unmessaged={"Ann", "Bob"})
        block = ScrollParse(scroll_only=True, pre_delay_ms=0)
        self.pipeline(block, engine)
        self.assertEqual(self.parser.collect_args["seek_nicks"],
                         {"Ann", "Bob"})
        self.assertIn("2 un-messaged", engine.text())

    def test_scroll_only_with_an_empty_backlog_collects_as_usual(self):
        """SP-09: the mode is "not a permanent off-switch"."""
        engine = FakeEngine(unmessaged=set())
        block = ScrollParse(scroll_only=True, pre_delay_ms=0)
        self.pipeline(block, engine)
        self.assertIsNone(self.parser.collect_args["seek_nicks"])
        self.assertIn("collecting new people as usual", engine.text())

    def test_normal_mode_never_seeks(self):
        """SP-10."""
        engine = FakeEngine(unmessaged={"Ann"})
        block = ScrollParse(scroll_only=False, pre_delay_ms=0)
        self.pipeline(block, engine, seek_nicks={"Ann"})
        self.assertIsNone(self.parser.collect_args["seek_nicks"])

    def test_explicit_seek_nicks_skip_the_engine_read(self):
        """SP-14."""
        engine = FakeEngine(unmessaged={"FromEngine"})
        block = ScrollParse(scroll_only=True, pre_delay_ms=0)
        self.pipeline(block, engine, seek_nicks={"Explicit"})
        self.assertEqual(self.parser.collect_args["seek_nicks"],
                         {"Explicit"})

    def test_the_engine_hooks_are_preferred(self):
        """SP-11."""
        engine = FakeEngine()
        block = ScrollParse(pre_delay_ms=0)
        self.pipeline(block, engine)
        # bound methods are re-created per attribute access, so compare by value
        self.assertEqual(self.parser.kwargs["on_collect"],
                         engine.person_collected)
        self.assertEqual(self.parser.kwargs["on_reject"],
                         engine.person_rejected)
        self.assertEqual(self.parser.kwargs["should_stop"], engine.is_stopping)

    def test_explicit_hooks_win_over_the_engine(self):
        engine = FakeEngine()

        async def on_collect(record, result=None):
            return None

        block = ScrollParse(pre_delay_ms=0)
        self.pipeline(block, engine, on_collect=on_collect)
        self.assertEqual(self.parser.kwargs["on_collect"], on_collect)
        self.assertNotEqual(self.parser.kwargs["on_collect"],
                            engine.person_collected)

    def test_reject_hook_is_still_muted_by_purge_rejected(self):
        engine = FakeEngine()
        block = ScrollParse(purge_rejected=False, pre_delay_ms=0)
        self.pipeline(block, engine)
        self.assertIsNone(self.parser.kwargs["on_reject"])

    def test_min_new_users_and_known_messaged_reach_collect(self):
        block = ScrollParse(min_new_users=4, pre_delay_ms=0)
        self.pipeline(block, known_messaged={"Zoe"})
        self.assertEqual(self.parser.collect_args["min_new_users"], 4)
        self.assertEqual(self.parser.collect_args["known_messaged"], {"Zoe"})

    def test_the_result_is_remembered_for_the_engine(self):
        """The engine reads `last_result` to build its queue."""
        block = ScrollParse(pre_delay_ms=0)
        self.pipeline(block)
        self.assertIs(block.last_result, self.result)


class TestExecuteMapping(PipelineCase):
    """SP-12."""

    def test_collected_people_are_a_success(self):
        self.result.collected.append(Person("Ann"))
        block = ScrollParse(pre_delay_ms=0)
        engine = FakeEngine()
        outcome = run(block.execute("Ann", object(), engine))
        self.assertEqual(outcome, ActionResult.OK)
        self.assertIn("STEP 3", engine.text())

    def test_nothing_collected_is_a_failure_with_a_warning(self):
        block = ScrollParse(pre_delay_ms=0)
        engine = FakeEngine()
        outcome = run(block.execute("Ann", object(), engine))
        self.assertEqual(outcome, ActionResult.FAIL)
        self.assertIn("warn", [lvl for lvl, _m in engine.lines])
        self.assertIn("No person matched", engine.text())

    def test_a_seek_that_found_nobody_is_a_failure(self):
        self.result.seeking = True
        self.result.found = None
        block = ScrollParse(scroll_only=True, pre_delay_ms=0)
        engine = FakeEngine()
        outcome = run(block.execute("Ann", object(), engine))
        self.assertEqual(outcome, ActionResult.FAIL)
        self.assertIn("Scroll-only", engine.text())

    def test_a_successful_seek_is_a_success(self):
        """The seek writes nothing new, but it DID find its target."""
        found = Person("Ann")
        self.result.seeking = True
        self.result.found = found
        self.result.collected.append(found)
        block = ScrollParse(scroll_only=True, pre_delay_ms=0)
        engine = FakeEngine()
        self.assertEqual(run(block.execute("Ann", object(), engine)),
                         ActionResult.OK)

    def test_the_queue_preview_lists_the_first_eight_people(self):
        self.result.collected.extend(Person(f"p{i}") for i in range(12))
        block = ScrollParse(pre_delay_ms=0)
        engine = FakeEngine()
        run(block.execute("x", object(), engine))
        self.assertIn("p7", engine.text())
        self.assertNotIn("p8,", engine.text())
        self.assertIn("+4 more", engine.text())

    def test_messaged_people_are_marked_in_the_preview(self):
        self.result.collected.append(Person("Ann", messaged=True))
        block = ScrollParse(pre_delay_ms=0)
        engine = FakeEngine()
        run(block.execute("x", object(), engine))
        self.assertIn("Ann (messaged)", engine.text())


class TestStackSnapshot(PipelineCase):
    """SP-13 — RULE 3 plus the JSON guarantee."""

    def test_the_block_is_still_serialisable_after_a_run(self):
        """A run must not make the stack unsavable.

        `run_pipeline` stores a `CollectResult` on the block; `to_dict()`
        serialises every public attribute and
        `bridge/stack_bridge.get_stack_json()` does `json.dumps(...)` on the
        live stack — so runtime state has to stay out of the snapshot
        (BUG-05).
        """
        block = ScrollParse(pre_delay_ms=0)
        self.pipeline(block)
        self.assertIsNotNone(block.last_result)
        data = block.to_dict()
        self.assertNotIn("last_result", data)
        json.dumps(data, ensure_ascii=False)

    def test_a_saved_stack_still_loads_after_a_run(self):
        """The snapshot must not carry runtime state back into __init__."""
        block = ScrollParse(pre_delay_ms=0)
        self.pipeline(block)
        data = block.to_dict()
        clone = ScrollParse(**{k: v for k, v in data.items()
                               if k != "block_id"})
        self.assertEqual(clone.to_dict(), data)
        self.assertIsNone(clone.last_result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
