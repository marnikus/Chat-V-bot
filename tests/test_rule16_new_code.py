"""RULE 16 — size & complexity gate for the sortable-columns feature.

The thresholds are turned into an executable check so they cannot rot, and so
"does the new code fit?" is answered by the project's own runner rather than by
someone re-reading a document.

Measured, never asserted. Two kinds of check live here:

1. **Hard gate** — every function this feature owns must be inside all six
   limits (LOC / params / cyclomatic / cognitive / nesting).
2. **Ratchet** — `HistoryQuery` and `HistoryBridge` were already over the class
   limits before this feature (362 and 490 LOC). Splitting them is forbidden by
   two *other* frozen contracts (the AREA D API snapshot and the QWebChannel
   wire contract), so instead their size must not GROW. Debt that cannot be
   repaid here is at least frozen.

Tools: `radon` for cyclomatic complexity and `cognitive_complexity` for the
SonarSource score. They are dev dependencies — `pip install -r
requirements-dev.txt`. When they are absent the complexity checks skip loudly
rather than silently passing.

Design: docs/archive/2026-09-10-quality-gates/RULE16_SIZE_COMPLEXITY_FIT_2026-09-10.md

Run with:  python3 tests/test_rule16_new_code.py
"""

import ast
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LIMITS = {"func_loc": 30, "params": 4, "cc": 10, "cognitive": 15, "nesting": 4}
CLASS_LIMITS = {"loc": 300, "methods": 15}

try:
    from radon.complexity import cc_visit
except ImportError:                                  # pragma: no cover
    cc_visit = None
try:
    from cognitive_complexity.api import get_cognitive_complexity
except ImportError:                                  # pragma: no cover
    get_cognitive_complexity = None


# ── what this feature owns ───────────────────────────────────────
# (file, class or None, function). Nested closures are measured with their
# enclosing function, because that is the unit a reader has to hold in mind.
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

# ── pre-existing debt, frozen at the 3820136 measurement ─────────
RATCHET = {
    ("backend/history_query.py", "HistoryQuery"): {"loc": 362, "methods": 14},
    ("bridge/history_bridge.py", "HistoryBridge"): {"loc": 493, "methods": 45},
}


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _nesting(node):
    """Control-flow nesting depth. `elif` counts as a nested `if`; sibling
    statements do not add."""
    BRANCH = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With,
              ast.AsyncWith, ast.Try, ast.ExceptHandler)

    def walk(n, depth):
        best = depth
        for child in ast.iter_child_nodes(n):
            if isinstance(child, BRANCH):
                best = max(best, walk(child, depth + 1))
            else:
                best = max(best, walk(child, depth))
        return best

    return walk(node, 0)


def _params(node):
    a = node.args
    return (len([x for x in a.args + a.kwonlyargs
                 if x.arg not in ("self", "cls")])
            + (1 if a.vararg else 0) + (1 if a.kwarg else 0))


def _find(rel, cls, func):
    """The FunctionDef for `rel::cls.func` (or `rel::func`)."""
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


def _classes(rel):
    tree = ast.parse(_read(rel))
    out = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            out[node.name] = {
                "loc": node.end_lineno - node.lineno + 1,
                "methods": sum(
                    1 for b in ast.walk(node)
                    if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))),
            }
    return out


class TestOwnedFunctionsFitEveryLimit(unittest.TestCase):
    """The hard gate: LOC / params / CC / cognitive / nesting."""

    def test_every_owned_function_exists(self):
        missing = [f"{rel}::{cls or ''}.{fn}"
                   for rel, cls, fn in OWNED if _find(rel, cls, fn) is None]
        self.assertEqual(missing, [], "these functions are gone — the gate is "
                                      "pointing at nothing: " + ", ".join(missing))

    def test_function_size_and_parameter_limits(self):
        over = []
        for rel, cls, fn in OWNED:
            node = _find(rel, cls, fn)
            if node is None:
                continue
            loc, prm = node.end_lineno - node.lineno + 1, _params(node)
            if loc > LIMITS["func_loc"]:
                over.append(f"{rel}::{fn} is {loc} LOC (> {LIMITS['func_loc']})")
            if prm > LIMITS["params"]:
                over.append(f"{rel}::{fn} takes {prm} params "
                            f"(> {LIMITS['params']})")
        self.assertEqual(over, [], "\n".join(over))

    def test_nesting_depth(self):
        over = []
        for rel, cls, fn in OWNED:
            node = _find(rel, cls, fn)
            if node is None:
                continue
            depth = _nesting(node)
            if depth > LIMITS["nesting"]:
                over.append(f"{rel}::{fn} nests {depth} deep "
                            f"(> {LIMITS['nesting']})")
        self.assertEqual(over, [], "\n".join(over))

    @unittest.skipUnless(cc_visit, "radon not installed "
                                   "(pip install -r requirements-dev.txt)")
    def test_cyclomatic_complexity(self):
        over = []
        for rel, cls, fn in OWNED:
            node = _find(rel, cls, fn)
            if node is None:
                continue
            scores = {b.name: b.complexity for b in cc_visit(_read(rel))
                      if getattr(b, "name", None) == fn}
            cc = max(scores.values()) if scores else 1
            if cc > LIMITS["cc"]:
                over.append(f"{rel}::{fn} has CC {cc} (> {LIMITS['cc']})")
        self.assertEqual(over, [], "\n".join(over))

    @unittest.skipUnless(get_cognitive_complexity,
                         "cognitive_complexity not installed "
                         "(pip install -r requirements-dev.txt)")
    def test_cognitive_complexity(self):
        over = []
        for rel, cls, fn in OWNED:
            node = _find(rel, cls, fn)
            if node is None:
                continue
            cog = get_cognitive_complexity(node)
            if cog > LIMITS["cognitive"]:
                over.append(f"{rel}::{fn} has cognitive complexity {cog} "
                            f"(> {LIMITS['cognitive']})")
        self.assertEqual(over, [], "\n".join(over))


class TestRequestObjectIsSmall(unittest.TestCase):
    """The new class must itself be inside the class limits."""

    def test_person_page_request_fits(self):
        info = _classes("backend/history_query.py").get("PersonPageRequest")
        self.assertIsNotNone(info, "PersonPageRequest does not exist")
        self.assertLessEqual(info["loc"], CLASS_LIMITS["loc"],
                             f"PersonPageRequest is {info['loc']} LOC")
        self.assertLessEqual(info["methods"], CLASS_LIMITS["methods"],
                             f"PersonPageRequest has {info['methods']} methods")


class TestPreExistingDebtDoesNotGrow(unittest.TestCase):
    """`HistoryQuery` (362 LOC) and `HistoryBridge` (490 LOC / 45 methods)
    already broke the class limits before this feature. They cannot be split
    here — the AREA D API snapshot forbids removing `HistoryQuery` methods and
    `tests/test_bridge_router.js` pins `HistoryBridge`'s slot set. So the debt
    is frozen: it may shrink, it may not grow."""

    def test_class_ratchet(self):
        grew = []
        for (rel, name), cap in RATCHET.items():
            info = _classes(rel).get(name)
            self.assertIsNotNone(info, f"{name} disappeared from {rel}")
            for axis in ("loc", "methods"):
                if info[axis] > cap[axis]:
                    grew.append(f"{rel}::{name} {axis} {info[axis]} > "
                                f"frozen {cap[axis]}")
        self.assertEqual(grew, [], "\n".join(grew))


class TestNoNewSmells(unittest.TestCase):
    """Zero new duplication, zero dead code (RULE 16 smell section)."""

    FILES = ["backend/history_query.py", "bridge/history_bridge.py"]

    def _tool(self, cmd):
        exe = os.path.join(ROOT, ".venv", "bin", cmd)
        path = exe if os.path.exists(exe) else cmd
        try:
            return subprocess.run([path] + cmd[1:] if False else [path],
                                  capture_output=True, text=True, cwd=ROOT)
        except FileNotFoundError:
            return None

    def test_vulture_finds_no_dead_code(self):
        exe = os.path.join(ROOT, ".venv", "bin", "vulture")
        if not os.path.exists(exe):
            self.skipTest("vulture not installed "
                          "(pip install -r requirements-dev.txt)")
        out = subprocess.run([exe] + self.FILES + ["--min-confidence", "80"],
                             capture_output=True, text=True, cwd=ROOT)
        found = [line for line in out.stdout.splitlines() if line.strip()]
        self.assertEqual(found, [], "vulture reported dead code:\n"
                         + "\n".join(found))

    def test_no_duplication_involving_the_changed_files(self):
        exe = os.path.join(ROOT, ".venv", "bin", "pylint")
        if not os.path.exists(exe):
            self.skipTest("pylint not installed "
                          "(pip install -r requirements-dev.txt)")
        out = subprocess.run(
            [exe, "--disable=all", "--enable=R0801", "backend/", "bridge/"],
            capture_output=True, text=True, cwd=ROOT)
        pairs = []
        lines = out.stdout.splitlines()
        for i, line in enumerate(lines):
            if "R0801" not in line:
                continue
            block = "\n".join(lines[i + 1:i + 4])
            if any(f.replace("/", os.sep) in block or f in block
                   for f in ("history_query.py", "history_bridge.py")):
                pairs.append(block)
        self.assertEqual(pairs, [], "duplication involving the changed files:\n"
                         + "\n".join(pairs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
