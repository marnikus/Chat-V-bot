"""Deletion plan / inventory / path policy / bounded helpers (AREA A).

No framework, no generic transaction abstraction, no new dependency.
Pure helpers are tested without a database; filesystem helpers are bounded
(single unlink / single rmdir, never rmtree).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger("chatbot")

#: SQLite file group members removed on delete. `SUFFIXES` in db_service
#: stays ("","-wal","-shm") for size/compat; deletion also best-effort
#: removes a rollback-journal sibling when present.
DB_GROUP_SUFFIXES = ("", "-wal", "-shm", "-journal")

SUPPORTED_BOUNDARY = (
    "active folder scan + active file + victim-directory scan + "
    "remembered in-root .db paths (deduped). Worlds outside this boundary "
    "are NOT scanned and NOT protected."
)


# ── canonical paths / containment ──────────────────────────────────

def canonical(path: str) -> str:
    """Canonical identity for comparison (symlink-aware)."""
    try:
        # realpath resolves symlinks/junctions; falls back to abspath.
        return os.path.realpath(os.path.abspath(str(path or "")))
    except Exception:  # noqa: BLE001
        try:
            return os.path.abspath(str(path or ""))
        except Exception:  # noqa: BLE001
            return str(path or "")


def is_within(child_abs: str, root_abs: str) -> bool:
    """True when `child` is strictly inside `root` (symlink-aware)."""
    try:
        child_c = canonical(child_abs)
        root_c = canonical(root_abs)
        if child_c == root_c:
            return False
        common = os.path.commonpath([root_c, child_c])
        return common == root_c
    except ValueError:  # different drives / mixed absolute
        return False
    except Exception:  # noqa: BLE001
        return False


def is_same_file(a: str, b: str) -> bool:
    try:
        return canonical(a) == canonical(b)
    except Exception:  # noqa: BLE001
        return os.path.abspath(str(a)) == os.path.abspath(str(b))


# ── inventory ──────────────────────────────────────────────────────

@dataclass
class DeletionInventory:
    worlds: list  # canonical abspaths, sorted, deduped (victim EXCLUDED for keep)
    complete: bool
    diagnostics: list = field(default_factory=list)
    victim_abs: str = ""
    victim_in_scope: bool = False
    all_worlds: list = field(default_factory=list)  # including victim


def _dedup(paths) -> list:
    seen: dict[str, str] = {}
    for p in paths or []:
        try:
            key = canonical(p)
        except Exception:  # noqa: BLE001
            key = os.path.abspath(str(p))
        # Keep the abspath form for display, dedup by canonical.
        absp = os.path.abspath(str(p))
        if key not in seen:
            seen[key] = absp
    return sorted(seen.values())


def _registry_active_dir(registry) -> str:
    """Directory of the active world; '' when the registry cannot say."""
    try:
        return os.path.dirname(
            os.path.abspath(registry.active_path())) or ""
    except Exception:  # noqa: BLE001
        return ""


def _registry_root(registry) -> str:
    """In-root containment base from the registry's host; '' on failure."""
    try:
        # DbRegistry host has .root; be defensive.
        host = getattr(registry, "_host", None)
        return os.path.abspath(getattr(host, "root", "") or "")
    except Exception:  # noqa: BLE001
        return ""


def _append_db_files(collected: list, folder: str) -> OSError | None:
    """Append existing `*.db` regular files from `folder` (no recursion).

    Per-file stat errors are skipped; a directory listing failure is
    returned so the caller can mark the inventory incomplete.
    """
    try:
        names = sorted(os.listdir(folder))
    except OSError as exc:
        return exc
    for name in names:
        if not name.lower().endswith(".db"):
            continue
        path = os.path.join(folder, name)
        try:
            if os.path.isfile(path):
                collected.append(path)
        except OSError:
            continue
    return None


def _known_db_in_root(point, root: str):
    """Abspath of a remembered in-root `*.db`, else None (skip)."""
    if not isinstance(point, str) or not point:
        return None
    if not point.lower().endswith(".db"):
        return None
    try:
        ap = os.path.abspath(point)
    except Exception:  # noqa: BLE001
        return None
    if root:
        try:
            common = os.path.commonpath([root, ap])
            if common != root or ap == root:
                return None
        except ValueError:
            return None
    return ap


@dataclass
class _InventoryCollector:
    """Accumulates the supported world sources for one victim query."""

    registry: object
    victim_abs: str
    collected: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)
    complete: bool = True

    def fail(self, message: str) -> None:
        self.complete = False
        self.diagnostics.append(message)

    def add_active_folder(self) -> None:
        # 1 — active folder + active file
        try:
            self.collected.extend(list(self.registry.existing_worlds() or []))
        except Exception as exc:  # noqa: BLE001
            self.fail(f"active folder scan failed: {exc}")

    def add_active_path(self) -> None:
        # Belt-and-braces (existing_worlds includes it, but be explicit).
        try:
            active = self.registry.active_path()
            if active and os.path.exists(active):
                self.collected.append(active)
        except Exception as exc:  # noqa: BLE001
            self.fail(f"active path read failed: {exc}")

    def add_victim_directory(self) -> None:
        # 2 — victim-directory scan when it differs from the active dir.
        try:
            victim_dir = os.path.dirname(self.victim_abs) or ""
            active_dir = _registry_active_dir(self.registry)
            if victim_dir and os.path.isdir(victim_dir) and \
                    os.path.abspath(victim_dir) != os.path.abspath(active_dir):
                list_error = _append_db_files(self.collected, victim_dir)
                if list_error is not None:
                    self.fail(
                        f"victim directory scan failed: {list_error}")
        except OSError as exc:
            self.fail(f"victim directory scan failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"victim directory handling failed: {exc}")

    def add_remembered(self) -> None:
        # 3 — remembered in-root *.db paths.
        try:
            self._append_remembered()
        except Exception as exc:  # noqa: BLE001
            self.fail(f"remembered-paths scan failed: {exc}")

    def _append_remembered(self) -> None:
        known = list(self.registry.known_paths() or [])
        root = _registry_root(self.registry)
        for point in known:
            ap = _known_db_in_root(point, root)
            if ap is None:
                continue
            try:
                if os.path.exists(ap):
                    self.collected.append(ap)
            except OSError:
                continue

    def add_victim(self) -> None:
        # The victim itself, when present, for the scope check.
        try:
            if self.victim_abs and os.path.exists(self.victim_abs):
                self.collected.append(self.victim_abs)
        except OSError:
            pass

    def build(self) -> DeletionInventory:
        deduped = _dedup(self.collected)
        victim_c = canonical(self.victim_abs) if self.victim_abs else ""
        in_scope = any(
            canonical(p) == victim_c for p in deduped) if victim_c else False
        worlds = [p for p in deduped if canonical(p) != victim_c]
        return DeletionInventory(
            worlds=worlds, complete=self.complete,
            diagnostics=self.diagnostics,
            victim_abs=self.victim_abs, victim_in_scope=in_scope,
            all_worlds=deduped)


def build_deletion_inventory(*, registry, victim_abs: str) -> DeletionInventory:
    """Collect every supported existing world for the safety scan.

    Sources: active-folder scan + active file (via existing_worlds),
    victim-directory *.db scan, remembered in-root *.db paths, active path.
    Any source failure → complete=False (refuse, not empty inventory).
    """
    victim_abs = os.path.abspath(str(victim_abs or ""))
    collector = _InventoryCollector(
        registry=registry, victim_abs=victim_abs)
    collector.add_active_folder()
    collector.add_active_path()
    collector.add_victim_directory()
    collector.add_remembered()
    collector.add_victim()
    return collector.build()


# ── plan ───────────────────────────────────────────────────────────

@dataclass
class DeletionPlan:
    victim_abs: str
    victim_folder_abs: str
    media_base_abs: str
    footprint_files: frozenset
    discovered_files: frozenset
    keep: frozenset
    candidates: frozenset  # to remove (after policy)
    retained: frozenset    # safety exclusions (after policy)
    folder_exclusive: bool
    inventory: DeletionInventory
    other_world_folders: frozenset = frozenset()


def _prune_symlink_dirs(root: str, dirnames: list) -> None:
    """Remove symlinked subdirectories in-place so os.walk never descends.

    A stat failure is treated as 'do not descend' (same fail-closed
    posture as the link check itself).
    """
    for dirname in list(dirnames):
        full = os.path.join(root, dirname)
        try:
            if os.path.islink(full):
                dirnames.remove(dirname)
        except OSError:
            dirnames.remove(dirname)
            continue


def _add_regular_files(root: str, filenames, out: set) -> None:
    """Add regular (non-symlink) files under `root` to `out`."""
    for name in filenames:
        full = os.path.join(root, name)
        try:
            # Never include symlinks (retained by policy), and only
            # regular files (skip dirs/fifos/sockets).
            if os.path.islink(full):
                continue
            if not os.path.isfile(full):
                continue
            out.add(os.path.abspath(full))
        except OSError:
            continue


def collect_discovered_files(victim_folder_abs: str,
                             base_abs: str) -> set[str]:
    """Walk the victim folder for eligible files (no symlink dirs).

    Returns abspaths of regular files only. Symlinks are never followed and
    never returned (they are retained by policy). Raises OSError on walk
    failure so the caller treats the plan as incomplete.
    """
    out: set[str] = set()
    folder = os.path.abspath(str(victim_folder_abs or ""))
    if not folder or not os.path.isdir(folder):
        return out
    # Never walk outside base or the base itself as victim folder.
    if not is_within(folder, os.path.abspath(str(base_abs or ""))):
        return out
    for root, dirnames, filenames in os.walk(folder, topdown=True,
                                             followlinks=False):
        _prune_symlink_dirs(root, dirnames)
        _add_regular_files(root, filenames, out)
    return out


# ── candidate policy: one named predicate per retain reason ────────

def _symlink_reason(candidate_abs: str) -> str | None:
    """Symlinks are never unlinked (never followed)."""
    try:
        if os.path.islink(candidate_abs):
            return "retain:symlink"
    except OSError:
        return "retain:symlink"
    return None


def _outside_root_reason(cand: str, base: str) -> str | None:
    """Outside the media root (or the root itself) is retained."""
    if is_within(cand, base):
        return None
    try:
        if canonical(cand) == canonical(base):
            return "retain:root"
    except Exception:  # noqa: BLE001
        pass
    return "retain:outside_root"


def _exact_root_reason(cand: str, base: str) -> str | None:
    """Defensive re-check: the media root itself is never a candidate."""
    try:
        if canonical(cand) == canonical(base):
            return "retain:root"
    except Exception:  # noqa: BLE001
        pass
    return None


def _other_folder_reason(cand: str, other_folders) -> str | None:
    """Another world's media folder (or anything inside it) is retained."""
    try:
        cand_c = canonical(cand)
        for other in (other_folders or frozenset()):
            try:
                other_c = canonical(other)
            except Exception:  # noqa: BLE001
                continue
            if cand_c == other_c:
                return "retain:other_world_folder"
            try:
                if os.path.commonpath([other_c, cand_c]) == other_c:
                    return "retain:other_world_folder"
            except ValueError:
                continue
    except Exception:  # noqa: BLE001
        pass
    return None


def _shared_reference_reason(cand: str, keep) -> str | None:
    """A file another world references is shared and retained."""
    try:
        cand_c = canonical(cand)
        for ref in (keep or frozenset()):
            try:
                if os.path.abspath(str(ref)) == cand or \
                        canonical(str(ref)) == cand_c:
                    return "retain:shared"
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return None


def _ambiguous_folder_reason(is_discovered: bool,
                             folder_exclusive: bool) -> str | None:
    """Walked file from a shared-stem (non-exclusive) folder is retained."""
    if is_discovered and not folder_exclusive:
        return "retain:ambiguous_folder"
    return None


def _non_file_reason(cand: str) -> str | None:
    """Only regular files are removed (missing is an idempotent no-op)."""
    try:
        if os.path.isfile(cand):
            return None
        if not os.path.lexists(cand):
            return "retain:missing"
        return "retain:not_file"
    except OSError:
        return "retain:not_file"


def classify_candidate(*, candidate_abs: str, base_abs: str,
                       victim_folder_abs: str, folder_exclusive: bool,
                       keep: frozenset, other_world_folders: frozenset,
                       is_discovered: bool) -> str:
    """Policy verdict for one candidate: 'remove' or 'retain:<reason>'.

    The predicate order is the safety ladder; do not reorder without a
    design doc (symlink → outside root → root → other folder → shared →
    ambiguous folder → file type).
    """
    cand = os.path.abspath(str(candidate_abs or ""))
    base = os.path.abspath(str(base_abs or ""))
    for reason in (
            _symlink_reason(candidate_abs),
            _outside_root_reason(cand, base),
            _exact_root_reason(cand, base),
            _other_folder_reason(cand, other_world_folders),
            _shared_reference_reason(cand, keep),
            _ambiguous_folder_reason(is_discovered, folder_exclusive),
            _non_file_reason(cand)):
        if reason:
            return reason
    return "remove"


@dataclass(frozen=True)
class _PathPolicy:
    """Immutable policy inputs shared by both classified file groups."""

    base: str
    vfolder: str
    exclusive: bool
    keep: frozenset
    others: frozenset

    def verdict(self, ap: str, is_discovered: bool) -> str:
        return classify_candidate(
            candidate_abs=ap, base_abs=self.base,
            victim_folder_abs=self.vfolder,
            folder_exclusive=self.exclusive,
            keep=self.keep, other_world_folders=self.others,
            is_discovered=is_discovered)


@dataclass
class _PolicyBuckets:
    candidates: set = field(default_factory=set)
    retained: set = field(default_factory=set)

    def sort(self, ap: str, verdict: str) -> None:
        if verdict == "remove":
            self.candidates.add(ap)
        else:
            self.retained.add(ap)


def _frozen_abspaths(group) -> frozenset:
    """Frozen abspath set (tolerates None / non-iterable input)."""
    return frozenset(os.path.abspath(str(p)) for p in (group or set()))


def _classify_file_group(group, is_discovered: bool,
                         policy: _PathPolicy, buckets: _PolicyBuckets) -> None:
    """Classify one group (footprint or discovered) into the buckets."""
    for point in (group or set()):
        ap = os.path.abspath(str(point))
        if ap in buckets.candidates or ap in buckets.retained:
            # A dup across groups is classified exactly once.
            continue
        buckets.sort(ap, policy.verdict(ap, is_discovered))


def plan_deletion(*, victim_abs: str, victim_folder_abs: str,
                  media_base_abs: str, footprint_files: set[str],
                  discovered_files: set[str], keep: set[str],
                  folder_exclusive: bool,
                  other_world_folders: set[str],
                  inventory) -> DeletionPlan:
    """Combine footprint + discovered − keep through the path policy."""
    base = os.path.abspath(str(media_base_abs or ""))
    vfolder = os.path.abspath(str(victim_folder_abs or ""))
    policy = _PathPolicy(
        base=base, vfolder=vfolder, exclusive=bool(folder_exclusive),
        keep=_frozen_abspaths(keep),
        others=_frozen_abspaths(other_world_folders))
    buckets = _PolicyBuckets()
    _classify_file_group(footprint_files, False, policy, buckets)
    _classify_file_group(discovered_files, True, policy, buckets)
    return DeletionPlan(
        victim_abs=os.path.abspath(str(victim_abs or "")),
        victim_folder_abs=vfolder, media_base_abs=base,
        footprint_files=_frozen_abspaths(footprint_files),
        discovered_files=_frozen_abspaths(discovered_files),
        keep=policy.keep, candidates=frozenset(buckets.candidates),
        retained=frozenset(buckets.retained),
        folder_exclusive=bool(folder_exclusive),
        inventory=inventory, other_world_folders=policy.others)


# ── bounded filesystem helpers ─────────────────────────────────────

def unlink_one(path: str) -> tuple[bool, str]:
    """Unlink one file; missing is success (idempotent). Never follows dirs.

    Returns (ok, error). Symlinks are never unlinked here (retained by
    policy); callers must have classified first. As a belt-and-braces guard,
    refuse to unlink a symlink or a directory.
    """
    try:
        # Never unlink symlinks or dirs via this helper.
        try:
            if os.path.islink(path):
                return False, "refused: symlink"
            if os.path.isdir(path) and not os.path.isfile(path):
                return False, "refused: not a file"
        except OSError as exc:
            return False, str(exc)
        if not os.path.lexists(path):
            return True, ""
        os.unlink(path)
        return True, ""
    except FileNotFoundError:
        return True, ""
    except OSError as exc:
        return False, str(exc)


def _prune_roots(base_abs: str, other_world_folders):
    """Canonical guard roots: (base abspath, canonical base, canonical others)."""
    base = os.path.abspath(str(base_abs or ""))
    try:
        base_c = canonical(base)
    except Exception:  # noqa: BLE001
        base_c = base
    other_c: set[str] = set()
    for other in (other_world_folders or frozenset()):
        try:
            other_c.add(canonical(other))
        except Exception:  # noqa: BLE001
            continue
    return base, base_c, other_c


def _prune_blocked(folder_c: str, folder: str, guard) -> bool:
    """True when verified-empty upward pruning must stop at `folder`."""
    base, base_c, other_c = guard
    if folder_c == base_c:
        return True
    if not is_within(folder, base):
        return True
    if folder_c in other_c:
        # Never prune another world's folder.
        return True
    try:
        if not os.path.isdir(folder) or os.path.islink(folder):
            return True
        if os.listdir(folder):
            return True
    except OSError:
        return True
    return False


def _prune_one_start(start, guard, seen: set, removed: list) -> None:
    """Walk upward from one parent dir while it stays removable."""
    folder = os.path.abspath(str(start or ""))
    while folder and folder not in seen:
        seen.add(folder)
        try:
            folder_c = canonical(folder)
        except Exception:  # noqa: BLE001
            break
        if _prune_blocked(folder_c, folder, guard):
            break
        try:
            os.rmdir(folder)
            removed.append(folder)
        except OSError as exc:
            log.debug("cannot prune %s: %s", folder, exc)
            break
        folder = os.path.dirname(folder)


def prune_empty_dirs(*, start_dirs, base_abs: str,
                     other_world_folders: frozenset) -> list[str]:
    """Rmdir verified-empty dirs strictly inside base (never base/others).

    `start_dirs` are parent dirs of removed files. Walks upward while empty.
    Never rmtree. Returns removed dir paths.
    """
    guard = _prune_roots(base_abs, other_world_folders)
    seen: set[str] = set()
    removed: list[str] = []
    for start in (start_dirs or []):
        _prune_one_start(start, guard, seen, removed)
    return removed


# ── outcome ────────────────────────────────────────────────────────

def _as_list(value) -> list:
    """List copy of an outcome field (None-safe; outcomes default to lists)."""
    return list(value or [])


@dataclass
class DeletionOutcome:
    ok: bool
    phase: str  # validate | scan | switch | detach | database | media | finalize
    error: str = ""
    partial: bool = False
    world_changed: bool = False
    active_path: str = ""
    removed_paths: list = field(default_factory=list)
    retained_paths: list = field(default_factory=list)
    failed_paths: list = field(default_factory=list)
    media_files_removed: int = 0
    # compat
    op: str = "delete"
    path: str = ""
    was_active: bool = False
    before_path: str = ""
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {
            "ok": bool(self.ok),
            "op": self.op or "delete",
            "path": self.path,
            "was_active": bool(self.was_active),
            "before_path": self.before_path or self.path,
            "media_files_removed": int(self.media_files_removed or 0),
            "phase": self.phase,
            "partial": bool(self.partial),
            "world_changed": bool(self.world_changed),
            "active_path": self.active_path,
            "removed_paths": _as_list(self.removed_paths),
            "retained_paths": _as_list(self.retained_paths),
            "failed_paths": _as_list(self.failed_paths),
        }
        if self.error:
            d["error"] = self.error
        # Preserve last_database flag and diagnostics when present.
        if self.extra:
            for k, v in self.extra.items():
                if k not in d:
                    d[k] = v
        return d
