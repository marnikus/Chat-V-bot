"""Fresh interpreter closes the transitive-import loophole in pure claims."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.pure


def test_no_transitive_qt_import():
    code = '''
import importlib.abc, sys
class NoQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('PySide6', 'PyQt6', 'PyQt5', 'shiboken6'):
            raise AssertionError('Qt dependency: ' + fullname)
sys.meta_path.insert(0, NoQt())
from bridge import wire_codec, wire_db, wire_undo
from core import scheduler, announcer
from services import world_events
assert wire_codec.selection('["x"]') == (['x'], None)
assert wire_undo.global_payload('stack', '[]') == (True, [])
assert wire_db.world_switched({'ok': True})
'''
    root = Path(__file__).resolve().parents[3]
    env = dict(os.environ, PYTHONPATH=str(root))
    result = subprocess.run([sys.executable, '-c', code], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
