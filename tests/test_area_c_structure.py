"""Boundary guards supplement (but never replace) the behavioral contracts."""

import ast
import inspect
import json
from pathlib import Path

import pytest

from services.collector_service import Collector
from services.db_service import DbManager
from services.history import HistoryService
from services.history.export import HistoryExportService
from services.undo_service import UndoService
from services.cdp_service import CdpService
from services.people_service import PeopleService

ROOT = Path(__file__).resolve().parents[1]
# Captured from the unchanged branch base, not from the extracted classes.
API = json.loads((ROOT / "tests/fixtures/area_c_public_api.json").read_text())


@pytest.mark.parametrize(
    "cls",
    [
        Collector,
        DbManager,
        HistoryService,
        HistoryExportService,
        UndoService,
        CdpService,
        PeopleService,
    ],
)
def test_public_signatures_remain_compatible(cls):
    for name, signature in API[cls.__name__].items():
        method = getattr(cls, name)
        if isinstance(method, property):
            method = method.fget
        assert str(inspect.signature(method)) == signature, name


def test_tick_is_a_small_coordinator_over_explicit_phases():
    assert len(inspect.getsource(Collector._tick).splitlines()) <= 60
    from services.collector.probe import CollectorProbe
    from services.collector.archive import CollectorArchive

    assert callable(CollectorProbe.verify)
    assert callable(CollectorArchive.advance)
    from services.undo.projection import UndoProjection
    from services.undo.world_store import UndoWorldStore

    assert UndoService.migrate_global_history is UndoProjection.migrate_global_history
    assert UndoService.sync_world_state is UndoWorldStore.sync_world_state


def test_extracted_modules_add_no_backend_dependencies():
    paths = [
        p
        for name in ("collector", "db", "undo")
        for p in (ROOT / "services" / name).glob("*.py")
    ]
    paths += [
        ROOT / "services/history" / (name + ".py")
        for name in ("binding", "lifecycle", "migration", "export")
    ]
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("backend"), path
            elif isinstance(node, ast.Import):
                assert not any(
                    alias.name.startswith("backend") for alias in node.names
                ), path
