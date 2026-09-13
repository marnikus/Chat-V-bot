"""The final sync facade is re-exports only, with no hidden runtime cycle."""

import ast
import importlib
import subprocess
import sys
from pathlib import Path
from typing import get_type_hints

import pytest

from backend import chat_sync
from backend.sync import lifecycle, session, viewport
from tests.unit.backend.test_chat_sync_phases import FakeParser, FakeRepo


@pytest.mark.parametrize("name, owner", [
    ("SyncSession", "session"), ("run_sync", "session"), ("SyncResult", "session"),
    ("SyncOptions", "planning"), ("ReadPlan", "planning"), ("SyncPlanner", "planning"),
    ("MODE_EMPTY", "planning"), ("MODE_UNCHANGED", "planning"),
    ("MODE_DELTA", "planning"), ("MODE_FULL", "planning"),
    ("SyncPersister", "persistence"), ("merge_live", "persistence"),
    ("ChunkReader", "reading"), ("DeltaAligner", "reading"), ("SLICE_RETRIES", "reading"),
])
def test_every_facade_export_is_the_implementation_object(name, owner):
    implementation = importlib.import_module("backend.sync." + owner)
    assert getattr(chat_sync, name) is getattr(implementation, name)
    assert name in chat_sync.__all__


def test_facade_contains_no_runtime_definitions_or_dynamic_export_code():
    tree = ast.parse(Path(chat_sync.__file__).read_text())
    assert isinstance(tree.body[0], ast.Expr)  # module documentation
    for node in tree.body[1:]:
        if isinstance(node, ast.Assign):
            assert len(node.targets) == 1 and node.targets[0].id == "__all__"
            assert set(ast.literal_eval(node.value)) == set(chat_sync.__all__)
        else:
            assert isinstance(node, ast.ImportFrom), ast.dump(node)
            assert node.module.startswith("backend.sync.")


@pytest.mark.parametrize("module", ["lifecycle", "viewport", "session"])
def test_lifecycle_imports_without_facade_parser_qt_or_registry(module):
    script = f'''
import importlib
import importlib.abc
import sys

class BlockRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {{'PySide6', 'services', 'actions'}}:
            raise AssertionError('phase imported ' + fullname)
        if fullname in {{'backend.chat_sync', 'backend.chat_parser'}}:
            raise AssertionError('phase imported ' + fullname)
        if '{module}' != 'session' and fullname == 'backend.sync.session':
            raise AssertionError('collaborator imported its session owner')

sys.meta_path.insert(0, BlockRuntime())
phase = importlib.import_module('backend.sync.{module}')
assert phase is not None
'''
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_sessions_compose_independent_collaborators_and_refresh_declared_state():
    first = session.SyncSession(FakeParser(), FakeRepo(), "A")
    second = session.SyncSession(FakeParser(), FakeRepo(), "B")
    assert isinstance(first.lifecycle, lifecycle.SyncLifecycle)
    assert isinstance(first.viewport, viewport.SyncViewport)
    assert first.lifecycle.s is first.viewport.s is first
    assert second.lifecycle.s is second.viewport.s is second
    assert first.lifecycle is not second.lifecycle and first.viewport is not second.viewport
    first.state = {"count": 3, "head": ["h", "1"], "tail": "t", "head_any": "ha", "tail_any": "ta"}
    first.sync_state()
    assert (first.count, first.result.count, first.head_sig, first.tail_sig,
            first.head_any, first.tail_any) == (3, 3, "h|1", "t", "ha", "ta")
    assert second.count == 0 and second.head_sig == ""
    assert get_type_hints(session.SyncSession)["options"] is chat_sync.SyncOptions
