"""JS coverage ratchet (metrics lane) — the AREA D follow-up W4.1 unblocked.

`tools/metrics/js_coverage.py` measures line coverage of every attributed
`.js` file by running all `tests/test_*.js` under V8 coverage (Node >= 18).
Now that the JS suites also run inside pytest (W4.1), the measurement becomes
a gate: per-file floors pinned in `tests/js_coverage_baseline.json` may only
be IMPROVED; the totals floor moves the same way; and a JS suite failure
(test_failures) fails here with the tool's stderr excerpt.

Regenerate the pins only after reviewing the drift:
    .venv/bin/python tools/metrics/js_coverage.py --json /tmp/jsc.json
    .venv/bin/python - <<'PY'
    import json
    d = json.load(open('/tmp/jsc.json'))
    floors = {n: round(max(f['pct'] - 0.1, 0.0), 1)
              for n, f in sorted(d['files'].items())}
    json.dump({'global': round(d['totals']['pct'] - 0.1, 1), 'files': floors},
              open('tests/js_coverage_baseline.json', 'w'), indent=1)
    PY
"""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "metrics" / "js_coverage.py"
PINS = Path(__file__).parent / "js_coverage_baseline.json"
NODE = shutil.which("node")

pytestmark = pytest.mark.metrics


@pytest.mark.skipif(NODE is None, reason="node executable not found")
class TestJsCoverage(unittest.TestCase):
    def _measure(self, tmpdir):
        out = Path(tmpdir) / "jsc.json"
        proc = subprocess.run(
            [str(ROOT / ".venv" / "bin" / "python") if (ROOT / ".venv" / "bin" / "python").exists()
             else "python3", str(TOOL), "--json", str(out)],
            capture_output=True, text=True, timeout=120, cwd=ROOT)
        self.assertEqual(proc.returncode, 0,
                         f"js_coverage.py failed:\n{proc.stderr[-1500:]}")
        return json.loads(out.read_text(encoding="utf-8"))

    def test_js_coverage_never_drops_below_the_pinned_floors(self):
        with self.subTest("pinned floors still present"):
            self.assertTrue(PINS.exists())
        pins = json.loads(PINS.read_text(encoding="utf-8"))
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            data = self._measure(td)
        self.assertEqual(data["test_failures"], [],
                         "a Node suite failed under coverage; run "
                         "tools/metrics/js_coverage.py for the list")
        files, deficits = data["files"], []
        for name, floor in pins["files"].items():
            self.assertIn(name, files, f"{name} vanished — re-pin the baseline")
            pct = round(files[name]["pct"], 1)
            if pct < floor:
                deficits.append(f"{name}: {pct} < pinned {floor}")
        self.assertEqual(deficits, [],
                         "JS coverage dropped below the pinned floors — "
                         "cover the new paths or review and re-pin")
        self.assertGreaterEqual(round(data["totals"]["pct"], 1),
                                pins["global"],
                                "JS totals coverage dropped below the floor")

    def test_pin_shape_is_honest(self):
        pins = json.loads(PINS.read_text(encoding="utf-8"))
        self.assertIn("global", pins)
        self.assertIn("files", pins)
        self.assertGreater(len(pins["files"]), 0)
        for floor in pins["files"].values():
            self.assertGreaterEqual(floor, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
