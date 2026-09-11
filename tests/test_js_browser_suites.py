"""RULE 8 for the browser half: the standalone JS suites have to actually run.

``tests/test_*.js`` are self-contained suites (``node tests/test_x.js`` exits
0) covering the UI contracts in ``ui/js/`` and the bridge protocol they speak.
Nothing executed them automatically, so a suite could fail for weeks without a
signal — the Python suite stayed green because it never looked. Each suite is
spawned with ``node`` here, the same mechanism the probe tests already use for
``tests/js_harness.js``.

Node is optional on a dev box, so the file skips when it is missing; the
discovery test pins the floor so a wrong path can not turn this into a suite
that silently runs nothing.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
PER_SUITE_TIMEOUT = 60
# Every suite runs with the repository as cwd: a few read fixtures relative
# to it (tests/test_bridge_router.js), the rest resolve through __dirname.
SUITES = sorted(
    f for f in os.listdir(os.path.join(ROOT, "tests"))
    if f.startswith("test_") and f.endswith(".js")
)
ids = [os.path.splitext(f)[0] for f in SUITES]

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _run(suite: str) -> subprocess.CompletedProcess:
    return subprocess.run([NODE, os.path.join("tests", suite)],
                          cwd=ROOT, capture_output=True, text=True,
                          timeout=PER_SUITE_TIMEOUT)


def _tail(text: str, lines: int = 25) -> str:
    body = (text or "").strip().splitlines()
    return "\n".join(body[-lines:])


@needs_node
@pytest.mark.parametrize("suite", SUITES, ids=ids)
def test_js_suite_passes(suite: str) -> None:
    """Each browser suite must exit 0; its own report is the failure text."""
    try:
        proc = _run(suite)
    except subprocess.TimeoutExpired:
        pytest.fail(f"tests/{suite} did not finish in {PER_SUITE_TIMEOUT}s")
    assert proc.returncode == 0, (
        f"tests/{suite} exited {proc.returncode}\n"
        f"--- stdout (last 25 lines) ---\n{_tail(proc.stdout)}\n"
        f"--- stderr (last 25 lines) ---\n{_tail(proc.stderr)}")


def test_js_suites_are_discovered() -> None:
    """The glob is the only link to those files — keep it from matching 0."""
    assert len(SUITES) >= 22, f"only {len(SUITES)} JS suites found"
