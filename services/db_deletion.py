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


def build_deletion_inventory(*, registry, victim_abs: str) -> DeletionInventory:
    """Collect every supported existing world for the safety scan.

    Sources: active-folder scan + active file (via existing_worlds),
    victim-directory *.db scan, remembered in-root *.db paths, active path.
    Any source failure → complete=False (refuse, not empty inventory).
    """
    victim_abs = os.path.abspath(str(victim_abs or ""))
    diagnostics: list[str] = []
    complete = True
    collected: list[str] = []

    # 1 — active folder + active file
    try:
        existing = list(registry.existing_worlds() or [])
        collected.extend(existing)
    except Exception as exc:  # noqa: BLE001
        complete = False
        diagnostics.append(f"active folder scan failed: {exc}")

    # Active path when it exists (belt-and-braces; existing_worlds includes it
    # but be explicit for the inventory contract).
    try:
        active = registry.active_path()
        if active and os.path.exists(active):
            collected.append(active)
    except Exception as exc:  # noqa: BLE001
        complete = False
        diagnostics.append(f"active path read failed: {exc}")

    # 2 — victim-directory scan when it differs from active dir
    try:
        victim_dir = os.path.dirname(victim_abs) or ""
        try:
            active_dir = os.path.dirname(
                os.path.abspath(registry.active_path())) or ""
        except Exception:  # noqa: BLE001
            active_dir = ""
        if victim_dir and os.path.isdir(victim_dir) and \
                os.path.abspath(victim_dir) != os.path.abspath(active_dir):
            try:
                for name in sorted(os.listdir(victim_dir)):
                    if not name.lower().endswith(".db"):
                        continue
                    p = os.path.join(victim_dir, name)
                    try:
                        if os.path.isfile(p):
                            collected.append(p)
                    except OSError:
                        continue
            except OSError as exc:
                complete = False
                diagnostics.append(
                    f"victim directory scan failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        complete = False
        diagnostics.append(f"victim directory handling failed: {exc}")

    # 3 — remembered in-root *.db paths
    try:
        known = list(registry.known_paths() or [])
        root = ""
        try:
            # DbRegistry host has .root; be defensive.
            host = getattr(registry, "_host", None)
            root = os.path.abspath(getattr(host, "root", "") or "")
        except Exception:  # noqa: BLE001
            root = ""
        for p in known:
            if not isinstance(p, str) or not p:
                continue
            if not p.lower().endswith(".db"):
                continue
            try:
                ap = os.path.abspath(p)
            except Exception:  # noqa: BLE001
                continue
            # In-root only (containment, not blind trust).
            if root:
                try:
                    common = os.path.commonpath([root, ap])
                    if common != root or ap == root:
                        continue
                except ValueError:
                    continue
            try:
                if os.path.exists(ap):
                    collected.append(ap)
            except OSError:
                continue
    except Exception as exc:  # noqa: BLE001
        complete = False
        diagnostics.append(f"remembered-paths scan failed: {exc}")

    # Victim itself for scope check
    try:
        if victim_abs and os.path.exists(victim_abs):
            collected.append(victim_abs)
    except OSError:
        pass

    deduped = _dedup(collected)
    # victim_in_scope: victim found in union (by canonical identity)
    victim_c = canonical(victim_abs) if victim_abs else ""
    in_scope = any(canonical(p) == victim_c for p in deduped) \
        if victim_c else False
    # worlds for keep-scan excludes victim
    worlds = [p for p in deduped if canonical(p) != victim_c]
    return DeletionInventory(
        worlds=worlds, complete=complete, diagnostics=diagnostics,
        victim_abs=victim_abs, victim_in_scope=in_scope,
        all_worlds=deduped)


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
        # Prune symlink dirs in-place (never descend).
        for d in list(dirnames):
            full = os.path.join(root, d)
            try:
                if os.path.islink(full):
                    dirnames.remove(d)
            except OSError:
                dirnames.remove(d)
                continue
        for name in filenames:
            full = os.path.join(root, name)
            try:
                # Never include symlinks (retained by policy).
                if os.path.islink(full):
                    continue
                # Regular files only; skip dirs/fifos/sockets.
                if not os.path.isfile(full):
                    continue
                out.add(os.path.abspath(full))
            except OSError:
                continue
    return out


def classify_candidate(*, candidate_abs: str, base_abs: str,
                       victim_folder_abs: str, folder_exclusive: bool,
                       keep: frozenset, other_world_folders: frozenset,
                       is_discovered: bool) -> str:
    """Policy verdict for one candidate: 'remove' or 'retain:<reason>'."""
    cand = os.path.abspath(str(candidate_abs or ""))
    base = os.path.abspath(str(base_abs or ""))
    # Symlinks never unlinked (never follow; target always survives).
    try:
        if os.path.islink(candidate_abs):
            return "retain:symlink"
    except OSError:
        return "retain:symlink"
    # Outside root → retain.
    if not is_within(cand, base):
        # Also handle exact base match.
        try:
            if canonical(cand) == canonical(base):
                return "retain:root"
        except Exception:  # noqa: BLE001
            pass
        return "retain:outside_root"
    # Media root itself → retain (defensive; is_within already False for ==).
    try:
        if canonical(cand) == canonical(base):
            return "retain:root"
    except Exception:  # noqa: BLE001
        pass
    # Another world's folder (or inside it) → retain.
    try:
        cand_c = canonical(cand)
        for other in (other_world_folders or frozenset()):
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
    # Shared reference → retain.
    # Compare by both abspath and canonical to catch symlink-aliased refs.
    try:
        cand_c = canonical(cand)
        for k in (keep or frozenset()):
            try:
                if os.path.abspath(str(k)) == cand or \
                        canonical(str(k)) == cand_c:
                    return "retain:shared"
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    # Discovered files in a NON-exclusive (shared-stem) folder → retain.
    if is_discovered and not folder_exclusive:
        return "retain:ambiguous_folder"
    # Only regular files are removed; dirs pruned separately.
    try:
        if not os.path.isfile(cand):
            # Missing files are idempotent no-ops → treat as retain (not fail).
            if not os.path.lexists(cand):
                return "retain:missing"
            return "retain:not_file"
    except OSError:
        return "retain:not_file"
    return "remove"


def plan_deletion(*, victim_abs: str, victim_folder_abs: str,
                  media_base_abs: str, footprint_files: set[str],
                  discovered_files: set[str], keep: set[str],
                  folder_exclusive: bool,
                  other_world_folders: set[str],
                  inventory) -> DeletionPlan:
    """Combine footprint + discovered − keep through the path policy."""
    base = os.path.abspath(str(media_base_abs or ""))
    vfolder = os.path.abspath(str(victim_folder_abs or ""))
    keep_f = frozenset(os.path.abspath(str(p)) for p in (keep or set()))
    others_f = frozenset(os.path.abspath(str(p))
                         for p in (other_world_folders or set()))
    candidates: set[str] = set()
    retained: set[str] = set()
    # Footprint files (victim refs inside base)
    for f in (footprint_files or set()):
        verdict = classify_candidate(
            candidate_abs=os.path.abspath(str(f)), base_abs=base,
            victim_folder_abs=vfolder, folder_exclusive=folder_exclusive,
            keep=keep_f, other_world_folders=others_f,
            is_discovered=False)
        if verdict == "remove":
            candidates.add(os.path.abspath(str(f)))
        else:
            retained.add(os.path.abspath(str(f)))
    # Discovered files (walk of victim folder)
    for f in (discovered_files or set()):
        ap = os.path.abspath(str(f))
        if ap in candidates or ap in retained:
            continue
        verdict = classify_candidate(
            candidate_abs=ap, base_abs=base,
            victim_folder_abs=vfolder, folder_exclusive=folder_exclusive,
            keep=keep_f, other_world_folders=others_f,
            is_discovered=True)
        if verdict == "remove":
            candidates.add(ap)
        else:
            retained.add(ap)
    return DeletionPlan(
        victim_abs=os.path.abspath(str(victim_abs or "")),
        victim_folder_abs=vfolder, media_base_abs=base,
        footprint_files=frozenset(os.path.abspath(str(p))
                                  for p in (footprint_files or set())),
        discovered_files=frozenset(os.path.abspath(str(p))
                                    for p in (discovered_files or set())),
        keep=keep_f, candidates=frozenset(candidates),
        retained=frozenset(retained),
        folder_exclusive=bool(folder_exclusive),
        inventory=inventory, other_world_folders=others_f)


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


def prune_empty_dirs(*, start_dirs, base_abs: str,
                     other_world_folders: frozenset) -> list[str]:
    """Rmdir verified-empty dirs strictly inside base (never base/others).

    `start_dirs` are parent dirs of removed files. Walks upward while empty.
    Never rmtree. Returns removed dir paths.
    """
    removed: list[str] = []
    base = os.path.abspath(str(base_abs or ""))
    try:
        base_c = canonical(base)
    except Exception:  # noqa: BLE001
        base_c = base
    other_c: set[str] = set()
    for o in (other_world_folders or frozenset()):
        try:
            other_c.add(canonical(str(o)))
        except Exception:  # noqa: BLE001
            continue
    seen: set[str] = set()
    for start in (start_dirs or []):
        folder = os.path.abspath(str(start or ""))
        while folder and folder not in seen:
            seen.add(folder)
            # Strictly inside base, never base itself.
            try:
                folder_c = canonical(folder)
            except Exception:  # noqa: BLE001
                break
            if folder_c == base_c:
                break
            if not is_within(folder, base):
                break
            if folder_c in other_c:
                break
            # Never prune another world's folder (or inside it? parents of
            # removed files are never inside another world's folder because
            # those files were retained; still guard the exact folder).
            try:
                if not os.path.isdir(folder) or os.path.islink(folder):
                    break
                if os.listdir(folder):
                    break
            except OSError:
                break
            try:
                os.rmdir(folder)
                removed.append(folder)
            except OSError as exc:
                log.debug("cannot prune %s: %s", folder, exc)
                break
            folder = os.path.dirname(folder)
    return removed


# ── outcome ────────────────────────────────────────────────────────

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
            "removed_paths": list(self.removed_paths or []),
            "retained_paths": list(self.retained_paths or []),
            "failed_paths": list(self.failed_paths or []),
        }
        if self.error:
            d["error"] = self.error
        # Preserve last_database flag and diagnostics when present.
        if self.extra:
            for k, v in self.extra.items():
                if k not in d:
                    d[k] = v
        return d
