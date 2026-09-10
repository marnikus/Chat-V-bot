#!/usr/bin/env python3
"""Print the exact source of named methods of a class, for a manual split.

    python tools/metrics/grab.py stores/history_repo.py HistoryRepo \\
            append _prepend _existing_dup_keys

The text is emitted verbatim (indentation normalised to 4 spaces) so a
collaborator module is assembled by moving code, not retyping it — the one
mechanical risk of an internal split is a transcription error in a body that
already has 25 passing tests on it.
"""

from __future__ import annotations

import ast
import sys


def grab(path: str, klass: str, names: list[str]) -> str:
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    lines = src.splitlines()
    target = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == klass:
            target = node
            break
    if target is None:
        sys.exit(f"{path} has no class {klass}")
    methods = {n.name: n for n in target.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    out: list[str] = []
    missing = []
    for name in names:
        node = methods.get(name)
        if node is None:
            missing.append(name)
            continue
        start = node.lineno - 1
        for deco in node.decorator_list:                # @property, @staticmethod
            start = min(start, deco.lineno - 1)
        body = "\n".join(lines[start:node.end_lineno])
        out.append(body.rstrip())
    if missing:
        sys.exit(f"{path}:{klass} has no method(s): {', '.join(missing)}")
    return "\n\n\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    print(grab(sys.argv[1], sys.argv[2], sys.argv[3:]))
