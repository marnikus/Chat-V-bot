"""Compatibility shim — the database lifecycle lives in services/db_service.py."""

from backend.legacy_shims import deprecated_module

deprecated_module("db_manager", "services.db_service")

from services.db_service import (  # noqa: F401
    DbManager, TRASH_DIR, SUFFIXES, safe_db_name, db_stem, folder_size,
    file_group_size,
)

__all__ = ["DbManager", "TRASH_DIR", "SUFFIXES", "safe_db_name", "db_stem",
           "folder_size", "file_group_size"]
