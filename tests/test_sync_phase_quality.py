"""RULE 16 hard gates for all definitions extracted in round 4 steps 4–5."""

import ast
from pathlib import Path

import pytest

from tools.metrics import rule16_gate as gate


ROOT = Path(__file__).resolve().parents[1]
FILES = ("backend/sync/persistence.py", "backend/sync/reading.py")


def phase_functions():
    for filename in FILES:
        for node in ast.parse((ROOT / filename).read_text()).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield filename, None, node.name
            if isinstance(node, ast.ClassDef):
                for method in node.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        yield filename, node.name, method.name


TARGETS = list(phase_functions())


@pytest.mark.parametrize("target", TARGETS)
def test_phase_function_fits_all_hard_limits(target):
    measured = gate.measure_function(*target)
    assert measured is not None, target
    assert measured["cc"] is not None, "Install requirements-dev.txt; CC unmeasured"
    assert measured["cognitive"] is not None, "Cognitive complexity unmeasured"
    assert gate.violations(measured) == [], (target, measured)


def test_phase_classes_fit_and_scopes_cannot_silently_disappear():
    expected = {"SyncPersister", "ChunkReader", "DeltaAligner"}
    classes = {name: info for filename in FILES for name, info in gate.classes(filename).items()}
    assert expected <= classes.keys()
    assert len(TARGETS) >= 23
    for name, info in classes.items():
        assert gate.class_violations(info) == [], (name, info)
