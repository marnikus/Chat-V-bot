"""The planning extraction remains pure and preserves legacy import identity."""

import subprocess
import sys
from datetime import datetime

import pytest

from backend import chat_sync
from backend.sync import planning


@pytest.mark.parametrize("name", [
    "MODE_EMPTY", "MODE_UNCHANGED", "MODE_DELTA", "MODE_FULL",
    "SyncOptions", "ReadPlan", "SyncPlanner",
])
def test_legacy_imports_are_the_same_objects(name):
    assert getattr(chat_sync, name) is getattr(planning, name)


def test_planning_import_and_execution_need_no_runtime_or_storage():
    script = '''
import importlib.abc
import sys

class BlockRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'PySide6', 'stores', 'services'}:
            raise AssertionError('planning loaded ' + fullname)
        if fullname in {'backend.chat_sync', 'backend.chat_parser'}:
            raise AssertionError('planning loaded ' + fullname)

sys.meta_path.insert(0, BlockRuntime())
from backend.sync.planning import SyncOptions, SyncPlanner, MODE_FULL
plan = SyncPlanner.plan({'count': 5}, {}, SyncOptions(max_messages=2))
assert (plan.mode, plan.start, plan.gap) == (MODE_FULL, 3, True)
'''
    completed = subprocess.run([sys.executable, "-c", script],
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_plan_cursor_contract_never_advertises_incomplete_tail():
    plan = planning.ReadPlan(mode=planning.MODE_DELTA, head_sig="h",
                             tail_sig="t", head_any="ha", tail_any="ta")
    assert plan.delta is True
    assert plan.is_empty is False
    assert plan.signatures == {"head_sig": "h", "tail_sig": "t",
                               "head_any": "ha", "tail_any": "ta"}
    assert plan.cursor_kwargs(8) == {"dom_count": 8, **plan.signatures}
    assert plan.cursor_kwargs(3, complete=False) == {
        "dom_count": 3, "head_sig": "h", "tail_sig": "",
        "head_any": "ha", "tail_any": "",
    }
    empty = planning.ReadPlan(mode=planning.MODE_EMPTY)
    assert empty.is_empty is True
    assert empty.delta is False


def test_explicit_options_clock_is_preserved():
    now = datetime(2026, 9, 12, 12)
    assert planning.SyncOptions(now=now).cursor_time() is now
    assert planning.SyncOptions().cursor_time() is None
