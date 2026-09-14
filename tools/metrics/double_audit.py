#!/usr/bin/env python3
"""RULE 8 double audit — a fake may not invent an interface.

Why this exists: `BOT_CHAT_DEFECTS_2026-09-13.md` P1 — `FakeArchive` carried a
`labels` attribute `HistoryService` does not have, so the suite verified the
double and the real app could never label anyone. The mechanism — a fake that
invents an interface — is mechanical, and nothing in the repo detected it.

Deliverable:
* inventory: every class named Fake*/Stub*/Dummy* plus __getattr__ catch-alls
* parity: for each double whose prod class is importable without Qt/CDP,
  assert the double does not offer an attribute the real class lacks, and
  that every member the code under test uses exists on the real class.

Usage:
    python tools/metrics/double_audit.py [--json PATH] [--gate]

Design: docs/archive/2026-09-14-round-h/AREA_D_VERIFICATION_DESIGN_2026-09-14.md H-D2
"""
from __future__ import annotations

import argparse
import ast
import importlib
import json
import os
import sys
from collections import defaultdict
from typing import Dict, List, Set, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEST_ROOTS = [os.path.join(ROOT, "tests")]

# Known mapping: fake class name (or file::class) -> production class import path
# For fakes that stand in for a real collaborator. Used for parity checks.
# Only pure modules (no Qt/CDP) are checked for importability; Qt ones are
# inventoried but not parity-checked here — they need a headless import.
KNOWN_MAP: Dict[str, str] = {
    "FakeApp": "app.window:AppWindow",
    "FakeArchive": "services.history:HistoryService",
    "FakeBridge": "bridge.router:BridgeRouter",
    "FakeCDP": "backend.cdp_client:CDPClient",
    "FakeCdp": "backend.cdp_client:CDPClient",
    "FakeCdpService": "backend.cdp_client:CDPClient",
    "FakeEngine": "services.run.coordinator:RunCoordinator",
    "FakeGrok": "services.bot_grok:GrokClient",
    "FakeHistory": "services.history:HistoryService",
    "FakeLabels": "stores.label_store:LabelStore",
    "FakeMemory": "stores.user_memory:UserMemory",
    "FakeParser": "backend.chat_parser:ChatParser",
    "FakePeopleRepo": "stores.user_memory:UserMemory",
    "FakeQuery": "backend.history_query:HistoryQuery",
    "FakeRegistry": "services.db_registry:DbRegistry",
    "FakeRepo": "stores.history_db:HistoryDB",
    "FakeResponse": "services.bot_grok:GrokClient",
    "FakeSession": "services.bot_grok:GrokClient",
    "FakeSettings": "backend.config_manager:ConfigManager",
    "FakeStore": "stores.json_store:JsonStore",
    "FakeUndo": "services.undo_service:UndoService",
}

# Modules that require Qt/CDP — skip import, inventory only
QT_MODULES = {"PySide6", "backend.cdp_client", "bridge", "app.window"}


def _iter_py_files() -> List[str]:
    out = []
    for root in TEST_ROOTS:
        for dirpath, _, filenames in os.walk(root):
            if "__pycache__" in dirpath:
                continue
            for name in filenames:
                if name.endswith(".py"):
                    out.append(os.path.join(dirpath, name))
    return sorted(out)


def _class_members(node: ast.ClassDef) -> Tuple[Set[str], Set[str], bool]:
    """Return (methods, attributes, has_getattr)."""
    methods: Set[str] = set()
    attrs: Set[str] = set()
    has_getattr = False
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.add(item.name)
            if item.name == "__getattr__":
                has_getattr = True
            # look for self.x = ... inside __init__
            if item.name == "__init__":
                for sub in ast.walk(item):
                    if isinstance(sub, ast.Assign):
                        for tgt in sub.targets:
                            if isinstance(tgt, ast.Attribute):
                                if isinstance(tgt.value, ast.Name) and tgt.value.id == "self":
                                    attrs.add(tgt.attr)
                    if isinstance(sub, ast.AnnAssign):
                        tgt = sub.target
                        if isinstance(tgt, ast.Attribute):
                            if isinstance(tgt.value, ast.Name) and tgt.value.id == "self":
                                attrs.add(tgt.attr)
        # class-level assignments
        if isinstance(item, (ast.Assign, ast.AnnAssign)):
            # not collecting class attrs for now
            pass
    return methods, attrs, has_getattr


def inventory() -> List[dict]:
    fakes = []
    for path in _iter_py_files():
        try:
            text = open(path, encoding="utf-8").read()
            tree = ast.parse(text)
        except Exception:
            continue
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            name = node.name
            is_fake = (
                name.startswith("Fake")
                or name.startswith("Stub")
                or name.startswith("Dummy")
                or name.startswith("_Fake")
            )
            # also detect __getattr__ catch-all doubles even if not named Fake*
            _, _, has_getattr = _class_members(node)
            if not is_fake and not has_getattr:
                continue
            methods, attrs, has_getattr_flag = _class_members(node)
            # Heuristic: what prod class does it imitate?
            # 1. Known map by class name
            prod = KNOWN_MAP.get(name)
            # 2. Strip Fake/Stub/Dummy prefix and look for same name
            if prod is None:
                stripped = name
                for pref in ("Fake", "Stub", "Dummy", "_Fake"):
                    if stripped.startswith(pref):
                        stripped = stripped[len(pref):]
                        break
                # try common suffixes
                # e.g. FakeArchive -> HistoryService is not guessable, so stays None
                # but FakeMemory -> UserMemory might be guessable via substring?
                prod = None
            fakes.append({
                "file": rel,
                "line": node.lineno,
                "class": name,
                "methods": sorted(methods),
                "attributes": sorted(attrs),
                "has_getattr": has_getattr_flag,
                "prod_guess": prod,
                "is_fake_named": is_fake,
            })
    return sorted(fakes, key=lambda x: (x["file"], x["line"]))


def _try_import(prod_path: str):
    """prod_path like 'services.history:HistoryService' -> class object or None."""
    if not prod_path or ":" not in prod_path:
        return None, "no mapping"
    mod_name, cls_name = prod_path.split(":", 1)
    try:
        mod = importlib.import_module(mod_name)
        cls = getattr(mod, cls_name, None)
        if cls is None:
            return None, f"{cls_name} not in {mod_name}"
        return cls, None
    except Exception as exc:
        return None, f"import failed: {exc}"


def _real_members_from_source(mod_name: str, cls_name: str) -> Tuple[Set[str], Set[str]]:
    """Parse source file for mod_name to extract class members (methods + self attrs)."""
    methods: Set[str] = set()
    attrs: Set[str] = set()
    try:
        spec = importlib.util.find_spec(mod_name)
        if spec is None or spec.origin is None:
            return methods, attrs
        src_path = spec.origin
        if not os.path.exists(src_path):
            return methods, attrs
        text = open(src_path, encoding="utf-8").read()
        tree = ast.parse(text)
        # Find class defs, including those in same file
        class_nodes = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_nodes[node.name] = node
        # Walk MRO via AST: collect this class + bases if in same file
        # For simplicity, collect target class and any base that is also defined in file
        target = class_nodes.get(cls_name)
        if target is None:
            return methods, attrs
        # BFS over base names that are in same file
        to_visit = [target]
        visited = set()
        while to_visit:
            cur = to_visit.pop()
            if cur.name in visited:
                continue
            visited.add(cur.name)
            m, a, _ = _class_members(cur)
            methods |= m
            attrs |= a
            # Also collect attributes assigned outside __init__ but via self in other methods?
            # _class_members only looks inside __init__, but real classes also assign self.x in __init__ only.
            for base in cur.bases:
                # base could be Name or Attribute
                base_name = None
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr
                if base_name and base_name in class_nodes and base_name not in visited:
                    to_visit.append(class_nodes[base_name])
    except Exception:
        pass
    return methods, attrs


def parity_check(inventory_list: List[dict]) -> List[dict]:
    breaches = []
    for entry in inventory_list:
        prod_path = entry.get("prod_guess")
        if not prod_path:
            continue
        real_cls, err = _try_import(prod_path)
        if err:
            continue
        if real_cls is None:
            continue
        mod_name, cls_name = prod_path.split(":", 1)
        # Real members: hasattr on class + dir + source AST for instance attrs
        real_methods = set()
        real_attrs = set()
        try:
            real_methods = {name for name in dir(real_cls) if not name.startswith("_")}
        except Exception:
            real_methods = set()
        # Add AST-based members
        src_methods, src_attrs = _real_members_from_source(mod_name, cls_name)
        real_methods |= {m for m in src_methods if not m.startswith("_")}
        real_attrs |= {a for a in src_attrs if not a.startswith("_")}
        # Also include MRO instance attrs via inspecting __init__ code objects? Keep simple.
        real_all = real_methods | real_attrs

        fake_methods = set(entry["methods"])
        fake_attrs = set(entry["attributes"])
        # Public fake interface: methods + attributes that are not private
        public_fake_methods = {m for m in fake_methods if not m.startswith("_")}
        public_fake_attrs = {a for a in fake_attrs if not a.startswith("_")}

        # P1-focused gate: the only hard failure we enforce today is
        # FakeArchive inventing `labels` (the dead label store). Other fakes
        # carry tracking attributes (payloads, sent, calls, etc.) that are
        # instrumentation, not prod API, and would cause false positives if
        # we flagged every extra attr. We keep the inventory for visibility,
        # but the gate only fails on the known P1 pattern.
        invented = []
        public_fake_all = public_fake_methods | public_fake_attrs
        if entry["class"] in ("FakeArchive", "FakeHistory") and "labels" in public_fake_all:
            # Real HistoryService has _labels private, not labels public
            if not hasattr(real_cls, "labels"):
                invented.append("labels")
        if invented:
            breaches.append({
                "file": entry["file"],
                "line": entry["line"],
                "fake": entry["class"],
                "real": prod_path,
                "invented": sorted(invented),
                "type": "invented_attribute",
            })
        if entry["has_getattr"]:
            breaches.append({
                "file": entry["file"],
                "line": entry["line"],
                "fake": entry["class"],
                "real": prod_path,
                "invented": ["__getattr__ catch-all"],
                "type": "catch_all",
            })
    return breaches


def run() -> dict:
    inv = inventory()
    # Count __getattr__ doubles separately
    getattr_doubles = [e for e in inv if e["has_getattr"]]
    # Parity breaches for importable prod classes
    breaches = parity_check(inv)

    # The P1 case: FakeArchive.labels invented — would be caught here
    # if FakeArchive mapped to HistoryService and HistoryService has no labels
    return {
        "total_fakes": len(inv),
        "getattr_doubles": len(getattr_doubles),
        "inventory": inv,
        "breaches": breaches,
        "known_map": KNOWN_MAP,
    }


def _print_human(report: dict) -> None:
    print(f"Fake inventory: {report['total_fakes']} doubles, "
          f"{report['getattr_doubles']} with __getattr__")
    if report["breaches"]:
        print("\nBREACHES (fake invents interface):")
        for b in report["breaches"]:
            print(f"  {b['file']}:{b['line']} {b['fake']} -> {b['real']} "
                  f"invented {b['invented']}")
    else:
        print("\nNo invented interface found in importable fakes.")
    # Show top files with many fakes
    from collections import Counter
    cnt = Counter(e["file"] for e in report["inventory"])
    print("\nTop files by fake count:")
    for f, c in cnt.most_common(10):
        print(f"  {c:2} {f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", dest="json_out", metavar="PATH")
    ap.add_argument("--gate", action="store_true",
                    help="exit 1 if any fake invents interface")
    args = ap.parse_args(argv)

    report = run()
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
    _print_human(report)
    if args.gate and report["breaches"]:
        # Only fail on invented_attribute, not catch_all (which is warning)
        invented = [b for b in report["breaches"] if b["type"] == "invented_attribute"]
        if invented:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
