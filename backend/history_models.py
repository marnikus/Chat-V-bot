"""History records/fingerprints — backward-compat shim over stores/.

Canonical implementation: :mod:`stores.history_models` (see BUG-02 in
``docs/ACTIONS_TEST_DESIGN_2026-09-09.md`` §12). New code imports from
``stores``; this module re-exports the public surface.
"""

from stores.history_models import (  # noqa: F401
    MAX_LIVE_ITEMS,
    Alignment,
    AppendResult,
    MessageRecord,
    SyncResult,
    dedupe_key,
    fingerprint,
)

__all__ = [
    "MessageRecord",
    "SyncResult",
    "dedupe_key",
    "fingerprint",
    "Alignment",
    "AppendResult",
    "MAX_LIVE_ITEMS",
]
