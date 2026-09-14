"""backend/send_button — the send click and its icon fallback ladder.

Round H (H5) split this module out of `message_injector`, and nothing tested
it afterwards: Round I measured it at **21.1%** line coverage, the worst in
the tree. Every other suite that touches `click_send` monkeypatches it, so
the real fallback ladder — the part that decides whether a message is
actually sent — ran in no test at all.

What matters here is not just "did it return True" but WHICH REASON the user
is told, because these log lines are the only diagnosis available when a send
silently does nothing. So each test asserts the outcome and the reported
reason together.

The CDP client is a stub: `evaluate()` returns canned probe JSON, one entry
per call, so a test can make the button probe miss and the icon probe hit.
No Qt, no browser.
"""

from __future__ import annotations

import asyncio
import json
import unittest

from backend.message_injector import SEND_SELECTOR
from backend.send_button import click_send


class FakeCDP:
    """Returns a scripted answer per `evaluate()` call.

    A script entry may be a JSON string, a dict (encoded for you), None (the
    "no data" case the code checks for), or an Exception instance, which is
    raised to exercise the probe's error handling.
    """

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []

    async def evaluate(self, expr):
        self.calls.append(expr)
        if not self.script:
            raise AssertionError("evaluate() called more times than scripted")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, dict):
            return json.dumps(item)
        return item


class SendCase(unittest.TestCase):
    def run_click(self, *script):
        """Run click_send against a scripted CDP; return (ok, log lines)."""
        reported = []
        cdp = FakeCDP(*script)
        ok = asyncio.run(click_send(
            cdp, lambda msg, level="info": reported.append((level, msg))))
        self.cdp = cdp
        return ok, reported

    def assertReported(self, reported, needle, level=None):
        hits = [(lv, m) for lv, m in reported if needle in m]
        self.assertTrue(
            hits, f"no log line containing {needle!r}; got: "
                  + "; ".join(m for _lv, m in reported))
        if level is not None:
            self.assertEqual(hits[0][0], level,
                             f"{needle!r} reported at the wrong level")


class TestTheButtonPathSucceeds(SendCase):
    def test_a_clicked_button_returns_true_and_says_so(self):
        ok, reported = self.run_click({"found": True, "clicked": True})
        self.assertTrue(ok)
        self.assertReported(reported, "clicked ✔", "success")

    def test_the_button_probe_targets_the_shared_send_selector(self):
        """SEND_SELECTOR stays owned by message_injector (H5's note)."""
        self.run_click({"found": True, "clicked": True})
        self.assertIn(SEND_SELECTOR, self.cdp.calls[0])

    def test_a_successful_button_click_never_runs_the_fallback(self):
        ok, reported = self.run_click({"found": True, "clicked": True})
        self.assertTrue(ok)
        self.assertEqual(len(self.cdp.calls), 1,
                         "the icon fallback ran after a successful click")
        self.assertNotIn("Fallback", " ".join(m for _l, m in reported))


class TestTheFallbackLadder(SendCase):
    def test_found_but_not_clickable_falls_back_and_can_still_send(self):
        ok, reported = self.run_click(
            {"found": True, "clicked": False},          # button: not clickable
            {"found": True, "clicked": True, "total": 3})  # icon: works
        self.assertTrue(ok)
        self.assertReported(reported, "NOT clickable", "warn")
        self.assertReported(reported, "Send icon found", "success")

    def test_button_not_found_at_all_reports_the_selector_then_falls_back(self):
        ok, reported = self.run_click(
            {"found": False, "clicked": False},
            {"found": True, "clicked": True, "total": 1})
        self.assertTrue(ok)
        # The selector also appears in the opening "Searching" line, so pin
        # the MISS line specifically — that is the one that diagnoses a send
        # that went nowhere.
        self.assertReported(reported, "Failed to find element: send button",
                            "warn")
        self.assertIn(SEND_SELECTOR,
                      next(m for _l, m in reported if "Failed to find" in m))
        self.assertReported(reported, "mat-icon", "warn")

    def test_the_icon_exists_but_its_button_is_dead(self):
        ok, reported = self.run_click(
            {"found": False},
            {"found": True, "clicked": False, "total": 2})
        self.assertFalse(ok)
        self.assertReported(reported, "NOT clickable", "error")

    def test_no_send_icon_on_the_page_counts_what_it_did_see(self):
        ok, reported = self.run_click(
            {"found": False},
            {"found": False, "clicked": False, "total": 7})
        self.assertFalse(ok)
        self.assertReported(reported, "7 icon(s)", "error")


class TestFailuresAreReportedNotRaised(SendCase):
    """A send that cannot be attempted must return False, never explode."""

    def test_the_button_probe_raising_is_reported_and_falls_back(self):
        ok, reported = self.run_click(
            RuntimeError("target closed"),
            {"found": True, "clicked": True, "total": 1})
        self.assertTrue(ok, "a raising button probe must not block the "
                            "fallback that can still send the message")
        self.assertReported(reported, "Probe error", "error")
        self.assertReported(reported, "target closed")

    def test_the_icon_probe_raising_returns_false(self):
        ok, reported = self.run_click({"found": False},
                                      RuntimeError("detached frame"))
        self.assertFalse(ok)
        self.assertReported(reported, "Fallback probe error", "error")

    def test_an_empty_fallback_response_is_no_data_not_a_crash(self):
        ok, reported = self.run_click({"found": False}, None)
        self.assertFalse(ok)
        self.assertReported(reported, "no data", "error")

    def test_an_error_field_in_the_icon_probe_is_surfaced(self):
        ok, reported = self.run_click(
            {"found": False}, {"error": "illegal selector"})
        self.assertFalse(ok)
        self.assertReported(reported, "illegal selector", "error")

    def test_an_empty_button_response_still_reaches_the_fallback(self):
        ok, _reported = self.run_click(None, {"found": True, "clicked": True})
        self.assertTrue(ok)
        self.assertEqual(len(self.cdp.calls), 2)


class TestReportingIsOptional(SendCase):
    def test_click_send_works_with_no_report_callback(self):
        """`report` defaults to None; the module must not assume a callback."""
        cdp = FakeCDP({"found": True, "clicked": True})
        self.assertTrue(asyncio.run(click_send(cdp)))

    def test_a_failing_path_with_no_callback_also_stays_quiet(self):
        cdp = FakeCDP({"found": False}, {"found": False, "total": 0})
        self.assertFalse(asyncio.run(click_send(cdp)))


if __name__ == "__main__":
    unittest.main()
