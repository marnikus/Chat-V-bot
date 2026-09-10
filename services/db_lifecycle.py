"""DbLifecycle — the write half of `services.db_service.DbManager` (AREA C).

Owns every MUTATION of the world databases: create, load, delete, clean
and restore_backup, together with the media-reference scans and the
clean-break bookkeeping those operations need. The registry reads (paths,
remembered list, scans, info) live in `services.db_registry.DbRegistry`;
this collaborator calls them through its host.

Every rule from the ONE DB = ONE WORLD design is preserved verbatim
(permanent delete, last-world protection, fail-closed switching, clean
with a trash backup).

AREA A (2026-09-10): deletion is fail-closed and serialized. Scans happen
before any switch/unlink; any incomplete scan refuses; per-file keep is never
bypassed by rmtree; partial work is reported truthfully; overlapping lifecycle
ops serialize via per-manager + root-global locks with unlocked delegates.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import datetime

from services.db_service import SUFFIXES, db_stem

log = logging.getLogger("chatbot")

# Root-keyed global locks for cross-manager serialization (same process).
_GLOBAL_LOCKS: dict[str, asyncio.Lock] = {}


class DbLifecycle:
    """Create / load / delete / clean / restore world database files."""

    def __init__(self, host):
        self._host = host
        self._op_lock: asyncio.Lock | None = None

    # ── convenience over the host ────────────────────────────────
    @property
    def _registry(self):
        return self._host.registry

    @property
    def _service(self):
        return self._host._service

    @property
    def _config(self):
        return self._host._config

    # ── serialization ────────────────────────────────────────────
    def _get_locks(self):
        """(global_root_lock, local_manager_lock), created lazily."""
        try:
            root = os.path.abspath(getattr(self._host, "root", "") or os.getcwd())
        except Exception:  # noqa: BLE001
            root = os.getcwd()
        g = _GLOBAL_LOCKS.get(root)
        if g is None:
            g = asyncio.Lock()
            _GLOBAL_LOCKS[root] = g
        if self._op_lock is None:
            self._op_lock = asyncio.Lock()
        return g, self._op_lock

    async def _guarded(self, coro_fn, *args, **kwargs):
        """Run one lifecycle op under global+local locks (fixed order)."""
        g, l = self._get_locks()
        async with g:
            async with l:
                return await coro_fn(*args, **kwargs)

    # ── lifecycle (public, serialized) ───────────────────────────
    async def create(self, name: str) -> dict:
        """Create an EMPTY world (the full schema) and connect to it.

        The fresh world is seeded with the app-template settings (D9) —
        nothing is copied from the world being left.
        """
        return await self._guarded(self._create_unlocked, name)

    async def load(self, path: str, create: bool = False) -> dict:
        """Switch the running world over to another database file."""
        return await self._guarded(self._load_unlocked, path, create)

    async def delete(self, path: str) -> dict:
        """PERMANENTLY delete a world (file + media + every reference).

        Fail-closed phases: validate → scan → switch → detach → database →
        media → finalize. See _delete_unlocked for the full contract.
        """
        return await self._guarded(self._delete_unlocked, path)

    async def clean(self) -> dict:
        """Empty every table, keeping the file (a backup goes to the trash)."""
        return await self._guarded(self._clean_unlocked)

    async def restore_backup(self, backup: str, target: str = "") -> dict:
        """Put a trashed/backed-up file back (the undo half of clean)."""
        return await self._guarded(self._restore_unlocked, backup, target)

    # ── unlocked delegates (internal; delete calls _load_unlocked) ─
    async def _create_unlocked(self, name: str) -> dict:
        path = self._registry.resolve(name)
        if not path:
            if str(name or "").strip():
                return {"ok": False,
                        "error": "the database must stay inside the app folder"}
            return {"ok": False, "error": "give the database a name"}
        if os.path.exists(path):
            return {"ok": False, "error": f"{os.path.basename(path)} already exists"}
        before = self._registry.active_path()
        folder = os.path.dirname(os.path.abspath(path))
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        result = await self._load_unlocked(path, create=True)
        if result.get("ok"):
            result["op"] = "create"
            result["before_path"] = before
            if self._service is not None:
                try:
                    await self._service.seed_app_settings()
                except Exception as exc:               # noqa: BLE001
                    log.warning("could not seed settings into %s: %s",
                                os.path.basename(path), exc)
        return result

    async def _load_unlocked(self, path: str, create: bool = False) -> dict:
        target = self._registry.resolve(path)
        if not target:
            return {"ok": False, "error": "no database selected"}
        if not create and not os.path.exists(target):
            return {"ok": False, "error": f"{target} does not exist"}
        before = self._registry.active_path()
        if os.path.abspath(target) == os.path.abspath(before) and not create:
            return {"ok": True, "op": "load", "path": target,
                    "before_path": before, "unchanged": True}
        if self._service is None:
            self._persist_path(target)
            self._registry._remember(target)
            return {"ok": True, "op": "load", "path": target,
                    "before_path": before, "offline": True}
        try:
            await self._service.switch_db(target)
        except Exception as exc:                       # noqa: BLE001
            log.warning("switching to %s failed: %s", target, exc)
            return {"ok": False, "error": str(exc), "path": target}
        self._persist_path(target)
        self._registry._remember(target)
        return {"ok": True, "op": "load", "path": target, "before_path": before}

    async def _delete_unlocked(self, path: str) -> dict:
        """Fail-closed permanent deletion with truthful partial results.

        Contract (master plan §3.2): ok only when fully completed; phase in
        validate/scan/switch/detach/database/media/finalize; partial True when
        some irreversible work happened but not all; world_changed distinct
        from partial; active_path observed; removed/retained/failed exact;
        media_files_removed counts actual unlinks.
        """
        from services.db_deletion import (
            DB_GROUP_SUFFIXES, DeletionOutcome, build_deletion_inventory,
            canonical, collect_discovered_files, is_within, plan_deletion,
            prune_empty_dirs, unlink_one,
        )
        from services.db_media_scan import scan_world_media

        def _observed_active() -> str:
            try:
                return self._registry.active_path()
            except Exception:  # noqa: BLE001
                return ""

        # ── validate ───────────────────────────────────────────
        target = self._registry.resolve(path)
        if not target or not os.path.exists(target):
            out = DeletionOutcome(
                ok=False, phase="validate",
                error="that database does not exist",
                partial=False, world_changed=False,
                active_path=_observed_active(),
                path=str(target or path or ""), before_path=str(target or path or ""),
                was_active=False)
            return out.as_dict()
        target_abs = os.path.abspath(target)
        try:
            existing_list = list(self._registry.existing_worlds() or [])
        except Exception:  # noqa: BLE001
            existing_list = []
        existing_abs = []
        for p in existing_list:
            try:
                existing_abs.append(os.path.abspath(p))
            except Exception:  # noqa: BLE001
                continue
        if len(existing_abs) < 2:
            out = DeletionOutcome(
                ok=False, phase="validate",
                error="cannot delete the last database — create a new one first",
                partial=False, world_changed=False,
                active_path=_observed_active(),
                path=target, before_path=target, was_active=False,
                extra={"last_database": True})
            return out.as_dict()
        try:
            was_active = target_abs == os.path.abspath(
                self._registry.active_path())
        except Exception:  # noqa: BLE001
            was_active = False

        # ── scan/plan BEFORE any switch/unlink ───────────────────
        try:
            inventory = build_deletion_inventory(
                registry=self._registry, victim_abs=target_abs)
        except Exception as exc:  # noqa: BLE001
            out = DeletionOutcome(
                ok=False, phase="scan",
                error=f"cannot verify other worlds before deletion: {exc}",
                partial=False, world_changed=False,
                active_path=_observed_active(),
                path=target, before_path=target, was_active=was_active)
            return out.as_dict()
        if not inventory.complete:
            detail = "; ".join(inventory.diagnostics) or "inventory incomplete"
            out = DeletionOutcome(
                ok=False, phase="scan",
                error=f"cannot verify all worlds before deletion: {detail}",
                partial=False, world_changed=False,
                active_path=_observed_active(),
                path=target, before_path=target, was_active=was_active)
            return out.as_dict()
        if not inventory.victim_in_scope:
            out = DeletionOutcome(
                ok=False, phase="scan",
                error="that database is not a supported registered world; "
                      "refusing to delete an unverifiable target",
                partial=False, world_changed=False,
                active_path=_observed_active(),
                path=target, before_path=target, was_active=was_active)
            return out.as_dict()
        # Victim scan (footprint source)
        try:
            victim_scan = await scan_world_media(target_abs)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            out = DeletionOutcome(
                ok=False, phase="scan",
                error=f"cannot scan the database to delete: {exc}",
                partial=False, world_changed=False,
                active_path=_observed_active(),
                path=target, before_path=target, was_active=was_active)
            return out.as_dict()
        if not victim_scan.complete:
            out = DeletionOutcome(
                ok=False, phase="scan",
                error=f"cannot verify the database to delete "
                      f"({victim_scan.detail or victim_scan.reason}); refusing",
                partial=False, world_changed=False,
                active_path=_observed_active(),
                path=target, before_path=target, was_active=was_active,
                extra={"unverifiable_worlds": [target_abs]})
            return out.as_dict()
        # Other-world scans (keep source)
        keep: set[str] = set()
        unverifiable: list[str] = []
        scan_details = []
        try:
            for world in inventory.worlds:
                try:
                    res = await scan_world_media(world)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    unverifiable.append(str(world))
                    scan_details.append(f"{world}: {exc}")
                    continue
                scan_details.append(res)
                if not res.complete:
                    unverifiable.append(str(world))
                else:
                    keep |= set(res.references or frozenset())
        except asyncio.CancelledError:
            raise
        if unverifiable:
            names = ", ".join(os.path.basename(str(w)) for w in unverifiable[:3])
            out = DeletionOutcome(
                ok=False, phase="scan",
                error=f"cannot verify media references in {names or 'another world'}; "
                      "deletion refused to protect shared files",
                partial=False, world_changed=False,
                active_path=_observed_active(),
                path=target, before_path=target, was_active=was_active,
                extra={"unverifiable_worlds": unverifiable})
            return out.as_dict()

        # Footprint: victim refs strictly inside media base (never root itself)
        try:
            base_abs = os.path.abspath(self._registry.media_base_dir())
            victim_folder_abs = os.path.abspath(
                self._registry.media_dir(target))
        except Exception as exc:  # noqa: BLE001
            out = DeletionOutcome(
                ok=False, phase="scan",
                error=f"cannot resolve media folders: {exc}",
                partial=False, world_changed=False,
                active_path=_observed_active(),
                path=target, before_path=target, was_active=was_active)
            return out.as_dict()
        footprint: set[str] = set()
        for ref in (victim_scan.references or frozenset()):
            try:
                ap = os.path.abspath(str(ref))
            except Exception:  # noqa: BLE001
                continue
            # Never include the base itself; only strictly-inside files.
            try:
                if canonical(ap) == canonical(base_abs):
                    continue
            except Exception:  # noqa: BLE001
                pass
            if is_within(ap, base_abs):
                footprint.add(ap)
            # Outside-root refs are retained by policy later (recorded).
            # To report them as retained, keep them in a separate set.
        # Outside-root victim refs (for retained reporting)
        outside_refs: set[str] = set()
        for ref in (victim_scan.references or frozenset()):
            try:
                ap = os.path.abspath(str(ref))
            except Exception:  # noqa: BLE001
                continue
            try:
                if canonical(ap) == canonical(base_abs):
                    outside_refs.add(ap)
                    continue
            except Exception:  # noqa: BLE001
                pass
            if not is_within(ap, base_abs):
                outside_refs.add(ap)

        # Other-world folders for policy (same-stem detection)
        other_folders: set[str] = set()
        try:
            for w in inventory.worlds:
                try:
                    other_folders.add(os.path.abspath(
                        self._registry.media_dir(w)))
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
        # Folder exclusivity: False when another world shares the same folder
        folder_exclusive = True
        try:
            vf_c = canonical(victim_folder_abs)
            for o in other_folders:
                if canonical(str(o)) == vf_c:
                    folder_exclusive = False
                    break
        except Exception:  # noqa: BLE001
            folder_exclusive = False
        # Victim folder must itself be strictly inside base to be exclusive.
        try:
            if not is_within(victim_folder_abs, base_abs):
                folder_exclusive = False
        except Exception:  # noqa: BLE001
            folder_exclusive = False

        # Discovered files (walk exclusive folder only)
        discovered: set[str] = set()
        if folder_exclusive:
            try:
                discovered = collect_discovered_files(
                    victim_folder_abs, base_abs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                out = DeletionOutcome(
                    ok=False, phase="scan",
                    error=f"cannot inventory the world's media folder: {exc}",
                    partial=False, world_changed=False,
                    active_path=_observed_active(),
                    path=target, before_path=target, was_active=was_active)
                return out.as_dict()

        try:
            plan = plan_deletion(
                victim_abs=target_abs,
                victim_folder_abs=victim_folder_abs,
                media_base_abs=base_abs,
                footprint_files=footprint,
                discovered_files=discovered,
                keep=keep,
                folder_exclusive=folder_exclusive,
                other_world_folders=other_folders,
                inventory=inventory)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            out = DeletionOutcome(
                ok=False, phase="scan",
                error=f"cannot plan safe deletion: {exc}",
                partial=False, world_changed=False,
                active_path=_observed_active(),
                path=target, before_path=target, was_active=was_active)
            return out.as_dict()
        # Merge outside-root refs into retained for truthful reporting
        plan_retained = set(plan.retained or frozenset()) | outside_refs

        # Snapshot for revalidation (TOCTOU guard)
        plan_keep_snapshot = frozenset(
            os.path.abspath(str(p)) for p in (keep or set()))
        plan_inventory_snapshot = tuple(sorted(
            canonical(str(p)) for p in (inventory.worlds or [])))

        # ── switch (only when victim was active) ─────────────────
        world_changed = False
        if was_active and self._service is not None:
            fallback = self._pick_fallback(target)
            if not fallback:
                out = DeletionOutcome(
                    ok=False, phase="switch",
                    error="no other database to switch to",
                    partial=False, world_changed=False,
                    active_path=_observed_active(),
                    path=target, before_path=target, was_active=was_active)
                return out.as_dict()
            try:
                opened = await self._load_unlocked(fallback)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                out = DeletionOutcome(
                    ok=False, phase="switch",
                    error=str(exc) or "cannot switch away",
                    partial=False, world_changed=False,
                    active_path=_observed_active(),
                    path=target, before_path=target, was_active=was_active)
                return out.as_dict()
            if not (opened or {}).get("ok"):
                out = DeletionOutcome(
                    ok=False, phase="switch",
                    error=str((opened or {}).get("error", "cannot switch away")),
                    partial=False, world_changed=False,
                    active_path=_observed_active(),
                    path=target, before_path=target, was_active=was_active)
                return out.as_dict()
            world_changed = True

        # ── detach any lingering handle on victim ───────────────
        if self._service is not None:
            try:
                svc_path = os.path.abspath(self._service.db.path)
            except Exception:  # noqa: BLE001
                svc_path = ""
            if svc_path and svc_path == target_abs:
                try:
                    await self._service.detach_db()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    out = DeletionOutcome(
                        ok=False, phase="detach",
                        error=str(exc),
                        partial=False, world_changed=world_changed,
                        active_path=_observed_active(),
                        path=target, before_path=target, was_active=was_active)
                    return out.as_dict()
                # Detaching changes live state → refresh required
                world_changed = True
        if self._service is not None and \
                getattr(self._service, "memory", None) is not None:
            try:
                mem_path = os.path.abspath(
                    getattr(self._service.memory, "db_path", "") or "")
            except Exception:  # noqa: BLE001
                mem_path = ""
            if mem_path and mem_path == target_abs:
                try:
                    await self._service.memory.close()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    out = DeletionOutcome(
                        ok=False, phase="detach",
                        error=str(exc),
                        partial=False, world_changed=world_changed,
                        active_path=_observed_active(),
                        path=target, before_path=target, was_active=was_active)
                    return out.as_dict()

        # ── revalidate (stale-plan guard, before any unlink) ─────
        try:
            re_inventory = build_deletion_inventory(
                registry=self._registry, victim_abs=target_abs)
        except Exception as exc:  # noqa: BLE001
            out = DeletionOutcome(
                ok=False, phase="database",
                error=f"cannot re-verify worlds before deletion: {exc}",
                partial=False, world_changed=world_changed,
                active_path=_observed_active(),
                path=target, before_path=target, was_active=was_active)
            return out.as_dict()
        if not re_inventory.complete:
            detail = "; ".join(re_inventory.diagnostics) or "re-scan incomplete"
            out = DeletionOutcome(
                ok=False, phase="database",
                error=f"worlds changed during deletion ({detail}); retry",
                partial=False, world_changed=world_changed,
                active_path=_observed_active(),
                path=target, before_path=target, was_active=was_active)
            return out.as_dict()
        re_worlds = tuple(sorted(
            canonical(str(p)) for p in (re_inventory.worlds or [])))
        if re_worlds != plan_inventory_snapshot:
            out = DeletionOutcome(
                ok=False, phase="database",
                error="world inventory changed during deletion; "
                      "stale plan refused, retry",
                partial=False, world_changed=world_changed,
                active_path=_observed_active(),
                path=target, before_path=target, was_active=was_active)
            return out.as_dict()
        # Re-scan keep; grown keep invalidates.
        try:
            re_keep: set[str] = set()
            for world in re_inventory.worlds:
                try:
                    res = await scan_world_media(world)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    out = DeletionOutcome(
                        ok=False, phase="database",
                        error="cannot re-verify media references; retry",
                        partial=False, world_changed=world_changed,
                        active_path=_observed_active(),
                        path=target, before_path=target, was_active=was_active)
                    return out.as_dict()
                if not res.complete:
                    out = DeletionOutcome(
                        ok=False, phase="database",
                        error=f"cannot re-verify {os.path.basename(str(world))}; "
                              "stale plan refused, retry",
                        partial=False, world_changed=world_changed,
                        active_path=_observed_active(),
                        path=target, before_path=target, was_active=was_active)
                    return out.as_dict()
                re_keep |= set(res.references or frozenset())
        except asyncio.CancelledError:
            raise
        re_keep_abs = frozenset(os.path.abspath(str(p)) for p in re_keep)
        # If keep grew (new shared refs), refuse; if shrank, use original
        # (safer: original keep is a superset for protection).
        if not plan_keep_snapshot.issuperset(
                frozenset(a for a in re_keep_abs if a in plan_keep_snapshot or True)):
            pass  # placeholder (explicit below)
        # Explicit: any re_keep not in plan_keep → new sharing → refuse.
        new_sharing = set(re_keep_abs) - set(plan_keep_snapshot)
        # Only new sharing that intersects our candidates matters; other new
        # refs elsewhere don't affect this victim. Check intersection.
        try:
            cand_set = set(plan.candidates or frozenset())
            # Compare by abspath and canonical
            cand_canon = {canonical(str(p)) for p in cand_set}
            dangerous = set()
            for n in new_sharing:
                try:
                    if os.path.abspath(str(n)) in cand_set or \
                            canonical(str(n)) in cand_canon:
                        dangerous.add(n)
                except Exception:  # noqa: BLE001
                    dangerous.add(n)
            if dangerous:
                out = DeletionOutcome(
                    ok=False, phase="database",
                    error="media references changed during deletion; "
                          "stale plan refused, retry",
                    partial=False, world_changed=world_changed,
                    active_path=_observed_active(),
                    path=target, before_path=target, was_active=was_active)
                return out.as_dict()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            pass

        # ── irreversible boundary ────────────────────────────────
        removed: list[str] = []
        failed: list[str] = []
        media_removed: list[str] = []
        irreversible_started = False

        async def _reconcile_after_work():
            try:
                self._forget(target)
            except Exception as exc:  # noqa: BLE001
                log.warning("delete reconcile (forget) failed: %s", exc)
                raise
            try:
                if was_active:
                    self._persist_path(self._registry.active_path())
            except Exception as exc:  # noqa: BLE001
                log.warning("delete reconcile (persist) failed: %s", exc)
                raise

        try:
            # ── database group (main-first, stop at first failure) ─
            for suffix in DB_GROUP_SUFFIXES:
                p = target + suffix
                try:
                    exists = os.path.lexists(p)
                except OSError:
                    exists = False
                if not exists:
                    continue
                irreversible_started = True
                try:
                    # Direct unlink to honor fault-injection on os.unlink;
                    # unlink_one would swallow CancelledError as OSError?
                    # No — CancelledError is BaseException, not OSError.
                    # Use os.unlink directly for exact parity with tests.
                    os.unlink(p)
                    removed.append(p)
                except asyncio.CancelledError:
                    raise
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    failed.append(p)
                    # Preserve remaining group members + all media.
                    try:
                        # Reconcile what we can, but report partial.
                        # Do NOT proceed to media cleanup.
                        pass
                    finally:
                        pass
                    out = DeletionOutcome(
                        ok=False, phase="database",
                        error=f"the database file is in use: {exc}",
                        partial=True, world_changed=world_changed,
                        active_path=_observed_active(),
                        removed_paths=list(removed),
                        retained_paths=sorted(plan_retained),
                        failed_paths=list(failed),
                        media_files_removed=0,
                        path=target, before_path=target,
                        was_active=was_active)
                    return out.as_dict()
            # ── media (per-file, never rmtree) ───────────────────
            parent_dirs: set[str] = set()
            for cand in sorted(plan.candidates or frozenset()):
                irreversible_started = True
                try:
                    if os.path.islink(cand):
                        # Belt-and-braces: policy already retained symlinks.
                        plan_retained.add(cand)
                        continue
                    if not os.path.lexists(cand):
                        continue
                    os.unlink(cand)
                    media_removed.append(cand)
                    removed.append(cand)
                    try:
                        parent_dirs.add(os.path.dirname(cand))
                    except Exception:  # noqa: BLE001
                        pass
                except asyncio.CancelledError:
                    raise
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    failed.append(cand)
                    log.debug("cannot remove media file %s: %s", cand, exc)
                    continue
            # Prune verified-empty dirs (bounded, never base/others)
            try:
                prune_empty_dirs(
                    start_dirs=parent_dirs, base_abs=base_abs,
                    other_world_folders=frozenset(other_folders))
                # Prune the exclusive victim folder itself when empty
                if folder_exclusive:
                    try:
                        if os.path.isdir(victim_folder_abs) and \
                                not os.path.islink(victim_folder_abs) and \
                                is_within(victim_folder_abs, base_abs):
                            try:
                                if not os.listdir(victim_folder_abs):
                                    os.rmdir(victim_folder_abs)
                            except OSError as exc:
                                log.debug("cannot prune victim folder %s: %s",
                                          victim_folder_abs, exc)
                    except OSError:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.debug("media prune failed: %s", exc)
            if failed:
                # Media partial: DB gone, some media failed.
                try:
                    await _reconcile_after_work()
                except Exception as exc:  # noqa: BLE001
                    out = DeletionOutcome(
                        ok=False, phase="finalize",
                        error=f"media cleanup incomplete and finalization failed: {exc}",
                        partial=True, world_changed=world_changed,
                        active_path=_observed_active(),
                        removed_paths=list(removed),
                        retained_paths=sorted(plan_retained),
                        failed_paths=list(failed),
                        media_files_removed=len(media_removed),
                        path=target, before_path=target,
                        was_active=was_active)
                    return out.as_dict()
                # Report media phase (failed media), even though DB + reconcile ok
                # Collect failed parent? No, keep phase=media.
                # Need truthful error mentioning media.
                out = DeletionOutcome(
                    ok=False, phase="media",
                    error="some media files could not be removed; "
                          "database deleted, media partially cleaned",
                    partial=True, world_changed=world_changed,
                    active_path=_observed_active(),
                    removed_paths=list(removed),
                    retained_paths=sorted(plan_retained),
                    failed_paths=list(failed),
                    media_files_removed=len(media_removed),
                    path=target, before_path=target,
                    was_active=was_active)
                return out.as_dict()
            # ── finalize ───────────────────────────────────────
            try:
                await _reconcile_after_work()
            except Exception as exc:  # noqa: BLE001
                out = DeletionOutcome(
                    ok=False, phase="finalize",
                    error=f"deletion completed but final bookkeeping failed: {exc}",
                    partial=True, world_changed=world_changed,
                    active_path=_observed_active(),
                    removed_paths=list(removed),
                    retained_paths=sorted(plan_retained),
                    failed_paths=list(failed),
                    media_files_removed=len(media_removed),
                    path=target, before_path=target,
                    was_active=was_active)
                return out.as_dict()
            out = DeletionOutcome(
                ok=True, phase="finalize",
                error="", partial=False, world_changed=world_changed,
                active_path=_observed_active(),
                removed_paths=list(removed),
                retained_paths=sorted(plan_retained),
                failed_paths=[],
                media_files_removed=len(media_removed),
                path=target, before_path=target, was_active=was_active)
            return out.as_dict()
        except asyncio.CancelledError:
            if irreversible_started:
                try:
                    # Best-effort reconcile, then propagate.
                    try:
                        self._forget(target)
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        if was_active:
                            self._persist_path(
                                self._registry.active_path())
                    except Exception:  # noqa: BLE001
                        pass
                    log.warning(
                        "delete of %s cancelled after partial work: "
                        "removed=%s failed=%s media_removed=%d",
                        os.path.basename(target), removed, failed,
                        len(media_removed))
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    pass
            raise


    def _forget(self, path: str) -> None:
        """Clean break: no reference to the deleted file survives."""
        self._registry._prune_remembered()
        if self._config is None:
            return
        stored = self._config.get("history", "db_path", default="")
        if isinstance(stored, str) and \
                os.path.abspath(stored) == os.path.abspath(path):
            replacement = self._registry.active_path()
            if replacement and os.path.exists(replacement) and \
                    os.path.abspath(replacement) != os.path.abspath(path):
                history = self._config.get("history", default={}) or {}
                if not isinstance(history, dict):
                    history = {}
                history = dict(history)
                history["db_path"] = replacement
                self._config.set("history", history)
                self._config.save()

    async def _clean_unlocked(self) -> dict:
        """Empty every table, keeping the file (a backup goes to the trash)."""
        path = self._registry.active_path()
        if self._service is None:
            return {"ok": False, "error": "the message archive is not running"}
        backup = self._copy_to_trash(path, tag="clean")
        db = self._service.db
        removed = {}
        try:
            for table in ("messages", "media", "cursors", "gaps", "persons",
                          "users"):
                removed[table] = int(await db.scalar(
                    f"SELECT COUNT(*) FROM {table}", (), 0))
                await db.execute(f"DELETE FROM {table}")
            await db.execute("DELETE FROM sqlite_sequence")
            if db.fts_enabled:
                try:
                    await db.execute(
                        "INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
                except Exception:                      # noqa: BLE001
                    pass
            await db.commit()
            await db.execute("VACUUM")
            await db.commit()
        except Exception as exc:                       # noqa: BLE001
            log.warning("clean failed: %s", exc)
            return {"ok": False, "error": str(exc), "backup": backup}
        media_moved = ""
        world_folder = os.path.abspath(self._registry.media_dir(path))
        base = os.path.abspath(self._registry.media_base_dir())
        if world_folder.startswith(base + os.sep) and world_folder != base \
                and os.path.isdir(world_folder):
            try:
                media_moved = os.path.join(
                    self._registry.trash_dir(),
                    self._stamp("clean_media", db_stem(path)))
                shutil.move(world_folder, media_moved)
            except OSError as exc:
                log.warning("cannot move world media to trash: %s", exc)
        return {"ok": True, "op": "clean", "path": path, "backup": backup,
                "removed": removed, "before_path": path,
                "media_moved": media_moved}

    async def _restore_unlocked(self, backup: str, target: str = "") -> dict:
        """Put a trashed/backed-up file back (the undo half of clean)."""
        source = str(backup or "")
        if not source or not os.path.exists(source):
            return {"ok": False, "error": "the backup is gone"}
        destination = self._registry.resolve(target) \
            or self._registry.active_path()
        active = (os.path.abspath(destination) ==
                  os.path.abspath(self._registry.active_path()))
        if active and self._service is not None:
            try:
                await self._service.detach_db()
            except Exception as exc:                   # noqa: BLE001
                return {"ok": False, "error": str(exc)}
        try:
            os.makedirs(os.path.dirname(os.path.abspath(destination)) or ".",
                        exist_ok=True)
            for suffix in SUFFIXES:
                if not os.path.exists(source + suffix):
                    continue
                shutil.copyfile(source + suffix, destination + suffix)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        if self._service is not None:
            await self._service.switch_db(destination)
        self._persist_path(destination)
        self._registry._remember(destination)
        return {"ok": True, "path": destination, "backup": source}

    # ── helpers ──────────────────────────────────────────────────
    def _persist_path(self, path: str) -> None:
        if self._config is None:
            return
        history = self._config.get("history", default={}) or {}
        if not isinstance(history, dict):
            history = {}
        history = dict(history)
        history["db_path"] = path
        self._config.set("history", history)
        self._config.save()

    def _pick_fallback(self, deleted: str) -> str:
        """Which database to open after the active one is deleted."""
        for item in self._registry.list_dbs():
            if (os.path.abspath(item["path"]) != os.path.abspath(deleted)
                    and item.get("exists")):
                return item["path"]
        return ""

    def _stamp(self, tag: str, name: str) -> str:
        return (f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{tag}_{name}")

    def _copy_to_trash(self, path: str, tag: str = "backup") -> str:
        trash = self._registry.trash_dir()
        try:
            os.makedirs(trash, exist_ok=True)
            target = os.path.join(trash,
                                  self._stamp(tag, os.path.basename(path)))
            for suffix in SUFFIXES:
                if os.path.exists(path + suffix):
                    shutil.copyfile(path + suffix, target + suffix)
            return target
        except OSError as exc:
            log.warning("cannot back up %s: %s", path, exc)
            return ""
