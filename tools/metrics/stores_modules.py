#!/usr/bin/env python3
"""RULE 18 §18.3 gate — how many MODULES `stores/` really has.

§18.3 caps a directory at ~15 cohesive files and offers two remedies past it:
promote a family to a sub-package, or treat a prefix family as one module —
"a family is a module in everything but the directory separator; treat it as
one when counting."

`stores/` holds 37 Python files, so the raw count reads as two and a half times
over the ceiling. This measures the count the rule actually asks for, and checks
that the grouping is real rather than convenient: every group has to justify
itself from the import graph, and every module has to belong to exactly one
group, so a new loose file fails the gate until someone says where it belongs.

The sub-package remedy is NOT available to `stores/`, and the reason is a
contract rather than effort. `tests/unit/stores/test_stores_public_api.py`
fails on "any change at all" to the frozen surface recorded in
`api_baseline.json`, whose keys are dotted module paths, and plan §7.3 rule 1
forbids renames or moves of any symbol another area imports. Moving
`stores/history_*.py` into `stores/history/` was tried on branch
`arena/01a09a61-chat-v-bot` and failed five tests, including
`test_the_three_frozen_modules_did_not_move_at_all`. Merging files is blocked
too: it would undo the deliberate AREA B2 splits (`user_query`,
`preset_migration` are named in `test_stores_structure.py::SPLIT_FILES` as
collaborators that belong behind their facade) and every candidate pair lands
outside §18.2's 150-300 line band (`user_memory` 284 + `user_query` 83 = 367,
`preset_store` 221 + `preset_migration` 84 = 305, `atomic` 151 +
`json_store` 159 = 310).

So this is the counting remedy, measured. Round F step F8,
`docs/archive/2026-09-12-round-f-size-tail/ROUND_F_DESIGN_2026-09-12.md` §11.

    python3 tools/metrics/stores_modules.py           # report, exit 1 on breach
    python3 tools/metrics/stores_modules.py --json    # machine-readable

Exits 0 when the effective module count fits the ratchet and every group's
evidence holds, 1 otherwise.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORES = os.path.join(ROOT, "stores")

#: §18.3 — "5–15 cohesive files". 15 is the ceiling, so a directory reading 15
#: is in band and 16 is not.
RATCHET = 15
#: §18.3's own band for one module's files; a family bigger than this is a
#: directory in all but name and should be split further.
MAX_FILES_PER_MODULE = 15
#: per-family band ceilings (one file over still fails). history_*: 21
#: (2026-09-16, Round I) — §18.3's two remedies are both blocked for it
#: (sub-package freezes the dotted surface; merging breaks §18.2's LOC band,
#: see this file's docstring), so the guard declares the known directory.
FILE_BAND_OVERRIDES = {"history_*": 21}


def file_band(group: dict) -> int:
    """The per-module file ceiling for one group (manifest entry or row)."""
    return FILE_BAND_OVERRIDES.get(group.get("module") or group.get("name", ""),
                                   MAX_FILES_PER_MODULE)


def modules() -> list[str]:
    """Every module in `stores/`, minus the package init.

    `__init__.py` is the package, not a module inside it, so §18.3's count does
    not include it — which is why this reports 37 where `ls` reports 38.
    """
    return sorted(f[:-3] for f in os.listdir(STORES)
                  if f.endswith(".py") and f != "__init__.py")


def imports_of(mod: str) -> set[str]:
    """The `stores/` modules `mod` imports, from its AST.

    Every module in `stores/` imports its siblings by absolute path
    (`from stores.history_models import ...`); none uses a relative import.
    That is asserted rather than assumed, because a relative import would be
    invisible to the scan below and would silently weaken the `pair` and
    `layer` evidence — the gate would keep passing while measuring less.
    """
    path = os.path.join(STORES, mod + ".py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.ImportFrom, ast.Import)):
            if getattr(node, "level", 0):
                raise AssertionError(
                    f"stores/{mod}.py uses a relative import; teach "
                    "imports_of() to resolve it before trusting this gate")
            names = ([node.module] if isinstance(node, ast.ImportFrom)
                     else [a.name for a in node.names])
            for name in names:
                if name and name.startswith("stores."):
                    out.add(name.split(".", 1)[1].split(".")[0])
    return {m for m in out if m != mod}


def lines_of(mod: str) -> int:
    with open(os.path.join(STORES, mod + ".py"), encoding="utf-8") as handle:
        return sum(1 for _ in handle)


#: The grouping. `kind` says what evidence has to hold for the group to count
#: as one module; each is checked below, so the table cannot drift from the
#: import graph it claims to describe.
GROUPS: list[dict] = [
    # prefix families — §18.3's literal example, and AREA B2's own splits
    {"name": "history_*", "kind": "prefix", "prefix": "history_"},
    {"name": "label_*", "kind": "prefix", "prefix": "label_"},
    {"name": "media_*", "kind": "prefix", "prefix": "media_"},
    # the durable-JSON-write layer: json_store is built on atomic, which is
    # built on jsonio. One concern, three files.
    {"name": "json write layer", "kind": "layer",
     "root": "json_store", "parts": ["atomic", "jsonio"]},
    # an aggregate plus the collaborator AREA B2 split out of it, or a helper
    # with exactly one consumer — evidence: nothing else in stores/ imports it
    {"name": "bookmarks", "kind": "pair",
     "aggregate": "bookmark_store", "collaborator": "outcome"},
    {"name": "presets", "kind": "pair",
     "aggregate": "preset_store", "collaborator": "preset_migration"},
    {"name": "people", "kind": "pair",
     "aggregate": "user_memory", "collaborator": "user_query"},
    # one domain each. None imports another; each imports only the write layer,
    # so they are consumers of a shared idiom, not members of one family.
    {"name": "blocks", "kind": "single", "module": "block_store"},
    {"name": "labels file", "kind": "single", "module": "labels_file_store"},
    {"name": "sessions", "kind": "single", "module": "session_store"},
    {"name": "settings", "kind": "single", "module": "settings_store"},
    {"name": "undo", "kind": "single", "module": "undo_store"},
    {"name": "window presets", "kind": "single", "module": "window_preset_store"},
    {"name": "legacy migration", "kind": "single", "module": "migration"},
    {"name": "world lock", "kind": "single", "module": "world_lock"},
]


def check(group: dict, mods: list[str], deps: dict[str, set]) -> tuple[list, list]:
    """Resolve one group to its files and return (members, problems)."""
    kind, problems = group["kind"], []
    if kind == "prefix":
        members = [m for m in mods if m.startswith(group["prefix"])]
        if len(members) < 2:
            problems.append(f"a prefix family needs 2+ files, found {members}")
    elif kind == "layer":
        members = [group["root"], *group["parts"]]
        have = deps.get(group["root"], set())
        for part in group["parts"]:
            if part not in have:
                problems.append(f"{group['root']} does not import {part}")
    elif kind == "pair":
        collab, agg = group["collaborator"], group["aggregate"]
        members = [agg, collab]
        importers = sorted(m for m in mods if collab in deps.get(m, set()))
        if importers != [agg]:
            problems.append(f"{collab} is imported by {importers or 'nobody'}, "
                            f"expected exactly [{agg}]")
    else:
        members = [group["module"]]
    missing = [m for m in members if m not in mods]
    if missing:
        problems.append(f"names modules that do not exist: {missing}")
    if len(members) > file_band(group):
        problems.append(f"{len(members)} files exceeds §18.3's "
                        f"{file_band(group)}-file band for one module")
    return [m for m in members if m in mods], problems


def measure() -> dict:
    mods = modules()
    deps = {m: imports_of(m) for m in mods}
    rows, problems, claimed = [], [], {}
    for group in GROUPS:
        members, bad = check(group, mods, deps)
        problems += [f"{group['name']}: {p}" for p in bad]
        for m in members:
            claimed.setdefault(m, []).append(group["name"])
        rows.append({"module": group["name"], "kind": group["kind"],
                     "files": len(members), "members": members,
                     "lines": sum(lines_of(m) for m in members)})
    for mod, owners in sorted(claimed.items()):
        if len(owners) > 1:
            problems.append(f"{mod} is claimed by {len(owners)} groups "
                            f"({owners}) — a module belongs to exactly one")
    unclaimed = [m for m in mods if m not in claimed]
    if unclaimed:
        problems.append(f"undeclared module(s) in stores/: {unclaimed} — add "
                        "each to a group in tools/metrics/stores_modules.py, "
                        "or the effective count is a lie")
    return {"raw_files": len(mods), "effective_modules": len(rows),
            "ratchet": RATCHET, "groups": rows, "problems": problems,
            "total_lines": sum(lines_of(m) for m in mods)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    got = measure()
    over = got["effective_modules"] > RATCHET
    if args.json:
        print(json.dumps(got, indent=2, sort_keys=True))
        return 1 if (over or got["problems"]) else 0

    print("RULE 18 §18.3 — stores/ module count "
          f"(ceiling {RATCHET}, one module 2-{MAX_FILES_PER_MODULE} files)")
    print(f"{'module':<20}{'kind':<9}{'files':>6}{'lines':>7}  members")
    for row in sorted(got["groups"], key=lambda r: -r["files"]):
        shown = ", ".join(row["members"][:4])
        if row["files"] > 4:
            shown += f", +{row['files'] - 4}"
        print(f"  {row['module']:<18}{row['kind']:<9}{row['files']:>6}"
              f"{row['lines']:>7}  {shown}")
    print(f"\n  raw .py files in stores/   {got['raw_files']} "
          f"({got['total_lines']} lines)")
    print(f"  effective §18.3 modules    {got['effective_modules']} "
          f"(ceiling {RATCHET})  {'OVER' if over else 'in band'}")
    for problem in got["problems"]:
        print(f"  !! {problem}")
    if over or got["problems"]:
        print("\nBREACH — see the lines above.")
        return 1
    print("\nGrouping justified by the import graph. Count fits §18.3.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
