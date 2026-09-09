"""backend/message_injector — text-handling contracts (format & failure).

Design refs: docs/BACKEND_TESTS_DESIGN_2026-09-09.md §MI#1–3.

The typing-ladder fallbacks are covered by test_message_block_composer
and test_search_users. This file pins the TEXT contracts:

  * `_same_text` tolerance matrix — CRLF==LF, exactly ONE trailing
    newline of difference tolerated, TWO are a real mismatch (a page
    that ate a blank line must NOT verify as "typed");
  * `_js` embeds hostile text so that REAL JavaScript (node) reads back
    the identical string — quotes, backslashes, newlines, U+2028;
  * a multiline message travels through the value-setter strategy with
    its newlines intact (Enter must never submit early);
  * empty text fails before touching the page.

Run with:  python3 tests/test_message_injector_text.py
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.message_injector import (  # noqa: E402
    _js,
    _same_text,
    type_message,
)

NODE = shutil.which("node")


class TestSameText(unittest.TestCase):

    def test_crlf_and_cr_normalise_to_lf(self):
        self.assertTrue(_same_text("a\r\nb", "a\nb"))
        self.assertTrue(_same_text("a\rb", "a\nb"))

    def test_exactly_one_trailing_newline_is_tolerated(self):
        self.assertTrue(_same_text("a\n", "a"))
        self.assertTrue(_same_text("a", "a\n"))

    def test_two_trailing_newlines_are_a_mismatch(self):
        """Ledger #15 — rstrip() used to forgive ANY number of eaten
        trailing newlines, so a mangled message verified as delivered."""
        self.assertFalse(_same_text("a\n\n", "a"))
        # actual="a\n\n" vs expected="a\n" IS one newline of
        # difference — tolerated by design, never a mismatch

    def test_internal_whitespace_is_significant(self):
        self.assertFalse(_same_text("a  b", "a b"))
        self.assertFalse(_same_text("a\nb", "a b"))
        self.assertFalse(_same_text("", "a"))
        self.assertFalse(_same_text(None, ""))


@unittest.skipIf(NODE is None, "node not available")
class TestJsEmbedding(unittest.TestCase):

    def roundtrip(self, literal: str) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(f"process.stdout.write({literal})")
            path = fh.name
        try:
            out = subprocess.run([NODE, path], capture_output=True,
                                 timeout=10, check=True)
            # bytes + manual decode: text mode translates 

            return out.stdout.decode("utf-8")
        finally:
            os.unlink(path)

    def test_hostile_text_survives_real_javascript(self):
        for text in ('say "hi"', "back\\slash", "line1\nline2\r\nline3",
                     "tab\there", "sep next", "emoji 👍",
                     "</script>alert(1)<b>", "100% _free"):
            self.assertEqual(self.roundtrip(_js(text)), text,
                             f"JS read-back differs for {text!r}")

    def test_line_separators_are_ascii_escaped(self):
        literal = _js("a\u2028b\u2029c")
        self.assertTrue(literal.isascii(),
                        "U+2028 must be \\u-escaped, not embedded raw")


class _TypedPage:
    """A fake page: the value-setter strategy lands, read-back is real."""

    def __init__(self):
        self.field = None
        self.exprs = []

    async def evaluate(self, expr, **kw):
        self.exprs.append(expr)
        if "JSON.stringify(out)" in expr:      # a find probe
            return json.dumps({"found": True, "total": 1, "index": 0,
                               "visible": True, "clickable": True,
                               "candidates": []})
        if "dispatchEvent" in expr:            # the value-setter strategy
            literals = re.findall(r'"(?:[^"\\]|\\.)*"', expr)
            if len(literals) >= 2:
                self.field = json.loads(literals[1])
            return "ok"
        if "insertText" in expr:               # strategy 3
            return "ok"
        return self.field or ""                # value read-back

    async def send(self, method, params=None):
        return {}


class TestTyping(unittest.TestCase):

    def type(self, text, page=None):
        page = page or _TypedPage()
        result = asyncio.run(type_message(page, text, typing_speed_ms=0))
        return result, page

    def test_multiline_message_lands_with_newlines_intact(self):
        text = "first line\nsecond line\n\nfourth"
        ok, page = self.type(text)
        self.assertTrue(ok, "multiline typing must verify")
        self.assertEqual(page.field, text,
                         "Enter must not submit early or eat lines")

    def test_hostile_text_lands_byte_for_byte(self):
        text = 'He said "go\\away"\t\t👍'
        ok, page = self.type(text)
        self.assertTrue(ok)
        self.assertEqual(page.field, text)

    def test_empty_text_fails_without_touching_the_page(self):
        page = _TypedPage()
        ok = asyncio.run(type_message(page, "", typing_speed_ms=0))
        self.assertFalse(ok)
        self.assertEqual(page.field, None,
                         "an empty message must not type anything")


if __name__ == "__main__":
    unittest.main(verbosity=2)
