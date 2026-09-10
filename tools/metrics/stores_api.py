#!/usr/bin/env python3
"""Regenerate `tests/unit/stores/api_baseline.json` — the frozen public surface
of `stores/`.

AREA B may only ADD names to `stores/`: every module-level public symbol, every
public method of every class, and the exact `inspect.signature` text (plus the
parameter names, so a documented *widening* can be checked for compatibility)
are pinned by `tests/unit/stores/test_stores_public_api.py`. The only names
allowed to change are the small-store constructors B1 widens on purpose —
see docs/archive/2026-09-09-four-area-refactor/REFACTOR_2026-09-09_AREA_B_DESIGN.md §6.1.

Run from the repo root:
    python tools/metrics/stores_api.py --write   # refresh the baseline
    python tools/metrics/stores_api.py           # diff it (exit 1 on drift)

`__all__`, when a module defines it, marks its re-exports as surface.

`tests/unit/stores/test_stores_public_api.py` applies the documented allowlist;
this command reports every difference, which is what a review wants to read.
"""
from __future__ import annotations

import importlib
import inspect
import json
import os
import pkgutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "tests", "unit", "stores", "api_baseline.json")

#: private names that other areas / other areas' tests reach across the
#: package border — they are part of the contract B must not break
EXTRA_PRIVATE = {
    "stores.history_repo": ("_last_ord",),
    "stores.media_store": ("_fetch_one", "_free_name", "_dirs"),
    "stores.history_db": ("_table_columns", "_repair_tables", "_verify_schema",
                           "_rebuild_legacy_messages", "_migrate_dup_keys",
                           "db_fetch_legacy", "LATE_COLUMNS",
                           "_add_missing_columns"),
    "stores.user_memory": ("_SCHEMA",),
}


def module_names() -> list[str]:
    pkg = importlib.import_module("stores")
    return sorted(f"stores.{info.name}"
                  for info in pkgutil.iter_modules(pkg.__path__))


def describe(obj) -> dict:
    """A comparable record of one callable/attribute."""
    if isinstance(obj, property):
        return {"kind": "property"}
    if isinstance(obj, (staticmethod, classmethod)):
        obj = obj.__func__
    try:
        sig = str(inspect.signature(obj))
    except (TypeError, ValueError):
        return {"kind": "opaque"}
    try:
        params = [name for name in inspect.signature(obj).parameters]
    except (TypeError, ValueError):
        params = []
    kind = "method"
    if inspect.isclass(obj):
        kind = "class"
    elif inspect.isfunction(obj):
        kind = "function"
    elif not callable(obj):
        kind = "constant"
    return {"kind": kind, "sig": sig, "params": params}


def class_surface(klass, private: tuple[str, ...]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name in sorted(dir(klass)):
        if name == "__init__":
            pass                        # widened on purpose by B1, checked below
        elif name.startswith("__"):
            continue
        elif name.startswith("_") and name not in private:
            continue
        member = getattr(klass, name, None)
        if isinstance(member, (staticmethod, classmethod)):
            out[name] = describe(member)
            continue
        if member is None:
            continue
        if isinstance(member, property) or inspect.isfunction(member) \
                or inspect.ismethod(member) or inspect.isbuiltin(member) \
                or inspect.isclass(member):
            out[name] = describe(member)
        else:
            record = describe(member)
            record["kind"] = "attribute"
            out[name] = record
    return out


def surface() -> dict:
    out: dict[str, dict] = {}
    for name in module_names():
        mod = importlib.import_module(name)
        private = EXTRA_PRIVATE.get(name, ())
        # a facade may re-export a helper that now lives in its own module; the
        # name stays part of the contract, and `__all__` is how it says so
        exports = set(getattr(mod, "__all__", ()) or ())
        entry: dict = {"functions": {}, "classes": {}, "constants": []}
        for attr, value in sorted(vars(mod).items()):
            if attr.startswith("_") and attr not in private:
                continue
            if attr.startswith("__"):
                continue
            owned = (getattr(value, "__module__", name) == name
                     or attr in exports)
            if inspect.isfunction(value) and owned:
                entry["functions"][attr] = describe(value)
            elif inspect.isclass(value) and owned:
                entry["classes"][attr] = class_surface(value, private)
            elif not callable(value) and attr.isupper():
                entry["constants"].append(attr)
        out[name] = entry
    return out


def diff(baseline: dict, current: dict, widened=(),
         allow_new_modules: bool = False) -> list[str]:
    """Every removal or signature change, compared with `widened` exemptions.

    A module that is not in the baseline at all is an *addition* — which is
    exactly how a decomposition inside `stores/` is allowed to look (design
    §6, gate 6) — so `allow_new_modules` silences it for the test while the
    command line keeps listing it for a reviewer.
    """
    problems: list[str] = []
    for module, expected in baseline.items():
        got = current.get(module)
        if got is None:
            problems.append(f"{module} disappeared")
            continue
        for func, record in expected["functions"].items():
            dotted = f"{module}.{func}"
            have = got["functions"].get(func)
            if have is None:
                problems.append(f"{dotted} removed")
            elif not compatible(record, have, dotted in widened):
                problems.append(f"{dotted} signature changed: "
                                f"{record.get('sig')} -> {have.get('sig')}")
        for const in expected["constants"]:
            if const not in got["constants"]:
                problems.append(f"{module}.{const} removed")
        for klass, methods in expected["classes"].items():
            if klass not in got["classes"]:
                problems.append(f"{module}.{klass} removed")
                continue
            live = got["classes"][klass]
            for meth, record in methods.items():
                dotted = f"{module}.{klass}.{meth}"
                have = live.get(meth)
                if have is None:
                    problems.append(f"{dotted} removed")
                elif not compatible(record, have, dotted in widened):
                    problems.append(f"{dotted} signature changed: "
                                    f"{record.get('sig')} -> {have.get('sig')}")
    for module in current:
        if module in baseline:
            continue
        if allow_new_modules:
            continue
        problems.append(f"{module} appeared without a baseline entry")
    return problems


def compatible(expected: dict, got: dict, widened: bool) -> bool:
    """Same surface, or a documented widening that keeps every parameter."""
    if expected == got:
        return True
    if expected.get("kind") != got.get("kind"):
        return False
    if not widened:
        return False
    want = set(expected.get("params") or ())
    return want <= set(got.get("params") or ())


def main() -> int:
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    current = surface()
    if "--write" in sys.argv:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as handle:
            json.dump(current, handle, indent=1, sort_keys=True)
            handle.write("\n")
        print(f"wrote {OUT}")
        return 0
    with open(OUT, encoding="utf-8") as handle:
        baseline = json.load(handle)
    problems = diff(baseline, current)
    if problems:
        print("API DRIFT (removals or undocumented signature changes):")
        for line in problems:
            print("  -", line)
        return 1
    print("stores/ public surface matches the baseline (additions allowed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
