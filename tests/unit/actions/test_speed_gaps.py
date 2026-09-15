"""Mutation pins for the wait-speed feature (ported 2026-09-13).

`mutmut run` over actions/speed.py + actions/speed_multiplier.py left 21
survivors; 6 are provably equivalent mutants (a swapped `getattr` default
that `coerce_multiplier` folds back to 1.0, an unreachable `<=` behind an
early `==` return). The other 15 are real: the describe() band between 1.0
and 2.0, `_is_active_speed`'s missing-attribute defaults, `resolve`'s
missing-multiplier skip, the report level of `execute`, and its diagnostic
log line. Each gets the smallest assertion that kills it — the house gap
file pattern (tests/unit/services/test_bot_gaps.py).
"""

import asyncio
import unittest

from actions.speed import (
    SPEED_BLOCK_ID, describe, read_multiplier, resolve_stack_multiplier)
from actions.speed_multiplier import SpeedMultiplier
from actions.base_action import ActionResult


class _Engine:
    """report() with NO default level: a dropped "info" arg must explode."""

    def __init__(self):
        self.reports = []
        self.speed_multiplier = 1.0

    def report(self, msg, level):
        self.reports.append((msg, level))


class _Block:
    """A stack entry with exactly the attributes the test gives it."""

    def __init__(self, **kw):
        for key, value in kw.items():
            setattr(self, key, value)


class TestDescribeBand(unittest.TestCase):

    def test_rates_between_one_and_two_are_slower_not_faster(self):
        # describe_7 mutant: `mult < 1.0` → `mult < 2.0` flips 1.5 into the
        # faster branch ("0.67× faster"); the real band says slower.
        self.assertEqual(describe(1.5), "×1.5 (1.5× slower)")


class TestActiveSpeedDefaults(unittest.TestCase):

    def test_a_block_without_any_attributes_is_not_a_speed_block(self):
        # is_active_7 mutant: dropping the getattr default raises
        # AttributeError on an attribute-less object instead of skipping.
        self.assertEqual(resolve_stack_multiplier([object()]), 1.0)

    def test_a_speed_block_without_enabled_still_votes(self):
        # is_active_14/17/20 mutants: the `enabled` default must be True —
        # None/False/missing all disenfranchise the block.
        block = _Block(block_id=SPEED_BLOCK_ID, multiplier=0.5)
        self.assertEqual(resolve_stack_multiplier([block]), 0.5)

    def test_a_speed_block_without_multiplier_is_skipped(self):
        # resolve_9 mutant: dropping the getattr default raises instead of
        # skipping a block that carries no value yet.
        block = _Block(block_id=SPEED_BLOCK_ID, enabled=True)
        self.assertEqual(resolve_stack_multiplier([block]), 1.0)

    def test_read_multiplier_falls_back_when_engine_lacks_the_field(self):
        self.assertEqual(read_multiplier(object()), 1.0)


class TestExecuteReporting(unittest.TestCase):

    def test_the_run_report_goes_out_at_info_level(self):
        # execute_8 mutant: the "info" level arg disappears; _Engine.report
        # has no default, so the mutant raises TypeError.
        engine = _Engine()
        block = SpeedMultiplier(multiplier=0.5)
        out = asyncio.run(block.execute("N", None, engine))
        self.assertEqual(out, ActionResult.OK)
        self.assertEqual(engine.reports,
                         [("⏩ Global wait speed ×0.5 (2× faster)", "info")])

    def test_the_diagnostic_log_line_is_exact(self):
        # execute_12..19 mutants: the log format string and its single
        # describe(value) argument are the whole observable surface here.
        block = SpeedMultiplier(multiplier=0.5)
        with self.assertLogs("chatbot", level="INFO") as cm:
            asyncio.run(block.execute("N", None, None))
        pinned = [r for r in cm.records
                  if r.msg == "Speed multiplier applied: %s"]
        self.assertEqual(len(pinned), 1)
        self.assertEqual(pinned[0].args, ("×0.5 (2× faster)",))


if __name__ == "__main__":
    unittest.main()
