"""Window preset validators — header part (H-C5 split)

Header decoding and validation, ≤150 LOC.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any

from services.window_preset_predicates import _is_obj, _is_text

FORMAT = "chat-v-bot.window-preset"
SCHEMA_VERSION = 1


def _decode(raw: Any) -> tuple[dict | None, str | None]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            return None, f"bad JSON ({exc.msg})"
    if not _is_obj(raw):
        return None, "document must be a JSON object"
    return copy.deepcopy(raw), None


def _text(doc: dict, key: str) -> tuple[str | None, str | None]:
    v = doc.get(key)
    if _is_text(v):
        return v.strip(), None
    return None, f"missing {key}"


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
    src = doc if name is None else {"name": name}
    n, err = _text(src, "name")
    if err:
        return None, err
    if len(n) > 80:
        return None, "name is longer than 80 characters"
    return n, None


def _timestamp(v: Any, fb: str) -> str:
    return v if isinstance(v, str) and v else fb


def _header(doc: dict, name: str | None) -> tuple[dict | None, str | None]:
    err = _header_error(doc)
    if err:
        return None, err
    app, err = _text(doc, "app_version")
    if err:
        return None, err
    pname, err = _preset_name(doc, name)
    if err:
        return None, err
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "app_version": app,
        "name": pname,
        "created_at": _timestamp(doc.get("created_at"), now),
        "updated_at": _timestamp(doc.get("updated_at"), now),
    }, None
