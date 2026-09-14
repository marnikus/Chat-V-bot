"""Root conftest — fast path + optional Qt seeding.

Design: docs/archive/2026-09-14-test-arch-redesign/TEST_ARCH_REDESIGN_2026-09-14.md

Old conftest imported Qt for every test (0.8 s tax). New conftest:
* Inserts ROOT to sys.path (always)
* Tries to import real PySide6 and seed RunCoordinator etc — if available,
  Qt tests work; if not (no stublibs), Qt tests will be skipped via qt_real fixture
* Provides mem_db (in-memory HistoryDB, 0.08 s vs 1.4 s file, 17× faster)
* Provides pure/db/qt/gate markers via simple file-name heuristics (fast, no AST parse)
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ── Try Qt seeding — optional, not required for pure tests ──────────────
# If Qt not available (no libGL), don't fail collection — pure tests still run.
try:
    from PySide6.QtCore import QObject  # noqa: F401

    _real_qobj = getattr(QObject.__init__, "__objclass__", None)
    _is_real_qt = _real_qobj is not None and getattr(_real_qobj, "__module__", "").startswith("PySide6")

    if _is_real_qt:
        # Seed commonly imported Qt-dependent modules
        from services.run import RunCoordinator, RunProgress  # noqa: F401
        from app.bootstrap import create_container, queue_path  # noqa: F401
        import main  # noqa: F401
except Exception:
    # Qt not available — pure tests still collect and run
    _is_real_qt = False


# ── Markers — fast heuristic, no AST parse ───────────────────────────────
# We use file path, not content, for speed (collection was 20 s with AST parse).
# Pure: tests/unit/core, backend, stores, actions, test_area_d_coverage_lift, etc.
# DB: file name contains db, history, world, userdb, etc.
# Qt: file path contains unit/app, integration, app, bridge, db_manager
# Gate: file name contains rule16, clone, smell, double_audit, file_coverage

def pytest_collection_modifyitems(config, items):
    for item in items:
        fspath = str(item.fspath)

        # Gate
        if any(k in fspath for k in ("rule16", "clone", "smell", "double_audit", "file_coverage", "stores_module")):
            item.add_marker("gate")
            item.add_marker("slow")
            continue

        # Qt — needs real QApplication
        if any(k in fspath for k in ("unit/app", "integration", "test_app", "test_db_manager", "test_world_write_gate", "test_history_bridge", "test_bridge", "test_file_bridge", "test_boot_chain", "test_router_contract", "test_world_ready")):
            item.add_marker("qt")
            item.add_marker("slow")
            continue

        # DB — needs HistoryDB
        if any(k in fspath for k in ("test_db", "test_history", "test_world", "test_userdb", "test_archive", "test_grid", "test_people", "test_person", "test_recollect", "test_media", "test_live_status")):
            # Distinguish file vs memory via fixture usage — mark db
            item.add_marker("db")
            if "tempfile.mkdtemp" in open(fspath, encoding="utf-8", errors="ignore").read()[:5000]:
                item.add_marker("slow")
            continue

        # Pure — default
        item.add_marker("pure")


# ── Fixtures ─────────────────────────────────────────────────────────────

import pytest


@pytest.fixture
async def mem_db():
    """In-memory HistoryDB — 0.08 s vs 1.4 s file DB (17× faster)."""
    from stores.history_db import HistoryDB

    db = await HistoryDB(":memory:").init()
    try:
        yield db
    finally:
        try:
            await db.close()
        except Exception:
            pass


@pytest.fixture
async def mem_db_file():
    """File DB in temp dir — for tests that assert file path exists."""
    from stores.history_db import HistoryDB

    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "world.db")
    db = await HistoryDB(path).init()
    try:
        yield db
    finally:
        try:
            await db.close()
        except Exception:
            pass
        import shutil
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass


@pytest.fixture
def qt_real():
    """Skip if real PySide6 not importable."""
    try:
        from PySide6.QtCore import QObject
        real = getattr(QObject.__init__, "__objclass__", None)
        is_real = real is not None and getattr(real, "__module__", "").startswith("PySide6")
        if not is_real:
            pytest.skip("real PySide6 not importable — Qt stubbed")
    except Exception as exc:
        pytest.skip(f"PySide6 not importable: {exc}")
    return True


def _qt_is_real():
    try:
        from PySide6.QtCore import QObject as current
    except Exception:
        return False
    real = getattr(current.__init__, "__objclass__", None)
    return real is not None and getattr(real, "__module__", "").startswith("PySide6")


def pytest_runtest_teardown(item, nextitem):
    if not _qt_is_real():
        if "PySide6.QtCore" in sys.modules:
            raise AssertionError(
                f"a test left a fake PySide6 in sys.modules (last item: {item.nodeid}). "
                "Qt stubs must be scoped with mock.patch.dict(sys.modules, ...) and restored."
            )
