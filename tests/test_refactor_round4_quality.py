"""Extend the real RULE 16 measurements to this round, not just OWNED.

Automatically enumerate the extracted planning module so future additions to
it cannot silently evade the gate. Legacy runtime remains outside hard new-code
limits; its before/after metrics are recorded in the round report.
"""

import ast
from pathlib import Path

import pytest

from tools.metrics import rule16_gate as gate


PLANNING = "backend/sync/planning.py"
ROOT = Path(__file__).resolve().parents[1]


def planning_functions():
    tree = ast.parse((ROOT / PLANNING).read_text())
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield PLANNING, None, node.name
        if isinstance(node, ast.ClassDef):
            for method in node.body:
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield PLANNING, node.name, method.name


TARGETS = list(planning_functions()) + [
    ("stores/settings_store.py", None, "_default_value"),
    ("stores/settings_store.py", "SettingsStore", "get"),
]


@pytest.mark.parametrize("target", TARGETS)
def test_every_round4_function_fits_rule16(target):
    measured = gate.measure_function(*target)
    assert measured is not None, target
    assert measured["cc"] is not None, "Install requirements-dev.txt: CC unchecked"
    assert measured["cognitive"] is not None, "Cognitive complexity unchecked"
    assert gate.violations(measured) == [], (target, measured)


def test_extracted_classes_fit_and_inventory_is_not_empty():
    classes = gate.classes(PLANNING)
    assert {"SyncOptions", "ReadPlan", "SyncPlanner"} <= classes.keys()
    assert len(TARGETS) >= 19
    for name, info in classes.items():
        assert gate.class_violations(info) == [], (name, info)
    settings = gate.classes("stores/settings_store.py")["SettingsStore"]
    assert gate.class_violations(settings) == []
