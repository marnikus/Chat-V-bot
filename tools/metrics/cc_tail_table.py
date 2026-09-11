#!/usr/bin/env python3
"""Prioritised CC-tail table for a refactoring pass: before vs after.

Reads two `current_audit.py` dumps and two coverage reports and prints one
Markdown row per function that was over the CC gate (CC > 10) when the pass
began, with its state now. A function whose file is frozen by a structural test
is marked, so the number is not read as an oversight.

Functions are matched by `file::name`, not by line: every extraction moves
lines. A name used twice in one file is matched to the nearest line, so the
table cannot credit a fix that belongs to a sibling function.

Usage:
    python3 tools/metrics/cc_tail_table.py BEFORE_AUDIT AFTER_AUDIT \\
        BEFORE_COV AFTER_COV [--frozen stores/migration.py ...]
"""
from __future__ import annotations

import argparse
import json
import sys

CC_GATE = 10


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("before_audit")
    ap.add_argument("after_audit")
    ap.add_argument("before_cov")
    ap.add_argument("after_cov")
    ap.add_argument("--frozen", nargs="*", default=[])
    ap.add_argument("--gate", type=int, default=CC_GATE)
    return ap.parse_args(argv)


def load_functions(path: str) -> dict:
    """`file::name` -> the audit records for that name, in file order."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    out: dict[str, list] = {}
    for fn in data["functions"]:
        out.setdefault(f"{fn['file']}::{fn['name']}", []).append(fn)
    return out


def load_line_coverage(path: str) -> dict:
    """`file` -> line coverage percent, never coverage.py's combined number."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    out: dict[str, float] = {}
    for name, info in data["files"].items():
        summary = info["summary"]
        total = summary["num_statements"]
        out[name] = 100.0 if not total else (
            (total - summary["missing_lines"]) / total * 100)
    return out


def pick(records: list, line: int) -> dict:
    """The record whose line is nearest the baseline one (same name twice)."""
    return min(records, key=lambda fn: abs(fn["line"] - line))


def status_of(old: dict, now, path: str, frozen) -> str:
    """What happened to one offender, as one word the table can be sorted by."""
    if now is None:
        return "gone/renamed"
    if path in frozen:
        return "frozen"
    return "done" if now["cc"] <= CC_GATE else "open"


def row_for(key: str, old: dict, now, frozen) -> dict:
    """One table row: the offender as it was, as it is, and what that means."""
    return {
        "key": key, "path": key.split("::")[0],
        "old_cc": old["cc"], "old_cog": old.get("cognitive"),
        "new_cc": None if now is None else now["cc"],
        "new_cog": None if now is None else now.get("cognitive"),
        "new_loc": None if now is None else now["loc"],
        "status": status_of(old, now, key.split("::")[0], frozen),
    }


def offenders_of(functions: dict, gate: int) -> list:
    """Every `file::name` whose worst record is over the CC gate, by CC desc."""
    found = [(key, max(recs, key=lambda fn: fn["cc"] or 0))
             for key, recs in functions.items()
             if max(fn["cc"] or 0 for fn in recs) > gate]
    found.sort(key=lambda item: (-item[1]["cc"], item[0]))
    return found


def build_rows(args) -> list:
    after = load_functions(args.after_audit)
    return [row_for(key, old, pick(after[key], old["line"]) if key in after else None,
                    args.frozen)
            for key, old in offenders_of(load_functions(args.before_audit), args.gate)]


def _cell(value) -> str:
    """A table cell; an em-dash means the function is not in the tree any more."""
    return "—" if value is None else str(value)


def cov_cell(path: str, coverage: tuple) -> str:
    """This file's line coverage, before then after, or ? if it was not read."""
    return " → ".join("?" if table.get(path) is None
                      else f"{table[path]:.0f}%" for table in coverage)


def print_table(rows: list, coverage: tuple) -> None:
    print("| # | function | CC | CC now | cog | cog now | LOC now | line cov | status |")
    print("|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, start=1):
        cov = cov_cell(r["path"], coverage)
        print(f"| {i} | `{r['key']}` | {r['old_cc']} | {_cell(r['new_cc'])} | "
              f"{r['old_cog']} | {_cell(r['new_cog'])} | {_cell(r['new_loc'])} | "
              f"{cov} | {r['status']} |")


def print_summary(rows: list) -> int:
    def count(word: str) -> int:
        return sum(1 for r in rows if r["status"] == word)

    open_rows = [r for r in rows if r["status"] == "open"]
    worse = sum(1 for r in rows
                if r["new_cc"] is not None and r["new_cc"] > r["old_cc"])
    print()
    print(f"inventory: {len(rows)} functions over CC {CC_GATE} at the start; "
          f"fixed {count('done')}; frozen {count('frozen')}; "
          f"open {len(open_rows)}; worsened {worse}; "
          f"gone/renamed {count('gone/renamed')}")
    for r in rows:
        if r["status"] == "done":
            print(f"  fixed {r['key']}: CC {r['old_cc']} → {r['new_cc']}, "
                  f"cognitive {r['old_cog']} → {r['new_cog']}")
    return 1 if worse else 0


def main(argv=None) -> int:
    args = parse_args(argv)
    rows = build_rows(args)
    print_table(rows, (load_line_coverage(args.before_cov),
                       load_line_coverage(args.after_cov)))
    return print_summary(rows)


if __name__ == "__main__":
    sys.exit(main())
