"""Every global a deletion phase reads must exist in its own module.

Round H (H2) split the deletion pipeline across four modules and one import
did not come with it: `db_deletion_pre` used `scan_world_media` without
importing it. That should have been an instant NameError. It was not,
because the pipeline is deliberately fail-closed -- the call site sits
inside `except Exception: raise_refusal(...)`, so the NameError was caught
and reported to the user as

    phase="database", error="cannot re-verify media references; retry"

A missing import became a plausible-looking safety refusal. Every deletion
silently stopped working, and the only reason it was caught is that
`tests/test_db_manager.py` asserts the file is actually gone afterwards.

That is a permanent hazard of this design, not a one-off mistake: any name
that goes missing inside a phase is swallowed by the same guard rails that
make the pipeline safe. A NameError from a typo and a genuine I/O failure
are indistinguishable in the outcome dict. So this test checks statically,
at import time, that every global name each phase reads is resolvable in
the module that defines the phase.

It complements rather than duplicates the behavioural tests: those prove
the pipeline works on the paths they exercise, this proves no phase can
reference a name that is not there, including phases and branches no test
happens to reach.
"""

from __future__ import annotations

import ast
import builtins
import importlib
import os
import pathlib
import sys
import unittest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

MODULES = [
    "services/db_deletion_flow.py",
    "services/db_deletion_pre.py",
    "services/db_deletion_remove.py",
    "services/db_deletion_state.py",
    "services/db_deletion_scan.py",
]


def _bound_locally(fn: ast.AST) -> set:
    """Names a function binds itself: params, assignments, loops, excepts."""
    out = set()
    args = getattr(fn, "args", None)
    if args is not None:
        for group in (args.args, args.posonlyargs, args.kwonlyargs):
            out |= {a.arg for a in group}
        for extra in (args.vararg, args.kwarg):
            if extra:
                out.add(extra.arg)
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            out.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                out.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Global):
            out |= set(node.names)
    return out


def _unresolved(path: str) -> set:
    module = importlib.import_module(path[:-3].replace("/", "."))
    tree = ast.parse(pathlib.Path(path).read_text())
    missing = set()
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        local = _bound_locally(fn)
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)):
                continue
            name = node.id
            if (name not in local and not hasattr(builtins, name)
                    and not hasattr(module, name)):
                missing.add(f"{path}::{fn.name} reads {name}")
    return missing


class TestDeletionModuleGlobals(unittest.TestCase):
    def test_no_phase_reads_a_name_its_module_does_not_have(self):
        problems = set()
        for path in MODULES:
            problems |= _unresolved(path)
        self.assertFalse(
            problems,
            "a deletion phase reads a global its module never imported. "
            "The fail-closed guards will turn this into a bogus "
            "'cannot re-verify ...' refusal instead of a crash, and "
            "deletion will silently stop working:\n  "
            + "\n  ".join(sorted(problems)))

    def test_the_check_would_catch_the_h2_regression(self):
        """Not vacuous: the exact H2 bug must be detectable."""
        source = (
            "def _rescan(st, inventory):\n"
            "    for world in inventory.worlds:\n"
            "        try:\n"
            "            res = scan_world_media(world)\n"
            "        except Exception:\n"
            "            raise_refusal(st, 'database', 'cannot re-verify')\n")
        tree = ast.parse(source)
        fn = tree.body[0]
        local = _bound_locally(fn)
        reads = {n.id for n in ast.walk(fn)
                 if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        self.assertIn("scan_world_media", reads - local,
                      "the analyser must see the un-imported call")
        self.assertNotIn("res", reads - local,
                         "assigned locals must not be reported")
        self.assertNotIn("world", reads - local,
                         "loop targets must not be reported")


if __name__ == "__main__":
    unittest.main()
