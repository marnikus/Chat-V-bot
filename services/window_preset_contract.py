"""The window-preset document contract: constants and leaf predicates.

The vocabulary every validator in the family shares — the four header
constants a document must carry, the bounds keys, and the four type
predicates (`_text`, `_number`, `_timestamp`, `_id_list`) the section
validators are built from. Nothing here knows the order the sections are
checked in; that precedence lives in `window_preset_service.validate_document`.

Split out by Round H step H-C5: the file this came from had MI 30.6 at 326
lines, and MI is a function of a file's Halstead volume, total cyclomatic
complexity and logical line count — renaming helpers *inside* one file moves
none of the three, so the only lever on MI is the module boundary.

Import direction: `services.layout_service` for the window id list; nothing
imports back.
"""

from __future__ import annotations

import math
from typing import Any

from services.layout_service import LayoutService

FORMAT = "chat-v-bot.window-preset"
SCHEMA_VERSION = 1
APP_VERSION = "0.1.0"
GRID_TYPE = "sash-tree"
_BOUNDS_KEYS = ("x", "y", "width", "height")

def _text(doc: dict, key: str) -> tuple[str | None, str | None]:
    value = doc.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip(), None
    return None, f"missing {key}"

def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)

def _timestamp(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback

def _id_list(value: Any, label: str) -> tuple[list[str] | None, str | None]:
    if not isinstance(value, list):
        return None, f"{label} must be a list"
    known = set(LayoutService.WINDOW_IDS)
    result = []
    for item in value:
        if not isinstance(item, str) or item not in known:
            return None, f"{label} contains an unknown window"
        if item in result:
            return None, f"{label} contains a duplicate window"
        result.append(item)
    return result, None
