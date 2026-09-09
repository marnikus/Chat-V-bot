"""Async SQLite history database — backward-compat shim over stores/.

The canonical implementation lives in :mod:`stores.history_db` (the
<150-LOC regroup split this module's constants block away and the copy
here could no longer be imported — BUG-02). Import from ``stores`` in
new code; this module re-exports the full public surface.
"""

from stores.history_db import (  # noqa: F401
    FTS_SCHEMA,
    LEGACY_MESSAGES_CONSTRAINT,
    SCHEMA,
    SCHEMA_VERSION,
    TABLE_COLUMNS,
    TABLE_CONSTRAINTS,
    TABLE_ORDER,
    HistoryDB,
)

__all__ = [
    "HistoryDB",
    "SCHEMA_VERSION",
    "TABLE_COLUMNS",
    "TABLE_CONSTRAINTS",
    "TABLE_ORDER",
    "LEGACY_MESSAGES_CONSTRAINT",
    "SCHEMA",
    "FTS_SCHEMA",
]
