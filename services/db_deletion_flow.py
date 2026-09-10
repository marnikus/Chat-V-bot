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

from services import db_deletion
from services.db_deletion import DB_GROUP_SUFFIXES, DeletionOutcome
from services.db_media_scan import scan_world_media

log = logging.getLogger("chatbot")


class _PhaseRefusal(Exception):
    """Internal signal: stop the pipeline and return ``outcome``."""

    def __init__(self, outcome: dict):
        super().__init__(outcome.get("error", ""))
        self.outcome = outcome


@dataclass
class _Fail:
    """Optional overrides for a failure outcome (a plain refusal needs none)."""

    partial: bool = False
    media_count: int | None = None
    extra: dict | None = None
    path: str | None = None
    before_path: str | None = None
    was_active: bool | None = None


@dataclass
class _DeleteState:
    """Mutable state carried through one deletion run."""

    path: str
    registry: object = None
    target: str = ""
    target_abs: str = ""
    was_active: bool = False
    world_changed: bool = False
    plan: object = None
    plan_retained: set = field(default_factory=set)
    base_abs: str = ""
    victim_folder_abs: str = ""
    folder_exclusive: bool = False
    other_folders: set = field(default_factory=set)
    keep: set = field(default_factory=set)
    footprint: set = field(default_factory=set)
    outside_refs: set = field(default_factory=set)
    keep_snapshot: frozenset = frozenset()
    inventory_snapshot: tuple = ()
    removed: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    media_removed: list = field(default_factory=list)
    irreversible_started: bool = False


# ── shared outcome / path helpers (used by the scanner too) ────────

def observed_active(registry) -> str:
    """Read the current active path defensively ('' if the registry raises)."""
    try:
        return registry.active_path()
    except Exception:  # noqa: BLE001
        return ""


def raise_refusal(st: _DeleteState, phase: str, error: str,
                  opt: _Fail | None = None) -> None:
    """Build the standard failure outcome for ``phase`` and stop the run."""
    opt = opt or _Fail()
    outcome = DeletionOutcome(
        ok=False, phase=phase, error=error, partial=opt.partial,
        world_changed=st.world_changed,
        active_path=observed_active(st.registry),
        removed_paths=list(st.removed),
        retained_paths=sorted(st.plan_retained),
        failed_paths=list(st.failed),
        media_files_removed=(len(st.media_removed)
                             if opt.media_count is None else opt.media_count),
        path=(st.target if opt.path is None else opt.path),
        before_path=(st.target if opt.before_path is None
                     else opt.before_path),
        was_active=(st.was_active if opt.was_active is None
                    else opt.was_active),
        extra=opt.extra or {})
    raise _PhaseRefusal(outcome.as_dict())


def lexists(path: str) -> bool:
    """os.path.lexists that treats a stat OSError as 'absent'."""
    try:
        return os.path.lexists(path)
    except OSError:
        return False


def abspath_or_none(value):
    """Abspath of ``value`` (stringified), or None on any failure."""
    try:
        return os.path.abspath(str(value))
    except Exception:  # noqa: BLE001
        return None


def same_canonical(a: str, b: str) -> bool:
    """Symlink-aware equality that never raises."""
    try:
        return db_deletion.canonical(a) == db_deletion.canonical(b)
    except Exception:  # noqa: BLE001
        return False


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


# ── phase 3: switch (only when the victim was active) ───────────────

async def _switch(lifecycle, st) -> None:
    if not (st.was_active and lifecycle._service is not None):
        return
    fallback = lifecycle._pick_fallback(st.target)
    if not fallback:
        raise_refusal(st, "switch", "no other database to switch to")
    try:
        opened = await lifecycle._load_unlocked(fallback)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise_refusal(st, "switch", str(exc) or "cannot switch away")
    if not (opened or {}).get("ok"):
        raise_refusal(
            st, "switch",
            str((opened or {}).get("error", "cannot switch away")))
    st.world_changed = True


# ── phase 4: detach lingering handles on the victim ─────────────────

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
