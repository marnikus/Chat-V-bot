"""Compatibility shim — the archive service lives in services/history/."""

from backend.legacy_shims import deprecated_module

deprecated_module("history_service", "services.history")

from services.history import (  # noqa: F401
    HistoryService, HISTORY_DEFAULTS, MAX_FILE_MB_DEFAULT, OLD_MAX_FILE_MB,
    _merge, _db_stem,
)

__all__ = ["HistoryService", "HISTORY_DEFAULTS", "MAX_FILE_MB_DEFAULT",
           "OLD_MAX_FILE_MB", "_merge", "_db_stem"]
