"""`HistoryMutateService` — the write half of the history service.

Round H step H-C2 split this file's three operations into one module each;
this file is now only their composition, so `services/history/__init__.py`
(and the `__all__` it re-exports) keeps importing one name:

    mutate_settings.py  SettingsMutateMixin  app_settings + gaze_data writes
    mutate_import.py    LegacyImportMixin    legacy `users` queue, config labels
    mutate_world.py     WorldUndoMixin       the world's `undo_history` rows

The three mixins are deliberately *not* a facade: every method is a real body
in exactly one of them, and `HistoryService` inherits all fifteen through this
class, so no caller and no monkeypatch target changed.

Why three and not one file: at 294 lines this module had MI 34.9 — dense, not
long (RULE 19 step 3 is naming, and the naming here is the operation). The
three operations share no vocabulary: settings writes are key/value rows,
the legacy import is row coercion and a one-time archive, and the world
undo half is a single-transaction rewrite that retries on a locked file.
"""

from __future__ import annotations

from .mutate_import import LegacyImportMixin
from .mutate_settings import SettingsMutateMixin
from .mutate_world import WorldUndoMixin


class HistoryMutateService(SettingsMutateMixin, LegacyImportMixin,
                           WorldUndoMixin):
    """The write half of `HistoryService`: settings, legacy import, undo rows."""


__all__ = ["HistoryMutateService", "LegacyImportMixin", "SettingsMutateMixin",
           "WorldUndoMixin"]
