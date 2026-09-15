"""W4.1 — every Node harness suite (tests/test_*.js) as one pytest item.

RULE 8's harness runs the real shipped UI/probe JS against a DOM stub
(tests/js_harness.js + tests/dom_stub.js). Until now the suites were run
by hand (`for f in tests/test_*.js; do node "$f"; done`), which meant a
broken JS suite only failed locally. Each file becomes a parametrized
item here — marked `node`, parallelised by xdist like any other test,
and skipped via the repo's existing pattern when node is unavailable.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
SUITES = sorted(p.name for p in HERE.glob("test_*.js"))
NODE = shutil.which("node")

pytestmark = pytest.mark.node


@pytest.mark.skipif(NODE is None, reason="node executable not found")
@pytest.mark.parametrize("suite", SUITES)
def test_node_harness_suite(suite):
    proc = subprocess.run([NODE, str(HERE / suite)],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, (
        f"{suite} exited {proc.returncode}\n"
        f"--- stdout tail ---\n{proc.stdout[-2000:]}\n"
        f"--- stderr tail ---\n{proc.stderr[-2000:]}")
