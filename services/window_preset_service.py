"""Portable window-preset document validation and compatibility metadata.

`validate_document` owns the one thing that must stay in exactly one place:
the **order** of the sections, because each validator returns
`(value, error)` and short-circuits, so the order of the checks IS the error
a caller sees.

    window_preset_contract.py  the constants and the four leaf predicates
    window_preset_header.py    decode + format/version/name/timestamps
    window_preset_grid.py      the sash-tree section
    window_preset_windows.py   the windows section
    window_preset_sections.py  window_states and screen

Round H step H-C5 moved the sections out of this file. Round F's F7 row
advised "decomposition and explanation, not splitting" for it, and that advice
is superseded here on measurement, not taste: MI is computed from a file's
Halstead volume, its total cyclomatic complexity and its logical line count,
so extracting named helpers *within* one file moves none of the three — the
function count goes up and MI stays flat or falls. The only lever on MI is the
module boundary. The same file's sibling in the F7 row,
`services/run/progress.py`, was split by this round's own H-C1 and went from
MI 31.0 to 71.8; the check order this file cares about is preserved by keeping
`validate_document` here.

`WindowPresetService` is the facade the bridge and tests import; the four
constants are re-exported so `from services.window_preset_service import
FORMAT` keeps working.

Import direction: this module reads the four section modules and nothing
imports back into them.
"""

from __future__ import annotations

from typing import Any

from .window_preset_contract import (APP_VERSION, FORMAT, GRID_TYPE,
                                     SCHEMA_VERSION)
from .window_preset_grid import _grid
from .window_preset_header import _decode, _header
from .window_preset_sections import _screen, _states
from .window_preset_windows import _windows

__all__ = ["APP_VERSION", "FORMAT", "GRID_TYPE", "SCHEMA_VERSION",
           "WindowPresetService", "validate_document"]


def _document_body(doc: dict) -> tuple[dict | None, str | None]:
    grid, error = _grid(doc)
    if error:
        return None, error
    states, error = _states(doc)
    if error:
        return None, error
    windows, error = _windows(doc, states)
    if error:
        return None, error
    screen, error = _screen(doc)
    if error:
        return None, error
    return {"grid": grid, "windows": windows,
            "window_states": states, "screen": screen}, None


def validate_document(raw: Any, name: str | None = None) -> tuple[dict | None, str | None]:
    """Validate a portable document; `(document, None)` or `(None, error)`.

    Four sections, checked in this order, each short-circuiting. The order is
    the contract: a document with several faults reports the earliest one, and
    callers (and their tests) match on that message.
    """
    doc, error = _decode(raw)
    if error:
        return None, error
    header, error = _header(doc, name)
    if error:
        return None, error
    body, error = _document_body(doc)
    if error:
        return None, error
    header.update(body)
    return header, None


class WindowPresetService:
    """Facade for the portable document contract used by bridge and tests."""

    FORMAT = FORMAT
    SCHEMA_VERSION = SCHEMA_VERSION
    APP_VERSION = APP_VERSION
    GRID_TYPE = GRID_TYPE

    @classmethod
    def validate(cls, raw: Any, name: str | None = None):
        return validate_document(raw, name)

    @staticmethod
    def compatibility_note(document: dict) -> str:
        version = document.get("app_version", "unknown")
        if version == APP_VERSION:
            return ""
        return f"Created by app version {version}; current version is {APP_VERSION}."

    @staticmethod
    def resolution_note(document: dict, width: int, height: int) -> str:
        screen = document.get("screen", {})
        if screen.get("width") == width and screen.get("height") == height:
            return ""
        return (f"Source screen {screen.get('width')}×{screen.get('height')}; "
                f"current screen {width}×{height} is different. "
                "Percentage layout will adapt.")
