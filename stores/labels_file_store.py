"""labels_file_store — the config/labels.json file.

Live person labels belong to the WORLD (they live in the active database
since the unified-DB redesign); this file is (a) the migration source for
pre-redesign installs and (b) the offline fallback the LabelStore uses
when no database is bound (unit tests, archive disabled). The shape is
the legacy config section: {defs, assign, filter, next_id}.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from stores.json_store import JsonFileStore

log = logging.getLogger("chatbot")

LABELS_DEFAULT: dict = {
    "defs": [],
    "assign": {},
    "filter": {"include": [], "exclude": []},
    "next_id": 0,
}


class LabelsFileStore(JsonFileStore):
    """One JSON file holding the legacy labels section shape."""

    DEFAULT_FILE = "config.json"
    DEFAULTS: dict[str, Any] = {}          # `_coerce` says what "empty" means

    def _coerce(self, raw: Any) -> dict[str, Any]:
        """A missing, corrupt or half-written file is the documented default.

        Anything else is kept verbatim: `LabelStore` normalises on read, so
        the file must not be quietly rewritten on the way in (a round-trip
        that "fixed" a value would make an undo restore lossy).
        """
        if not isinstance(raw, dict):
            return copy.deepcopy(LABELS_DEFAULT)
        if raw:
            return copy.deepcopy(raw)
        return copy.deepcopy(LABELS_DEFAULT)

    # ── reads ────────────────────────────────────────────────────
    def get(self, key: str, default: Any = None) -> Any:
        value = self._data.get(key, default)
        return copy.deepcopy(value) if isinstance(value, (dict, list)) \
            else value

    # ── writes ───────────────────────────────────────────────────
    def set_data(self, labels: Any) -> None:
        """Replace the whole section (dirty until `flush()`/`save()`)."""
        self._data = copy.deepcopy(labels) if isinstance(labels, dict) \
            else copy.deepcopy(LABELS_DEFAULT)
        self._touch()
