#!/usr/bin/env python3
"""Prioritised cyclomatic-complexity inventory for the whole production tree.

RULE 16 §8 step 4 says every complexity change must be *measured*, and §6 says
legacy hotspots must not get worse. Before the first CC round it was possible
to read the maximum; after it, nobody could list the whole tail without
re-deriving it by hand. This tool is that list, ranked, with the two facts that
decide whether a function may be touched safely:

  * how well the file that owns it is covered (a refactor without a test net is
    a rewrite), and
  * whether a shipped test asserts on its source text / signature (a pin that
    constrains *how* the function may be split, see RULE 16 §6 and
    `docs/CC_TAIL_EXTRACTION_DESIGN_2026-09-10.md`).

Ranking (higher = fix sooner) — deliberately simple and reproducible:

    priority = 3*(CC - 10) + 1*(cognitive - 15 if > 15) + 2*(nesting - 4 if > 4)
             + 1*(LOC - 30 if > 30) + 2*(params - 4 if > 4)
             + 40 if file line-coverage < 75 % else 0
             - 25 if the function is pinned by a source-inspection test

Coverage and pins are optional: without a `coverage.json` / a test tree the
table still ranks on size and complexity alone.

Usage:
    python3 tools/metrics/cc_inventory.py                     # table
    python3 tools/metrics/cc_inventory.py --json out.json     # machine-readable
    python3 tools/metrics/cc_inventory.py --tier 16           # only CC >= 16
    python3 tools/metrics/cc_inventory.py --gate              # exit 1 if CC > 0 on new code
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKGS = ["core", "actions", "backend", "bridge", "services", "stores", "app"]
GATE_CC = 10


def py_files():
    out = []
    for pkg in PKGS:
        base = os.path.join(ROOT, pkg)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            out += [os.path.join(dirpath, f) for f in filenames if f.endswith(".py")]
    out.append(os.path.join(ROOT, "main.py"))
    return sorted(out)


def radon_cc(path):
    """CC of every function in `path` by Radon (the gate's own counting rules).

    Returns a list of (name, line, cc, complexity-class). Falls back to an
    AST decision count when radon is not installed, flagged by the caller.
    """
    src = open(path, encoding="utf-8").read()
    try:
        from radon.complexity import Function, cc_visit
        blocks = cc_visit(src)
    except Exception:                                    # pragma: no cover
        return _fallback_cc(src), False
    # radon hands back one block per class with its methods nested in `inner`,
    # and only functions carry a rank; the inventory counts functions, so the
    # tree is flattened here (nested defs included, as the gate counts them).
    out, stack = [], list(blocks)
    while stack:
        block = stack.pop()
        stack.extend(getattr(block, "inner", []))
        if isinstance(block, Function):
            out.append((block.name, block.lineno, block.complexity, block.rank))
    return out, True


def _fallback_cc(src):
    import ast as _a

    def cc_of(node):
        c = 1
        for n in _a.walk(node):
            if isinstance(n, (_a.If, _a.For, _a.AsyncFor, _a.While, _a.ExceptHandler,
                             _a.Assert, _a.IfExp)):
                c += 1
            elif isinstance(n, _a.BoolOp):
                c += len(n.values) - 1
            elif isinstance(n, _a.comprehension):
                c += 1 + len(n.ifs)
        return c

    tree = _a.parse(src)
    return [(n.name, n.lineno, cc_of(n), "?") for n in _a.walk(tree)
            if isinstance(n, (_a.FunctionDef, _a.AsyncFunctionDef))]


def metrics_of(path, name, lineno):
    """LOC / nesting / params / cognitive for one function, by frozen definition."""
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    target = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name and node.lineno == lineno:
            target = node
            break
    if target is None:
        return {}
    BLOCK = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith,
             ast.Try, ast.Match)

    def nesting(node, depth=0):
        best = depth
        for n in ast.iter_child_nodes(node):
            d = depth + 1 if isinstance(n, BLOCK) else depth
            best = max(best, nesting(n, d))
        return best

    arg = target.args
    params = len(arg.args) + len(getattr(arg, "posonlyargs", [])) + len(arg.kwonlyargs)
    if params and arg.args and arg.args[0].arg in ("self", "cls"):
        params -= 1
    params += bool(arg.vararg) + bool(arg.kwarg)
    out = {"loc": (target.end_lineno or target.lineno) - target.lineno + 1,
           "nesting": nesting(target.body and target or target) if target.body else 0,
           "params": params}
    try:
        from cognitive_complexity.api import get_cognitive_complexity
        out["cognitive"] = get_cognitive_complexity(target)
    except Exception:
        out["cognitive"] = None
    return out


def file_line_coverage(coverage_json):
    """{relative path: line %} from a `coverage json` dump, or {}."""
    out = {}
    if not coverage_json or not os.path.exists(coverage_json):
        return out
    data = json.load(open(coverage_json))
    for fname, info in data.get("files", {}).items():
        rel = os.path.relpath(fname, ROOT) if os.path.isabs(fname) else fname
        s = info["summary"]
        n = s["num_statements"]
        # frozen report definition: line = covered / statements (NOT coverage.py's
        # combined percent_covered, which mixes branches in).
        out[rel] = round((n - s["missing_lines"]) / n * 100, 1) if n else 100.0
    return out


def source_pins():
    """Names that shipped tests inspect textually (getsource / __code__.co_names).

    A pin constrains the *shape* of a refactor: the symbol must stay reachable
    from the pinned place. Detected, never guessed — the pattern list mirrors
    the idiom used in this repo's suites.
    """
    pats = (re.compile(r"getsource\(\s*([A-Za-z_][\w.]*)\s*\)"),
            re.compile(r"inspect\.getsource\(([\w.]+)"),
            re.compile(r"co_names"),
            re.compile(r"\.py\"\s*,\s*\n?\s*(?:[^#]*?)assert.*in\b"))
    pinned = set()
    troot = os.path.join(ROOT, "tests")
    if not os.path.isdir(troot):
        return pinned
    for dirpath, dirnames, filenames in os.walk(troot):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for f in filenames:
            if not f.endswith(".py"):
                continue
            text = open(os.path.join(dirpath, f), encoding="utf-8", errors="replace").read()
            for p in pats[:3]:
                for m in p.finditer(text):
                    tok = m.group(1) if m.groups() else m.group(0)
                    if tok:
                        pinned.add(tok.split(".")[-1])
    return pinned


def collect(coverage_json):
    cov = file_line_coverage(coverage_json)
    pins = source_pins()
    rows = []
    for path in py_files():
        rel = os.path.relpath(path, ROOT)
        blocks, exact = radon_cc(path)
        for name, lineno, cc, rank in blocks:
            if cc <= GATE_CC:
                continue
            fn = os.path.basename(path)
            base = fn[:-3]
            m = metrics_of(path, name.split(".")[-1] if "." in name else name, lineno)
            if not m:                                   # nested/class-qualified name
                m = metrics_of(path, name.split(".")[-1], lineno)
            loc = m.get("loc", 0)
            cog = m.get("cognitive") or 0
            nest = m.get("nesting", 0)
            params = m.get("params", 0)
            fcover = cov.get(rel)
            sym = name.split(".")[-1]
            is_pinned = sym in pins
            pr = 3 * (cc - GATE_CC)
            pr += 1 * max(0, cog - 15) + 2 * max(0, nest - 4)
            pr += 1 * max(0, loc - 30) + 2 * max(0, params - 4)
            if fcover is not None and fcover < 75:
                pr += 40
            if is_pinned:
                pr -= 25
            rows.append({"file": rel, "name": sym, "line": lineno, "cc": cc,
                         "rank": rank, "cognitive": m.get("cognitive"),
                         "nesting": nest, "loc": loc, "params": params,
                         "file_line_cov": fcover, "pinned": is_pinned,
                         "priority": pr})
    rows.sort(key=lambda r: (-r["priority"], -r["cc"], r["file"]))
    return rows, bool(cov)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--tier", type=int, default=11)
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--coverage", default=os.path.join(ROOT, "coverage.json"))
    args = ap.parse_args()

    rows, have_cov = collect(args.coverage)
    shown = [r for r in rows if r["cc"] >= args.tier]
    if args.json:
        json.dump(rows, open(args.json, "w"), indent=1)
        print(f"wrote {args.json} ({len(rows)} offenders)")
    print(f"CC > {GATE_CC} offenders: {len(rows)}   "
          f"(CC>=16: {sum(1 for r in rows if r['cc'] >= 16)}, "
          f"11-15: {sum(1 for r in rows if 11 <= r['cc'] <= 15)})   "
          f"coverage data: {'yes' if have_cov else 'NONE (pass --coverage)'}")
    print(f"{'prio':>5} {'CC':>3} {'cog':>4} {'nst':>3} {'LOC':>4} {'p':>3} {'cov%':>6} {'pin':>4}  file:line name")
    for r in shown:
        print(f"{r['priority']:5d} {r['cc']:3d} {str(r['cognitive']):>4} {r['nesting']:3d} "
              f"{r['loc']:4d} {r['params']:3d} {str(r['file_line_cov']):>6} "
              f"{'YES' if r['pinned'] else '-':>4}  {r['file']}:{r['line']} {r['name']}")
    if args.gate and rows:
        print(f"GATE: {len(rows)} functions over CC {GATE_CC} in production scope")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
