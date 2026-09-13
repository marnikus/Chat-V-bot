"""Resolve CI comparison bases from environment data, never shell interpolation."""

import os
from pathlib import Path
import sys

from .snapshots import git


def commit(root, revision):
    if not revision:
        raise ValueError("missing required CI revision")
    return git(root, "rev-parse", "--verify", "--end-of-options",
               revision + "^{commit}").decode().strip()


def resolve(root, environ):
    head = commit(root, environ.get("HEAD_SHA"))
    if commit(root, "HEAD") != head:
        raise ValueError("checkout HEAD differs from the event head; tests would cover another revision")
    event = environ.get("GITHUB_EVENT_NAME")
    if event == "pull_request":
        base = commit(root, environ.get("PR_BASE_SHA"))
        return git(root, "merge-base", base, head).decode().strip()
    if event != "push":
        raise ValueError(f"unsupported CI event {event!r}")
    before = environ.get("BEFORE_SHA", "")
    if before and set(before) == {"0"}:
        default = environ.get("DEFAULT_BRANCH")
        if not default or environ.get("CURRENT_BRANCH") == default:
            return "EMPTY"  # first default-branch push: all source is new
        try:
            base = commit(root, f"refs/remotes/origin/{default}")
            return git(root, "merge-base", base, head).decode().strip()
        except ValueError:
            return "EMPTY"  # unavailable/unrelated default history: conservative all-code check
    return commit(root, before)


def main():
    try:
        print("base=" + resolve(Path.cwd(), os.environ))
        return 0
    except (ValueError, OSError) as exc:
        print(f"CI base resolution failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
