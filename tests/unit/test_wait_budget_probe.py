"""The wait-budget probe itself: does it count what the round's plan sells?

`tools/metrics/wait_budget.py` is the instrument Round K's design rests on —
"252 s of the suite's 386 s is `asyncio.sleep`" is only as good as the counting.
These tests install it against fake "real" waits, so the accounting is checked
without spending the wall clock it is there to measure.

Nothing here patches globally for longer than one test: `uninstall()` is on
`addCleanup`, and the conftest's teardown gate would notice a leak of the
Qt kind — this is the same discipline for the timekeeping kind.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.metrics import wait_budget as probe  # noqa: E402


async def _awaits_sleep(budget, delay):
    """The real call shape: a coroutine that awaits the probe's wrapper."""
    await budget.sleep(delay)


def _instant(*_args, **_kwargs):
    """A stand-in for the real `asyncio.sleep` — records, never waits."""
    async def _coro(*_a, **_k):
        return None
    return _coro()


class ProbeCase(unittest.TestCase):
    """One installed probe per test, removed even when the test fails."""

    def setUp(self):
        self.budget = probe.WaitBudget()
        self.budget.install()
        self.addCleanup(self.budget.uninstall)
        self.addCleanup(setattr, probe, "_CURRENT", probe._CURRENT)
        probe._CURRENT = f"test::{self.id()}"

    def _fake_sleeps(self):
        """Make the probe's pass-through instant — accounting only."""
        self.budget._saved["sleep_attr"] = _instant
        self.budget._saved["tsleep_attr"] = lambda *_a, **_k: None


class TestAccounting(ProbeCase):

    def test_asyncio_sleep_is_attributed_to_test_and_file(self):
        self._fake_sleeps()
        asyncio.run(_awaits_sleep(self.budget, 0.25))
        self.assertEqual(0.25, self.budget.by_test_seconds[probe._CURRENT])
        self.assertEqual(1, self.budget.by_test_calls[probe._CURRENT])
        mine = "tests/unit/test_wait_budget_probe.py"
        self.assertEqual(0.25, round(self.budget.by_file_seconds[mine], 2))
        self.assertEqual(asyncio.sleep, self.budget.sleep,
                         "installed wrapper must be what asyncio.sleep resolves to")

    def test_zero_delay_counts_as_a_call_but_no_seconds(self):
        self._fake_sleeps()
        asyncio.run(_awaits_sleep(self.budget, 0))
        self.assertEqual(0, self.budget.by_test_seconds[probe._CURRENT])
        self.assertEqual(1, self.budget.by_test_calls[probe._CURRENT])

    def test_time_sleep_is_counted_too(self):
        self._fake_sleeps()
        self.budget.tsleep(0.05)
        self.assertEqual(0.05, round(self.budget.by_test_seconds[probe._CURRENT], 2))
        self.assertEqual(time.sleep, self.budget.tsleep)

    def test_connect_counts_and_still_connects(self):
        connection = self.budget.connect(":memory:")
        self.addCleanup(connection.close)
        self.assertEqual("ok", connection.execute("select 'ok'").fetchone()[0])
        self.assertEqual(1, self.budget.connects[probe._CURRENT])

    def test_subprocess_spawn_is_timed(self):
        self.budget.run([sys.executable, "-c", "pass"], check=True)
        self.assertEqual(1, self.budget.spawns[probe._CURRENT])
        self.assertGreaterEqual(self.budget.spawn_seconds[probe._CURRENT], 0.0)


class TestReport(ProbeCase):

    def test_snapshot_carries_the_headline_numbers(self):
        self._fake_sleeps()
        asyncio.run(_awaits_sleep(self.budget, 0.5))
        report = self.budget.snapshot(top=5)
        self.assertEqual(0.5, report["wait_seconds"])
        self.assertEqual(1, report["wait_calls"])
        self.assertEqual(0, report["subprocess_spawns"])
        self.assertEqual(0, report["sqlite_connects"])
        self.assertTrue(report["top_tests"][0][0].startswith("test::"))
        self.assertIn("wait 0.5s", self.budget.headline(report))

    def test_sessionfinish_writes_the_json_it_reports(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = os.path.join(scratch, "wait.json")
            with mock.patch.dict(os.environ, {"WAIT_REPORT": path}):
                with mock.patch.object(probe, "BUDGET", self.budget):
                    probe.pytest_sessionfinish(session=None, exitstatus=0)
            with open(path, encoding="utf-8") as handle:
                written = json.load(handle)
        self.assertIn("wait_seconds", written)
        self.assertIn("top_files", written)
        self.assertEqual(written["sqlite_connects"],
                         sum(self.budget.connects.values()))


class TestInstallation(unittest.TestCase):

    def test_install_is_idempotent_and_uninstall_restores(self):
        original_sleep = asyncio.sleep
        original_connect = sqlite3.connect
        original_run = subprocess.run
        budget = probe.WaitBudget()
        budget.install()
        budget.install()
        self.assertTrue(budget.installed)
        self.assertEqual(asyncio.sleep, budget.sleep)
        budget.uninstall()
        budget.uninstall()
        self.assertFalse(budget.installed)
        self.assertIs(asyncio.sleep, original_sleep)
        self.assertIs(sqlite3.connect, original_connect)
        self.assertIs(subprocess.run, original_run)

    def test_uninstall_without_install_leaves_the_world_alone(self):
        original = asyncio.sleep
        probe.WaitBudget().uninstall()
        self.assertIs(asyncio.sleep, original)

    def test_importing_the_module_installs_nothing(self):
        """The probe stays inert unless the suite loads it with `-p`."""
        if probe.BUDGET.installed:
            self.skipTest("probe is loaded as a plugin for this run")
        self.assertNotEqual(asyncio.sleep, probe.BUDGET.sleep)
        self.assertNotEqual(sqlite3.connect, probe.BUDGET.connect)
        self.assertNotEqual(subprocess.run, probe.BUDGET.run)


if __name__ == "__main__":
    unittest.main()
