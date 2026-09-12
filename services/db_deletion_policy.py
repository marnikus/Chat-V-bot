"""Which discovered files are safe to unlink (AREA A).

Owns: one named predicate per retain reason, the path policy that combines them,
and `plan_deletion`, which buckets candidates into delete and retain. Imports
down to `db_deletion_paths` and `db_deletion_plan`; imported only by the shim.
Decides and returns a plan — it never touches the filesystem itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from services import db_deletion_paths as _paths
from services.db_deletion_plan import DeletionPlan


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
    if _paths.is_within(cand, base):
        return None
    try:
        if _paths.canonical(cand) == _paths.canonical(base):
            return "retain:root"
    except Exception:  # noqa: BLE001
        pass
    return "retain:outside_root"


def _exact_root_reason(cand: str, base: str) -> str | None:
    """Defensive re-check: the media root itself is never a candidate."""
    try:
        if _paths.canonical(cand) == _paths.canonical(base):
            return "retain:root"
    except Exception:  # noqa: BLE001
        pass
    return None


def _other_folder_reason(cand: str, other_folders) -> str | None:
    """Another world's media folder (or anything inside it) is retained."""
    try:
        cand_c = _paths.canonical(cand)
        for other in (other_folders or frozenset()):
            try:
                other_c = _paths.canonical(other)
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
        cand_c = _paths.canonical(cand)
        for ref in (keep or frozenset()):
            try:
                if os.path.abspath(str(ref)) == cand or \
                        _paths.canonical(str(ref)) == cand_c:
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
