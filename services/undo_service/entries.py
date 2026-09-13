"""Timeline-entry identity — what makes two entries the same edit.

Three module-level helpers the undo machinery shares:

* `_values_equal` — JSON-first deep equality, falling back to `==` for values
  JSON cannot serialise. `bridge/router.py` imports it by name and publishes it
  on the wire class as both `_values_equal` and `_stacks_equal`.
* `_same_entry` — kind + value, deliberately ignoring `seq` and timestamps:
  comparing them made an identical re-push look different (the fresh entry has
  no seq yet) and grew the timeline with duplicates.
* `_position_of` — where an entry sits in a timeline, by identity first and by
  equality second, because `rewind_after_failure` is handed a copy rebuilt from
  the wire rather than the stored object.

Extracted unchanged from `services/undo_service.py` (god-class round, step 7);
the package `__init__` re-exports all three, so no import line changed. See
`docs/archive/2026-09-13-god-classes/STEP7_UNDO_SERVICE_DESIGN_2026-09-13.md`.
"""

from __future__ import annotations

import json


def _values_equal(a, b) -> bool:
    try:
        return json.dumps(a, sort_keys=True, ensure_ascii=False) == \
               json.dumps(b, sort_keys=True, ensure_ascii=False)
    except Exception:                                   # noqa: BLE001
        return a == b


def _same_entry(a: dict, b: dict) -> bool:
    """Two timeline entries carry the same edit (kind + value).

    ``seq``/timestamps are bookkeeping, not part of the edit identity:
    comparing them made an identical re-push look different (the fresh entry
    has no seq yet) and grew the timeline with duplicates.
    """
    return (isinstance(a, dict) and isinstance(b, dict)
            and a.get("kind") == b.get("kind")
            and _values_equal(a.get("value"), b.get("value")))


def _position_of(history: list, entry: dict) -> int:
    """Where this exact entry sits in the timeline (-1 when it is gone)."""
    for pos, item in enumerate(history):
        if item is entry:
            return pos
    for pos, item in enumerate(history):
        if _same_entry(item, entry):
            return pos
    return -1
