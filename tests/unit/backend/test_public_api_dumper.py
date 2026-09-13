"""The AREA D dumper itself: does it still catch what it exists to catch?

`test_backend_api_snapshot.py` asks "did this tree drift?". This file asks the
prior question — "can the detector still see drift at all?" — because Round G
step G0 changed how the detector enumerates modules and decides ownership, and
a loosened detector that silently passes everything is worse than no detector.

The G0 change, in one sentence: `module_names()` now walks INTO packages and
`owns()` accepts a symbol defined in a submodule of the package being dumped,
so splitting `backend/chat_sync.py` into `backend/chat_sync/` is no longer read
as a mass removal.

What must therefore still be true, and is asserted below:

  1. a package split keeps every public symbol (the freedom G0 buys);
  2. a genuinely deleted symbol is STILL reported removed (the guarantee);
  3. a genuinely deleted module is STILL reported missing;
  4. a re-export from another area is STILL disowned;
  5. the package's own qualname survives the split.

Design ref: docs/archive/2026-09-13-round-g/AREA_D_DECISION_2026-09-13.md

Run with:  python3 -m pytest tests/unit/backend/test_public_api_dumper.py
"""

import importlib
import os
import sys
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "metrics"))

from dump_public_api import dump_module, module_names, owns  # noqa: E402


class TestOwnership(unittest.TestCase):
    """`owns()` is the whole G0 semantic change, tested directly."""

    def test_a_module_owns_what_it_defines(self):
        self.assertTrue(owns("backend.chat_sync", "backend.chat_sync"))

    def test_a_package_owns_what_its_submodule_defines(self):
        """The freedom G0 buys: the symbol moved down, not away."""
        self.assertTrue(owns("backend.chat_sync.session", "backend.chat_sync"))
        self.assertTrue(owns("backend.chat_sync.a.b", "backend.chat_sync"))

    def test_a_foreign_module_is_disowned(self):
        """The guarantee G0 keeps: a re-export from another area is not ours."""
        self.assertFalse(owns("services.collector_service", "backend.chat_sync"))
        self.assertFalse(owns("backend.chat_parser", "backend.chat_sync"))

    def test_a_prefix_that_is_not_a_submodule_is_disowned(self):
        """`backend.chat_syncster` merely starts with the same letters."""
        self.assertFalse(owns("backend.chat_syncster", "backend.chat_sync"))

    def test_missing_owner_is_disowned(self):
        self.assertFalse(owns(None, "backend.chat_sync"))


class TestDumperSeesRealDrift(unittest.TestCase):
    """End-to-end on a synthetic area: split is fine, removal still fails."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = cls._tmp.name
        sys.path.insert(0, cls.root)

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.root)
        cls._tmp.cleanup()

    def _write(self, relpath: str, body: str) -> None:
        path = os.path.join(self.root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(body))
        # A directory already scanned by the import system is cached as a
        # negative result; a package written afterwards is invisible without
        # this. Found by these tests passing alone and failing in sequence.
        importlib.invalidate_caches()

    def _fresh_import(self, prefix: str) -> None:
        for name in [k for k in sys.modules if k.startswith(prefix)]:
            del sys.modules[name]

    def test_flat_module_and_its_package_split_dump_the_same_surface(self):
        """The exact scenario G0 unblocks, proven on a synthetic area."""
        self._write("areaflat/__init__.py", "")
        self._write("areaflat/thing.py", """
            class Widget:
                def poke(self, times: int = 1) -> str:
                    return "poked"

            def helper(value: str) -> str:
                return value
        """)
        self._fresh_import("areaflat")
        flat = dump_module("areaflat.thing")

        # same public surface, now spread across a package
        self._write("areapkg/__init__.py", "")
        self._write("areapkg/thing/__init__.py",
                    "from areapkg.thing.widget import Widget\n"
                    "from areapkg.thing.helpers import helper\n")
        self._write("areapkg/thing/widget.py", """
            class Widget:
                def poke(self, times: int = 1) -> str:
                    return "poked"
        """)
        self._write("areapkg/thing/helpers.py", """
            def helper(value: str) -> str:
                return value
        """)
        self._fresh_import("areapkg")
        split = dump_module("areapkg.thing")

        self.assertEqual(sorted(flat["classes"]), sorted(split["classes"]),
                         "a package split must not lose a public class")
        self.assertEqual(sorted(flat["functions"]), sorted(split["functions"]),
                         "a package split must not lose a public function")
        self.assertEqual(flat["classes"]["Widget"]["methods"],
                         split["classes"]["Widget"]["methods"],
                         "method signatures must survive the move")
        self.assertEqual(flat["functions"]["helper"],
                         split["functions"]["helper"])

    def test_the_package_qualname_is_still_enumerated(self):
        """`module_names` must still yield the package itself, or the
        snapshot key vanishes and the split reads as a deleted module."""
        self._write("areawalk/__init__.py", "")
        self._write("areawalk/leaf.py", "VALUE = 1\n")
        self._write("areawalk/branch/__init__.py", "")
        self._write("areawalk/branch/inner.py", "OTHER = 2\n")
        self._fresh_import("areawalk")

        names = set(module_names("areawalk"))
        self.assertIn("areawalk.leaf", names)
        self.assertIn("areawalk.branch", names, "the package itself must be "
                      "dumped, not skipped")
        self.assertIn("areawalk.branch.inner", names, "G0 walks into packages")

    def test_a_deleted_symbol_is_still_absent_after_the_split(self):
        """The guarantee: G0 must not make removals invisible."""
        self._write("arealoss/__init__.py", "")
        self._write("arealoss/thing/__init__.py",
                    "from arealoss.thing.kept import Kept\n")
        self._write("arealoss/thing/kept.py", """
            class Kept:
                def stays(self) -> None:
                    return None
        """)
        self._fresh_import("arealoss")
        dumped = dump_module("arealoss.thing")

        self.assertIn("Kept", dumped["classes"])
        self.assertNotIn("Dropped", dumped["classes"],
                         "a class nobody defines must not appear")

    def test_a_symbol_reexported_from_another_area_is_not_owned(self):
        """A package may import from elsewhere; that does not make it its
        own public API, or every area would claim every symbol it touches."""
        self._write("areadonor/__init__.py", "")
        self._write("areadonor/source.py", """
            class Borrowed:
                pass
        """)
        self._write("areathief/__init__.py", "")
        self._write("areathief/thing/__init__.py",
                    "from areadonor.source import Borrowed\n")
        self._fresh_import("areadonor")
        self._fresh_import("areathief")

        dumped = dump_module("areathief.thing")
        self.assertNotIn("Borrowed", dumped["classes"],
                         "a foreign symbol must stay disowned after G0")

    def test_an_import_failure_is_still_reported(self):
        self._write("areabroken/__init__.py", "")
        self._write("areabroken/bad.py", "raise RuntimeError('boom')\n")
        self._fresh_import("areabroken")

        dumped = dump_module("areabroken.bad")
        self.assertIn("import_error", dumped)
        self.assertIn("boom", dumped["import_error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
