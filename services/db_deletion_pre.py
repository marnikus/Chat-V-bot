"""Deletion phases BEFORE the irreversible boundary -- all still reversible.

Split out of `services.db_deletion_flow` in round H (H2). The pipeline has a
hard boundary in it: everything in this module runs checks and detaches
handles, and any phase may still refuse and leave the world exactly as it
was. Once `db_deletion_remove` starts unlinking, that is no longer true.
Keeping the two sides in separate modules makes the boundary impossible to
cross by accident when editing.

    validate -> scan (db_deletion_scan) -> switch -> detach -> revalidate

Every phase here signals failure by calling `raise_refusal`, which raises
`_PhaseRefusal` and is caught once in `delete_world`. That raise must stay
OUTSIDE any broad `except Exception` -- a control-flow exception that
subclasses Exception is disarmed by an enclosing catch-all, which is how a
safety guard here was silently dead before round G found it.

Imports point one way: `db_deletion_flow` imports this; this imports the
shared primitives from `db_deletion_flow` at call time, never at module
load, so there is no cycle.
"""

from __future__ import annotations

import asyncio
import os

from services import db_deletion
from services.db_media_scan import scan_world_media
from services.db_deletion_state import _Fail, abspath_or_none, raise_refusal


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
async def _switch(lifecycle, st) -> None:
    if not (st.was_active and lifecycle._service is not None):
        return
    fallback = lifecycle._pick_fallback(st.target)
    if not fallback:
        raise_refusal(st, "switch", "no other database to switch to")
    opened = await _open_fallback(lifecycle, fallback)
    if not opened.get("ok"):
        raise_refusal(st, "switch",
                      str(opened.get("error", "cannot switch away")))
    st.world_changed = True
async def _open_fallback(lifecycle, fallback) -> dict:
    """Open `fallback`, reporting any failure as a result dict.

    A raised error and a returned `ok: False` mean the same thing to the
    caller -- the switch did not happen -- so both are normalised here and
    the caller is left with one refusal path. CancelledError is re-raised
    because a cancelled switch is not a failed switch.
    """
    try:
        return await lifecycle._load_unlocked(fallback) or {}
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc) or "cannot switch away"}
async def _detach(lifecycle, st) -> None:
    service = lifecycle._service
    if service is None:
        return
    await _detach_service_db(st, service)
    memory = getattr(service, "memory", None)
    if memory is not None:
        await _close_memory(st, memory)
async def _detach_service_db(st, service) -> None:
    try:
        svc_path = os.path.abspath(service.db.path)
    except Exception:  # noqa: BLE001
        svc_path = ""
    if svc_path and svc_path == st.target_abs:
        try:
            await service.detach_db()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise_refusal(st, "detach", str(exc))
        # Detaching changes live state → refresh required.
        st.world_changed = True
async def _close_memory(st, memory) -> None:
    try:
        mem_path = os.path.abspath(
            getattr(memory, "db_path", "") or "")
    except Exception:  # noqa: BLE001
        mem_path = ""
    if mem_path and mem_path == st.target_abs:
        try:
            await memory.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise_refusal(st, "detach", str(exc))
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
        dangerous = _dangerous_refs(new_sharing, st.plan.candidates)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        return          # cannot classify — treat as "nothing new", as before
    if dangerous:
        raise_refusal(
            st, "database",
            "media references changed during deletion; "
            "stale plan refused, retry")


def _dangerous_refs(new_sharing, candidates) -> set:
    """Of the newly-appeared references, those pointing at a file we are about
    to delete. A reference we cannot even resolve counts as dangerous —
    when in doubt about a deletion, refuse it.
    """
    cand_set = set(candidates or frozenset())
    cand_canon = {db_deletion.canonical(str(p)) for p in cand_set}
    dangerous = set()
    for new_ref in new_sharing:
        try:
            if (os.path.abspath(str(new_ref)) in cand_set
                    or db_deletion.canonical(str(new_ref)) in cand_canon):
                dangerous.add(new_ref)
        except Exception:  # noqa: BLE001
            dangerous.add(new_ref)
    return dangerous
