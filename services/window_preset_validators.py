"""Window preset validators — facade (H-C5 split)

Document validation DAG, now ≤150 LOC via header/grid/windows parts.
"""

from __future__ import annotations

from typing import Any

from services.window_preset_validators_grid import _grid, _screen
from services.window_preset_validators_header import FORMAT, SCHEMA_VERSION, _decode, _header
from services.window_preset_validators_windows import _states, _windows

APP_VERSION = "0.1.0"


def _document_body(doc: dict) -> tuple[dict | None, str | None]:
    g, err = _grid(doc)
    if err:
        return None, err
    st, err = _states(doc)
    if err:
        return None, err
    wins, err = _windows(doc, st)
    if err:
        return None, err
    scr, err = _screen(doc)
    if err:
        return None, err
    return {"grid": g, "windows": wins, "window_states": st, "screen": scr}, None


def validate_document(raw: Any, name: str | None = None) -> tuple[dict | None, str | None]:
    doc, err = _decode(raw)
    if err:
        return None, err
    hdr, err = _header(doc, name)
    if err:
        return None, err
    body, err = _document_body(doc)
    if err:
        return None, err
    hdr.update(body)
    return hdr, None


__all__ = ["validate_document", "FORMAT", "SCHEMA_VERSION", "APP_VERSION"]
