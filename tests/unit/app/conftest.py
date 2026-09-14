"""Qt conftest — only for tests that need real PySide6.

This conftest is loaded only for tests under tests/unit/app/ (and subdirs).
It imports real PySide6 and seeds the commonly imported Qt-dependent modules
so that `services.run` and `bridge.router` are real QObject subclasses.

Design: docs/archive/2026-09-14-test-arch-redesign/TEST_ARCH_REDESIGN_2026-09-14.md
Root conftest is now minimal and does NOT import Qt — this file pays the Qt tax
only for the 25 files that actually need it.
"""

from __future__ import annotations

import sys

# Verify real PySide6 is importable
from PySide6.QtCore import QObject  # noqa: E402

_real_qobj = getattr(QObject.__init__, "__objclass__", None)
assert _real_qobj is not None and getattr(_real_qobj, "__module__", "").startswith("PySide6"), (
    "tests/unit/app/conftest.py requires real PySide6.QtCore.QObject; "
    "a test module started stubbing PySide6 before conftest could verify it."
)

# Seed the commonly imported, Qt-dependent modules with real PySide6
from services.run import RunCoordinator, RunProgress  # noqa: E402,F401
from app.bootstrap import create_container, queue_path  # noqa: E402,F401
import main  # noqa: E402,F401
