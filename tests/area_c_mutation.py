"""Reproducible scoped mutation check for Area C's run helpers.

Run manually: python tests/area_c_mutation.py --output /path/to/results.json
Uses only the standard library plus pytest and the app's test dependencies.
Each mutant runs in a fresh pytest process in a disposable source copy; neither
production files nor another area's coordinator/progress are rewritten.

Operators: negate comparisons, exchange and/or, remove not, replace arithmetic,
flip boolean literals, replace nonempty return values, and delete standalone
call statements (including event emissions). All eligible sites are tested,
not a random sample. Equivalent survivors are not silently discounted.
This is a scoped operator-set score, not a claim of a mutmut/full-package score.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

FILES = (
    "services/run/state_machine.py",
    "services/run/hooks.py",
    "services/run/error_recovery.py",
)
ROOT = Path(__file__).resolve().parents[1]
SWAPS = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE,
    ast.LtE: ast.Gt,
    ast.Gt: ast.LtE,
    ast.GtE: ast.Lt,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.Add,
    ast.Pow: ast.Mult,
}


def candidates(tree):
    for index, node in enumerate(ast.walk(tree)):
        if isinstance(node, ast.Compare):
            for position, op in enumerate(node.ops):
                if type(op) in SWAPS:
                    yield index, "compare", position
        elif isinstance(node, ast.BoolOp):
            yield index, "boolean", None
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            yield index, "not", None
        elif isinstance(node, ast.BinOp) and type(node.op) in SWAPS:
            yield index, "arithmetic", None
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            yield index, "literal", None
        elif isinstance(node, ast.Return) and node.value is not None:
            if not (isinstance(node.value, ast.Constant) and node.value.value is None):
                yield index, "return", None
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            yield index, "call", None


def mutate(tree, index, operator, position):
    tree = copy.deepcopy(tree)
    target = list(ast.walk(tree))[index]
    if operator == "compare":
        target.ops[position] = SWAPS[type(target.ops[position])]()
    elif operator == "boolean":
        target.op = ast.Or() if isinstance(target.op, ast.And) else ast.And()
    elif operator == "arithmetic":
        target.op = SWAPS[type(target.op)]()
    elif operator == "literal":
        target.value = not target.value
    elif operator in ("return", "call"):
        target.value = ast.Constant(None)
    elif operator == "not":

        class RemoveNot(ast.NodeTransformer):
            def visit_UnaryOp(self, node):
                return node.operand if node is target else self.generic_visit(node)

        tree = RemoveNot().visit(tree)
    return ast.unparse(ast.fix_missing_locations(tree))


def run_tests(folder):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1")
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                "tests/test_area_c_run_contracts.py",
                "-q",
                "-x",
                "-p",
                "no:cacheprovider",
            ],
            cwd=folder,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            text=True,
        )
        return {0: "survived", 1: "killed"}.get(
            result.returncode, "error"
        ), result.stdout
    except subprocess.TimeoutExpired:
        return "timeout", "pytest exceeded 10 seconds"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    records = []
    with tempfile.TemporaryDirectory(prefix="area-c-mutation-") as temp:
        folder = Path(temp)
        for name in ("services", "core", "actions", "stores", "backend"):
            shutil.copytree(
                ROOT / name, folder / name, ignore=shutil.ignore_patterns("__pycache__")
            )
        (folder / "tests").mkdir()
        shutil.copyfile(
            ROOT / "tests/test_area_c_run_contracts.py",
            folder / "tests/test_area_c_run_contracts.py",
        )
        baseline, output = run_tests(folder)
        if baseline != "survived":
            raise RuntimeError("Unmutated tests must pass:\n" + output)
        for path in FILES:
            source = (ROOT / path).read_text()
            tree = ast.parse(source)
            for index, operator, position in candidates(tree):
                node = list(ast.walk(tree))[index]
                (folder / path).write_text(mutate(tree, index, operator, position))
                try:
                    status, output = run_tests(folder)
                finally:
                    (folder / path).write_text(source)
                record = {
                    "file": path,
                    "line": node.lineno,
                    "operator": operator,
                    "position": position,
                    "status": status,
                }
                if status == "error":
                    record["output"] = output[-3000:]
                records.append(record)
                print(
                    f"{len(records)} {path}:{node.lineno} {operator}: {status}",
                    flush=True,
                )
    counts = {
        status: sum(r["status"] == status for r in records)
        for status in ("killed", "survived", "timeout", "error")
    }
    # Timeouts count as detected; infrastructure errors are reported, not kills.
    scored = counts["killed"] + counts["survived"] + counts["timeout"]
    report = {
        "scope": FILES,
        "counts": counts,
        "score_percent": 100 * (counts["killed"] + counts["timeout"]) / scored,
        "mutants": records,
    }
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "mutants"}, indent=2
        )
    )
    return int(bool(counts["error"]) or report["score_percent"] < 60)


if __name__ == "__main__":
    raise SystemExit(main())
