"""Header validation of a portable window-preset document (H-C5 split).

The first section of the chain: JSON decode, then `format` /
`schema_version` / `app_version` / `name` / the two timestamps. Its errors
are the ones a caller sees first, so the order inside `_header_error` and
`_header` is load-bearing and must not be reordered.

Import direction: `.window_preset_contract` for the constants and leaf
predicates; nothing else.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any

from .window_preset_contract import FORMAT, SCHEMA_VERSION, _text, _timestamp

def _decode(raw: Any) -> tuple[dict | None, str | None]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            return None, f"bad JSON ({exc.msg})"
    if not isinstance(raw, dict):
        return None, "document must be a JSON object"
    return copy.deepcopy(raw), None

def _header_error(doc: dict) -> str | None:
    if "format" not in doc:
        return "missing format"
    if doc.get("format") != FORMAT:
        return f"unsupported format {doc.get('format')!r}"
    if "schema_version" not in doc:
        return "missing schema_version"
    if doc.get("schema_version") != SCHEMA_VERSION:
        return f"unsupported schema version {doc.get('schema_version')!r}"
    return None

def _preset_name(doc: dict, name: str | None) -> tuple[str | None, str | None]:
    source = doc
    if name is not None:
        source = {"name": name}
    preset_name, error = _text(source, "name")
    if error:
        return None, error
    if len(preset_name) > 80:
        return None, "name is longer than 80 characters"
    return preset_name, None

def _header(doc: dict, name: str | None) -> tuple[dict | None, str | None]:
    error = _header_error(doc)
    if error:
        return None, error
    app, error = _text(doc, "app_version")
    if error:
        return None, error
    preset_name, error = _preset_name(doc, name)
    if error:
        return None, error
    now = datetime.now().isoformat(timespec="seconds")
    return {"format": FORMAT, "schema_version": SCHEMA_VERSION,
            "app_version": app, "name": preset_name,
            "created_at": _timestamp(doc.get("created_at"), now),
            "updated_at": _timestamp(doc.get("updated_at"), now)}, None
