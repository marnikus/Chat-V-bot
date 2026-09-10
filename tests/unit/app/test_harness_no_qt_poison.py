"""Gate 1 — no test module may leave a fake PySide6 in sys.modules.

The historical P0-3/P0-4 poisoners installed fake ``PySide6`` modules at
import time.  This regression test imports the two former poisoner test
modules and then asserts the global ``PySide6.QtCore.QObject`` is still the
real PySide6 class.
"""

from __future__ import annotations

import importlib
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestNoQtPoisoning(unittest.TestCase):
    def test_former_poisoner_modules_leave_real_qt(self):
        importlib.import_module("tests.test_main_entry")
        importlib.import_module(
            "tests.integration.services.test_run_service_paths")

        from PySide6.QtCore import QObject

        module = getattr(QObject.__init__, "__objclass__", None)
        if module is None:
            self.fail("QtCore.QObject does not expose __objclass__; "
                      "the Qt module may be stubbed")
        self.assertTrue(
            getattr(module, "__module__", "").startswith("PySide6"),
            f"PySide6.QtCore.QObject was replaced by {module!r}; a test "
            "module still stubs Qt globally")


if __name__ == "__main__":
    unittest.main(verbosity=2)
