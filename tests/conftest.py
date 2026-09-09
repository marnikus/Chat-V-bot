"""AREA A — pytest harness configuration.

* puts the repository root on ``sys.path``;
* verifies real PySide6 is importable at collection (fails fast if a test
  ever re-introduces a global Qt stub);
* seeds the run engine and entry-point modules against real PySide6 before
  any scoped fake can be installed, so the widely-used ``services.run`` and
  ``bridge.router`` classes are real QObject subclasses for the whole session;
* after each test, re-checks that no test left a fake PySide6 in ``sys.modules``.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ── Gate 1a: real PySide6 must be importable before anything else ─────────
from PySide6.QtCore import QObject  # noqa: E402

_real_qobj = getattr(QObject.__init__, "__objclass__", None)
assert _real_qobj is not None and getattr(_real_qobj, "__module__",
                                          "").startswith("PySide6"), (
    "tests/conftest.py requires real PySide6.QtCore.QObject; a test module "
    "started stubbing PySide6 before conftest could verify it."
)

# ── Seed the commonly imported, Qt-dependent modules with real PySide6 ────
# This is what removes the historical collection errors: bridge.router is
# built once against the real QObject metaclass and stays valid even when an
# app test temporarily installs fake Qt modules inside a scoped context.
from services.run import RunCoordinator, RunProgress  # noqa: E402,F401
from app.bootstrap import create_container, queue_path  # noqa: E402,F401
import main  # noqa: E402,F401


def _qt_is_real():
    # Re-read from sys.modules so a fake installed by a test is detected,
    # rather than comparing against the real QObject captured above.
    try:
        from PySide6.QtCore import QObject as current  # noqa: N812
    except Exception:
        return False
    real = getattr(current.__init__, "__objclass__", None)
    return real is not None and getattr(real, "__module__", "").startswith(
        "PySide6")


def pytest_runtest_teardown(item, nextitem):  # noqa: ANN001
    """Gate 1b: no test may leak a fake PySide6 into the global process."""
    if not _qt_is_real():
        raise AssertionError(
            "a test left a fake PySide6 in sys.modules "
            f"(last item: {item.nodeid}). Qt stubs must be scoped with "
            "mock.patch.dict(sys.modules, ...) and restored before teardown."
        )
