"""Read production snapshots without checking out, stashing or changing the index."""

from dataclasses import dataclass
from importlib.util import decode_source
from pathlib import Path, PurePosixPath
import subprocess

PACKAGES = {"core", "actions", "backend", "bridge", "services", "stores", "app"}


def production(path):
    parts = PurePosixPath(path).parts
    return path == "main.py" or (len(parts) > 1 and parts[0] in PACKAGES
                                 and path.endswith(".py"))


def git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True)
    if result.returncode:
        raise ValueError(f"git {' '.join(args[:2])}: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def decode(path, data):
    try:
        return decode_source(data)
    except (SyntaxError, UnicodeError) as exc:
        raise ValueError(f"{path}: cannot decode Python source: {exc}") from exc


def tree(root, revision):
    if revision == "EMPTY":
        return "EMPTY", {}
    resolved = git(root, "rev-parse", "--verify", "--end-of-options",
                   revision + "^{tree}").decode().strip()
    entries = git(root, "ls-tree", "-rz", resolved).split(b"\0")
    sources = {}
    for entry in filter(None, entries):
        metadata, raw_path = entry.split(b"\t", 1)
        path = raw_path.decode("utf-8", "surrogateescape")
        if not production(path):
            continue
        mode, kind, oid = metadata.split()
        if mode not in (b"100644", b"100755") or kind != b"blob":
            raise ValueError(f"{path}: unsupported production mode {mode.decode()} (symlinks rejected)")
        sources[path] = decode(path, git(root, "cat-file", "blob", oid.decode()))
    return resolved, sources


def index(root):
    sources = {}
    for entry in filter(None, git(root, "ls-files", "--stage", "-z").split(b"\0")):
        metadata, raw_path = entry.split(b"\t", 1)
        path = raw_path.decode("utf-8", "surrogateescape")
        if not production(path):
            continue
        mode, oid, stage = metadata.split()
        if stage != b"0":
            raise ValueError(f"{path}: unresolved index conflict")
        if mode not in (b"100644", b"100755"):
            raise ValueError(f"{path}: index symlink/unsupported mode {mode.decode()}")
        sources[path] = decode(path, git(root, "cat-file", "blob", oid.decode()))
    return sources


def worktree(root):
    root = Path(root).resolve()
    sources = {}
    conflicts = git(root, "ls-files", "--unmerged", "-z")
    for entry in filter(None, conflicts.split(b"\0")):
        path = entry.split(b"\t", 1)[1].decode("utf-8", "surrogateescape")
        if production(path):
            raise ValueError(f"{path}: unresolved index conflict")
    paths = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for raw in filter(None, paths.split(b"\0")):
        path = raw.decode("utf-8", "surrogateescape")
        if not production(path):
            continue
        source = root / path
        chain = [source, *source.parents]
        if any(p.is_symlink() for p in chain if p != root and root in p.parents):
            raise ValueError(f"{path}: production symlink rejected")
        if not source.exists():
            continue  # tracked deletion
        if not source.is_file():
            raise ValueError(f"{path}: production source is not a regular file")
        sources[path] = decode(path, source.read_bytes())
    return sources


@dataclass
class Pair:
    base: str
    target: str
    before: dict
    after: dict

    @property
    def changed_files(self):
        return sorted(p for p in self.before.keys() | self.after.keys()
                      if self.before.get(p) != self.after.get(p))

    @property
    def deleted_files(self):
        return sorted(self.before.keys() - self.after.keys())


def load(root, base="HEAD", head=None, staged=False):
    if head and staged:
        raise ValueError("--head and --staged are mutually exclusive")
    base_id, before = tree(root, base)
    if head:
        target, after = tree(root, head)
    elif staged:
        target, after = "INDEX", index(root)
    else:
        target, after = "WORKTREE", worktree(root)
    return Pair(base_id, target, before, after)
