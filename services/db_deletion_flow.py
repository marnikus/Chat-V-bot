"""Fail-closed permanent-deletion pipeline, split out from ``DbLifecycle``.

The former ``DbLifecycle._delete_unlocked`` was a single 631-line method
(Radon CC 143). The read-only verification half (inventory, strict media
scans, footprint and plan) lives in ``services.db_deletion_scan``; this
module owns the mutating phases:

    validate → scan (deletion_scan) → switch → detach
             → database (revalidate) → unlinks (database group, then
             per-file media) → finalize

Contract (master plan §3.2): ``ok`` only when fully completed; ``phase`` in
validate/scan/switch/detach/database/media/finalize; ``partial`` True when
some irreversible work happened but not all; ``world_changed`` distinct
from partial; ``active_path`` observed (never guessed);
removed/retained/failed exact; ``media_files_removed`` counts actual
unlinks. The result dict shape is produced by
``services.db_deletion.DeletionOutcome`` and is pinned bit-for-bit by
``tests/integration/safety_deletion/``.

Control flow: phases call :func:`raise_refusal` to stop the pipeline with a
finished result dict (:class:`_PhaseRefusal`), caught once in
:func:`delete_world`. ``asyncio.CancelledError`` is a ``BaseException`` and
is never swallowed by that handler.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

from services.db_deletion_pre import (
    _detach, _revalidate, _switch, _validate,
)
from services.db_deletion_remove import (
    _cancel_reconcile, _finalize, _prune_dirs, _remove_database_group,
    _remove_media,
)
from services.db_deletion_state import (                      # noqa: F401
    _DeleteState, _Fail, _PhaseRefusal, abspath_or_none, lexists,
    observed_active, raise_refusal, same_canonical,
)

log = logging.getLogger("chatbot")


# ── shared outcome / path helpers (used by the scanner too) ────────


# ── orchestration ──────────────────────────────────────────────────

async def delete_world(lifecycle, path: str) -> dict:
    """Run every fail-closed phase; always returns a result dict."""
    st = _DeleteState(path=path, registry=lifecycle._registry)
    # function-local import keeps the flow ↔ scanner edge one-directional
    # (deletion_scan imports the shared helpers above at module load).
    from services.db_deletion_scan import run_scan
    try:
        _validate(lifecycle, st)
        await run_scan(st)
        await _switch(lifecycle, st)
        await _detach(lifecycle, st)
        await _revalidate(lifecycle, st)
        # ── irreversible boundary ────────────────────────────────
        try:
            _remove_database_group(st)
            parent_dirs = _remove_media(st)
            _prune_dirs(st, parent_dirs)
            return await _finalize(lifecycle, st)
        except asyncio.CancelledError:
            _cancel_reconcile(lifecycle, st)
            raise
    except _PhaseRefusal as refusal:
        return refusal.outcome


# ── phase 1: validate ───────────────────────────────────────────────


# ── phase 3: switch (only when the victim was active) ───────────────


# ── phase 4: detach lingering handles on the victim ─────────────────


# ── phase 5: revalidate (stale-plan guard, before any unlink) ───────


# ── phase 6a: database group (main-first, stop at first failure) ────


# ── phase 6b: media (per-file, never rmtree) ─────────────────────────


# ── phase 7: finalize (clean-break bookkeeping) ─────────────────────


