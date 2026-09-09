"""backend/dom_probe — JS building and result interpretation contracts.

Design refs: docs/BACKEND_TESTS_DESIGN_2026-09-09.md §DP#1–3.

The generated probe string is EVALUATED BY CHROME — a selector or match
text containing quotes/backslashes/newlines must arrive escaped, or the
whole probe becomes a syntax error and every action using it fails with
"no data from page". Proven here:

  * `_js_str` escaping survives a REAL JavaScript round-trip (node);
  * the assembled probe is syntactically valid JS even with hostile
    inputs (node --check), the candidate cap and match mode land;
  * the interpreters answer every nil/garbage result with a clear
    (message, level) pair instead of raising.

Run with:  python3 tests/unit/backend/test_dom_probe_contract.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from backend.dom_probe import (  # noqa: E402
    MATCH_CONTAINS,
    MATCH_EXACT,
    _js_str,
    build_probe,
    interpret,
    interpret_wait,
)

NODE = shutil.which("node")


@unittest.skipIf(NODE is None, "node not available")
class TestJsStrEscaping(unittest.TestCase):

    def roundtrip(self, literal: str) -> str:
        """Evaluate the JS string literal with node, return its value."""
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(f"process.stdout.write(JSON.stringify({literal}))")
            path = fh.name
        try:
            out = subprocess.run([NODE, path], capture_output=True,
                                 text=True, timeout=10, check=True)
            return json.loads(out.stdout)
        finally:
            os.unlink(path)

    def test_hostile_text_round_trips_through_real_javascript(self):
        hostile = 'say "hi" \\ / tab\tnl\n卿   line'
        literal = _js_str(hostile)
        self.assertEqual(self.roundtrip(literal), hostile)

    def test_control_characters_and_line_separators(self):
        for s in ("a\x00b", "a\x1fb", "x\r\ny", "  ",
                  "</script><b>not html</b>"):
            self.assertEqual(self.roundtrip(_js_str(s)), s)


class TestBuildProbe(unittest.TestCase):

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

    def test_probe_is_valid_js_for_hostile_inputs(self):
        expr = build_probe(
            selector='div.a[title="x’y"]',
            label_selector='.n"quote',
            match_text='multi\nline \\ "text"',
            click=True,
            click_selector='button.it\'s',
            max_candidates=3,
        )
        self.check_valid_js(expr)       # must not be a syntax error

    def test_match_mode_switches_the_comparator(self):
        contains = build_probe("div", match_text="x",
                               match_mode=MATCH_CONTAINS)
        exact = build_probe("div", match_text="x", match_mode=MATCH_EXACT)
        self.assertIn("var exact = false;", contains)
        self.assertIn("var exact = true;", exact)

    def test_candidate_cap_lands_in_the_js(self):
        self.assertIn("slice(0, 3)", build_probe("div", max_candidates=3))
        self.assertIn("slice(0, 12)", build_probe("div", max_candidates=12))

    def test_no_click_by_default_and_optional_click_target(self):
        self.assertNotIn("target.click()", build_probe("div"))
        with_click = build_probe("div", click=True,
                                 click_selector="button.go")
        self.assertIn("target.click()", with_click)
        self.assertIn("button.go", with_click)
        root_click = build_probe("div", click=True, click_root=True)
        self.check_valid_js(root_click)

    def test_empty_optionals_become_null_not_empty_quotes(self):
        expr = build_probe("div")
        self.assertIn("var childSel = null;", expr)
        self.assertIn("var matchText = null;", expr)


class TestInterpretNilSafety(unittest.TestCase):

    def test_none_and_empty_get_a_clear_error_not_an_exception(self):
        msg, level = interpret(None, "tab")
        self.assertEqual(level, "error")
        self.assertIn("no usable data", msg)
        msg, level = interpret({}, "tab")
        self.assertEqual(level, "error")

    def test_probe_error_is_surfaced(self):
        msg, level = interpret({"error": "SyntaxError", "found": False},
                               "tab")
        self.assertEqual(level, "error")
        self.assertIn("SyntaxError", msg)

    def test_found_visible_clicked_matrix(self):
        base = {"found": True, "visible": True, "disabled": False,
                "text": "Гостиная", "index": 1, "total": 3}
        self.assertEqual(interpret(dict(base, clicked=True), "t")[1],
                         "success")
        self.assertEqual(interpret(dict(base), "t")[1], "success")
        self.assertEqual(interpret(dict(base, visible=False), "t")[1],
                         "warn")
        self.assertEqual(interpret(dict(base, disabled=True), "t")[1],
                         "warn")
        self.assertEqual(interpret(dict(base, clicked=False,
                                        clickable=True), "t")[1], "error")

    def test_not_found_lists_candidates(self):
        msg, level = interpret({"found": False, "total": 2, "candidates": [
            {"index": 0, "text": "A", "visible": True, "clickable": False},
            {"index": 1, "text": "B", "visible": False, "clickable": False},
        ]}, "tab")
        self.assertEqual(level, "error")
        self.assertIn("Candidates", msg)
        self.assertIn("A", msg)

    def test_garbage_result_types_are_a_clear_error(self):
        """Ledger #14 — a debugger helper must summarise anything the
        page hands back; a bare string used to raise AttributeError."""
        for garbage in ("garbage", "123", '["list"]', 7, object()):
            msg, level = interpret(garbage, "tab")
            self.assertEqual(level, "error", repr(garbage))
            msg, level = interpret_wait(garbage, "tab")
            self.assertEqual(level, "error", repr(garbage))

    def test_wait_interpreter_levels(self):
        self.assertEqual(interpret_wait(None, "t")[1], "error")
        self.assertEqual(interpret_wait({"found": False, "total": 0}, "t")[1],
                         "warn")
        self.assertEqual(interpret_wait({"found": True, "visible": True,
                                         "disabled": False}, "t")[1],
                         "success")
        self.assertEqual(interpret_wait({"found": True, "visible": False},
                                        "t")[1], "success")
        self.assertEqual(interpret_wait({"found": True, "error": "x"}, "t")[1],
                         "error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
