"""Compatibility shim — canonical history code lives in services/history/."""

from services.history import (  # noqa: F401
    HISTORY_DEFAULTS,
    MAX_FILE_MB_DEFAULT,
    OLD_MAX_FILE_MB,
    _db_stem,
    _merge,
)

__all__ = [
    "HistoryService", "HistoryQueryService", "HistoryMutateService",
    "HistoryExportService", "HISTORY_DEFAULTS", "MAX_FILE_MB_DEFAULT",
    "OLD_MAX_FILE_MB", "_merge", "_db_stem",
]


def __getattr__(name):
    if name in {"HistoryService", "HistoryQueryService",
                "HistoryMutateService", "HistoryExportService"}:
        from services.history import (
            HistoryExportService,
            HistoryMutateService,
            HistoryQueryService,
            HistoryService,
        )
        return {
            "HistoryService": HistoryService,
            "HistoryQueryService": HistoryQueryService,
            "HistoryMutateService": HistoryMutateService,
            "HistoryExportService": HistoryExportService,
        }[name]
    raise AttributeError(name)
