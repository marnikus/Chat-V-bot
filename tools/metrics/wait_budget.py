#!/usr/bin/env python3
"""Wait-budget probe — attribute a test run's wall clock to what it *waits* for.

The suite spends most of its wall clock inside `await asyncio.sleep(...)`
loops, not on CPU (measured 2026-09-15: 251.75 s of a 386.5 s run, 154 s of
test CPU).  `pytest --durations` shows which *tests* are slow; this probe shows
which **wait** each test paid for and where the sleeping code lives, which is
what a fix has to move.

    PYTHONPATH=. .venv/bin/python -m pytest -q -p tools.metrics.wait_budget \
        --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine

Writes ``$WAIT_REPORT`` (default ``/tmp/wait_budget.json``) and prints the
headline.  Counts, attributed per test id and per caller file:

  * `asyncio.sleep` / `time.sleep`      → requested seconds and calls
  * `subprocess.run` / `Popen`          → spawns and the seconds each cost
  * `sqlite3.connect`                   → connections

Nothing else is measured and no behaviour is changed: the wrappers add the
delay to a counter and then call through.  Loading the module *without*
`-p tools.metrics.wait_budget` does nothing at all, so the file is inert in
every other context.

Part of: docs/archive/2026-09-15-round-k-test-time/ROUND_K_TEST_TIME_DESIGN_2026-09-15.md
"""
from __future__ import annotations

import asyncio
import collections
import json
import os
import sqlite3
import subprocess
import sys
import time

DEFAULT_REPORT = "/tmp/wait_budget.json"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

_ME = __file__
_CURRENT = "<session>"


def _caller() -> str:
    """The repo-relative file that asked for the wait (first frame not us)."""
    frame = sys._getframe(2)
    while frame is not None and frame.f_code.co_filename == _ME:
        frame = frame.f_back
    if frame is None:
        return "?"
    name = frame.f_code.co_filename
    prefix = ROOT + os.sep
    return name[len(prefix):] if name.startswith(prefix) else name


class WaitBudget:
    """Counters plus the wrappers that fill them.

    One instance per process.  Installed once, by `pytest_configure`; the
    original callables are kept so `uninstall()` can put them back (which a
    test of this probe needs, and nothing else does).
    """

    def __init__(self) -> None:
        self.by_test_seconds: collections.Counter = collections.Counter()
        self.by_test_calls: collections.Counter = collections.Counter()
        self.by_file_seconds: collections.Counter = collections.Counter()
        self.by_file_calls: collections.Counter = collections.Counter()
        self.spawns: collections.Counter = collections.Counter()
        self.spawn_seconds: collections.Counter = collections.Counter()
        self.connects: collections.Counter = collections.Counter()
        self._saved: dict = {}
        self._in_run = 0
        self.installed = False

    # ── installation ───────────────────────────────────────────────
    def install(self) -> None:
        """Patch the four wait surfaces; idempotent."""
        if self.installed:
            return
        for name, target, replacement in (
            ("sleep", asyncio, self.sleep),
            ("tsleep", time, self.tsleep),
            ("run", subprocess, self.run),
            ("popen", subprocess.Popen, self.popen),
            ("connect", sqlite3, self.connect),
        ):
            self._saved[name] = target
        self._saved["sleep_attr"] = asyncio.sleep
        self._saved["tsleep_attr"] = time.sleep
        self._saved["run_attr"] = subprocess.run
        self._saved["popen_attr"] = subprocess.Popen
        self._saved["connect_attr"] = sqlite3.connect
        asyncio.sleep = self.sleep
        time.sleep = self.tsleep
        subprocess.run = self.run
        subprocess.Popen = self.popen
        sqlite3.connect = self.connect
        self.installed = True

    def uninstall(self) -> None:
        """Restore the originals (used by the probe's own test)."""
        if not self.installed:
            return
        asyncio.sleep = self._saved["sleep_attr"]
        time.sleep = self._saved["tsleep_attr"]
        subprocess.run = self._saved["run_attr"]
        subprocess.Popen = self._saved["popen_attr"]
        sqlite3.connect = self._saved["connect_attr"]
        self.installed = False

    # ── the wrappers ───────────────────────────────────────────────
    async def sleep(self, delay, result=None):                 # noqa: D401
        """`asyncio.sleep` — record the requested delay, then really sleep."""
        try:
            seconds = float(delay)
        except (TypeError, ValueError):
            seconds = 0.0
        where = _caller()
        self.by_test_seconds[_CURRENT] += seconds
        self.by_test_calls[_CURRENT] += 1
        self.by_file_seconds[where] += seconds
        self.by_file_calls[where] += 1
        return await self._saved["sleep_attr"](delay, result)

    def tsleep(self, seconds):
        """`time.sleep` — same accounting, blocking flavour."""
        try:
            wanted = float(seconds)
        except (TypeError, ValueError):
            wanted = 0.0
        self.by_test_seconds[_CURRENT] += wanted
        self.by_test_calls[_CURRENT] += 1
        self.by_file_seconds[_caller()] += wanted
        return self._saved["tsleep_attr"](seconds)

    def _spawn(self, real, *args, **kwargs):
        started = time.perf_counter()
        try:
            return real(*args, **kwargs)
        finally:
            self.spawns[_CURRENT] += 1
            self.spawn_seconds[_CURRENT] += time.perf_counter() - started

    def run(self, *args, **kwargs):
        """`subprocess.run` — count the spawn and what it cost in wall clock.

        `subprocess.run` builds its child through the module-level `Popen`,
        which is also wrapped; the guard keeps one logical spawn in the
        counters, with the timing of the whole call rather than its parts.
        """
        self._in_run += 1
        try:
            return self._spawn(self._saved["run_attr"], *args, **kwargs)
        finally:
            self._in_run -= 1

    def popen(self, *args, **kwargs):
        """`subprocess.Popen` — counted only when it is not `run`'s own."""
        if self._in_run:
            return self._saved["popen_attr"](*args, **kwargs)
        return self._spawn(self._saved["popen_attr"], *args, **kwargs)

    def connect(self, *args, **kwargs):
        """`sqlite3.connect` — count connections (the DB cost is real work)."""
        self.connects[_CURRENT] += 1
        return self._saved["connect_attr"](*args, **kwargs)

    # ── the report ────────────────────────────────────────────────
    def snapshot(self, top: int = 40) -> dict:
        """The JSON document this probe writes."""
        files = sorted(self.by_file_seconds, key=lambda k: -self.by_file_seconds[k])
        tests = self.by_test_seconds.most_common(top)
        spawns = sorted(self.spawns, key=lambda k: -self.spawn_seconds[k])
        return {
            "wait_seconds": round(sum(self.by_test_seconds.values()), 2),
            "wait_calls": sum(self.by_test_calls.values()),
            "subprocess_spawns": sum(self.spawns.values()),
            "subprocess_seconds": round(sum(self.spawn_seconds.values()), 2),
            "sqlite_connects": sum(self.connects.values()),
            "top_tests": [[t, round(s, 2), self.by_test_calls[t]]
                          for t, s in tests],
            "top_files": [[f, round(self.by_file_seconds[f], 2),
                           self.by_file_calls[f]] for f in files[:top]],
            "top_spawn_tests": [[t, self.spawns[t],
                                 round(self.spawn_seconds[t], 2)]
                                for t in spawns[:10]],
            "top_connect_tests": self.connects.most_common(10),
        }

    def headline(self, report: dict) -> str:
        """One line a human reads in CI output."""
        return (f"wait {report['wait_seconds']}s in {report['wait_calls']} calls; "
                f"subprocess {report['subprocess_spawns']} spawns / "
                f"{report['subprocess_seconds']}s; "
                f"sqlite {report['sqlite_connects']} connects")


BUDGET = WaitBudget()


# ── pytest plugin surface (no-op unless loaded with -p) ────────────
def pytest_configure(config):                                  # noqa: ANN001
    """Install the wrappers before any test runs."""
    BUDGET.install()


def pytest_runtest_logstart(nodeid, location):                 # noqa: ANN001
    """Attribute everything until the next call to this test."""
    global _CURRENT
    _CURRENT = nodeid


def pytest_runtest_logfinish(nodeid, location):                # noqa: ANN001
    """Anything after the test body belongs to no test in particular."""
    global _CURRENT
    _CURRENT = "<between-tests>"


def pytest_sessionfinish(session, exitstatus):                 # noqa: ANN001
    """Write the JSON report and print the headline."""
    report = BUDGET.snapshot()
    path = os.environ.get("WAIT_REPORT", DEFAULT_REPORT)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)
    print(f"\n[wait-budget] {BUDGET.headline(report)}")
    print(f"[wait-budget] report: {path}")


def main() -> int:                                             # pragma: no cover
    """Print where the report would go — the probe runs *inside* pytest."""
    print(__doc__)
    return 0


if __name__ == "__main__":                                     # pragma: no cover
    raise SystemExit(main())
