"""`actions.custom_find` — find rules and fallback plumbing (P2).

SPEC-FIRST (docs/ACTIONS_TEST_DESIGN_2026-09-09.md §7). The block is a thin,
fully configurable front for the shared visual runner, so its contract is
*what it forwards*: the nine settings, the match mode, the human-readable
label, and the placeholder its own config panel advertises.

Run with:  python3 tests/test_custom_find_block.py
"""

import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions.custom_find as cf  # noqa: E402
from actions.base_action import ActionResult  # noqa: E402
from actions.custom_find import CustomFind  # noqa: E402
from backend.dom_probe import MATCH_CONTAINS  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeEngine:
    def __init__(self, selected_nick=""):
        self.selected_nick = selected_nick
        self.lines = []

    def report(self, message, level="info"):
        self.lines.append((level, message))


class RecordingRunner:
    def __init__(self, outcome=ActionResult.OK):
        self.outcome = outcome
        self.calls = []

    async def __call__(self, cdp, **kwargs):
        self.calls.append(kwargs)
        return self.outcome

    @property
    def last(self):
        return self.calls[-1]


class BlockCase(unittest.TestCase):
    def setUp(self):
        self.runner = RecordingRunner()
        patcher = mock.patch.object(cf, "find_and_click", self.runner)
        patcher.start()
        self.addCleanup(patcher.stop)

    def execute(self, block, user_nick="Ann", engine=None):
        return run(block.execute(user_nick, object(), engine))


class TestForwardedRules(BlockCase):
    """CF-01, CF-02, CF-07."""

    def test_every_setting_reaches_the_shared_runner(self):
        """CF-01."""
        block = CustomFind(selector="div.tab", label_selector="p.title",
                           match_text="Гостиная", click_enabled=True,
                           click_selector="button", highlight_enabled=False,
                           confirm_pause_ms=123, highlight_ms=456,
                           pre_delay_ms=0)
        self.execute(block)
        call = self.runner.last
        self.assertEqual(call["selector"], "div.tab")
        self.assertEqual(call["label_selector"], "p.title")
        self.assertEqual(call["match_text"], "Гостиная")
        self.assertIs(call["click_enabled"], True)
        self.assertEqual(call["click_selector"], "button")
        self.assertIs(call["highlight_enabled"], False)
        self.assertEqual(call["confirm_pause_ms"], 123)
        self.assertEqual(call["highlight_ms"], 456)

    def test_the_match_mode_is_substring_not_exact(self):
        """CF-01: Find & Click matches partially; Click User is the exact one."""
        self.execute(CustomFind(selector="div.x", pre_delay_ms=0))
        self.assertEqual(self.runner.last["match_mode"], MATCH_CONTAINS)

    def test_find_without_click_is_forwarded(self):
        """CF-02."""
        self.execute(CustomFind(selector="div.x", click_enabled=False,
                                pre_delay_ms=0))
        self.assertIs(self.runner.last["click_enabled"], False)

    def test_a_failed_find_is_passed_through(self):
        """CF-07."""
        self.runner.outcome = ActionResult.FAIL
        block = CustomFind(selector="div.x", pre_delay_ms=0)
        self.assertEqual(self.execute(block), ActionResult.FAIL)

    def test_the_engine_is_handed_to_the_runner(self):
        engine = FakeEngine()
        self.execute(CustomFind(selector="div.x", pre_delay_ms=0),
                     engine=engine)
        self.assertIs(self.runner.last["engine"], engine)


class TestLabel(BlockCase):
    """CF-03 — the log line the user reads while the block searches."""

    def test_selector_only(self):
        block = CustomFind(selector="div.tab", pre_delay_ms=0)
        self.execute(block)
        self.assertEqual(self.runner.last["label"], "element 'div.tab'")

    def test_selector_plus_inner_text_element(self):
        block = CustomFind(selector="div.tab", label_selector="p.title",
                           pre_delay_ms=0)
        self.execute(block)
        self.assertEqual(self.runner.last["label"],
                         "element 'div.tab' text inside 'p.title'")

    def test_full_description_includes_the_match_text(self):
        block = CustomFind(selector="div.tab", label_selector="p.title",
                           match_text="Гостиная", pre_delay_ms=0)
        self.execute(block)
        self.assertEqual(self.runner.last["label"],
                         "element 'div.tab' text inside 'p.title' "
                         "matching \"Гостиная\"")


class TestNickPlaceholder(BlockCase):
    """CF-05 — the schema label says "{{nick}} = selected user"."""

    def test_match_text_placeholder_resolves_to_the_selected_user(self):
        block = CustomFind(selector="user-item", match_text="{{nick}}",
                           pre_delay_ms=0)
        self.execute(block, user_nick="Queued",
                     engine=FakeEngine(selected_nick="Ксюша"))
        self.assertEqual(self.runner.last["match_text"], "Ксюша")

    def test_match_text_placeholder_falls_back_to_the_queued_user(self):
        block = CustomFind(selector="user-item", match_text="{{nick}}",
                           pre_delay_ms=0)
        self.execute(block, user_nick="Ксюша")
        self.assertEqual(self.runner.last["match_text"], "Ксюша")

    def test_the_schema_still_advertises_the_placeholder(self):
        label = CustomFind().config_schema()["match_text"]["label"]
        self.assertIn("{{nick}}", label)


class TestSettings(unittest.TestCase):
    """CF-04, CF-06 + the config contract."""

    def test_negative_timings_are_clamped(self):
        """CF-04."""
        block = CustomFind(confirm_pause_ms=-5, highlight_ms=-5)
        self.assertEqual(block.confirm_pause_ms, 0)
        self.assertEqual(block.highlight_ms, 0)

    def test_none_timings_are_clamped(self):
        block = CustomFind(confirm_pause_ms=None, highlight_ms=None)
        self.assertEqual(block.confirm_pause_ms, 0)
        self.assertEqual(block.highlight_ms, 0)

    def test_custom_name_drives_the_display_name(self):
        """CF-06."""
        block = CustomFind(custom_name="  Открыть вкладку  ")
        self.assertEqual(block.display_name, "Открыть вкладку")
        self.assertEqual(CustomFind().display_name, "Find & Click")

    def test_defaults(self):
        block = CustomFind()
        self.assertEqual((block.selector, block.label_selector,
                          block.match_text, block.click_selector),
                         ("", "", "", ""))
        self.assertTrue(block.click_enabled)
        self.assertTrue(block.highlight_enabled)
        self.assertEqual(block.confirm_pause_ms, 700)
        self.assertEqual(block.highlight_ms, 1200)

    def test_schema_exposes_every_setting(self):
        schema = CustomFind().config_schema()
        for key in ("custom_name", "selector", "label_selector", "match_text",
                    "click_enabled", "click_selector", "highlight_enabled",
                    "confirm_pause_ms", "highlight_ms", "pre_delay_ms"):
            self.assertIn(key, schema, f"{key} missing from the schema")

    def test_settings_round_trip(self):
        block = CustomFind(custom_name="n", selector="s", match_text="m",
                           click_enabled=False, pre_delay_ms=0)
        data = block.to_dict()
        clone = CustomFind(**{k: v for k, v in data.items()
                              if k != "block_id"})
        self.assertEqual(clone.to_dict(), data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
