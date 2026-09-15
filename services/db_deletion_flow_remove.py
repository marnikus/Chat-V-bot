"""Revalidation and irreversible removal phases of the flow (file 3).

Phase 5 re-checks the plan against the live inventory before any unlink;
phase 6a removes the database file group (main first, stop at the first
failure); phase 6b unlinks media files one by one and prunes the emptied
directories — never ``rmtree``. Verbatim moves out of
``services.db_deletion_flow`` (Round G3, RULE 18).
"""

from __future__ import annotations

import asyncio
import logging
import os

from services import db_deletion
from services.db_deletion import DB_GROUP_SUFFIXES
from services.db_deletion_flow_state import _Fail, lexists, raise_refusal
from services.db_media_scan import scan_world_media

log = logging.getLogger("chatbot")

# ── phase 5: revalidate (stale-plan guard, before any unlink) ───────

async def _revalidate(lifecycle, st) -> None:
    try:
        inventory = db_deletion.build_deletion_inventory(
            registry=st.registry, victim_abs=st.target_abs)
    except Exception as exc:  # noqa: BLE001
        raise_refusal(
            st, "database",
            f"cannot re-verify worlds before deletion: {exc}")
    if not inventory.complete:
        detail = "; ".join(inventory.diagnostics) or "re-scan incomplete"
        raise_refusal(
            st, "database",
            f"worlds changed during deletion ({detail}); retry")
    re_worlds = tuple(sorted(
        db_deletion.canonical(str(p))
        for p in (inventory.worlds or [])))
    if re_worlds != st.inventory_snapshot:
        raise_refusal(
            st, "database",
            "world inventory changed during deletion; "
            "stale plan refused, retry")
    re_keep = await _rescan_keep(st, inventory)
    _reject_new_sharing(st, re_keep)


async def _rescan_keep(st, inventory) -> frozenset:
    re_keep: set[str] = set()
    try:
        for world in inventory.worlds:
            try:
                res = await scan_world_media(world)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                raise_refusal(st, "database",
                              "cannot re-verify media references; retry")
            if not res.complete:
                raise_refusal(
                    st, "database",
                    f"cannot re-verify {os.path.basename(str(world))}; "
                    "stale plan refused, retry")
            re_keep |= set(res.references or frozenset())
    except asyncio.CancelledError:
        raise
    return frozenset(os.path.abspath(str(p)) for p in re_keep)


def _reject_new_sharing(st, re_keep_abs) -> None:
    """New references from other worlds onto our candidates refuse."""
    new_sharing = set(re_keep_abs) - set(st.keep_snapshot)
    try:
        cand_set = set(st.plan.candidates or frozenset())
        cand_canon = {
            db_deletion.canonical(str(p)) for p in cand_set}
        dangerous = set()
        for new_ref in new_sharing:
            try:
                if os.path.abspath(str(new_ref)) in cand_set or \
                        db_deletion.canonical(str(new_ref)) in cand_canon:
                    dangerous.add(new_ref)
            except Exception:  # noqa: BLE001
                dangerous.add(new_ref)
        if dangerous:
            raise_refusal(
                st, "database",
                "media references changed during deletion; "
                "stale plan refused, retry")
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        pass


# ── phase 6a: database group (main-first, stop at first failure) ────

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


# ── phase 6b: media (per-file, never rmtree) ─────────────────────────

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
