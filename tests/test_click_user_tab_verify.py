"""`actions.click_user` — find, memory mode, and the new-tab proof (P1).

SPEC-FIRST (docs/ACTIONS_TEST_DESIGN_2026-09-09.md §8). Contract from the
module docstring: locate the row by an EXACT nickname match, click it through
the shared visual runner, "and finally **confirm that a new chat tab actually
appeared** before reporting the step as done".

`tests/test_click_user_memory.py` covers the memory checkbox against the real
engine and `tests/test_click_user_order.py` the Order(#) column; the
untested surface is the verification step itself — the four ways it can end
(confirmed by count, confirmed by title, refuted, unreadable) plus the
not-found path.

Run with:  python3 tests/test_click_user_tab_verify.py
"""

import asyncio
import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions.click_user as cu  # noqa: E402
from actions.base_action import ActionResult  # noqa: E402
from actions.click_user import ClickUser, build_tab_count_js  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def tabs(count, titles=()):
    return json.dumps({"count": count, "titles": list(titles)})


class FakeCDP:
    """Serves the tab-count probe; raises or returns junk on demand."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.calls = 0

    async def evaluate(self, expression):
        self.calls += 1
        if not self.answers:
            return tabs(0)
        answer = self.answers.pop(0) if len(self.answers) > 1 \
            else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeEngine:
    def __init__(self, selected_nick=""):
        self.selected_nick = selected_nick
        self.noted = []
        self.lines = []

    def report(self, message, level="info"):
        self.lines.append((level, message))

    def note_selected(self, nick):
        self.noted.append(nick)

    def text(self):
        return " | ".join(m for _lvl, m in self.lines)


class RecordingClick:
    """Stands in for backend.visual_click.find_and_click_exact."""

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
        self.click = RecordingClick()
        patcher = mock.patch.object(cu, "find_and_click_exact", self.click)
        patcher.start()
        self.addCleanup(patcher.stop)

    def execute(self, block, cdp, user_nick="Ann", engine=None):
        return run(block.execute(user_nick, cdp, engine))


class TestNotFound(BlockCase):
    """CU-01 — the person is not on the page."""

    def test_a_failed_click_is_returned_unchanged(self):
        self.click.outcome = ActionResult.FAIL
        cdp = FakeCDP([tabs(1)])
        engine = FakeEngine()
        block = ClickUser(pre_delay_ms=0, tab_pause_ms=0)
        self.assertEqual(self.execute(block, cdp, engine=engine),
                         ActionResult.FAIL)

    def test_nobody_is_remembered_after_a_failed_click(self):
        """A click that did not happen must not poison {{nick}}."""
        self.click.outcome = ActionResult.FAIL
        engine = FakeEngine()
        block = ClickUser(pre_delay_ms=0, tab_pause_ms=0)
        self.execute(block, FakeCDP([tabs(1)]), engine=engine)
        self.assertEqual(engine.noted, [])

    def test_no_tab_probe_is_made_after_a_failed_click(self):
        self.click.outcome = ActionResult.FAIL
        cdp = FakeCDP([tabs(1)])
        block = ClickUser(pre_delay_ms=0, tab_pause_ms=0)
        self.execute(block, cdp)
        self.assertEqual(cdp.calls, 1, "only the pre-click snapshot is read")


class TestVerificationOff(BlockCase):
    """CU-02."""

    def test_no_tab_probe_at_all(self):
        engine = FakeEngine()
        block = ClickUser(verify_new_tab=False, pre_delay_ms=0)
        cdp = FakeCDP([tabs(0)])
        self.assertEqual(self.execute(block, cdp, engine=engine),
                         ActionResult.OK)
        self.assertEqual(cdp.calls, 0)
        self.assertEqual(engine.noted, ["Ann"])


class TestTabProof(BlockCase):
    """CU-03 .. CU-05, CU-12."""

    def test_a_grown_tab_count_confirms_the_click(self):
        """CU-03."""
        cdp = FakeCDP([tabs(1, ["Гостиная"]), tabs(2, ["Гостиная", "Ann"])])
        engine = FakeEngine()
        block = ClickUser(pre_delay_ms=0, tab_pause_ms=0)
        self.assertEqual(self.execute(block, cdp, engine=engine),
                         ActionResult.OK)
        self.assertIn("tab count 1 → 2", engine.text())

    def test_a_matching_title_confirms_the_click(self):
        """CU-04."""
        cdp = FakeCDP([tabs(2, ["Гостиная", "Ann"]),
                       tabs(2, ["Гостиная", "Ann"])])
        engine = FakeEngine()
        block = ClickUser(pre_delay_ms=0, tab_pause_ms=0)
        self.assertEqual(self.execute(block, cdp, engine=engine),
                         ActionResult.OK)
        self.assertIn("a tab titled", engine.text())

    def test_no_new_tab_and_no_title_is_a_failure(self):
        """CU-05."""
        cdp = FakeCDP([tabs(1, ["Гостиная"]), tabs(1, ["Гостиная"])])
        engine = FakeEngine()
        block = ClickUser(pre_delay_ms=0, tab_pause_ms=0)
        self.assertEqual(self.execute(block, cdp, engine=engine),
                         ActionResult.FAIL)
        self.assertIn("error", [lvl for lvl, _m in engine.lines])
        self.assertIn("Гостиная", engine.text())

    def test_the_before_snapshot_is_announced(self):
        cdp = FakeCDP([tabs(3, ["a", "b", "c"])])
        engine = FakeEngine()
        block = ClickUser(verify_new_tab=False, pre_delay_ms=0)
        self.execute(block, cdp, engine=engine)
        self.assertEqual(engine.lines, [], "no probe, no snapshot line")

    def test_the_tab_pause_can_be_switched_off(self):
        """CU-12."""
        cdp = FakeCDP([tabs(0), tabs(1, ["Ann"])])
        block = ClickUser(pre_delay_ms=0, tab_pause_ms=0)
        start = time.monotonic()
        self.assertEqual(self.execute(block, cdp), ActionResult.OK)
        self.assertLess(time.monotonic() - start, 0.2)

    def test_the_tab_pause_is_awaited_and_announced(self):
        cdp = FakeCDP([tabs(0), tabs(1, ["Ann"])])
        engine = FakeEngine()
        block = ClickUser(pre_delay_ms=0, tab_pause_ms=150)
        start = time.monotonic()
        self.execute(block, cdp, engine=engine)
        self.assertGreaterEqual(time.monotonic() - start, 0.145)
        self.assertIn("Waiting 150 ms for the new tab", engine.text())


class TestUnreadableTabList(BlockCase):
    """CU-06, CU-07 — a broken probe must not turn a good click into a fail."""

    def test_malformed_json_after_the_click_is_taken_as_success(self):
        """CU-06."""
        cdp = FakeCDP([tabs(1, ["Гостиная"]), "{oops"])
        engine = FakeEngine()
        block = ClickUser(pre_delay_ms=0, tab_pause_ms=0)
        self.assertEqual(self.execute(block, cdp, engine=engine),
                         ActionResult.OK)
        self.assertIn("assuming the click worked", engine.text())

    def test_a_probe_that_raises_after_the_click_is_taken_as_success(self):
        cdp = FakeCDP([tabs(1), RuntimeError("socket closed")])
        engine = FakeEngine()
        block = ClickUser(pre_delay_ms=0, tab_pause_ms=0)
        self.assertEqual(self.execute(block, cdp, engine=engine),
                         ActionResult.OK)

    def test_a_probe_that_raises_before_the_click_does_not_crash(self):
        """CU-07."""
        cdp = FakeCDP([RuntimeError("socket closed"), tabs(2, ["Ann"])])
        engine = FakeEngine()
        block = ClickUser(pre_delay_ms=0, tab_pause_ms=0)
        self.assertEqual(self.execute(block, cdp, engine=engine),
                         ActionResult.OK)

    def test_a_json_array_is_not_mistaken_for_a_tab_list(self):
        cdp = FakeCDP([tabs(1), "[1,2,3]"])
        engine = FakeEngine()
        block = ClickUser(pre_delay_ms=0, tab_pause_ms=0)
        self.assertEqual(self.execute(block, cdp, engine=engine),
                         ActionResult.OK)


class TestMemoryMode(BlockCase):
    """CU-08 .. CU-10."""

    def test_no_engine_means_nobody_to_click(self):
        """CU-08."""
        block = ClickUser(use_person_from_memory=True, pre_delay_ms=0)
        self.assertEqual(self.execute(block, FakeCDP([tabs(1)])),
                         ActionResult.FAIL)
        self.assertEqual(self.click.calls, [])

    def test_an_empty_memory_is_a_loud_failure(self):
        """CU-09."""
        engine = FakeEngine(selected_nick="")
        block = ClickUser(use_person_from_memory=True, pre_delay_ms=0)
        self.assertEqual(self.execute(block, FakeCDP([tabs(1)]),
                                      engine=engine), ActionResult.FAIL)
        self.assertEqual(self.click.calls, [])
        self.assertIn("Pick Person", engine.text())

    def test_the_memory_nick_is_clicked_instead_of_the_queued_user(self):
        """CU-10."""
        engine = FakeEngine(selected_nick="Ксюша")
        cdp = FakeCDP([tabs(0), tabs(1, ["Ксюша"])])
        block = ClickUser(use_person_from_memory=True, pre_delay_ms=0,
                          tab_pause_ms=0)
        self.assertEqual(self.execute(block, cdp, user_nick="Ignored",
                                      engine=engine), ActionResult.OK)
        self.assertEqual(self.click.last["text"], "Ксюша")
        self.assertIn("Ксюша", self.click.last["label"])

    def test_a_whitespace_only_memory_is_treated_as_empty(self):
        engine = FakeEngine(selected_nick="   ")
        block = ClickUser(use_person_from_memory=True, pre_delay_ms=0)
        self.assertEqual(self.execute(block, FakeCDP([tabs(1)]),
                                      engine=engine), ActionResult.FAIL)
        self.assertEqual(self.click.calls, [])


class TestTabProbeJs(unittest.TestCase):
    """CU-11 — the probe is built by string formatting, so escaping matters."""

    def test_both_selectors_are_embedded(self):
        js = build_tab_count_js("div.tab", "p.title")
        self.assertIn("div.tab", js)
        self.assertIn("p.title", js)

    def test_a_quote_in_a_selector_cannot_break_out_of_the_js_string(self):
        js = build_tab_count_js("div[data-x='\"]", "p.title")
        self.assertIn("\\\"", js)          # escaped for JS
        self.assertNotIn("div[data-x='\"]", js)

    def test_the_result_is_a_count_and_a_title_list(self):
        js = build_tab_count_js("div.tab", "p.title")
        self.assertIn("count", js)
        self.assertIn("titles", js)


class TestSettings(unittest.TestCase):
    def test_negative_timings_are_clamped(self):
        block = ClickUser(tab_pause_ms=-5, confirm_pause_ms=-5)
        self.assertEqual(block.tab_pause_ms, 0)
        self.assertEqual(block.confirm_pause_ms, 0)

    def test_the_exact_match_settings_are_the_documented_ones(self):
        block = ClickUser()
        self.assertEqual(block.selector, "user-item")
        self.assertEqual(block.label_selector, ".primary-text")
        self.assertEqual(block.click_selector, ".user-container")
        self.assertTrue(block.verify_new_tab)
        self.assertEqual(block.pre_delay_ms, 1000)

    def test_settings_round_trip(self):
        block = ClickUser(respect_order=True, use_person_from_memory=True,
                          verify_new_tab=False, pre_delay_ms=0)
        data = block.to_dict()
        clone = ClickUser(**{k: v for k, v in data.items()
                             if k != "block_id"})
        self.assertEqual(clone.to_dict(), data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
