"""Run real tests and bind their coverage to an unchanged working-tree snapshot."""

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import snapshots

BASELINE = Path(__file__).resolve().parents[3] / "reports/quality/coverage_baseline.json"
SOURCES = "core,actions,backend,bridge,services,stores,app,main"
DESELECT = "tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine"


def coverage_breaches(report, baseline, sources, new_functions):
    if report["meta"]["branch_coverage"] is not True:
        raise ValueError("coverage report was not collected with branches enabled")
    totals = report["totals"]
    errors, ratios = [], {}
    for metric, covered_key, total_key in (
        ("line", "covered_lines", "num_statements"),
        ("branch", "covered_branches", "num_branches"),
    ):
        covered, total = totals[covered_key], totals[total_key]
        if type(covered) is not int or type(total) is not int or not 0 <= covered <= total:
            raise ValueError(f"invalid {metric} coverage totals")
        if metric == "line" and total == 0:
            raise ValueError("coverage measured no production statements")
        previous = baseline[metric]
        if previous["total"] <= 0 or not 0 <= previous["covered"] <= previous["total"]:
            raise ValueError(f"invalid {metric} coverage baseline")
        ratios[metric] = {"covered": covered, "total": total}
        # A branchless program is 100% branch covered, not a division by zero.
        if total and covered * previous["total"] < previous["covered"] * total:
            errors.append(f"{metric} coverage decreased: {covered}/{total} < {previous['covered']}/{previous['total']}")
    for path in sources:
        if path not in report["files"]:
            errors.append(f"coverage did not measure production source {path}")
    for symbol in new_functions:
        hits = set(report["files"].get(symbol.path, {}).get("executed_lines", []))
        if not symbol.body_lines or not hits.intersection(symbol.body_lines):
            errors.append(f"zero-hit/ambiguous new function {symbol.label}; a def-line hit alone is not execution")
    return errors, ratios


def isolated_environment(temporary):
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)  # do not silently inherit a developer's -k/-m filter
    env.pop("COVERAGE_PROCESS_START", None)
    # -B only disables writes, NOT stale reads. A unique cache prevents same-size,
    # same-timestamp source/test edits from reusing pre-existing bytecode.
    env["PYTHONPYCACHEPREFIX"] = str(Path(temporary) / "pycache")
    return env


def run_tests(root, pair, new_functions):
    if pair.target != "WORKTREE":
        raise ValueError("--run-tests requires the working-tree target, not --staged/--head")
    importlib.import_module("coverage")
    root = Path(root).resolve()
    with tempfile.TemporaryDirectory(prefix="rule16-coverage-") as temporary:
        data, output = Path(temporary) / "data", Path(temporary) / "coverage.json"
        env = isolated_environment(temporary)
        command = [sys.executable, "-m", "coverage", "run", f"--data-file={data}",
                   "--branch", f"--source={SOURCES}", "-m", "pytest", "tests", "-q", "-o", "addopts=",
                   "-p", "no:cacheprovider", "--strict-markers",
                   f"--deselect={DESELECT}"]
        try:
            tests = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=1800)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("test/coverage run timed out after 1800 seconds") from exc
        if snapshots.worktree(root) != pair.after:
            raise ValueError("production sources changed during tests; coverage cannot prove this snapshot")
        if tests.returncode:
            return {"breaches": [f"pytest failed (exit {tests.returncode})"],
                    "summary": (tests.stdout + tests.stderr)[-6000:]}
        export = subprocess.run([sys.executable, "-m", "coverage", "json",
                                 f"--data-file={data}", "-o", str(output)], cwd=root,
                                capture_output=True, text=True, timeout=60, env=env)
        if export.returncode:
            raise ValueError(f"coverage JSON export failed: {export.stderr or export.stdout}")
        if snapshots.worktree(root) != pair.after:
            raise ValueError("production sources changed during coverage export")
        try:
            report = json.loads(output.read_text())
            baseline = json.loads(BASELINE.read_text())
            breaches, ratios = coverage_breaches(report, baseline, pair.after, new_functions)
        except (KeyError, TypeError) as exc:
            raise ValueError(f"invalid coverage data: {exc}") from exc
        return {"breaches": breaches, "ratios": ratios,
                "summary": (tests.stdout + tests.stderr)[-6000:],
                "source_binding": "working-tree production content verified unchanged after pytest"}
