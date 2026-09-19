"""Deprecation and actual-import inventory; keep every compatibility export."""
import ast
import importlib
from pathlib import Path
import unittest
import warnings

from backend.legacy_shims import SHIMS, deprecated_module

ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = ('core', 'actions', 'backend', 'bridge', 'services', 'stores', 'app')
GRANDFATHERED = {('app/bootstrap.py', 'backend.bridge')}


def shim_importers():
    found = set()
    files = [ROOT/'main.py']
    for package in PRODUCTION:
        files.extend((ROOT/package).rglob('*.py'))
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if rel in {f'backend/{name}.py' for name in SHIMS}:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                if node.level and path.parent == ROOT/'backend':
                    module = 'backend' + ('.' + module if module else '')
                names = [module + '.' + a.name for a in node.names] + [module]
            for name in names:
                parts = name.split('.')
                if len(parts) >= 2 and parts[0] == 'backend' and parts[1] in SHIMS:
                    found.add((rel, '.'.join(parts[:2])))
    return found


class TestShims(unittest.TestCase):
    def test_registry_and_shim_calls(self):
        files = {p.stem for p in (ROOT/'backend').glob('*.py') if 'Compatibility shim' in p.read_text()}
        self.assertEqual(files, set(SHIMS))
        for name, target in SHIMS.items():
            self.assertIn(f'deprecated_module("{name}", "{target}")', (ROOT/f'backend/{name}.py').read_text())

    def test_every_shim_import_warns_with_correct_target(self):
        for name, target in SHIMS.items():
            with self.subTest(name=name):
                # Reload rather than deleting modules: do not leave other tests
                # holding different identities for the same imported object.
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', DeprecationWarning)
                    module = importlib.import_module('backend.' + name)
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always', DeprecationWarning)
                    importlib.reload(module)
                messages = [str(w.message) for w in caught if w.category is DeprecationWarning]
                self.assertEqual(len(messages), 1)
                self.assertIn('backend.' + name, messages[0])
                self.assertIn(target, messages[0])

    def test_warning_and_validation(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            deprecated_module('history_repo', 'stores.history_repo')
        self.assertEqual(len(caught), 1)
        self.assertIs(caught[0].category, DeprecationWarning)
        with self.assertRaises(KeyError):
            deprecated_module('not_a_shim', 'nowhere')
        with self.assertRaises(ValueError):
            deprecated_module('history_repo', 'wrong.target')

    def test_no_new_importers(self):
        self.assertEqual(shim_importers()-GRANDFATHERED, set())

    def test_grandfathered_only_shrinks(self):
        self.assertEqual(GRANDFATHERED-shim_importers(), set())
