"""Filesystem presence is not the same as a loadable chat archive.

One inventory serves discovery, name conflicts and UI capabilities. Invalid
files and orphan SQLite sidecars reserve names too; they are visible but read-
only. Config paths are discovery hints, never proof that a file exists.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterable

from backend.db_paths import canonical_path, same_database
from backend.history_db import inspect_archive_details

SUFFIXES = ("", "-wal", "-shm", "-journal")
LAST_DATABASE = "Cannot delete the last database. Create a new one first."
ALIAS_DATABASE = "This name is an alias of another database. Use the original database path."
READ_ONLY_FILE = "This file is not a loadable chat archive. Reveal it to inspect or rename it safely."


def path_key(path: str) -> str:
    """A filename's identity, deliberately NOT following a symlink."""
    return os.path.normcase(os.path.abspath(path))


def existing_group(path: str) -> list[str]:
    """The exact entries which reserve a name, including broken links."""
    return [path + suffix for suffix in SUFFIXES if os.path.lexists(path + suffix)]


def group_size(path: str) -> int:
    total = 0
    for member in existing_group(path):
        try:
            if os.path.isfile(member):
                total += os.path.getsize(member)
        except OSError:
            pass
    return total


def _candidate_name(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".db"):
        return name
    for suffix in SUFFIXES[1:]:
        if lower.endswith(".db" + suffix):
            return name[:-len(suffix)]
    return ""


def _describe(path: str, members: list[str], alias_of: str = "", *, external_link: bool = False) -> dict:
    main_exists = os.path.lexists(path)
    item = {
        "path": path, "name": os.path.basename(path),
        "exists": True, "main_exists": main_exists, "blocking": True,
        "files": members, "bytes": group_size(path),
        "active": False, "compatible": False, "manageable": False,
        "kind": "file", "status": "unavailable", "detail": "",
        "can_load": False, "can_delete": False,
        "delete_reason": READ_ONLY_FILE,
        "can_reveal": True, "reveal_path": path if main_exists else members[0],
    }
    if not main_exists:
        names = ", ".join(os.path.basename(p) for p in members)
        item.update(status="sidecars", detail=(
            f"{item['name']} is missing, but SQLite sidecar files reserve its name: {names}. "
            "Reveal the files before renaming or moving them; they may contain recoverable data."))
    elif os.path.islink(path):
        missing = not os.path.exists(path)
        item.update(status="broken_link" if missing else "alias",
                    alias_of=canonical_path(path), delete_reason=ALIAS_DATABASE,
                    detail=("Broken symbolic link; the filename still exists. " if missing else
                            "Symbolic link; not a separate archive. ") + canonical_path(path))
    elif alias_of or external_link:
        item.update(status="alias", alias_of=alias_of, delete_reason=ALIAS_DATABASE,
                    detail=("Same database file as " + alias_of + "; not a separate archive."
                            if alias_of else "Hard-linked file with another name outside this inventory. "
                            "It may share data with a backup or another application; reveal it to inspect the links."))
    else:
        try:
            info = os.stat(path)
            if not stat.S_ISREG(info.st_mode):
                item.update(status="not_file", detail="A directory or non-regular file occupies this database name.")
            elif not info.st_size:
                item.update(status="empty", detail="Empty file (0 bytes); not an initialized chat archive.")
            else:
                item.update(inspect_archive_details(path, full=True))
                if item["compatible"]:
                    item.update(kind="archive", manageable=True, delete_reason="")
        except OSError as exc:
            item.update(status="unavailable", detail=str(exc))
    # A read-only SQLite probe can establish WAL/SHM companions. Report the
    # group after the probe, not a pre-probe manifest/size that we made stale.
    current = existing_group(path)
    present = path in current
    item.update(files=current, bytes=group_size(path), exists=bool(current),
                blocking=bool(current), main_exists=present, can_reveal=bool(current),
                reveal_path=path if present else (current[0] if current else ""))
    if present != main_exists:
        item.update(status="unavailable", compatible=False, manageable=False, kind="file",
                    delete_reason=READ_ONLY_FILE,
                    detail="This file changed during inspection. Refresh Databases before loading it.")
    return item


def inventory(active: str, recent: Iterable[str], *, protected: Callable[[str], bool],
              extra: Iterable[str] = ()) -> list[dict]:
    """Fresh visible file groups, with capabilities based on independent archives.

    An explicit extra target makes even an external Create conflict discoverable.
    Known symlink/hardlink aliases do not get probed through a second WAL name or
    counted as another fallback database. Lexical paths remain available to the
    file manager instead of being silently replaced by their targets.
    """
    candidates = [active, *recent, *extra]
    if os.path.islink(active):
        candidates.insert(0, canonical_path(active))
    folder = os.path.dirname(active)
    try:
        for name in sorted(os.listdir(folder)):
            base = _candidate_name(name)
            if base:
                candidates.append(os.path.join(folder, base))
    except OSError:
        # Recent/active/explicit paths remain inspectable if listing is denied.
        pass

    paths, seen = [], set()
    for path in candidates:
        if not path:
            continue
        path = os.path.abspath(path)
        key = path_key(path)
        if key in seen or protected(path):
            continue
        seen.add(key)
        paths.append(path)
    # Prefer the actual active filename, then non-symlink paths and a stable
    # path order. Remembering a conflict must not turn a known alias into the
    # primary archive merely by moving it to the front of recents.
    paths.sort(key=lambda p: (path_key(p) != path_key(active), os.path.islink(p), path_key(p)))
    found, originals = [], []
    for path in paths:
        members = existing_group(path)
        if not members:
            continue
        alias = next((old for old in originals if same_database(path, old)), "")
        external_link = False
        if not alias and not same_database(path, active):
            try:
                info = os.stat(path)
                if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
                    names = {canonical_path(p) for p in paths
                             if not os.path.islink(p) and same_database(path, p)}
                    # A link into a backup/external DB must not become loadable
                    # just because its original name disappeared from the list.
                    external_link = info.st_nlink > len(names)
            except OSError:
                pass  # _describe supplies the actual missing/unavailable reason
        item = _describe(path, members, alias, external_link=external_link)
        if not item["blocking"]:
            continue
        if item["status"] not in ("alias", "broken_link", "sidecars"):
            originals.append(path)
        if item["manageable"]:
            item["active"] = same_database(path, active)
        found.append(item)

    count = sum(item["manageable"] for item in found)
    for item in found:
        if item["manageable"]:
            item["can_load"] = not item["active"]
            item["can_delete"] = count > 1
            item["delete_reason"] = "" if count > 1 else LAST_DATABASE
    found.sort(key=lambda item: (not item["active"], item["name"].lower(), item["path"]))
    return found
