"""`actions.pause` — resume / cancel contract (P2).

SPEC-FIRST (docs/ACTIONS_TEST_DESIGN_2026-09-09.md §5). Contract:

  * the docstring says the block "manages its own delay" — so `pre_delay_ms`
    must not be applied on top of `duration_ms`;
  * `duration_ms` is declared as a `"number"` control in `config_schema`,
    which means it arrives from a saved preset as whatever JSON/Qt produced:
    the block has to cope with a numeric string, exactly like every sibling
    block does (`int(...)`), instead of crashing mid-run.

Run with:  python3 tests/test_pause_block.py
"""

import asyncio
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.base_action import ActionResult  # noqa: E402
from actions.pause import Pause  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeEngine:
    def __init__(self):
        self.lines = []

    def report(self, message, level="info"):
        self.lines.append((level, message))

    def text(self):
        return " | ".join(m for _lvl, m in self.lines)


class TestDuration(unittest.TestCase):
    """PAU-01, PAU-02, PAU-06, PAU-07."""

    def test_zero_duration_returns_at_once(self):
        """PAU-01."""
        start = time.monotonic()
        self.assertEqual(run(Pause(duration_ms=0).execute("Ann", None)),
                         ActionResult.OK)
        self.assertLess(time.monotonic() - start, 0.02)

    def test_waits_for_the_configured_duration(self):
        """PAU-02."""
        start = time.monotonic()
        self.assertEqual(run(Pause(duration_ms=150).execute("Ann", None)),
                         ActionResult.OK)
        self.assertGreaterEqual(time.monotonic() - start, 0.145)

    def test_a_numeric_string_from_a_preset_still_pauses(self):
        """PAU-06: "number" fields reach blocks as strings all the time.

        Every other block coerces (`int(duration or 0)`); Pause did not, so a
        preset saved with duration_ms="1500" ended the run with
        `TypeError: unsupported operand type(s) for /: 'str' and 'float'`
        instead of pausing.
        """
        start = time.monotonic()
        outcome = run(Pause(duration_ms="120").execute("Ann", None))
        elapsed = time.monotonic() - start
        self.assertEqual(outcome, ActionResult.OK)
        self.assertGreaterEqual(elapsed, 0.115)

    def test_none_duration_is_treated_as_zero(self):
        self.assertEqual(run(Pause(duration_ms=None).execute("Ann", None)),
                         ActionResult.OK)

    def test_negative_duration_does_not_crash(self):
        """PAU-07."""
        self.assertEqual(run(Pause(duration_ms=-500).execute("Ann", None)),
                         ActionResult.OK)


class TestReporting(unittest.TestCase):
    """PAU-03."""

    def test_reports_start_and_finish_with_the_duration(self):
        engine = FakeEngine()
        run(Pause(duration_ms=0).execute("Ann", None, engine))
        text = engine.text()
        self.assertIn("0 ms", text)
        self.assertIn("finished", text)
        self.assertEqual(len(engine.lines), 2)

    def test_works_without_an_engine(self):
        self.assertEqual(run(Pause(duration_ms=0).execute("Ann", None)),
                         ActionResult.OK)


class TestOwnsItsOwnDelay(unittest.TestCase):
    """PAU-04, PAU-05."""

    def test_pre_delay_is_dropped_not_added(self):
        """PAU-04: "pause manages its own delay"."""
        block = Pause(duration_ms=0, pre_delay_ms=999)
        self.assertEqual(block.pre_delay_ms, 0)
        start = time.monotonic()
        run(block.execute("Ann", None))
        self.assertLess(time.monotonic() - start, 0.05,
                        "pre_delay_ms was applied on top of duration_ms")

    def test_pre_delay_is_zero_after_a_round_trip(self):
        data = Pause(duration_ms=1200).to_dict()
        self.assertEqual(data["pre_delay_ms"], 0)
        clone = Pause(**{k: v for k, v in data.items() if k != "block_id"})
        self.assertEqual(clone.to_dict(), data)

    def test_schema_describes_the_duration(self):
        """PAU-05."""
        schema = Pause().config_schema()
        self.assertIn("duration_ms", schema)
        self.assertEqual(schema["duration_ms"]["type"], "number")

    def test_default_duration_is_one_second(self):
        self.assertEqual(Pause().duration_ms, 1000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
