"""W2.1 ratchet — no NEW test may add a >50 ms real sleep without a reason.

Policy (`requirements-dev.txt`, W2.1 of the 2026-09-15 plan): a test may spend
≤ 50 ms in real sleeps unless it is marked `slow` with a one-line
`# wait-budget:` reason. Enforcement is a RATCHET, not a rewrite: the
violations that exist today (the slow/e2e families whose wall-clock waits are
real contracts — undo pollers, switch lifecycles) are pinned in
`tests/wait_budget_baseline.txt`; anything NEW fails this gate.

Regenerate the baseline only when a violation was reviewed and accepted:
    python3 tests/test_wait_budget.py --regen > tests/wait_budget_baseline.txt

The guard parses, it does not execute: calls whose sleep amount is not a
numeric constant are ignored (they are condition polls, not fixed waits),
and `# wait-budget:` on the sleep line or the one above is an exemption.
"""

import ast
import re
import sys
import unittest
from pathlib import Path

import pytest

TESTS = Path(__file__).parent
BASELINE = TESTS / "wait_budget_baseline.txt"
MAX_SLEEP_S = 0.05
REASON = "wait-budget"

pytestmark = pytest.mark.metrics

_CALLS = ("sleep",)


def _numeric_seconds(node):
    """Seconds if the argument is a compile-time constant, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left, right = (_numeric_seconds(node.left), _numeric_seconds(node.right))
        if left is not None and right not in (None, 0):
            return left / right
    return None


def _has_reason(lines, lineno):
    return any(REASON in lines[i] for i in (lineno - 1, lineno - 2)
               if 0 <= i < len(lines))


def violations():
    """`path:lineno` for every numeric sleep longer than the budget."""
    found = []
    for path in sorted(TESTS.rglob("test_*.py")):
        if "__pycache__" in path.parts or path.name == Path(__file__).name:
            continue
        src = path.read_text(encoding="utf-8")
        lines = src.splitlines()
        for node in ast.walk(ast.parse(src)):
            if not (isinstance(node, ast.Call) and node.args
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _CALLS):
                continue
            seconds = _numeric_seconds(node.args[0])
            if seconds is None or seconds <= MAX_SLEEP_S:
                continue
            if _has_reason(lines, node.lineno):
                continue
            found.append(f"{path.relative_to(TESTS.parent)}:{node.lineno}")
    return found


class TestWaitBudget(unittest.TestCase):
    def test_no_new_unexplained_long_sleeps(self):
        current = set(violations())
        pinned = set(filter(None, BASELINE.read_text(
            encoding="utf-8").split())) if BASELINE.exists() else set()
        new = sorted(current - pinned)
        self.assertEqual(new, [],
                         "new real sleeps above 50 ms need a slow marker and a "
                         "# wait-budget: reason, or a reviewed baseline entry")
        stale = sorted(pinned - current)
        self.assertEqual(stale, [],
                         "baseline pins sleeps that are gone — rerun --regen")


class TestDetector(unittest.TestCase):
    def test_numeric_seconds_forms(self):
        tree = ast.parse("await asyncio.sleep(80 / 1000)")
        call = tree.body[0].value.value
        self.assertAlmostEqual(_numeric_seconds(call.args[0]), 0.08)
        self.assertIsNone(_numeric_seconds(ast.parse("sleep(ms / 1000.0)")
                                           .body[0].value.args[0]))


def _regen():
    for entry in violations():
        print(entry)


if __name__ == "__main__":
    if "--regen" in sys.argv:
        _regen()
    else:
        unittest.main(verbosity=2)
