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

from stores.jsonio import load_json, save_json

log = logging.getLogger("chatbot")

LABELS_DEFAULT: dict = {
    "defs": [],
    "assign": {},
    "filter": {"include": [], "exclude": []},
    "next_id": 0,
}


class LabelsFileStore:
    """One JSON file holding the legacy labels section shape."""

    def __init__(self, path: Any | None = None):
        from stores.atomic import AtomicJsonStore as _AJS
        if isinstance(path, _AJS):
            self._path = path._path
        elif isinstance(path, str) and path:
            self._path = path
        else:
            self._path = "config.json" if not isinstance(path, str) else path
            if not self._path:
                self._path = "config.json"
        self._data: dict = copy.deepcopy(LABELS_DEFAULT)
        self._dirty = False
        self.reload()

    def save(self, force: bool = False) -> bool:
        """Alias of flush() for small-store API uniformity (B1)."""
        return self.flush()

    def reload(self) -> None:
        raw = load_json(self._path, default=None)
        self._data = raw if isinstance(raw, dict) else \
            copy.deepcopy(LABELS_DEFAULT)

    def flush(self) -> bool:
        if not self._dirty:
            return True
        ok = save_json(self._path, self._data)
        if ok:
            self._dirty = False
        return ok

    @property
    def dirty(self) -> bool:
        return self._dirty

    # ── API ──────────────────────────────────────────────────────
    def data(self) -> dict:
        return copy.deepcopy(self._data)

    def set_data(self, labels: dict) -> None:
        self._data = copy.deepcopy(labels) if isinstance(labels, dict) \
            else copy.deepcopy(LABELS_DEFAULT)
        self._dirty = True
