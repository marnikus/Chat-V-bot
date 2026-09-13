#!/usr/bin/env python3
"""Diff a plain module's surface against an older copy of itself.

The Qt sibling of this tool (`qt_surface_diff.py`) measures a QObject's
*published metaobject*; this one measures an ordinary module, which is what
most of the tree is. Splitting a module into a package is safe only if every
name an importer could reach still resolves to the same kind of thing with the
same signature — and a mixin split has one extra trap: the class's surface is
what the MRO resolves, not what its own body declares, so the comparison has to
walk inherited members too.

What is compared between an old module file and the module as importable today:

  1. every top-level name the old file DEFINED (function, class, constant):
     still reachable, same kind, same `inspect.signature` (functions) or same
     value (constants);
  2. for every shared class: each non-dunder attribute reachable on it
     (including inherited ones) — its kind (method / staticmethod / classmethod
     / property / data) and, when callable, its signature;
  3. the names the old file merely IMPORTED, reported as information: they are
     not API, so they are allowed to disappear (`--strict-imports` to forbid).

Deliberate removals (dead code with zero callers, say) are named with
`--allow-missing NAME`, which reports them as ALLOWED instead of failing: the
verdict stays honest about what changed and why.

Usage (the old copy comes from git, the new one is imported):

    git show HEAD~1:services/undo_service.py > /tmp/old_undo_service.py
    python3 tools/metrics/module_surface_diff.py \\
        /tmp/old_undo_service.py services.undo_service \\
        --allow-missing UndoService._migrated_entry

Exit 0 when nothing unexplained differs, 1 otherwise.
"""
from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def load_module_file(path: str, name: str = "_module_surface_old"):
    """Import a standalone copy of a module (e.g. `git show HEAD~1:file.py`)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def defined_names(path: str) -> tuple[dict, set]:
    """(name → kind) for names the file DEFINES, plus the names it imports."""
    defined, imported = {}, set()
    for node in ast.parse(open(path, encoding="utf-8").read()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined[node.name] = "function"
        elif isinstance(node, ast.ClassDef):
            defined[node.name] = "class"
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined[target.id] = "constant"
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                imported.add((alias.asname or alias.name).split(".")[0])
    return defined, imported


def _kind_of(static) -> str:
    if isinstance(static, staticmethod):
        return "staticmethod"
    if isinstance(static, classmethod):
        return "classmethod"
    if isinstance(static, property):
        return "property"
    if callable(static):
        return "method"
    return "data:" + type(static).__name__


def class_surface(cls) -> dict:
    """Every non-dunder attribute reachable on the class, by kind."""
    out = {}
    for name in dir(cls):
        if name.startswith("__"):
            continue
        out[name] = _kind_of(inspect.getattr_static(cls, name, None))
    return out


def signature_of(obj) -> str:
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return ""


def compare_values(old, new, label: str) -> list:
    """Constants must be equal; functions must share a signature."""
    if callable(old) and callable(new):
        if signature_of(old) != signature_of(new):
            return [f"SIGNATURE CHANGED on {label}: "
                    f"{signature_of(old)} -> {signature_of(new)}"]
        return []
    if repr(old) != repr(new):
        return [f"VALUE CHANGED on {label}: {old!r} -> {new!r}"]
    return []


def compare_classes(old_cls, new_cls, label: str) -> list:
    problems = []
    old_surf, new_surf = class_surface(old_cls), class_surface(new_cls)
    for name in sorted(set(old_surf) - set(new_surf)):
        problems.append(f"{label}.{name} MISSING ({old_surf[name]})")
    for name in sorted(set(new_surf) - set(old_surf)):
        problems.append(f"{label}.{name} ADDED ({new_surf[name]})")
    for name in sorted(set(old_surf) & set(new_surf)):
        if old_surf[name] != new_surf[name]:
            problems.append(f"{label}.{name} KIND CHANGED: "
                            f"{old_surf[name]} -> {new_surf[name]}")
    return problems + _compare_class_signatures(old_cls, new_cls, label)


def _compare_class_signatures(old_cls, new_cls, label: str) -> list:
    """Signatures of the callables both classes resolve (inherited included)."""
    shared = set(class_surface(old_cls)) & set(class_surface(new_cls))
    problems = []
    for name in sorted(shared):
        old_attr = inspect.getattr_static(old_cls, name, None)
        new_attr = inspect.getattr_static(new_cls, name, None)
        if not (callable(old_attr) and callable(new_attr)):
            continue
        old_sig = signature_of(getattr(old_cls, name))
        new_sig = signature_of(getattr(new_cls, name))
        if old_sig != new_sig:
            problems.append(f"{label}.{name} SIGNATURE CHANGED: "
                            f"{old_sig} -> {new_sig}")
    return problems


def _rows_for(name: str, kind: str, old_module, new_module) -> list:
    """Every difference one defined name has, MISSING included."""
    if not hasattr(new_module, name):
        return [f"{kind} MISSING from the new module: {name}"]
    old_obj = getattr(old_module, name)
    new_obj = getattr(new_module, name)
    if kind == "class":
        return compare_classes(old_obj, new_obj, name)
    return compare_values(old_obj, new_obj, name)


def _split(rows: list, allowed: set) -> tuple[list, list]:
    """(rows nobody explained, rows an --allow-missing entry covers)."""
    return ([row for row in rows if not _allowable(row, allowed)],
            [row for row in rows if _allowable(row, allowed)])


def diff(old_module, new_module, allowed: set, strict_imports: bool) -> list:
    old_defined, old_imported = defined_names(old_module.__file__)
    problems, allowed_hits = [], []
    for name, kind in sorted(old_defined.items()):
        keep, waived = _split(_rows_for(name, kind, old_module, new_module),
                              allowed)
        problems += keep
        allowed_hits += waived
    problems += _import_report(old_imported, new_module, strict_imports)
    _verdict(old_defined, new_module, problems, allowed_hits)
    return problems


def _allowable(row: str, allowed: set) -> bool:
    """Does an --allow-missing entry (Name or Class.attr) cover this row?"""
    for name in allowed:
        if name in row:
            return True
    return False


def _import_report(old_imported, new_module, strict: bool) -> list:
    gone = sorted(n for n in old_imported if not hasattr(new_module, n))
    if gone and strict:
        return [f"imported name no longer reachable: {n}" for n in gone]
    if gone:
        print(f"  info: {len(gone)} name(s) the old file only imported are not "
              f"re-exported (not API): {', '.join(gone)}")
    return []


def _verdict(old_defined, new_module, problems, allowed_hits) -> None:
    reachable = sum(1 for n in old_defined if hasattr(new_module, n))
    label = "IDENTICAL" if not problems else f"{len(problems)} DIFFERENCE(S)"
    if allowed_hits:
        label += f" ({len(allowed_hits)} ALLOWED)"
    print(f"module surface: {len(old_defined)} defined name(s), "
          f"{reachable} reachable — {label}")
    for row in allowed_hits:
        print("  allowed: " + row)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("old_file", help="a copy of the pre-refactor module")
    ap.add_argument("new_module", help="import path of the refactored module")
    ap.add_argument("--allow-missing", action="append", default=[],
                    help="a deliberate removal (Name or Class.attr); "
                         "repeatable")
    ap.add_argument("--strict-imports", action="store_true",
                    help="also fail on imported names that are not re-exported")
    args = ap.parse_args()

    old_module = load_module_file(args.old_file)
    new_module = importlib.import_module(args.new_module)
    problems = diff(old_module, new_module, set(args.allow_missing),
                    args.strict_imports)
    for line in problems:
        print("  " + line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
