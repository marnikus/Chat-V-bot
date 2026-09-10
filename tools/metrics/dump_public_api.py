#!/usr/bin/env python3
"""Dump the public API of the AREA D packages into a golden JSON snapshot.

The refactor plan (docs/REFACTOR_2026-09-09_FOUR_AREA_PLAN.md §8.3 Gate 6)
allows a branch to ADD public symbols and forbids it to CHANGE or REMOVE
any. `tests/unit/backend/test_backend_api_snapshot.py` enforces exactly that
against the snapshot written here, for `backend/**` and `actions/**` — the two
packages AREA D owns.

What is captured per module:

  * every public module-level function: its signature;
  * every public class: bases, its public method signatures (plus
    ``__init__``/``__init_subclass__``), its public class attributes, and —
    for dataclasses — the field names, types and default reprs;
  * for ``actions`` blocks additionally: the ``config_schema()`` output, the
    default ``to_dict()`` and the full ``__init__`` signature, because those
    three ARE the preset wire format (RULE 3).

Usage:
    python3 tools/metrics/dump_public_api.py --write      # refresh the golden file
    python3 tools/metrics/dump_public_api.py --diff       # report drift, exit 1
"""
from __future__ import annotations

import argparse
import dataclasses
import inspect
import json
import os
import pkgutil
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

SNAPSHOT = os.path.join(ROOT, "tests", "unit", "backend",
                        "backend_api_snapshot.json")
BLOCKS = os.path.join(ROOT, "tests", "unit", "actions",
                      "block_wire_snapshot.json")


def _sig(obj) -> str:
    """Signature string with object reprs stabilised (``0x7f…`` addresses
    differ per process, which would make the golden file flap)."""
    try:
        text = str(inspect.signature(obj))
    except (TypeError, ValueError):
        return "<builtin>"
    return re.sub(r"0x[0-9a-fA-F]+", "0xADDR", text)


def _default_repr(value) -> str:
    if isinstance(value, (str, int, float, bool, type(None), list, tuple, dict)):
        return repr(value)
    return f"<{type(value).__name__}>"


def module_names(package: str):
    pkg = __import__(package, fromlist=["__path__"])
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.ispkg:
            continue
        yield f"{package}.{info.name}"


def dump_module(qualname: str) -> dict:
    try:
        mod = __import__(qualname, fromlist=["__name__"])
    except Exception as exc:                      # noqa: BLE001
        return {"import_error": repr(exc)}
    out = {"functions": {}, "classes": {}, "values": {}}
    for name, obj in sorted(vars(mod).items()):
        if name.startswith("_"):
            continue
        owner = getattr(obj, "__module__", None)
        if inspect.isfunction(obj) and owner == qualname:
            out["functions"][name] = _sig(obj)
        elif inspect.isclass(obj) and owner == qualname:
            out["classes"][name] = dump_class(obj)
        elif owner == qualname and not isinstance(obj, types.ModuleType):
            if isinstance(obj, (str, int, float, bool, type(None), tuple)):
                out["values"][name] = repr(obj)
            elif isinstance(obj, (list, dict, set)):
                out["values"][name] = f"<{type(obj).__name__} len={len(obj)}>"
    return out


def dump_class(cls: type) -> dict:
    data = {"bases": [b.__name__ for b in cls.__bases__],
            "methods": {}, "attrs": {}, "fields": {}}
    for name, obj in sorted(vars(cls).items()):
        keep_dunder = name in ("__init__", "__init_subclass__", "__bool__",
                               "__call__", "__post_init__", "__await__")
        if name.startswith("_") and not keep_dunder:
            continue      # privates are this area's own business (Gate 6 = public API)
        if inspect.isfunction(obj) or isinstance(obj, (classmethod, staticmethod)):
            fn = obj.__func__ if isinstance(obj, (classmethod, staticmethod)) else obj
            data["methods"][name] = _sig(fn)
        elif isinstance(obj, property):
            data["methods"][name] = "<property>"
        elif isinstance(obj, (str, int, float, bool, type(None), tuple)):
            data["attrs"][name] = repr(obj)
        elif isinstance(obj, (list, dict)):
            data["attrs"][name] = _default_repr(obj)
    if dataclasses.is_dataclass(cls):
        for f in cls.__dataclass_fields__.values():
            default = getattr(f, "default", inspect.Parameter.empty)
            data["fields"][f.name] = {
                "type": getattr(f.type, "__name__", str(f.type)),
                "default": None if default is inspect.Parameter.empty
                else _default_repr(default),
            }
    return data


def _shipped_blocks() -> dict:
    """Every block class, read from the module that defines it.

    Deliberately not `ActionRegistry.all_ids()`: the registry is process-wide
    state, and the suite has tests that register a probe under an existing
    block id to prove re-registration works. The snapshot is a statement about
    the SHIPPED code, so it walks `actions/*.py` instead.
    """
    import importlib

    from actions.base_action import BaseAction
    import actions as actions_pkg          # importing runs the registry scan
    del actions_pkg

    out: dict[str, type] = {}
    root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "actions")
    for info in pkgutil.iter_modules([root]):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"actions.{info.name}")
        for obj in vars(module).values():
            if not isinstance(obj, type) or not issubclass(obj, BaseAction):
                continue
            block_id = getattr(obj, "block_id", "")
            if not block_id or obj.__module__ != module.__name__:
                continue
            out[block_id] = obj
    return out


def dump_blocks() -> dict:
    out = {}
    for block_id, cls in sorted(_shipped_blocks().items()):
        try:
            instance = cls()
            schema, as_dict = instance.config_schema(), instance.to_dict()
        except Exception as exc:                    # noqa: BLE001
            schema, as_dict = {"error": repr(exc)}, {}
        out[block_id] = {
            "class": f"{cls.__module__}.{cls.__name__}",
            "init": _sig(cls.__init__),
            "schema": {k: {kk: _default_repr(vv) for kk, vv in v.items()}
                       for k, v in sorted(schema.items())
                       if isinstance(v, dict)},
            "schema_keys": list(schema),
            "to_dict": {k: _default_repr(v) for k, v in sorted(as_dict.items())},
        }
    return out


def _all_ids():
    from actions.registry import ActionRegistry
    return ActionRegistry.all_ids()


def build() -> dict:
    api = {}
    for pkg in ("backend", "actions"):
        for qualname in module_names(pkg):
            api[qualname] = dump_module(qualname)
    return {"public_api": api, "blocks": dump_blocks()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--out", default=None, help="public-API snapshot path")
    ap.add_argument("--blocks", default=None, help="block wire snapshot path")
    args = ap.parse_args(argv)

    data = build()
    actual = data
    if args.write:
        snapshot = args.out or SNAPSHOT
        blocks = args.blocks or BLOCKS
        for path, payload in ((snapshot, data), (blocks, data["blocks"])):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=1, sort_keys=True,
                          ensure_ascii=False)
                fh.write("\n")
            print(f"wrote {path}")
        return 0

    with open(args.out or SNAPSHOT, encoding="utf-8") as fh:
        expected = json.load(fh)
    with open(args.blocks or BLOCKS, encoding="utf-8") as fh:
        expected_blocks = json.load(fh)
    problems = []
    for qualname, mod in expected["public_api"].items():
        now = actual["public_api"].get(qualname)
        if now is None:
            problems.append(f"module {qualname} disappeared")
            continue
        if now.get("import_error"):
            problems.append(f"{qualname}: {now['import_error']}")
            continue
        for kind, entries in mod.items():
            for name, want in entries.items():
                have = now.get(kind, {})
                if name not in have:
                    problems.append(f"{qualname}.{name} ({kind}) removed")
                elif kind == "classes" and want != have[name]:
                    for sub in want:
                        if sub == "methods":
                            for m, sig in want["methods"].items():
                                if have[name]["methods"].get(m) != sig:
                                    problems.append(
                                        f"{qualname}.{name}.{m}{sig} → "
                                        f"{have[name]['methods'].get(m)!r}")
                        elif want[sub] != have[name].get(sub):
                            problems.append(f"{qualname}.{name}.{sub} changed")
                elif kind != "classes" and want != have[name]:
                    problems.append(f"{qualname}.{name} ({kind}) {want!r} → "
                                    f"{have[name]!r}")
    for block_id, want in expected_blocks.items():
        have = actual["blocks"].get(block_id)
        if have is None:
            problems.append(f"block {block_id} is no longer registered")
            continue
        for key in ("init", "schema", "schema_keys", "to_dict"):
            if want[key] != have[key]:
                problems.append(f"block {block_id}.{key} changed")
    if problems:
        print("PUBLIC API DRIFT (new symbols are allowed; these are not new):")
        for line in problems:
            print("  ✗", line)
        return 1
    print("public API: no removed or changed symbols")
    return 0


if __name__ == "__main__":
    sys.exit(main())
