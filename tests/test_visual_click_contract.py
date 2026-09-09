"""backend/visual_click — runner-level confirmation pass/fail contract.

Design refs: docs/BACKEND_TESTS_DESIGN_2026-09-09.md §VC#1–5.

find_click_visual covers the probe JS; this file pins what the RUNNER
promises every action block (docs/AGENT_RULES: "THE way blocks click"):

  * an empty selector fails BEFORE touching the page;
  * find-only mode (click disabled) succeeds on a found element and
    never sends a click probe;
  * found-but-not-visible fails without a click attempt;
  * a find failure means the click phase is never attempted;
  * page garbage (None / bad JSON) fails loudly instead of crashing;
  * the exact wrapper forces exact matching;
  * `find_and_click` returns ActionResult values, never raises.

Run with:  python3 tests/test_visual_click_contract.py
"""

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.base_action import ActionResult  # noqa: E402
from backend.visual_click import (  # noqa: E402
    _parse,
    find_and_click,
    find_and_click_exact,
)

FOUND_VISIBLE = {
    "phase": "find", "found": True, "visible": True, "clickable": True,
    "total": 2, "index": 0, "text": "Гостиная", "highlighted": True,
    "rect": {"x": 1, "y": 2, "width": 3, "height": 4},
}
FOUND_HIDDEN = dict(FOUND_VISIBLE, visible=False, clickable=False)
NOT_FOUND = {"phase": "find", "found": False, "total": 3, "candidates": []}
CLICKED = {"phase": "click", "clickable": True, "clicked": True,
           "text": "btn", "target_desc": "button.go"}
UNCLICKABLE = {"phase": "click", "clickable": False, "clicked": False,
               "visible": False}


class FakeCDP:
    """Records every probe; plays scripted answers in order."""

    def __init__(self, script):
        self.script = list(script)
        self.exprs = []

    async def evaluate(self, expr, **kw):
        self.exprs.append(expr)
        item = self.script.pop(0) if self.script else None
        if isinstance(item, Exception):
            raise item
        return item


class RecordingEngine:
    def __init__(self):
        self.lines = []

    def report(self, message, level="info"):
        self.lines.append((level, message))


def run(coro):
    return asyncio.run(coro)


class RunnerCase(unittest.TestCase):
    def play(self, script, **kw):
        kw.setdefault("confirm_pause_ms", 0)
        kw.setdefault("selector", "div.tab")
        cdp = FakeCDP(script)
        engine = RecordingEngine()
        result = run(find_and_click(cdp, label="tab", engine=engine, **kw))
        return result, cdp, engine


class TestConfirmationPass(RunnerCase):

    STAGE = {"clickable": True, "highlighted": True,
             "target_desc": "button.go"}

    def test_found_and_clicked_is_ok_with_three_probe_rounds(self):
        result, cdp, engine = self.play(
            [json.dumps(FOUND_VISIBLE), json.dumps(self.STAGE),
             json.dumps(CLICKED)])
        self.assertEqual(result, ActionResult.OK)
        self.assertEqual(len(cdp.exprs), 3, "find + stage + click")

    def test_find_only_mode_clicks_nothing(self):
        result, cdp, engine = self.play([json.dumps(FOUND_VISIBLE)],
                                        click_enabled=False)
        self.assertEqual(result, ActionResult.OK)
        self.assertEqual(len(cdp.exprs), 1,
                         "no probe may be sent after the find phase")
        self.assertTrue(any("Click disabled" in m for _, m in engine.lines))

    def test_click_disabled_with_hidden_element_still_succeeds(self):
        """Find-only mode promises FIND success, not clickability."""
        result, cdp, _ = self.play([json.dumps(FOUND_HIDDEN)],
                                   click_enabled=False)
        self.assertEqual(result, ActionResult.OK)


class TestConfirmationFail(RunnerCase):

    def test_empty_selector_fails_before_touching_the_page(self):
        result, cdp, engine = self.play([], selector="   ")
        self.assertEqual(result, ActionResult.FAIL)
        self.assertEqual(cdp.exprs, [])
        self.assertTrue(any("selector" in m.lower() for _, m in engine.lines))

    def test_not_found_fails_and_skips_the_click_phase(self):
        result, cdp, engine = self.play([json.dumps(NOT_FOUND)])
        self.assertEqual(result, ActionResult.FAIL)
        self.assertEqual(len(cdp.exprs), 1)

    def test_found_but_not_visible_never_clicks(self):
        result, cdp, engine = self.play([json.dumps(FOUND_VISIBLE)])
        result = run(find_and_click(
            FakeCDP([json.dumps(FOUND_HIDDEN)]),
            selector="div.tab", label="tab", engine=engine,
            confirm_pause_ms=0))
        self.assertEqual(result, ActionResult.FAIL)
        self.assertTrue(any("not visible" in m for _, m in engine.lines))

    def test_unclickable_click_target_fails_without_clicking(self):
        result, cdp, engine = self.play(
            [json.dumps(FOUND_VISIBLE), json.dumps(UNCLICKABLE),
             json.dumps(CLICKED)])
        self.assertEqual(result, ActionResult.FAIL)
        self.assertEqual(len(cdp.exprs), 2, "no click probe after a "
                                             "not-clickable staging")

    def test_page_garbage_fails_loudly_not_crash(self):
        for garbage in (None, "not json", '["a list"]', ""):
            result, cdp, engine = self.play([garbage])
            self.assertEqual(result, ActionResult.FAIL, repr(garbage))
            self.assertTrue(any("no data" in m for _, m in engine.lines),
                            repr(garbage))

    def test_cdp_exception_is_a_fail_not_a_raise(self):
        result, cdp, engine = self.play([RuntimeError("socket gone")])
        self.assertEqual(result, ActionResult.FAIL)
        self.assertTrue(any("CDP error" in m for _, m in engine.lines))

    def test_click_phase_garbage_fails(self):
        result, cdp, engine = self.play(
            [json.dumps(FOUND_VISIBLE),
             json.dumps({"clickable": True, "target_desc": "b"}),
             " garbage "])
        self.assertEqual(result, ActionResult.FAIL)


class TestExactWrapper(unittest.TestCase):

    def test_exact_mode_is_forced(self):
        cdp = FakeCDP([json.dumps(NOT_FOUND)])
        result = run(find_and_click_exact(
            cdp, text="Ann", selector="div.user", confirm_pause_ms=0))
        self.assertEqual(result, ActionResult.FAIL)
        self.assertIn("var exact = true;", cdp.exprs[0])
        self.assertIn("Ann", cdp.exprs[0])

    def test_wrapper_overrides_a_caller_supplied_mode(self):
        cdp = FakeCDP([json.dumps(NOT_FOUND)])
        run(find_and_click_exact(cdp, text="Ann", selector="div.user",
                                 match_mode="contains", confirm_pause_ms=0))
        self.assertIn("var exact = true;", cdp.exprs[0])


class TestParse(unittest.TestCase):

    def test_parse_matrix(self):
        self.assertIsNone(_parse(None))
        self.assertIsNone(_parse(""))
        self.assertIsNone(_parse("not json"))
        self.assertIsNone(_parse('["list"]'))
        self.assertIsNone(_parse(42))
        self.assertEqual(_parse('{"found": true}'), {"found": True})
        self.assertEqual(_parse('  {"a": 1}  '), {"a": 1})


if __name__ == "__main__":
    unittest.main(verbosity=2)
