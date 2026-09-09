"""`actions.click_main_tab` / `actions.click_back` — tab switching (P2).

SPEC-FIRST. These two blocks are not in section B of the coverage plan, but
their `config_schema` advertises the same "{{nick}} = selected user"
placeholder as Search Users and Find & Click, and neither expanded it
(BUG-04 — docs/ACTIONS_TEST_DESIGN_2026-09-09.md §12). Pinning them here
keeps the four placeholder-supporting blocks honest as one group.

Run with:  python3 tests/test_click_tab_blocks.py
"""

import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions.click_back as cb  # noqa: E402
import actions.click_main_tab as cmt  # noqa: E402
from actions.base_action import ActionResult  # noqa: E402
from actions.click_back import ClickBack  # noqa: E402
from actions.click_main_tab import ClickMainTab  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeEngine:
    def __init__(self, selected_nick=""):
        self.selected_nick = selected_nick


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


class TabBlockCase(unittest.TestCase):
    module = None
    cls = None

    def setUp(self):
        self.runner = RecordingRunner()
        patcher = mock.patch.object(self.module, "find_and_click",
                                    self.runner)
        patcher.start()
        self.addCleanup(patcher.stop)

    def execute(self, block, user_nick="Ann", engine=None):
        return run(block.execute(user_nick, object(), engine))


class TestClickMainTab(TabBlockCase):
    module = cmt
    cls = ClickMainTab

    def test_the_configured_tab_name_is_searched(self):
        self.execute(ClickMainTab(tab_name="Гостиная", pre_delay_ms=0))
        self.assertEqual(self.runner.last["match_text"], "Гостиная")

    def test_the_click_is_always_enabled(self):
        self.execute(ClickMainTab(pre_delay_ms=0))
        self.assertIs(self.runner.last["click_enabled"], True)

    def test_settings_reach_the_runner(self):
        self.execute(ClickMainTab(selector="div.tab",
                                  child_selector="p.title",
                                  highlight_enabled=False,
                                  confirm_pause_ms=55, pre_delay_ms=0))
        call = self.runner.last
        self.assertEqual(call["selector"], "div.tab")
        self.assertEqual(call["label_selector"], "p.title")
        self.assertIs(call["highlight_enabled"], False)
        self.assertEqual(call["confirm_pause_ms"], 55)

    def test_nick_placeholder_resolves_to_the_selected_user(self):
        self.execute(ClickMainTab(tab_name="{{nick}}", pre_delay_ms=0),
                     engine=FakeEngine(selected_nick="Ксюша"))
        self.assertEqual(self.runner.last["match_text"], "Ксюша")

    def test_nick_placeholder_falls_back_to_the_queued_user(self):
        self.execute(ClickMainTab(tab_name="{{nick}}", pre_delay_ms=0),
                     user_nick="Ксюша")
        self.assertEqual(self.runner.last["match_text"], "Ксюша")

    def test_the_log_label_uses_the_resolved_name(self):
        self.execute(ClickMainTab(tab_name="{{nick}}", pre_delay_ms=0),
                     user_nick="Ксюша")
        self.assertIn("Ксюша", self.runner.last["label"])
        self.assertNotIn("{{nick}}", self.runner.last["label"])

    def test_negative_confirm_pause_is_clamped(self):
        self.assertEqual(ClickMainTab(confirm_pause_ms=-1).confirm_pause_ms, 0)

    def test_defaults_and_round_trip(self):
        block = ClickMainTab()
        self.assertEqual(block.tab_name, "Гостиная")
        self.assertEqual(block.pre_delay_ms, 500)
        data = block.to_dict()
        clone = ClickMainTab(**{k: v for k, v in data.items()
                                if k != "block_id"})
        self.assertEqual(clone.to_dict(), data)


class TestClickBack(TabBlockCase):
    module = cb
    cls = ClickBack

    def test_the_configured_tab_name_is_searched(self):
        self.execute(ClickBack(tab_name="Гостиная", pre_delay_ms=0))
        self.assertEqual(self.runner.last["match_text"], "Гостиная")

    def test_the_label_says_it_is_the_back_tab(self):
        self.execute(ClickBack(pre_delay_ms=0))
        self.assertIn("back tab", self.runner.last["label"])

    def test_nick_placeholder_resolves_to_the_selected_user(self):
        self.execute(ClickBack(tab_name="{{nick}}", pre_delay_ms=0),
                     engine=FakeEngine(selected_nick="Ксюша"))
        self.assertEqual(self.runner.last["match_text"], "Ксюша")
        self.assertIn("Ксюша", self.runner.last["label"])

    def test_negative_confirm_pause_is_clamped(self):
        self.assertEqual(ClickBack(confirm_pause_ms=-1).confirm_pause_ms, 0)

    def test_defaults_and_round_trip(self):
        block = ClickBack()
        self.assertEqual(block.tab_name, "Гостиная")
        self.assertEqual(block.pre_delay_ms, 800)
        data = block.to_dict()
        clone = ClickBack(**{k: v for k, v in data.items()
                             if k != "block_id"})
        self.assertEqual(clone.to_dict(), data)


class TestSchemaPromises(unittest.TestCase):
    """The label and the behaviour must agree — or the label must go."""

    def test_both_blocks_advertise_the_placeholder(self):
        self.assertIn("{{nick}}",
                      ClickMainTab().config_schema()["tab_name"]["label"])
        self.assertIn("{{nick}}",
                      ClickBack().config_schema()["tab_name"]["label"])

    def test_both_schemas_keep_pre_delay(self):
        self.assertIn("pre_delay_ms", ClickMainTab().config_schema())
        self.assertIn("pre_delay_ms", ClickBack().config_schema())


if __name__ == "__main__":
    unittest.main(verbosity=2)
