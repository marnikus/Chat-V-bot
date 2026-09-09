"""Compatibility shim — the archive service lives in services/history/."""

from services.history import (  # noqa: F401
    HistoryService, HISTORY_DEFAULTS, MAX_FILE_MB_DEFAULT, OLD_MAX_FILE_MB,
    _merge, _db_stem,
)

__all__ = ["HistoryService", "HISTORY_DEFAULTS", "MAX_FILE_MB_DEFAULT",
           "OLD_MAX_FILE_MB", "_merge", "_db_stem"]
