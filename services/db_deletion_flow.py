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

Family map (Round G3, RULE 18): this seam owns the orchestration
(:func:`delete_world`), validate, finalize and reconcile, and re-exports
the shared helpers ``services.db_deletion_scan`` imports. The state
vocabulary lives in :mod:`services.db_deletion_flow_state`, switch/detach
in :mod:`services.db_deletion_flow_detach`, revalidation and removal in
:mod:`services.db_deletion_flow_remove`. One-way imports: seam → siblings,
detach/remove → state; every function moved verbatim.
"""

from __future__ import annotations

import asyncio
import logging
import os

from services.db_deletion import DeletionOutcome
from services.db_deletion_flow_detach import _detach, _switch
from services.db_deletion_flow_remove import (
    _prune_dirs, _revalidate, _remove_database_group, _remove_media)
from services.db_deletion_flow_state import (
    _DeleteState, _Fail, _PhaseRefusal, abspath_or_none, observed_active,
    raise_refusal)
# Same re-export discipline as the db_deletion.py shim's _append_db_files:
# db_deletion_scan imports the shared helpers through this seam; the
# orchestrator itself never calls same_canonical.
from services.db_deletion_flow_state import (  # noqa: F401  # pylint: disable=unused-import
    same_canonical)

log = logging.getLogger("chatbot")

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

def _validate(lifecycle, st) -> None:
    registry = st.registry
    target = registry.resolve(st.path)
    if not target or not os.path.exists(target):
        shown = str(target or st.path or "")
        raise_refusal(st, "validate", "that database does not exist",
                      _Fail(path=shown, before_path=shown, was_active=False))
    st.target = target
    st.target_abs = os.path.abspath(target)
    if len(_existing_abspaths(registry)) < 2:
        raise_refusal(
            st, "validate",
            "cannot delete the last database — create a new one first",
            _Fail(extra={"last_database": True}))
    try:
        st.was_active = (
            st.target_abs == os.path.abspath(registry.active_path()))
    except Exception:  # noqa: BLE001
        st.was_active = False


def _existing_abspaths(registry) -> list:
    try:
        worlds = list(registry.existing_worlds() or [])
    except Exception:  # noqa: BLE001
        worlds = []
    out = []
    for point in worlds:
        ap = abspath_or_none(point)
        if ap is not None:
            out.append(ap)
    return out


# ── phase 7: finalize (clean-break bookkeeping) ─────────────────────

async def _finalize(lifecycle, st) -> dict:
    if st.failed:
        # Media partial: DB gone, some media failed (never returns).
        await _finalize_media_partial(lifecycle, st)
    try:
        await _reconcile(lifecycle, st)
    except Exception as exc:  # noqa: BLE001
        raise_refusal(
            st, "finalize",
            f"deletion completed but final bookkeeping failed: {exc}",
            _Fail(partial=True))
    return _success_outcome(st)


async def _finalize_media_partial(lifecycle, st) -> None:
    """Reconcile, then report the media-phase partial result."""
    try:
        await _reconcile(lifecycle, st)
    except Exception as exc:  # noqa: BLE001
        raise_refusal(
            st, "finalize",
            f"media cleanup incomplete and finalization failed: {exc}",
            _Fail(partial=True))
    raise_refusal(
        st, "media",
        "some media files could not be removed; "
        "database deleted, media partially cleaned",
        _Fail(partial=True))


def _success_outcome(st) -> dict:
    return DeletionOutcome(
        ok=True, phase="finalize", error="", partial=False,
        world_changed=st.world_changed,
        active_path=observed_active(st.registry),
        removed_paths=list(st.removed),
        retained_paths=sorted(st.plan_retained),
        failed_paths=[],
        media_files_removed=len(st.media_removed),
        path=st.target, before_path=st.target,
        was_active=st.was_active).as_dict()


async def _reconcile(lifecycle, st) -> None:
    """Forget the victim and persist the replacement active path."""
    try:
        lifecycle._forget(st.target)
    except Exception as exc:  # noqa: BLE001
        log.warning("delete reconcile (forget) failed: %s", exc)
        raise
    try:
        if st.was_active:
            lifecycle._persist_path(st.registry.active_path())
    except Exception as exc:  # noqa: BLE001
        log.warning("delete reconcile (persist) failed: %s", exc)
        raise


def _cancel_reconcile(lifecycle, st) -> None:
    """Best-effort bookkeeping after cancellation post-unlink; never
    raises (the CancelledError must propagate)."""
    if not st.irreversible_started:
        return
    try:
        try:
            lifecycle._forget(st.target)
        except Exception:  # noqa: BLE001
            pass
        try:
            if st.was_active:
                lifecycle._persist_path(st.registry.active_path())
        except Exception:  # noqa: BLE001
            pass
        log.warning(
            "delete of %s cancelled after partial work: "
            "removed=%s failed=%s media_removed=%d",
            os.path.basename(st.target), st.removed, st.failed,
            len(st.media_removed))
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        pass
