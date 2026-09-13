"""API snapshots must inspect explicit re-exports, not incidental imports."""

import sys
from types import ModuleType

from tools.metrics.dump_public_api import dump_module


class ExportedClass:
    def action(self, value: str = "") -> str:
        return value


def exported_function(value: int = 1) -> int:
    return value


def test_explicit_exports_preserve_full_class_and_function_contract(monkeypatch):
    facade = ModuleType("round4_facade")
    facade.__all__ = ["ExportedClass", "exported_function"]
    facade.ExportedClass = ExportedClass
    facade.exported_function = exported_function
    facade.incidental = ModuleType
    monkeypatch.setitem(sys.modules, facade.__name__, facade)

    snapshot = dump_module(facade.__name__)
    assert snapshot["functions"] == {"exported_function": "(value: int = 1) -> int"}
    assert snapshot["classes"]["ExportedClass"]["methods"]["action"] == (
        "(self, value: str = '') -> str")
    assert "incidental" not in snapshot["classes"]

    del facade.ExportedClass
    assert "ExportedClass" not in dump_module(facade.__name__)["classes"]
    facade.exported_function = lambda: None
    assert dump_module(facade.__name__)["functions"] != snapshot["functions"]


def test_incidental_foreign_imports_are_not_added_without_exports(monkeypatch):
    facade = ModuleType("round4_incidental")
    facade.ExportedClass = ExportedClass
    facade.exported_function = exported_function
    monkeypatch.setitem(sys.modules, facade.__name__, facade)
    assert dump_module(facade.__name__) == {
        "functions": {}, "classes": {}, "values": {},
    }
