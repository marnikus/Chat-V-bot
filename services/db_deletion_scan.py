"""Read-only verification/planning half of the fail-closed delete pipeline.

Everything here runs **before any switch or unlink** and mutates no world
state: it enumerates the other worlds, strictly scans media references,
classifies the footprint and builds the `DeletionPlan` plus the snapshots
the executor revalidates against. Any unverifiable world or unplannable
target raises `_PhaseRefusal` (deletion refused, nothing touched).

The mutating phases live in `services.db_deletion_flow`, which calls
:func:`run_scan` as phase 2.
"""

from __future__ import annotations

import asyncio
import logging
import os

from services import db_deletion
from services.db_deletion_flow import (
    _Fail,
    _DeleteState,
    abspath_or_none,
    raise_refusal,
    same_canonical,
)
from services.db_media_scan import scan_world_media

log = logging.getLogger("chatbot")


async def run_scan(st: _DeleteState) -> None:
    """Populate st's plan fields; refuse (no mutation) on uncertainty."""
    inventory = _scan_inventory(st)
    victim_scan = await _scan_victim(st)
    st.keep = await _scan_other_worlds(st, inventory)
    st.footprint, st.outside_refs = _resolve_footprint(st, victim_scan)
    st.other_folders, st.folder_exclusive = _resolve_folder_policy(
        st, inventory)
    _build_plan(st, inventory)


# ── inventory ───────────────────────────────────────────────────────

def _scan_inventory(st: _DeleteState):
    """Other worlds must be enumerable; victim must be in the union."""
    try:
        inventory = db_deletion.build_deletion_inventory(
            registry=st.registry, victim_abs=st.target_abs)
    except Exception as exc:  # noqa: BLE001
        raise_refusal(
            st, "scan",
            f"cannot verify other worlds before deletion: {exc}")
    if not inventory.complete:
        detail = "; ".join(inventory.diagnostics) or "inventory incomplete"
        raise_refusal(
            st, "scan",
            f"cannot verify all worlds before deletion: {detail}")
    if not inventory.victim_in_scope:
        raise_refusal(
            st, "scan",
            "that database is not a supported registered world; "
            "refusing to delete an unverifiable target")
    return inventory


# ── strict media scans ──────────────────────────────────────────────

async def _scan_victim(st: _DeleteState):
    """Strict media scan of the world to delete (never best-effort)."""
    try:
        victim_scan = await scan_world_media(st.target_abs)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise_refusal(st, "scan",
                      f"cannot scan the database to delete: {exc}")
    if not victim_scan.complete:
        raise_refusal(
            st, "scan",
            f"cannot verify the database to delete "
            f"({victim_scan.detail or victim_scan.reason}); refusing",
            _Fail(extra={"unverifiable_worlds": [st.target_abs]}))
    return victim_scan


async def _scan_other_worlds(st: _DeleteState, inventory) -> set:
    """Scan every other world; any unverifiable one refuses deletion."""
    keep: set[str] = set()
    unverifiable: list[str] = []
    for world in inventory.worlds:
        try:
            res = await scan_world_media(world)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            unverifiable.append(str(world))
            log.debug("other-world scan failed for %s: %s", world, exc)
            continue
        if not res.complete:
            unverifiable.append(str(world))
        else:
            keep |= set(res.references or frozenset())
    if unverifiable:
        names = ", ".join(
            os.path.basename(str(w)) for w in unverifiable[:3])
        raise_refusal(
            st, "scan",
            f"cannot verify media references in "
            f"{names or 'another world'}; "
            "deletion refused to protect shared files",
            _Fail(extra={"unverifiable_worlds": unverifiable}))
    return keep


# ── footprint / folder policy ───────────────────────────────────────

def _resolve_footprint(st: _DeleteState, victim_scan):
    """Split victim refs into in-base footprint vs retained outside refs.

    The media base itself is never a removal candidate; it is reported
    as retained. Outside-root refs are retained by policy too.
    """
    try:
        st.base_abs = os.path.abspath(st.registry.media_base_dir())
        st.victim_folder_abs = os.path.abspath(
            st.registry.media_dir(st.target))
    except Exception as exc:  # noqa: BLE001
        raise_refusal(st, "scan", f"cannot resolve media folders: {exc}")
    footprint: set[str] = set()
    outside_refs: set[str] = set()
    for ref in (victim_scan.references or frozenset()):
        ap = abspath_or_none(ref)
        if ap is None:
            continue
        if same_canonical(ap, st.base_abs):
            # Never include the base itself; report it as retained.
            outside_refs.add(ap)
            continue
        if db_deletion.is_within(ap, st.base_abs):
            footprint.add(ap)
        else:
            outside_refs.add(ap)
    return footprint, outside_refs


def _resolve_folder_policy(st: _DeleteState, inventory):
    """Other-world media folders + victim-folder exclusivity."""
    other_folders: set[str] = set()
    for world in inventory.worlds:
        try:
            other_folders.add(os.path.abspath(
                st.registry.media_dir(world)))
        except Exception:  # noqa: BLE001
            continue
    exclusive = True
    try:
        victim_c = db_deletion.canonical(st.victim_folder_abs)
        for other in other_folders:
            if db_deletion.canonical(str(other)) == victim_c:
                exclusive = False
                break
    except Exception:  # noqa: BLE001
        exclusive = False
    try:
        if not db_deletion.is_within(
                st.victim_folder_abs, st.base_abs):
            exclusive = False
    except Exception:  # noqa: BLE001
        exclusive = False
    return other_folders, exclusive


# ── plan + snapshots ────────────────────────────────────────────────

def _discover_media_files(st: _DeleteState) -> set:
    """Walk the exclusive victim folder (no symlink dirs followed)."""
    if not st.folder_exclusive:
        return set()
    try:
        return db_deletion.collect_discovered_files(
            st.victim_folder_abs, st.base_abs)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise_refusal(
            st, "scan",
            f"cannot inventory the world's media folder: {exc}")


def _build_plan(st: _DeleteState, inventory) -> None:
    """Apply path policy and snapshot the plan for the stale-plan
    revalidation before any unlink."""
    discovered = _discover_media_files(st)
    try:
        plan = db_deletion.plan_deletion(
            victim_abs=st.target_abs,
            victim_folder_abs=st.victim_folder_abs,
            media_base_abs=st.base_abs,
            footprint_files=st.footprint,
            discovered_files=discovered,
            keep=st.keep,
            folder_exclusive=st.folder_exclusive,
            other_world_folders=st.other_folders,
            inventory=inventory)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise_refusal(st, "scan", f"cannot plan safe deletion: {exc}")
    st.plan = plan
    st.plan_retained = set(plan.retained or frozenset()) | st.outside_refs
    st.keep_snapshot = frozenset(
        os.path.abspath(str(p)) for p in (st.keep or set()))
    st.inventory_snapshot = tuple(sorted(
        db_deletion.canonical(str(p))
        for p in (inventory.worlds or [])))
