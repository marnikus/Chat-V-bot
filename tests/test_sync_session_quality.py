"""RULE 16 for round 4 steps 6–7, with one narrow frozen-signature exception."""

import ast
from pathlib import Path

import pytest

from tools.metrics import rule16_gate as gate


ROOT = Path(__file__).resolve().parents[1]
FILES = ("backend/sync/session.py", "backend/sync/lifecycle.py", "backend/sync/viewport.py")
ENTRY = ("backend/sync/session.py", None, "run_sync")


def lifecycle_functions():
    for filename in FILES:
        for node in ast.parse((ROOT / filename).read_text()).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield filename, None, node.name
            if isinstance(node, ast.ClassDef):
                for method in node.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        yield filename, node.name, method.name


TARGETS = list(lifecycle_functions())


@pytest.mark.parametrize("target", TARGETS)
def test_lifecycle_functions_fit_rule16(target):
    measured = gate.measure_function(*target)
    assert measured is not None, target
    assert measured["cc"] is not None, "Install requirements-dev.txt; CC unmeasured"
    assert measured["cognitive"] is not None, "Cognitive complexity unmeasured"
    violations = gate.violations(measured)
    if target == ENTRY:
        # Keep the exact established arity; do not exempt any other metric.
        assert measured["params"] == 5
        assert violations == ["params 5 > 4"]
        assert "quality-override: params=5 reason=frozen public run_sync" in (
            ROOT / ENTRY[0]).read_text()
    else:
        assert violations == [], (target, measured)


def test_lifecycle_classes_fit_and_inventory_cannot_disappear():
    classes = {name: info for path in FILES for name, info in gate.classes(path).items()}
    assert {"SyncSession", "SyncLifecycle", "SyncViewport"} <= classes.keys()
    assert len(TARGETS) >= 34
    for name, info in classes.items():
        assert gate.class_violations(info) == [], (name, info)
