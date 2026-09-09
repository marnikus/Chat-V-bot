"""`actions.wait_page` — timeout, condition met, never met (P1).

SPEC-FIRST (docs/ACTIONS_TEST_DESIGN_2026-09-09.md §4). Contract, from the
module docstring: "Polls the DOM and reports: each probe attempt (throttled),
the moment the element is found (with visibility/interactivity state), or the
timeout with the last known DOM state so the failure can be traced."

So the block must (a) stop as soon as the probe reports `found`, (b) honour
`timeout_ms` and never poll forever, (c) survive a probe that raises or
returns junk, and (d) leave a trace in every case.

Run with:  python3 tests/test_wait_page_block.py
"""

import asyncio
import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.base_action import ActionResult  # noqa: E402
from actions.wait_page import TEXTAREA_SEL, WaitPageLoad  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def probe(found=False, total=0, visible=True, disabled=False, error=None):
    return json.dumps({"found": found, "total": total, "visible": visible,
                       "disabled": disabled, "error": error})


class FakeCDP:
    """Answers cdp.evaluate with a scripted list of probe results."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def evaluate(self, expression):
        self.calls.append(expression)
        if not self.answers:
            return probe(found=False)
        answer = self.answers.pop(0) if len(self.answers) > 1 \
            else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeEngine:
    def __init__(self):
        self.lines = []

    def report(self, message, level="info"):
        self.lines.append((level, message))

    def levels(self):
        return [lvl for lvl, _m in self.lines]

    def text(self):
        return " | ".join(m for _lvl, m in self.lines)


class WaitCase(unittest.TestCase):
    def execute(self, block, cdp, engine=None):
        return run(block.execute("Ann", cdp, engine))


class TestConditionMet(WaitCase):
    """WAIT-01, WAIT-03."""

    def test_found_on_the_first_probe_is_one_probe(self):
        """WAIT-01: a wait that succeeds must not keep polling."""
        cdp = FakeCDP([probe(found=True, total=1)])
        engine = FakeEngine()
        block = WaitPageLoad(timeout_ms=5000, pre_delay_ms=0)
        self.assertEqual(self.execute(block, cdp, engine), ActionResult.OK)
        self.assertEqual(len(cdp.calls), 1)
        self.assertIn("success", engine.levels())
        self.assertIn("found", engine.text())

    def test_found_on_a_later_probe(self):
        """WAIT-03."""
        cdp = FakeCDP([probe(found=False), probe(found=True, total=1)])
        block = WaitPageLoad(timeout_ms=5000, pre_delay_ms=0)
        self.assertEqual(self.execute(block, cdp), ActionResult.OK)
        self.assertEqual(len(cdp.calls), 2)

    def test_found_but_not_interactive_is_still_a_success(self):
        cdp = FakeCDP([probe(found=True, total=1, visible=False)])
        engine = FakeEngine()
        block = WaitPageLoad(timeout_ms=5000, pre_delay_ms=0)
        self.assertEqual(self.execute(block, cdp, engine), ActionResult.OK)
        self.assertIn("not interactive", engine.text())

    def test_the_probe_carries_the_configured_selector(self):
        cdp = FakeCDP([probe(found=True, total=1)])
        block = WaitPageLoad(target_selector="div.chat", timeout_ms=100,
                             pre_delay_ms=0)
        self.execute(block, cdp)
        self.assertIn("div.chat", cdp.calls[0])


class TestNeverMet(WaitCase):
    """WAIT-02, WAIT-08, WAIT-09, WAIT-10."""

    def test_timeout_is_honoured_and_reported(self):
        """WAIT-02: never met -> FAIL, and the deadline is respected."""
        cdp = FakeCDP([probe(found=False)])
        engine = FakeEngine()
        block = WaitPageLoad(timeout_ms=300, pre_delay_ms=0)
        start = time.monotonic()
        outcome = self.execute(block, cdp, engine)
        elapsed = time.monotonic() - start
        self.assertEqual(outcome, ActionResult.FAIL)
        self.assertGreaterEqual(elapsed, 0.30)
        self.assertLess(elapsed, 1.2, "the wait ran far past its deadline")
        self.assertIn("error", engine.levels())
        self.assertIn("300 ms", engine.text())

    def test_zero_timeout_checks_once_and_gives_up(self):
        """WAIT-08."""
        cdp = FakeCDP([probe(found=False, total=2)])
        block = WaitPageLoad(timeout_ms=0, pre_delay_ms=0)
        start = time.monotonic()
        self.assertEqual(self.execute(block, cdp), ActionResult.FAIL)
        self.assertLess(time.monotonic() - start, 0.25)
        self.assertEqual(len(cdp.calls), 1)

    def test_the_failure_line_names_the_last_known_dom_state(self):
        """WAIT-09/WAIT-10: the trace must say how many nodes matched."""
        cdp = FakeCDP([probe(found=False, total=3)])
        engine = FakeEngine()
        block = WaitPageLoad(timeout_ms=0, pre_delay_ms=0)
        self.execute(block, cdp, engine)
        self.assertIn("3 node", engine.text())

    def test_the_start_of_the_wait_is_announced(self):
        cdp = FakeCDP([probe(found=True, total=1)])
        engine = FakeEngine()
        block = WaitPageLoad(timeout_ms=100, pre_delay_ms=0)
        self.execute(block, cdp, engine)
        self.assertEqual(engine.lines[0][0], "info")
        self.assertIn("Waiting for", engine.lines[0][1])


class TestBrokenProbes(WaitCase):
    """WAIT-04, WAIT-05, WAIT-06, WAIT-11."""

    def test_a_raising_probe_never_escapes_and_is_reported(self):
        """WAIT-04."""
        cdp = FakeCDP([RuntimeError("cdp socket closed")])
        engine = FakeEngine()
        block = WaitPageLoad(timeout_ms=0, pre_delay_ms=0)
        self.assertEqual(self.execute(block, cdp, engine), ActionResult.FAIL)
        self.assertIn("error", engine.levels())
        self.assertIn("Probe error", engine.text())

    def test_empty_probe_result_means_not_found(self):
        """WAIT-05."""
        for empty in ("", None):
            cdp = FakeCDP([empty])
            block = WaitPageLoad(timeout_ms=0, pre_delay_ms=0)
            self.assertEqual(self.execute(block, cdp), ActionResult.FAIL,
                             f"{empty!r} was not treated as 'not found'")

    def test_malformed_json_does_not_escape(self):
        """WAIT-06."""
        cdp = FakeCDP(["{not json"])
        block = WaitPageLoad(timeout_ms=0, pre_delay_ms=0)
        self.assertEqual(self.execute(block, cdp), ActionResult.FAIL)

    def test_a_non_dict_json_payload_does_not_escape(self):
        cdp = FakeCDP(["[1, 2, 3]"])
        block = WaitPageLoad(timeout_ms=0, pre_delay_ms=0)
        self.assertEqual(self.execute(block, cdp), ActionResult.FAIL)

    def test_works_without_an_engine(self):
        """WAIT-11."""
        cdp = FakeCDP([probe(found=True, total=1)])
        block = WaitPageLoad(timeout_ms=100, pre_delay_ms=0)
        self.assertEqual(self.execute(block, cdp), ActionResult.OK)


class TestSettings(WaitCase):
    """WAIT-07 + the config contract."""

    def test_empty_selector_falls_back_to_the_message_field(self):
        """WAIT-07."""
        self.assertEqual(WaitPageLoad().target_selector, TEXTAREA_SEL)

    def test_defaults(self):
        block = WaitPageLoad()
        self.assertEqual(block.timeout_ms, 5000)
        self.assertEqual(block.pre_delay_ms, 200)

    def test_schema_exposes_selector_and_timeout(self):
        schema = WaitPageLoad().config_schema()
        self.assertIn("target_selector", schema)
        self.assertIn("timeout_ms", schema)
        self.assertIn("pre_delay_ms", schema)

    def test_settings_round_trip(self):
        block = WaitPageLoad(target_selector="div.x", timeout_ms=1234,
                             pre_delay_ms=0)
        data = block.to_dict()
        clone = WaitPageLoad(**{k: v for k, v in data.items()
                                if k != "block_id"})
        self.assertEqual(clone.to_dict(), data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
