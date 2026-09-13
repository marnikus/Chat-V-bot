#!/usr/bin/env python3
"""Diff a QObject's PUBLISHED surface against an older copy of the same class.

Why this exists: `bridge/router.py` builds the ONE QWebChannel class by
probing each domain bridge and enumerating its metaobject **from
`methodOffset()`**. That makes the wire API a property of the metaobject, not
of the source file — so a refactor can delete a slot from the published
surface without breaking a single import. Splitting a bridge into mixins is
safe only if the mixins are PLAIN classes: a signal or slot inherited from a
QObject *base* lands below `methodOffset()` and silently disappears.

This tool measures that instead of arguing about it. It compares three things
between an old module file and the class as it is importable today:

  1. the metaobject members published after `methodOffset()`
     (kind, name, parameter type names, return type name);
  2. every non-dunder attribute reachable on the class, and its kind
     (method / staticmethod / classmethod / property / Signal / …);
  3. the `inspect.signature` of every callable in both.

Usage (the old copy comes from git, the new one is imported):

    git show HEAD~1:bridge/history_bridge.py > /tmp/old_history_bridge.py
    python3 tools/metrics/qt_surface_diff.py \\
        /tmp/old_history_bridge.py HistoryBridge bridge.history_bridge

Exit 0 when the surfaces are identical, 1 on any difference. Needs a Qt
platform: run headless with QT_QPA_PLATFORM=offscreen (and
LD_LIBRARY_PATH=<stubs> on a machine without GL/X11 — `tools/build_stubs.py`).
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QMetaMethod  # noqa: E402

from bridge.context import BridgeContext  # noqa: E402


def _qt_text(value) -> str:
    """QByteArray (and bytes) → str; PySide6 already returns str in places."""
    try:
        return bytes(value).decode()
    except (TypeError, UnicodeDecodeError):
        return str(value)


def published(cls) -> set:
    """The metaobject members published after `methodOffset()`.

    Exactly what `bridge/router.py::_meta_members` reads, so a difference here
    IS a difference in the QWebChannel wire API.
    """
    probe = cls(BridgeContext())
    try:
        meta = probe.metaObject()
        out = set()
        for i in range(meta.methodOffset(), meta.methodCount()):
            method = meta.method(i)
            kind = method.methodType()
            label = ("signal" if kind == QMetaMethod.MethodType.Signal
                     else "slot" if kind == QMetaMethod.MethodType.Slot
                     else "method")
            out.add((label, _qt_text(method.name()),
                     tuple(_qt_text(p) for p in method.parameterTypes()),
                     _qt_text(method.typeName()) or None))
        return out
    finally:
        probe.deleteLater()


def attributes(cls) -> dict:
    """Every non-dunder attribute of the class, by kind."""
    out = {}
    for name in dir(cls):
        if name.startswith("__"):
            continue
        static = inspect.getattr_static(cls, name, None)
        if isinstance(static, staticmethod):
            kind = "staticmethod"
        elif isinstance(static, classmethod):
            kind = "classmethod"
        elif isinstance(static, property):
            kind = "property"
        elif callable(static):
            kind = "method"
        else:
            kind = type(static).__name__
        out[name] = kind
    return out


def signatures(cls, names) -> dict:
    out = {}
    for name in names:
        try:
            out[name] = str(inspect.signature(getattr(cls, name)))
        except (AttributeError, TypeError, ValueError):
            continue
    return out


def load_module_file(path: str, name: str = "_qt_surface_old"):
    """Import a standalone copy of a module (e.g. `git show HEAD~1:file.py`)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def attribute_rows(old_cls, new_cls, label: str) -> tuple[list, list]:
    """(rows about missing / added / re-kinded attributes, shared names)."""
    old_attrs, new_attrs = attributes(old_cls), attributes(new_cls)
    rows = []
    for name in sorted(set(old_attrs) - set(new_attrs)):
        rows.append(f"attribute MISSING from the new {label}: "
                    f"{name} ({old_attrs[name]})")
    for name in sorted(set(new_attrs) - set(old_attrs)):
        rows.append(f"attribute ADDED by the new {label}: "
                    f"{name} ({new_attrs[name]})")
    for name in sorted(set(old_attrs) & set(new_attrs)):
        if old_attrs[name] != new_attrs[name]:
            rows.append(f"attribute KIND CHANGED on {label}.{name}: "
                        f"{old_attrs[name]} -> {new_attrs[name]}")
    return rows, sorted(set(old_attrs) & set(new_attrs))


def _metaobject_rows(old_pub: set, new_pub: set, label: str) -> list:
    rows = []
    for row in sorted(old_pub - new_pub):
        rows.append(f"metaobject member MISSING from the new {label}: {row}")
    for row in sorted(new_pub - old_pub):
        rows.append(f"metaobject member ADDED by the new {label}: {row}")
    return rows


def diff(old_cls, new_cls, label: str) -> list:
    old_pub, new_pub = published(old_cls), published(new_cls)
    problems = _metaobject_rows(old_pub, new_pub, label)
    attr_rows, shared = attribute_rows(old_cls, new_cls, label)
    problems += attr_rows

    old_sig, new_sig = signatures(old_cls, shared), signatures(new_cls, shared)
    for name in shared:
        if name in old_sig and name in new_sig and old_sig[name] != new_sig[name]:
            problems.append(f"SIGNATURE CHANGED on {label}.{name}: "
                            f"{old_sig[name]} -> {new_sig[name]}")

    print(f"{label}: {len(new_pub)} published metaobject members, "
          f"{len(attributes(new_cls))} attributes — "
          + ("IDENTICAL" if not problems else f"{len(problems)} DIFFERENCE(S)"))
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("old_file", help="a copy of the pre-refactor module")
    ap.add_argument("class_name")
    ap.add_argument("new_module", help="import path of the refactored module")
    args = ap.parse_args()

    old_cls = getattr(load_module_file(args.old_file), args.class_name)
    new_cls = getattr(importlib.import_module(args.new_module), args.class_name)
    problems = diff(old_cls, new_cls, args.class_name)
    for line in problems:
        print("  " + line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
