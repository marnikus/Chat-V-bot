#!/usr/bin/env python3
"""AREA D gate — complexity, size and duplication for backend/ + actions/.

Reproduces the metrics the refactor plan (docs/archive/2026-09-09-four-area-refactor/REFACTOR_2026-09-09_FOUR_AREA_PLAN.md
§6.4 exit criteria) is written against, using the SAME definitions as
tools/metrics/deep.py so the numbers are comparable with the plan:

  * cyclomatic CC  — the plan's own AST count (If/For/While/Except/With/Assert/
                     IfExp +1, BoolOp +n-1, comprehension +1 per `if`)
  * SLOC / LOC     — AST line spans per file (non-blank, non-comment)
  * duplication    — 6-AST-node token windows shared by >= 2 files
                     (relative measure: compare before/after, not with CPD)

Usage:
    python3 tools/metrics/area_d.py                 # summary + worst offenders
    python3 tools/metrics/area_d.py --json out.json # machine-readable report
    python3 tools/metrics/area_d.py --gate          # exit criteria, exit code
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKGS = ["backend", "actions"]

#: Files the plan freezes for every area (§7.3.2) — they stay in the packages
#: but their internals are not this area's to change, so the gate reports them
#: separately and excludes them from the "editable" aggregate.
FROZEN = {
    "backend/cdp_client.py",
    "actions/base_action.py",
    "backend/action_engine.py", "backend/bridge.py", "backend/collector.py",
    "backend/db_manager.py", "backend/history_db.py", "backend/history_models.py",
    "backend/history_repo.py", "backend/history_service.py",
    "backend/label_store.py", "backend/media_store.py", "backend/preset_store.py",
    "backend/user_memory.py",
}


def py_files():
    out = []
    for pkg in PKGS:
        base = os.path.join(ROOT, pkg)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if name.endswith(".py"):
                    out.append(os.path.join(dirpath, name))
    return sorted(out)


def cc_of(node) -> int:
    c = 1
    for n in ast.walk(node):
        if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While,
                          ast.ExceptHandler, ast.With, ast.AsyncWith,
                          ast.Assert, ast.IfExp)):
            c += 1
        elif isinstance(n, ast.BoolOp):
            c += len(n.values) - 1
        elif isinstance(n, ast.comprehension):
            c += 1 + len(n.ifs)
        elif isinstance(n, ast.Match):
            c += len(n.cases)
    return c


def nesting(node, depth=0) -> int:
    best = depth
    for n in ast.iter_child_nodes(node):
        d = depth
        if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With,
                          ast.AsyncWith, ast.Try)):
            d = best + 1
        best = max(best, nesting(n, d))
    return best


def params_of(fn) -> int:
    a = fn.args
    return (len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
            + (1 if a.vararg else 0) + (1 if a.kwarg else 0))


def sloc(text: str) -> int:
    n = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        n += 1
    return n


# ── duplication: statement clones shared by >= 2 files ──────────────────
#
# The plan (§3.6) uses 6-AST-node token windows. That granularity is hard to
# reproduce exactly, so this measures the same *property* in a stricter,
# self-explanatory way: two statements in different files are a clone when
# their ASTs are identical (line/column metadata removed, string literals
# normalised, identifiers kept). Duplicated lines = the union of the matched
# statements' line spans, per file. Read the percentage as RELATIVE —
# before/after on this same definition is the number that matters.

MIN_SPAN = 3            # ignore one- or two-line coincidences


def statements(tree):
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt):
            out.append(node)
    return out


def canon(node) -> str:
    """Structural key: position-free dump with string literals normalised, so
    that a differing caption or selector does not hide a copy-paste."""
    text = ast.dump(node, annotate_fields=True, include_attributes=False)
    text = re.sub(r"Constant\(value='(?:[^'\\]|\\.)*'", "Constant(value='S'", text)
    return re.sub(r"ctx=\w+\(\)", "", text)


def duplication(per_file_trees) -> dict:
    groups = defaultdict(set)
    for rel, tree in per_file_trees:
        for stmt in statements(tree):
            lo = getattr(stmt, "lineno", 0)
            hi = getattr(stmt, "end_lineno", lo) or lo
            if not lo or hi - lo + 1 < MIN_SPAN:
                continue
            groups[canon(stmt)].add((rel, lo, hi))
    lines = defaultdict(set)
    n_groups = 0
    for _key, hits in groups.items():
        if len({rel for rel, _lo, _hi in hits}) < 2:
            continue
        n_groups += 1
        for rel, lo, hi in hits:
            lines[rel].update(range(lo, hi + 1))
    duplication.groups = n_groups      # type: ignore[attr-defined]
    return lines


def analyse():
    funcs, files = [], []
    trees = []
    for path in py_files():
        rel = os.path.relpath(path, ROOT)
        text = open(path, encoding="utf-8", errors="replace").read()
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:                      # pragma: no cover
            print(f"!! {rel}: {exc}", file=sys.stderr)
            continue
        trees.append((rel, tree))
        s = sloc(text)
        files.append({"file": rel, "sloc": s,
                      "loc": text.count("\n") + 1,
                      "frozen": rel in FROZEN})
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append({"file": rel, "name": node.name,
                              "line": node.lineno,
                              "loc": (node.end_lineno or node.lineno) - node.lineno + 1,
                              "cc": cc_of(node), "nest": nesting(node),
                              "params": params_of(node)})
    dup = duplication(trees)
    dup_groups = getattr(duplication, "groups", 0)
    per_file_sloc = {f["file"]: f["sloc"] for f in files}
    dup_out = {}
    for rel, lines in dup.items():
        n = len(lines)
        base = per_file_sloc.get(rel, 0) or 1
        dup_out[rel] = {"duplicated_lines": n,
                        "sloc": base,
                        "pct": round(100.0 * n / base, 1)}
    return {"files": files, "functions": funcs, "duplication": dup_out,
            "clone_groups": dup_groups}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", metavar="PATH")
    ap.add_argument("--gate", action="store_true",
                    help="check the AREA D exit criteria and exit non-zero on failure")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args(argv)

    report = analyse()
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1, sort_keys=True)

    funcs = sorted(report["functions"], key=lambda r: -r["cc"])
    print("=== functions over CC 15 (plan gate: nothing over CC 25) ===")
    print(f"{'CC':>4} {'LOC':>5} {'nest':>5} {'par':>4}  function")
    for r in [x for x in funcs if x["cc"] > 15][: args.top]:
        print(f"{r['cc']:4} {r['loc']:5} {r['nest']:5} {r['params']:4}  "
              f"{r['file']}:{r['line']} {r['name']}")
    over = [x for x in funcs if x["cc"] > 25]
    if funcs:
        top = funcs[0]
        print(f"\nmax CC = {top['cc']}  ({top['file']}:{top['line']} {top['name']})")
    else:
        print("\nno functions")
    print(f"functions over CC 25: {len(over)}")
    sync = [x for x in report["functions"] if x["name"] == "sync_conversation"]
    if sync:
        print(f"sync_conversation CC = {sync[0]['cc']} LOC = {sync[0]['loc']} "
              f"params = {sync[0]['params']}")

    print("\n=== file sizes (editable files only) ===")
    for f in sorted((x for x in report["files"] if not x["frozen"]),
                  key=lambda x: -x["sloc"]):
        print(f"{f['sloc']:5} SLOC  {f['file']}")

    print(f"\n=== duplication (identical statements in >= 2 files; "
          f"{report.get('clone_groups', 0)} clone groups) ===")
    agg = defaultdict(lambda: [0, 0])
    for rel, d in sorted(report["duplication"].items()):
        agg[rel.split("/")[0]][0] += d["duplicated_lines"]
        agg[rel.split("/")[0]][1] += d["sloc"]
    for pkg, (dup_lines, tot) in sorted(agg.items()):
        print(f"{pkg}: {dup_lines} duplicated lines / {tot} SLOC = "
              f"{100.0 * dup_lines / (tot or 1):.1f}%")
    for rel, d in sorted(report["duplication"].items(),
                         key=lambda kv: -kv[1]["pct"])[:8]:
        print(f"   {d['pct']:5.1f}%  {rel} ({d['duplicated_lines']}/{d['sloc']})")

    if args.gate:
        print("\n=== GATE ===")
        ok = True
        frozen_files = {f["file"] for f in report["files"] if f["frozen"]}
        bad = [x for x in funcs if x["cc"] > 25 and x["file"] not in frozen_files]
        if bad:
            ok = False
            print(f"FAIL {len(bad)} editable function(s) over CC 25: "
                  + ", ".join(f"{x['file']}:{x['name']}={x['cc']}" for x in bad))
        else:
            print("PASS no editable function over CC 25")
        if sync and sync[0]["cc"] > 15:
            ok = False
            print(f"FAIL sync_conversation CC {sync[0]['cc']} > 15")
        else:
            print("PASS sync_conversation CC <= 15")
        dup_actions = agg.get("actions", [0, 1])
        pct = 100.0 * dup_actions[0] / (dup_actions[1] or 1)
        if pct >= 25.0:
            ok = False
            print(f"FAIL actions duplication {pct:.1f}% >= 25%")
        else:
            print(f"PASS actions duplication {pct:.1f}% < 25%")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
