"""Compatibility shim — the SQLite engine lives in stores/history_db.py."""

from stores.history_db import (  # noqa: F401
    HistoryDB, SCHEMA_VERSION, TABLE_COLUMNS,
)

__all__ = ["HistoryDB", "SCHEMA_VERSION", "TABLE_COLUMNS"]
