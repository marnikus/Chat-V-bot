"""What exists on disk for a world that is about to be deleted (AREA A).

Owns: the deletion inventory — active-folder scan, active file, victim-directory
scan and remembered in-root .db paths, deduped. Import direction is one-way: this
module imports down to `db_deletion_paths`, and is imported by
`db_deletion_plan` and by the `db_deletion` shim. Reads the filesystem; never
writes to it and never unlinks anything.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from services import db_deletion_paths as _paths


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
            key = _paths.canonical(p)
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
        victim_c = _paths.canonical(self.victim_abs) if self.victim_abs else ""
        in_scope = any(
            _paths.canonical(p) == victim_c for p in deduped) if victim_c else False
        worlds = [p for p in deduped if _paths.canonical(p) != victim_c]
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
