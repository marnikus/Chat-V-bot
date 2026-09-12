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
import importlib.util
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LIMITS = {"func_loc": 30, "params": 4, "cc": 10, "cognitive": 15, "nesting": 4}
# Per docs/AGENT_RULES_CODE_QUALITY.md §1, the CI fail line is class > 150 LOC.
# (An earlier draft of this gate used 300, which was the cap before main's
# 9f84454 tightened it. The doc is the source of truth; this must match it.)
CLASS_LIMITS = {"loc": 150, "methods": 15}

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

# Exact-AST clone groups already in the tree at 53ba5fb, measured with
# `python tools/metrics/clone_scan.py .`. The spec fails on *new* groups, not
# on these, so they are frozen here the same way RATCHET freezes class size:
# they may disappear, they may not be joined by new ones.
#
# One of these touches an owned file — ('bridge/db_bridge.py',
# 'bridge/history_bridge.py'). It is the standard import header (from
# __future__ / json / logging / os / PySide6.QtCore), present since the base
# commit 3820136, i.e. it predates this feature. Verified with
# `git log -L 8,15:bridge/history_bridge.py`.
#
# Maintenance 2026-09-11 (DB undo/restore): the AREA C sized split removed two
# of these outright — ('app/lifecycle.py', 'services/history/export.py') and
# ('services/history/mutate.py', 'services/undo_service.py') no longer share a
# window (export.py gained one import, UndoService shed the commit/scheduling
# code). One new group appeared and is the same kind of noise:
# ('services/history/query.py', 'services/undo_service.py') is the plain
# `from __future__ / copy / json / logging / os` header — undo_service no
# longer imports asyncio (the task plumbing moved to undo_timeline.py), which
# left those two files with the identical 6-line header. No logic is copied.
#
# Maintenance 2026-09-12 (Round F, step F1): splitting `services/db_deletion.py`
# (665 lines) into the `db_deletion_*` family added one group of the same kind —
# ('services/db_deletion_inventory.py', 'services/db_deletion_policy.py') share
# the 6-line header `from __future__ / os / dataclasses(dataclass, field) /
# from services import db_deletion_paths as _paths`. Both modules genuinely need
# exactly those four imports, and the shared `_paths` alias is not incidental:
# it is what keeps `canonical()` patchable at one place now that its callers
# live in five files (see the note in tests/integration/safety_deletion/
# test_deletion_defensive.py). No logic is copied.
# Tried and rejected as fixes: a module constant between the imports and the
# code does NOT dissolve the group, because the scanner hashes every
# *consecutive* statement window and the four imports remain one; and dropping
# the blank line between import groups would hide the group by shrinking its
# span below MIN_SPAN, which is gaming the scanner (§18.5), not fixing it.
#
# Maintenance 2026-09-12 (Round F, step F2): decomposing `Collector`
# (526 class LOC / 40 methods) into the `services/collector_*` family removed
# one group and added one, so the count is unchanged at 12. Both halves are
# recorded because they were verified separately, not assumed.
#
# REMOVED — ('bridge/stack_bridge.py', 'services/collector_service.py'). Same
# header noise as the others: both opened
# `from __future__ / asyncio / json / logging / datetime`. Moving the payload
# shaping into services/collector_report.py left collector_service.py with no
# `json` use at all, so the dead import was deleted and the header shrank to
# four statements. The ratchet working as intended, not a scanner dodge: the
# import genuinely went unused (pylint W0611 flagged it).
#
# ADDED — ('services/collector_partner.py', 'services/collector_report.py'),
# span 6 at line 9 in both: `from __future__ import annotations` / `import
# json` / `import logging` / `from typing import Optional`. This one only
# appeared once the two modules were given PEP8-grouped imports (pylint C0411
# failed on the alphabetical-by-text order the generator first emitted), which
# is the honest order and the one every other module here uses. No logic is
# copied. Each of the four names is genuinely used in BOTH files — `json.dumps`
# for the emitted payloads, `log.debug` in the emit-failure handlers, `Optional`
# in the `nick` parameter — and vulture at confidence 90 reports no dead code in
# either module, so there is no unused import to delete that would dissolve the
# window. Tried and rejected: reordering the imports back to dissolve the group
# would reintroduce C0411 and is exactly the cosmetic span-shrinking §18.5
# forbids. This is the same situation as the F1 pair
# ('services/db_deletion_inventory.py', 'services/db_deletion_policy.py')
# directly below.
CLONE_BASELINE = frozenset({
    ("actions/click_back.py", "actions/click_main_tab.py"),
    ("backend/media_handler.py", "backend/message_injector.py"),
    ("bridge/cdp_bridge.py", "bridge/people_bridge.py"),
    ("bridge/collector_bridge.py", "bridge/label_bridge.py",
     "bridge/layout_bridge.py", "bridge/undo_bridge.py"),
    ("bridge/db_bridge.py", "bridge/history_bridge.py"),
    ("services/collector_partner.py", "services/collector_report.py"),
    ("services/db_deletion_inventory.py", "services/db_deletion_policy.py"),
    ("services/history/query.py", "services/undo_service.py"),
    ("services/run/__init__.py", "services/run_service/__init__.py"),
    ("services/run/coordinator.py", "services/run/progress.py"),
    ("stores/atomic.py", "stores/jsonio.py"),
    ("stores/labels_file_store.py", "stores/session_store.py",
     "stores/settings_store.py"),
})


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


def class_violations(info: dict) -> list[str]:
    """Which class limits `info` breaks. Separate from `violations` so the
    class check is directly testable with a synthetic over-cap class."""
    out = []
    for axis in ("loc", "methods"):
        if info[axis] > CLASS_LIMITS[axis]:
            out.append(f"{axis} {info[axis]} > {CLASS_LIMITS[axis]}")
    return out


# ── the gate ──────────────────────────────────────────────────────
def run(with_clones: bool = False) -> dict:
    breaches, stale, rows, class_rows = [], [], [], []

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

    # Enforce the class limits on every class in the owned files. Ratcheted
    # classes are exempt — they are pre-existing offenders governed by RATCHET
    # above, and failing them here would make the gate unfixable. Without this
    # loop CLASS_LIMITS is decoration: declared, reported, never enforced.
    for rel in sorted({k[0] for k in OWNED}):
        for name, info in classes(rel).items():
            if (rel, name) in RATCHET:
                continue
            cv = class_violations(info)
            class_rows.append({"target": f"{rel}::{name}", **info,
                               "violations": cv})
            if cv:
                breaches.append(f"{rel}::{name}: " + ", ".join(cv))

    for key, why in OVERRIDES.items():
        if len(why.strip()) < 40:
            breaches.append(f"override for {key[2]} has no real justification")
        if not violations(measure_function(*key)):
            stale.append(f"{key[0]}::{key[2]} now fits — delete the override")

    found, not_checked = smells()
    breaches += [f"smell: {f}" for f in found]

    # Opt-in. clone_scan walks every production package and takes ~20s, which
    # is too slow to impose on every commit. main's spec §7 puts duplication in
    # CI, not in pre-commit, so the hook skips it and CI passes --with-clones.
    # A skipped scan is reported as such rather than counted as a pass.
    new_clones, clone_stale = [], []
    if with_clones:
        new_clones, clone_stale, clone_missing = clones()
        breaches += [f"new clone group: {c}" for c in new_clones]
        breaches += [f"clone baseline stale (group is gone, delete it): {c}"
                     for c in clone_stale]
        not_checked = not_checked + clone_missing

    return {"rows": rows, "class_rows": class_rows,
            "breaches": breaches + stale,
            "new_clones": new_clones, "clone_stale": clone_stale,
            "clones_checked": with_clones,
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
        r = subprocess.run([vulture] + SMELL_FILES + ["--min-confidence", "90"],
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


def clones() -> tuple[list[str], list[str], list[str]]:
    """(new clone groups, baseline entries gone stale, tools missing).

    Delegates to the repo's own `tools/metrics/clone_scan.py` rather than
    re-implementing a scan, so this gate and the audit report cannot drift
    apart. `CLONE_BASELINE` is pre-existing debt and is not reported; a group
    that is *not* in it is new and is a breach. A baseline entry that no
    longer exists is reported stale, so the baseline ratchets down instead of
    quietly rotting into fiction.
    """
    path = os.path.join(ROOT, "tools", "metrics", "clone_scan.py")
    if not os.path.exists(path):
        return [], [], ["clone_scan"]

    spec = importlib.util.spec_from_file_location("clone_scan", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    groups, _lines = module.scan(ROOT)

    seen, new = set(), []
    for g in groups:
        where = [(os.path.relpath(p, ROOT), a) for p, a, _b in g]
        sig = tuple(sorted(rel for rel, _a in where))
        seen.add(sig)
        if sig not in CLONE_BASELINE:
            new.append(" | ".join(f"{rel}:{a}" for rel, a in where))

    stale = [" | ".join(sig) for sig in sorted(CLONE_BASELINE - seen)]
    return new, stale, []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--with-clones", action="store_true",
                    help="also run the AST clone scan (~20s). CI passes this; "
                         "the pre-commit hook does not, per spec §7.")
    args = ap.parse_args()

    result = run(with_clones=args.with_clones)
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

    C = CLASS_LIMITS
    print(f"\nclass limits: {C['loc']} LOC, {C['methods']} methods "
          f"(ratcheted legacy classes exempt — see RATCHET)")
    print(f"{'class':52s} {'LOC':>4} {'mth':>4}  verdict")
    for r in result["class_rows"]:
        print(f"{r['target']:52s} {r['loc']:4d} {r['methods']:4d}  "
              f"{'ok' if not r['violations'] else 'FAIL ' + '; '.join(r['violations'])}")

    if result["not_checked"]:
        print("\nNOT CHECKED (tool missing — not a pass): "
              + ", ".join(result["not_checked"])
              + "   pip install -r requirements-dev.txt")
    # A scan that did not run is stated, never implied to have passed.
    if result["clones_checked"]:
        print(f"\nclone scan: {len(result['new_clones'])} new group(s), "
              f"{len(result['clone_stale'])} stale baseline entr(ies)")
    else:
        print("\nclone scan: SKIPPED — not a pass. Run with --with-clones "
              "(CI does; the pre-commit hook does not, per spec §7).")

    for b in result["breaches"]:
        print(f"\nBREACH: {b}")
    if not result["breaches"]:
        print("\nAll owned functions fit. Ratchet intact. No stale overrides.")
    return 1 if result["breaches"] else 0


if __name__ == "__main__":
    sys.exit(main())
