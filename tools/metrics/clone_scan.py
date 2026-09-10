#!/usr/bin/env python3
"""Conservative exact-AST cross-file statement-window clone scanner.

Methodology (reproducible; supersedes the ad-hoc scan referenced in
reports/CODE_QUALITY_METRICS_2026-09-10.md):

* Within every statement container (module / class / function body), hash
  every consecutive window of direct child statements whose inclusive
  source span is >= 6 physical lines.
* Windows with identical ``ast.dump`` text appearing in TWO OR MORE files
  are exact clones. Identifiers are NOT normalized, so renamed copies are
  missed; JS payloads are excluded.
* Greedily keep the longest non-overlapping windows per file, then report
  the surviving cross-file groups and the sum of their canonical spans
  ("unique physical lines").

Usage: python tools/metrics/clone_scan.py [repo_root]
"""
from __future__ import annotations

import ast
import os
import sys
from collections import defaultdict

PKGS = ["core", "actions", "backend", "bridge", "services", "stores", "app"]
MIN_SPAN = 6

CONTAINERS = (ast.Module, ast.ClassDef, ast.FunctionDef,
              ast.AsyncFunctionDef)


def py_files(root: str) -> list[str]:
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(base, f))
    return sorted(out)


def windows_for(stmts, path, out) -> None:
    n = len(stmts)
    for i in range(n):
        for j in range(i + 1, n + 1):
            chunk = stmts[i:j]
            span = chunk[-1].end_lineno - chunk[0].lineno + 1
            if span < MIN_SPAN:
                continue
            h = hash("\u0000".join(ast.dump(s) for s in chunk))
            out[h].append((path, chunk[0].lineno, chunk[-1].end_lineno, span))


def collect(root: str) -> dict:
    buckets: dict = defaultdict(list)
    paths = []
    for pkg in PKGS:
        d = os.path.join(root, pkg)
        if os.path.isdir(d):
            paths += py_files(d)
    main_py = os.path.join(root, "main.py")
    if os.path.exists(main_py):
        paths.append(main_py)
    for path in paths:
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, CONTAINERS):
                windows_for(list(node.body), path, buckets)
    return buckets


def scan(root: str):
    buckets = collect(root)
    cross = {h: v for h, v in buckets.items()
             if len({p for p, _, _, _ in v}) > 1}
    picks = sorted(((v[0][3], h, sorted(v)) for h, v in cross.items()),
                   reverse=True)
    busy: dict = defaultdict(list)
    groups = []
    for _span, h, v in picks:
        kept = []
        for p, a, b, _ in v:
            if all(b < x0 or a > x1 for x0, x1 in busy[p]):
                busy[p].append((a, b))
                kept.append((p, a, b))
        if len({p for p, _, _ in kept}) > 1:
            groups.append(kept)
    lines = sum(g[0][2] - g[0][1] + 1 for g in groups)
    return groups, lines


def main(root: str) -> None:
    groups, lines = scan(root)
    print(f"clone groups: {len(groups)}, unique physical lines: {lines}")
    for g in sorted(groups, key=lambda g: -(g[0][2] - g[0][1])):
        span = g[0][2] - g[0][1] + 1
        where = " | ".join(
            f"{os.path.relpath(p, root)}:{a}" for p, a, _b in g)
        print(f"  span {span}: {where}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
