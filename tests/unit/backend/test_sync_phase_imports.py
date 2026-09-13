"""Phase modules import independently; legacy facade exports retain identity."""

import subprocess
import sys

import pytest

from backend import chat_sync
from backend.sync import persistence, reading


@pytest.mark.parametrize("module, name", [
    (persistence, "SyncPersister"), (persistence, "merge_live"),
    (reading, "ChunkReader"), (reading, "DeltaAligner"), (reading, "SLICE_RETRIES"),
])
def test_phase_exports_are_identical_to_the_legacy_facade(module, name):
    assert getattr(chat_sync, name) is getattr(module, name)
    assert name in chat_sync.__all__


@pytest.mark.parametrize("module", ["persistence", "reading"])
def test_phase_import_needs_no_runtime_session_or_registry(module):
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

sys.meta_path.insert(0, BlockRuntime())
phase = importlib.import_module('backend.sync.{module}')
assert phase is not None
'''
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
