"""Generate the complete, deterministic Router QWebChannel contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def schema() -> dict:
    from PySide6.QtCore import QMetaMethod
    from bridge.router import Router

    meta = Router.staticMetaObject
    result = {"version": 1, "methods": {}, "signals": {}}
    for index in range(meta.methodOffset(), meta.methodCount()):
        method = meta.method(index)
        kind = method.methodType()
        if kind not in (QMetaMethod.Slot, QMetaMethod.Signal):
            continue
        group = "signals" if kind == QMetaMethod.Signal else "methods"
        name = bytes(method.name()).decode()
        if name in result[group]:
            raise ValueError(f"Overloaded wire member needs explicit schema support: {name}")
        result[group][name] = {
            "arity": method.parameterCount(),
            "params": [bytes(p).decode() for p in method.parameterTypes()],
            "return": method.typeName(),
        }
    return result


def render() -> str:
    return json.dumps(schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "ui/js/wire-schema.json")
    args = parser.parse_args()
    text = render()
    if args.check:
        return 0 if args.output.exists() and args.output.read_text() == text else 1
    args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
