"""backend/dom_highlight — highlight build/clear + interpreter nil-safety.

Design refs: docs/BACKEND_TESTS_DESIGN_2026-09-09.md §DH#1–3.

(The JS overlay behaviour itself is covered by tests/test_find_click_
visual.py through the node harness; this file pins the PYTHON side.)

  * captions/selectors/match text with quotes, backslashes, newlines or
    script tags must produce syntactically valid JS (checked with node);
  * the clear probe removes every overlay and is safe to run twice / on
    a page with none (idempotent, never throws);
  * the interpreters turn nil/garbage results into loud error pairs.

Run with:  python3 tests/unit/backend/test_dom_highlight_contract.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from backend.dom_highlight import (  # noqa: E402
    COLOR_CLICK,
    COLOR_FIND,
    HIGHLIGHT_ATTR,
    STASH_KEY,
    build_clear_probe,
    build_click_probe,
    build_find_probe,
    build_highlight_probe,
    interpret_click,
    interpret_click_target,
    interpret_find,
)

NODE = shutil.which("node")


class JsCheck(unittest.TestCase):
    def check_valid_js(self, expr: str):
        if NODE is None:
            return
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(expr)
            path = fh.name
        try:
            subprocess.run([NODE, "--check", path], check=True,
                           capture_output=True, text=True, timeout=10)
        finally:
            os.unlink(path)


class TestBuildProbes(JsCheck):

    def test_find_probe_survives_hostile_captions_and_selectors(self):
        expr = build_find_probe(
            selector='div.i[title="it’s"]',
            label_selector='.t"q',
            match_text='line1\nline2 \\ "x',
            caption='FÜND "红"',
        )
        self.check_valid_js(expr)
        self.assertIn(STASH_KEY, expr,
                     "the find phase must stash the element")

    def test_click_probe_stages_then_clicks(self):
        staged = build_click_probe(click_selector="button.go",
                                   highlight=True, highlight_ms=900,
                                   do_click=False)
        click = build_click_probe(highlight=False, do_click=True)
        self.check_valid_js(staged)
        self.check_valid_js(click)
        # the real switch is the doClick flag (the click() call itself is
        # compiled into both probes behind `if (doClick && out.clickable)`)
        self.assertIn("var doClick = false;", staged,
                      "staging probe must NOT click")
        self.assertIn("var doClick = true;", click,
                      "the click probe must click")

    def test_highlight_probe_never_clicks_or_touches_the_stash(self):
        expr = build_highlight_probe("div.x", color=COLOR_CLICK,
                                     caption="COLLECT", highlight_ms=800,
                                     clear_first=True)
        self.check_valid_js(expr)
        self.assertNotIn(".click()", expr)
        self.assertIn(COLOR_CLICK, expr, "custom colour must be used")

    def test_clear_probe_targets_the_overlay_attribute(self):
        expr = build_clear_probe()
        self.assertIn(HIGHLIGHT_ATTR, expr)
        self.check_valid_js(expr)       # trivially valid, no interpolation

    def test_highlight_expiry_is_encoded(self):
        expr = build_find_probe("div", highlight=True, highlight_ms=1500)
        self.assertIn("1500", expr)


class TestInterpreters(unittest.TestCase):

    def test_find_interpreter_nil_and_error_paths(self):
        msg, level = interpret_find(None, "tab")
        self.assertEqual(level, "error")
        self.assertIn("no data", msg)
        msg, level = interpret_find({}, "tab")
        self.assertEqual(level, "error")
        msg, level = interpret_find({"error": "boom"}, "tab")
        self.assertEqual(level, "error")
        self.assertIn("boom", msg)

    def test_find_interpreter_reports_the_red_outline(self):
        res = {"found": True, "visible": True, "total": 2, "index": 0,
               "text": "Гостиная", "highlighted": True,
               "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}
        msg, level = interpret_find(res, "tab")
        self.assertEqual(level, "success")
        self.assertIn("red outline", msg)
        self.assertIn("Гостиная", msg)
        res["visible"] = False
        self.assertEqual(interpret_find(res, "tab")[1], "warn")

    def test_click_interpreter_matrix(self):
        self.assertEqual(interpret_click(None, "t")[1], "error")
        self.assertEqual(
            interpret_click({"error": "detached"}, "t")[1], "error")
        self.assertEqual(
            interpret_click({"clickable": False, "visible": False}, "t")[1],
            "error")
        msg, level = interpret_click({"clickable": True, "clicked": True,
                                      "text": "ok", "target_desc": "btn"},
                                     "t")
        self.assertEqual(level, "success")
        self.assertIn("btn", msg)
        self.assertEqual(
            interpret_click({"clickable": True, "clicked": False}, "t")[1],
            "warn")

    def test_click_target_interpreter(self):
        self.assertEqual(interpret_click_target({"clickable": True})[1],
                         "success")
        self.assertEqual(interpret_click_target({"clickable": False})[1],
                         "warn")
        self.assertEqual(interpret_click_target(None)[1], "warn")


if __name__ == "__main__":
    unittest.main(verbosity=2)
