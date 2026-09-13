"""History store sub-package.

This package contains the SQLite-based message archive storage layer.
All history-related stores live here; the top-level stores/ namespace
re-exports them for backward compatibility (see the shim modules in
stores/history_*.py).

Structure:
  - history_db.py: SQLite engine and connection management
  - history_models.py: Data model classes (MessageRecord, etc.)
  - history_repo.py: Main repository interface
  - history_repo_append.py: Append-only operations
  - history_repo_identity.py: Identity/key management
  - history_repo_lifecycle.py: Lifecycle operations
  - history_repo_media.py: Media attachment handling
  - history_schema.py: Database schema definitions
  - history_schema_repair.py: Schema repair/migration utilities
"""
