"""Round G, step G7 — the two extracted helpers stay shared.

Deleting a clone is easy; keeping it deleted is the part that fails. Both
extractions below replaced a copy-paste that had already drifted once, and the
cheapest way for them to come back is for someone to "just inline this one
case". These tests fail if that happens.

They also pin the two behaviours the duplicated code had that are easy to lose
in an extraction: `report_and_log` must swallow a raising callback while still
writing the log line, and `tab_fields()` must hand each block its own tuple.
"""

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")))

from actions import base as actions_base          # noqa: E402
from actions.click_back import ClickBack          # noqa: E402
from actions.click_main_tab import ClickMainTab   # noqa: E402
from backend import media_handler, message_injector  # noqa: E402
from backend.logger import report_and_log         # noqa: E402


class TestReportAndLogIsShared(unittest.TestCase):

    def test_both_backends_use_the_one_helper(self):
        self.assertIs(media_handler._rep, report_and_log)
        self.assertIs(message_injector._rep, report_and_log)

    def test_a_raising_callback_does_not_escape_but_still_logs(self):
        """The narration must never take down the operation it narrates — and
        the log line must survive the UI's failure, or the event vanishes."""
        def angry(_msg, _level):
            raise RuntimeError("UI is gone")

        with self.assertLogs("chatbot", level="INFO") as caught:
            report_and_log(angry, "media saved", "info")   # must not raise
        self.assertTrue(any("media saved" in line for line in caught.output))

    def test_no_report_callback_still_logs(self):
        with self.assertLogs("chatbot", level="INFO") as caught:
            report_and_log(None, "still recorded")
        self.assertTrue(any("still recorded" in line
                            for line in caught.output))

    def test_an_unknown_level_falls_back_to_info(self):
        with self.assertLogs("chatbot", level="INFO") as caught:
            report_and_log(None, "odd level", "banana")
        self.assertEqual(caught.records[0].levelno, logging.INFO)

    def test_the_level_reaches_both_sinks(self):
        seen = []
        with self.assertLogs("chatbot", level="WARNING") as caught:
            report_and_log(lambda m, lv: seen.append((m, lv)),
                           "careful", "warning")
        self.assertEqual(seen, [("careful", "warning")])
        self.assertEqual(caught.records[0].levelno, logging.WARNING)


class TestTabFieldsIsShared(unittest.TestCase):

    def test_both_tab_blocks_declare_the_same_fields(self):
        names = lambda cls: [f.name for f in cls.FIELDS]  # noqa: E731
        self.assertEqual(names(ClickBack), names(ClickMainTab))
        self.assertEqual(names(ClickBack), [f.name for f in
                                            actions_base.tab_fields()])

    def test_each_class_gets_its_own_tuple_object(self):
        """FIELDS is read per class; sharing one instance would make two
        blocks' declarations indistinguishable by identity."""
        self.assertIsNot(ClickBack.FIELDS, ClickMainTab.FIELDS)
        self.assertIsNot(actions_base.tab_fields(), actions_base.tab_fields())

    def test_the_request_mapping_survived_the_extraction(self):
        """These names are the runner's keyword arguments — a typo here breaks
        the click silently, since find_and_click would just not receive it."""
        mapping = {f.name: f.request for f in ClickBack.FIELDS}
        self.assertEqual(mapping, {
            "selector": "selector",
            "child_selector": "label_selector",
            "tab_name": "match_text",
            "highlight_enabled": "highlight_enabled",
            "confirm_pause_ms": "confirm_pause_ms",
        })

    def test_the_blocks_keep_their_own_constructor_defaults(self):
        """What was deliberately NOT shared: ClickBack waits longer, because it
        runs after leaving a private chat."""
        self.assertEqual(ClickBack().pre_delay_ms, 800)
        self.assertEqual(ClickMainTab().pre_delay_ms, 500)


if __name__ == "__main__":
    unittest.main()
