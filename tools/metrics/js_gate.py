#!/usr/bin/env python3
"""JavaScript quality gate (Round H, step H-A2) — the RULE 16 mirror for JS.

RULE 16 §16.0/§16.5 has two faces: hard limits on NEW code, and a ratchet on
legacy code that may only get smaller / better. This gate applies the same
two faces to the frontend (`ui/js/**` + `backend/js/**`), whose two god
objects (SashGrid 1,331 LOC / 69 methods, StackDnD 1,168 / 58) had sat
outside every gate for four rounds of Python refactoring.

Checks (frozen in reports/JS_SIZE_BASELINE_2026-09-14.md):

| Check                | Fail if                                                        |
|----------------------|----------------------------------------------------------------|
| File LOC             | a file exceeds max(500, its baseline) — new files: 500        |
| Function/method LOC  | a NEW function exceeds 30; a baseline function GROWS          |
| Object literal LOC   | a file's largest gated object exceeds max(150, baseline max)  |
| Methods per object   | a file's max exceeds max(15, baseline max)                    |
| Per-file coverage    | drops below its baseline; a never-loaded file stays at 0      |
| Node suites          | any tests/test_*.js fails                                      |

Size is measured by tools/metrics/js_size.py (same counting rule), coverage
by tools/metrics/js_coverage.py — both re-run live; the baselines are the
committed reports/js_size_baseline.json + reports/js_coverage_baseline.json.
A separate script by design: it cannot collide with other areas' edits to
rule16_gate.py (Round H area ownership).

Reproduce:
    .venv/bin/python tools/metrics/js_gate.py           # report, exit 1 on breach
    .venv/bin/python tools/metrics/js_gate.py --json    # machine-readable
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import js_size  # noqa: E402  (same package, frozen interface)

SIZE_BASELINE = os.path.join(ROOT, "reports", "js_size_baseline.json")
COV_BASELINE = os.path.join(ROOT, "reports", "js_coverage_baseline.json")

FILE_LOC_LIMIT = 500
FUNC_LOC_LIMIT = 30
OBJ_LOC_LIMIT = 150
OBJ_METHODS_LIMIT = 15
COV_TOLERANCE = 0.05  # float jitter between V8 runs


# ── size comparison ──────────────────────────────────────────────
def _baseline_functions(baseline: dict) -> dict:
    """(file, name) -> list of baseline entries (line, loc)."""
    out: dict = {}
    for f in baseline["files"]:
        for fn in f["functions"]:
            out.setdefault((f["file"], fn["name"]), []).append(
                {"line": fn["line"], "loc": fn["loc"]})
    return out


def compare_sizes(current: dict, baseline: dict) -> tuple:
    violations, notes = [], []
    base_files = {f["file"]: f for f in baseline["files"]}
    base_fns = _baseline_functions(baseline)
    base_obj_loc = {f["file"]: f["summary"]["max_object_loc"]
                    for f in baseline["files"]}
    base_obj_meth = {f["file"]: f["summary"]["max_object_methods"]
                     for f in baseline["files"]}

    for f in current["files"]:
        name = f["file"]
        old = base_files.get(name)

        # file LOC: new files must fit 500; known files only shrink
        cap = FILE_LOC_LIMIT if old is None else max(
            FILE_LOC_LIMIT, old["lines"])
        if f["lines"] > cap:
            violations.append(
                "%s: %d lines > %d (baseline %s)"
                % (name, f["lines"], cap, old["lines"] if old else "new"))

        # objects: per-file ratchet on the largest gated object
        cap_loc = OBJ_LOC_LIMIT if old is None else max(
            OBJ_LOC_LIMIT, base_obj_loc.get(name, 0))
        if f["summary"]["max_object_loc"] > cap_loc:
            violations.append(
                "%s: largest object %d lines > %d"
                % (name, f["summary"]["max_object_loc"], cap_loc))
        cap_meth = OBJ_METHODS_LIMIT if old is None else max(
            OBJ_METHODS_LIMIT, base_obj_meth.get(name, 0))
        if f["summary"]["max_object_methods"] > cap_meth:
            violations.append(
                "%s: object with %d methods > %d"
                % (name, f["summary"]["max_object_methods"], cap_meth))

        # functions: baseline entries must not grow; new ones must fit
        seen = set()
        for fn in f["functions"]:
            key = (name, fn["name"])
            candidates = base_fns.get(key, [])
            match = None
            for c in candidates:
                if c["line"] == fn["line"]:
                    match = c
                    break
            if match is None and len(candidates) == 1:
                match = candidates[0]  # unique name: match regardless of line
            if match is not None:
                seen.add((key, match["line"]))
                if fn["loc"] > match["loc"]:
                    violations.append(
                        "%s::%s grew %d -> %d lines"
                        % (name, fn["name"], match["loc"], fn["loc"]))
            elif fn["loc"] > FUNC_LOC_LIMIT:
                violations.append(
                    "%s::%s is NEW at %d lines (> %d)"
                    % (name, fn["name"], fn["loc"], FUNC_LOC_LIMIT))
        for key, entries in base_fns.items():
            if key[0] != name:
                continue
            for c in entries:
                if (key, c["line"]) not in seen:
                    notes.append("%s::%s (baseline %d lines) no longer "
                                 "present" % (name, key[1], c["loc"]))

    for name in base_files:
        if name not in {f["file"] for f in current["files"]}:
            notes.append("%s: removed" % name)
    return violations, notes


# ── coverage comparison ──────────────────────────────────────────
def compare_coverage(current: dict, baseline: dict) -> tuple:
    violations, notes = [], []
    base_files = {name: f for name, f in baseline["files"].items()}
    cur_files = {name: f for name, f in current["files"].items()}

    for name, base in sorted(base_files.items()):
        cur = cur_files.get(name)
        if cur is None:
            notes.append("%s: no longer measured" % name)
            continue
        if base["pct"] == 0.0:
            if cur["pct"] <= 0.0:
                violations.append(
                    "%s: still never loaded by any Node test (ratchets up "
                    "from 0)" % name)
            continue
        if cur["pct"] < base["pct"] - COV_TOLERANCE:
            violations.append("%s: coverage %.1f%% < baseline %.1f%%"
                              % (name, cur["pct"], base["pct"]))
    for name, cur in sorted(cur_files.items()):
        if name not in base_files and cur["pct"] <= 0.0:
            violations.append("%s: NEW file never loaded by any Node test"
                              % name)

    if current["totals"]["pct"] < baseline["totals"]["pct"] - COV_TOLERANCE:
        violations.append("total coverage %.2f%% < baseline %.2f%%"
                          % (current["totals"]["pct"],
                             baseline["totals"]["pct"]))
    for fail in current.get("test_failures", []):
        violations.append("Node suite failed: %s" % fail["test"])
    return violations, notes


# ── live measurement ─────────────────────────────────────────────
def measure_coverage() -> dict:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
        path = fh.name
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tools", "metrics",
                                          "js_coverage.py"), "--json", path],
            cwd=ROOT, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError("js_coverage.py failed:\n"
                               + (proc.stderr or proc.stdout)[-2000:])
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def run() -> dict:
    with open(SIZE_BASELINE, encoding="utf-8") as fh:
        size_base = json.load(fh)
    with open(COV_BASELINE, encoding="utf-8") as fh:
        cov_base = json.load(fh)

    size_cur = js_size.run(ROOT)
    size_v, size_n = compare_sizes(size_cur, size_base)

    print("running the Node suites under coverage (this takes ~20s)…")
    cov_cur = measure_coverage()
    cov_v, cov_n = compare_coverage(cov_cur, cov_base)

    return {
        "size": {"violations": size_v, "notes": size_n,
                 "totals": size_cur["totals"],
                 "baseline_totals": size_base["totals"]},
        "coverage": {"violations": cov_v, "notes": cov_n,
                     "totals": cov_cur["totals"],
                     "baseline_totals": cov_base["totals"]},
    }


def print_report(report: dict) -> None:
    for kind in ("size", "coverage"):
        block = report[kind]
        print("── %s ──────────────────────────────────────────────" % kind)
        cur, base = block["totals"], block["baseline_totals"]
        if kind == "size":
            print("files %d (base %d) · lines %d (base %d) · functions %d"
                  % (cur["files"], base["files"], cur["lines"],
                     base["lines"], cur["functions"]))
            print("functions over 30: %d (base %d)"
                  % (cur["over_30"], base["over_30"]))
        else:
            print("line coverage %.2f%% (base %.2f%%) · %d/%d of %d files"
                  % (cur["pct"], base["pct"], cur["covered"],
                     cur["executable"], cur["files"]))
        for v in block["violations"]:
            print("  VIOLATION  " + v)
        if not block["violations"]:
            print("  ok — no violations")
    all_v = report["size"]["violations"] + report["coverage"]["violations"]
    if all_v:
        print("\nJS GATE: FAIL (%d violation%s)"
              % (len(all_v), "s" if len(all_v) != 1 else ""))
    else:
        print("\nJS GATE: PASS")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", help="write the machine-readable report here")
    args = ap.parse_args(argv)

    report = run()
    print_report(report)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1, sort_keys=True)
        print("wrote " + args.json)
    return 1 if (report["size"]["violations"]
                 or report["coverage"]["violations"]) else 0


if __name__ == "__main__":
    sys.exit(main())
