#!/usr/bin/env python3
"""RULE 16 gate — size and complexity limits, measured rather than asserted.

One implementation, three callers: a human reading the report, the pre-commit
hook, and `tests/test_rule16_new_code.py`. Keeping the policy tables here
instead of in the test is what stops the two from drifting apart and giving
different answers about the same code.

    python3 tools/metrics/rule16_gate.py            # report, exit 1 on breach
    python3 tools/metrics/rule16_gate.py --json     # machine-readable

Rule: docs/AGENT_RULES_CODE_QUALITY.md
Worked example: docs/RULE16_SIZE_COMPLEXITY_FIT_2026-09-10.md

Exits 0 when everything fits, 1 on any breach — so it can gate a commit.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LIMITS = {"func_loc": 30, "params": 4, "cc": 10, "cognitive": 15, "nesting": 4}
CLASS_LIMITS = {"loc": 300, "methods": 15}

# ── policy ────────────────────────────────────────────────────────
# Functions the sortable-columns feature owns. (file, class or None, function.)
OWNED = [
    ("backend/history_query.py", "PersonPageRequest", "needle"),
    ("backend/history_query.py", "PersonPageRequest", "where"),
    ("backend/history_query.py", "PersonPageRequest", "order"),
    ("backend/history_query.py", "PersonPageRequest", "spec"),
    ("backend/history_query.py", "PersonPageRequest", "columns"),
    ("backend/history_query.py", "PersonPageRequest", "resolved_dir"),
    ("backend/history_query.py", "HistoryQuery", "list_persons"),
    ("backend/history_query.py", None, "_person_item"),
    ("bridge/history_bridge.py", None, "_person_request"),
    ("bridge/history_bridge.py", "HistoryBridge", "userdb_page"),
]

# Pre-existing oversized classes this feature cannot split — the AREA D API
# snapshot forbids removing `HistoryQuery` methods and the QWebChannel wire
# contract pins `HistoryBridge`'s slot set. Frozen at the 3820136 measurement:
# they may shrink, they may not grow.
RATCHET = {
    ("backend/history_query.py", "HistoryQuery"): {"loc": 362, "methods": 14},
    ("bridge/history_bridge.py", "HistoryBridge"): {"loc": 493, "methods": 45},
}

# Escape hatch. A limit that can never be bent gets bypassed silently, which is
# worse than a limit with a visible escape hatch. Key = an OWNED entry; value =
# prose a reviewer reads. Two invariants, both enforced by the test suite:
#   * the justification must be real (>= 40 chars, not "TODO"/"noqa");
#   * an override whose function now FITS is reported as stale and must be
#     deleted, so the hatch cannot become a dumping ground.
OVERRIDES: dict[tuple, str] = {}

SMELL_FILES = ["backend/history_query.py", "bridge/history_bridge.py"]


# ── measurement ───────────────────────────────────────────────────
def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _tool(name: str) -> str | None:
    exe = os.path.join(ROOT, ".venv", "bin", name)
    return exe if os.path.exists(exe) else None


def nesting(node: ast.AST) -> int:
    """Control-flow nesting depth. `elif` counts as a nested `if`; sibling
    statements do not add."""
    BRANCH = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With,
              ast.AsyncWith, ast.Try, ast.ExceptHandler)

    def walk(n, depth):
        best = depth
        for child in ast.iter_child_nodes(n):
            best = max(best, walk(child, depth + 1 if isinstance(child, BRANCH)
                                  else depth))
        return best

    return walk(node, 0)


def params(node) -> int:
    """Parameter count excluding self/cls; *args and **kwargs count as one."""
    a = node.args
    return (len([x for x in a.args + a.kwonlyargs
                 if x.arg not in ("self", "cls")])
            + (1 if a.vararg else 0) + (1 if a.kwarg else 0))


def find(rel: str, cls: str | None, func: str):
    """The FunctionDef for `rel::cls.func` (or `rel::func`), else None."""
    tree = ast.parse(_read(rel))
    scope = tree.body
    if cls:
        scope = [n.body for n in tree.body
                 if isinstance(n, ast.ClassDef) and n.name == cls]
        if not scope:
            return None
        scope = scope[0]
    for node in scope:
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == func):
            return node
    return None


def classes(rel: str) -> dict:
    out = {}
    for node in ast.parse(_read(rel)).body:
        if isinstance(node, ast.ClassDef):
            out[node.name] = {
                "loc": node.end_lineno - node.lineno + 1,
                "methods": sum(1 for b in ast.walk(node)
                               if isinstance(b, (ast.FunctionDef,
                                                 ast.AsyncFunctionDef))),
            }
    return out


def _cyclomatic(rel: str, func: str):
    """radon's CC for `func`, or None when radon is not installed."""
    exe = _tool("radon")
    if exe is None:
        return None
    sys.path.insert(0, os.path.join(ROOT, ".venv", "lib", "python3.11",
                                    "site-packages"))
    from radon.complexity import cc_visit
    scores = [b.complexity for b in cc_visit(_read(rel))
              if getattr(b, "name", None) == func]
    return max(scores) if scores else 1


def _cognitive(node):
    """SonarSource cognitive complexity, or None when the lib is absent."""
    sys.path.insert(0, os.path.join(ROOT, ".venv", "lib", "python3.11",
                                    "site-packages"))
    try:
        from cognitive_complexity.api import get_cognitive_complexity
    except ImportError:
        return None
    return get_cognitive_complexity(node)


def measure_function(rel: str, cls: str | None, func: str) -> dict | None:
    node = find(rel, cls, func)
    if node is None:
        return None
    return {"loc": node.end_lineno - node.lineno + 1,
            "params": params(node),
            "cc": _cyclomatic(rel, func),
            "cognitive": _cognitive(node),
            "nesting": nesting(node)}


def violations(m: dict | None) -> list[str]:
    """Which limits this measurement breaks. None metrics are skipped — a
    missing optional tool must not be reported as a breach."""
    if m is None:
        return ["function not found"]
    out = []
    if m["loc"] > LIMITS["func_loc"]:
        out.append(f"LOC {m['loc']} > {LIMITS['func_loc']}")
    if m["params"] > LIMITS["params"]:
        out.append(f"params {m['params']} > {LIMITS['params']}")
    if m["cc"] is not None and m["cc"] > LIMITS["cc"]:
        out.append(f"CC {m['cc']} > {LIMITS['cc']}")
    if m["cognitive"] is not None and m["cognitive"] > LIMITS["cognitive"]:
        out.append(f"cognitive {m['cognitive']} > {LIMITS['cognitive']}")
    if m["nesting"] > LIMITS["nesting"]:
        out.append(f"nesting {m['nesting']} > {LIMITS['nesting']}")
    return out


# ── the gate ──────────────────────────────────────────────────────
def run() -> dict:
    breaches, stale, rows = [], [], []

    for key in OWNED:
        rel, cls, func = key
        m = measure_function(*key)
        v = violations(m)
        rows.append({"target": f"{rel}::{cls + '.' if cls else ''}{func}",
                     **(m or {}), "violations": v})
        if v and key in OVERRIDES:
            continue                     # justified, and the hatch is audited
        if v:
            breaches.append(f"{rel}::{func}: " + ", ".join(v))

    for (rel, name), cap in RATCHET.items():
        info = classes(rel).get(name)
        if info is None:
            breaches.append(f"{rel}::{name} disappeared")
            continue
        for axis in ("loc", "methods"):
            if info[axis] > cap[axis]:
                breaches.append(f"{rel}::{name} {axis} {info[axis]} > "
                                f"frozen {cap[axis]}")

    for key, why in OVERRIDES.items():
        if len(why.strip()) < 40:
            breaches.append(f"override for {key[2]} has no real justification")
        if not violations(measure_function(*key)):
            stale.append(f"{key[0]}::{key[2]} now fits — delete the override")

    found, not_checked = smells()
    breaches += [f"smell: {f}" for f in found]

    return {"rows": rows, "breaches": breaches + stale,
            "not_checked": not_checked,
            "limits": LIMITS, "class_limits": CLASS_LIMITS}


def smells() -> tuple[list[str], list[str]]:
    """(findings, tools that were missing).

    A missing tool is reported as *not checked*, never as a pass — a gate that
    quietly degrades to green is worse than one that says it could not look.
    """
    findings, missing = [], []

    vulture = _tool("vulture")
    if vulture is None:
        missing.append("vulture")
    else:
        r = subprocess.run([vulture] + SMELL_FILES + ["--min-confidence", "80"],
                           capture_output=True, text=True, cwd=ROOT)
        findings += [l for l in r.stdout.splitlines() if l.strip()]

    pylint = _tool("pylint")
    if pylint is None:
        missing.append("pylint")
    else:
        r = subprocess.run([pylint, "--disable=all", "--enable=R0801",
                            "backend/", "bridge/"],
                           capture_output=True, text=True, cwd=ROOT)
        lines = r.stdout.splitlines()
        for i, line in enumerate(lines):
            if "R0801" not in line:
                continue
            block = "\n".join(lines[i + 1:i + 4])
            if any(f in block for f in ("history_query.py",
                                        "history_bridge.py")):
                findings.append(block)

    return findings, missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    result = run()
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 1 if result["breaches"] else 0

    L = LIMITS
    print(f"RULE 16 — limits: {L['func_loc']} LOC, {L['params']} params, "
          f"CC {L['cc']}, cognitive {L['cognitive']}, nesting {L['nesting']}")
    print(f"{'target':52s} {'LOC':>4} {'prm':>4} {'CC':>4} {'cog':>4} "
          f"{'nest':>4}  verdict")
    for r in result["rows"]:
        if "loc" not in r:
            print(f"{r['target']:52s} {'MISSING':>25}")
            continue
        cc = "-" if r["cc"] is None else r["cc"]
        cog = "-" if r["cognitive"] is None else r["cognitive"]
        print(f"{r['target']:52s} {r['loc']:4d} {r['params']:4d} {cc:>4} "
              f"{cog:>4} {r['nesting']:4d}  "
              f"{'ok' if not r['violations'] else 'FAIL ' + '; '.join(r['violations'])}")

    if result["not_checked"]:
        print("\nNOT CHECKED (tool missing — not a pass): "
              + ", ".join(result["not_checked"])
              + "   pip install -r requirements-dev.txt")
    for b in result["breaches"]:
        print(f"\nBREACH: {b}")
    if not result["breaches"]:
        print("\nAll owned functions fit. Ratchet intact. No stale overrides.")
    return 1 if result["breaches"] else 0


if __name__ == "__main__":
    sys.exit(main())
