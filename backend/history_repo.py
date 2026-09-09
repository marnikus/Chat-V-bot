"""History repository — backward-compat shim over stores/.

Canonical implementation: :mod:`stores.history_repo` (see BUG-02 in
``docs/ACTIONS_TEST_DESIGN_2026-09-09.md`` §12). New code imports from
``stores``; this module re-exports the public surface.
"""

from stores.history_repo import HistoryRepo, align_batch, resolve_days  # noqa: F401

__all__ = ["HistoryRepo", "align_batch", "resolve_days"]
