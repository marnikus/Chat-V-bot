"""Deletion phases AFTER the irreversible boundary -- unlinks and finalize.

Split out of `services.db_deletion_flow` in round H (H2). Everything in this
module destroys something. By the time the first function here runs, the
world has been validated, switched away from and detached; a failure now
cannot restore what is already gone, so these phases report `partial` rather
than refusing.

    remove database group -> remove media -> prune dirs -> finalize
                                                        -> reconcile

`_cancel_reconcile` exists because an asyncio cancellation during the
unlink loop leaves the registry describing files that no longer exist.
CancelledError is a BaseException and is deliberately NOT caught by the
pipeline's `_PhaseRefusal` handler; it is re-raised after reconciling.

Imports point one way: `db_deletion_flow` imports this; this imports the
shared primitives from `db_deletion_state`.
"""

from __future__ import annotations

import asyncio
import logging
import os

from services import db_deletion
from services.db_deletion import DB_GROUP_SUFFIXES, DeletionOutcome
from services.db_deletion_state import (
    _Fail, lexists, observed_active, raise_refusal,
)

log = logging.getLogger("chatbot")


def _remove_database_group(st) -> None:
    for suffix in DB_GROUP_SUFFIXES:
        path = st.target + suffix
        if not lexists(path):
            continue
        st.irreversible_started = True
        try:
            # Direct os.unlink (not unlink_one) for exact fault-injection
            # parity with the safety tests.
            os.unlink(path)
            st.removed.append(path)
        except asyncio.CancelledError:
            raise
        except FileNotFoundError:
            continue
        except OSError as exc:
            st.failed.append(path)
            # Preserve remaining group members + all media: stop here.
            raise_refusal(
                st, "database",
                f"the database file is in use: {exc}",
                _Fail(partial=True, media_count=0))


def _remove_media(st) -> set:
    parent_dirs: set[str] = set()
    for cand in sorted(st.plan.candidates or frozenset()):
        st.irreversible_started = True
        try:
            if os.path.islink(cand):
                # Belt-and-braces: policy already retained symlinks.
                st.plan_retained.add(cand)
                continue
            if not os.path.lexists(cand):
                continue
            os.unlink(cand)
            st.media_removed.append(cand)
            st.removed.append(cand)
            parent_dirs.add(os.path.dirname(cand))
        except asyncio.CancelledError:
            raise
        except FileNotFoundError:
            continue
        except OSError as exc:
            st.failed.append(cand)
            log.debug("cannot remove media file %s: %s", cand, exc)
    return parent_dirs


def _prune_dirs(st, parent_dirs) -> None:
    try:
        db_deletion.prune_empty_dirs(
            start_dirs=parent_dirs, base_abs=st.base_abs,
            other_world_folders=frozenset(st.other_folders))
        if st.folder_exclusive:
            _prune_victim_folder(st)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.debug("media prune failed: %s", exc)


def _prune_victim_folder(st) -> None:
    try:
        folder = st.victim_folder_abs
        if os.path.isdir(folder) and not os.path.islink(folder) \
                and db_deletion.is_within(folder, st.base_abs):
            try:
                if not os.listdir(folder):
                    os.rmdir(folder)
            except OSError as exc:
                log.debug("cannot prune victim folder %s: %s", folder, exc)
    except OSError:
        pass
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
