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

Usage: python tools/metrics/clone_scan.py [repo_root] [--cache PATH]

Cache: --cache /tmp/clone_cache.json stores file hashes + groups.
If all hashes match, reuse groups (23.8 s → ~0.2 s cache hit).
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
from collections import defaultdict

PKGS = ["core", "actions", "backend", "bridge", "services", "stores", "app"]
MIN_SPAN = 6

CONTAINERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


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
    cross = {h: v for h, v in buckets.items() if len({p for p, _, _, _ in v}) > 1}
    picks = sorted(((v[0][3], h, sorted(v)) for h, v in cross.items()), reverse=True)
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


def _file_hashes(root: str) -> dict:
    hashes = {}
    for pkg in PKGS:
        d = os.path.join(root, pkg)
        if os.path.isdir(d):
            for p in py_files(d):
                try:
                    h = hashlib.sha256(open(p, "rb").read()).hexdigest()
                    hashes[os.path.relpath(p, root)] = h
                except Exception:
                    pass
    main_py = os.path.join(root, "main.py")
    if os.path.exists(main_py):
        try:
            h = hashlib.sha256(open(main_py, "rb").read()).hexdigest()
            hashes["main.py"] = h
        except Exception:
            pass
    return hashes


def main(root: str, cache_path: str | None = None) -> None:
    if cache_path and os.path.exists(cache_path):
        try:
            cached = json.load(open(cache_path, encoding="utf-8"))
            current = _file_hashes(root)
            if cached.get("file_hashes") == current and "groups" in cached:
                groups = cached["groups"]
                lines = cached.get("lines", 0)
                print(f"clone groups: {len(groups)} (cached), unique physical lines: {lines}")
                for g in sorted(groups, key=lambda g: -(g[0][2] - g[0][1]))[:20]:
                    span = g[0][2] - g[0][1] + 1
                    where = " | ".join(f"{p}:{a}" for p, a, _b in g)
                    print(f"  span {span}: {where}")
                return
        except Exception as exc:
            print(f"cache miss ({exc}), recomputing...")

    groups, lines = scan(root)
    print(f"clone groups: {len(groups)}, unique physical lines: {lines}")
    for g in sorted(groups, key=lambda g: -(g[0][2] - g[0][1])):
        span = g[0][2] - g[0][1] + 1
        where = " | ".join(f"{os.path.relpath(p, root)}:{a}" for p, a, _b in g)
        print(f"  span {span}: {where}")

    if cache_path:
        try:
            hashes = _file_hashes(root)
            serial_groups = []
            for g in groups:
                serial_groups.append([(os.path.relpath(p, root) if os.path.isabs(p) else p, a, b) for p, a, b in g])
            json.dump({"file_hashes": hashes, "groups": serial_groups, "lines": lines},
                      open(cache_path, "w", encoding="utf-8"), indent=2)
            print(f"cache written to {cache_path}")
        except Exception as exc:
            print(f"failed to write cache: {exc}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=os.getcwd())
    ap.add_argument("--cache", dest="cache_path", metavar="PATH", help="cache file, e.g. /tmp/clone_cache.json")
    args = ap.parse_args()
    main(args.root, cache_path=args.cache_path)
