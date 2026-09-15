"""Portable window-preset document validation and compatibility metadata.

Validator DAG: _decode → _header → _grid → _states → _windows → _screen → validate_document
H-C4: predicates moved to `window_preset_predicates.py` (≤200), validators to `window_preset_validators.py` (≤300).
This file keeps facade WindowPresetService ≤300.

Design: ROUND_F_DESIGN §6, §12, §18.1; AREA_C H-C5.
"""

from __future__ import annotations

from typing import Any

from services.window_preset_predicates import GRID_TYPE
from services.window_preset_validators import (
    APP_VERSION,
    FORMAT,
    SCHEMA_VERSION,
    validate_document,
)


class WindowPresetService:
    FORMAT = FORMAT
    SCHEMA_VERSION = SCHEMA_VERSION
    APP_VERSION = APP_VERSION
    GRID_TYPE = GRID_TYPE

    @classmethod
    def validate(cls, raw: Any, name: str | None = None):
        return validate_document(raw, name)

    @staticmethod
    def compatibility_note(doc: dict) -> str:
        v = doc.get("app_version", "unknown")
        if v == APP_VERSION:
            return ""
        return f"Created by app version {v}; current version is {APP_VERSION}."

    @staticmethod
    def resolution_note(doc: dict, width: int, height: int) -> str:
        scr = doc.get("screen", {})
        if scr.get("width") == width and scr.get("height") == height:
            return ""
        return (
            f"Source screen {scr.get('width')}×{scr.get('height')}; "
            f"current screen {width}×{height} is different. Percentage layout will adapt."
        )
