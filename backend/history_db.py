"""Compatibility shim — the SQLite engine lives in stores/history_db.py."""

from backend.legacy_shims import deprecated_module

deprecated_module("history_db", "stores.history_db")

from stores.history_db import (  # noqa: F401
    HistoryDB, SCHEMA_VERSION, TABLE_COLUMNS,
)

__all__ = ["HistoryDB", "SCHEMA_VERSION", "TABLE_COLUMNS"]
