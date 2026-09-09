"""Know/like user memory — backward-compat shim over stores/.

Canonical implementation: :mod:`stores.user_memory` (see BUG-02 in
``docs/ACTIONS_TEST_DESIGN_2026-09-09.md`` §12). New code imports from
``stores``; this module re-exports the public surface (including the
private `_SCHEMA`, which `tests/test_db_migration.py` imports).
"""

from stores.user_memory import _SCHEMA, UserMemory, UserRecord  # noqa: F401

__all__ = ["UserMemory", "UserRecord", "_SCHEMA"]
