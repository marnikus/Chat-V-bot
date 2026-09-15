#!/usr/bin/env python3
"""Per-file coverage floor — closes the hole global % hides.

Global line 92.64% can be green while `message_injector_send.py` sits at
21.1%. This gate requires every production module with ≥30 statements to
hold ≥80% line coverage, with a ratchet table for the files below the line
today that may only rise.

Wired from `coverage.json` (RULE 16 §16.3's measurement, no new tool).
Owned by Area D (verification) — Areas B/C own their files, this owns the
floor and the ratchet protocol, same as `rule16_gate.py`'s RATCHET.

Usage:
    python tools/metrics/file_coverage_floor.py [--json PATH] [--coverage PATH]
    python tools/metrics/file_coverage_floor.py --gate  # exit 1 on breach

Design: docs/archive/2026-09-14-round-h/AREA_D_VERIFICATION_DESIGN_2026-09-14.md H-D3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROD_PREFIXES = ("core/", "actions/", "backend/", "bridge/", "services/", "stores/", "app/", "main.py")
MIN_STMTS = 30
FLOOR = 80.0

# Ratchet: files below FLOOR today. Value is the minimal coverage that must
# not decrease. May only rise; once a file reaches FLOOR it can be removed.
# Measured 2026-09-14 from coverage.json after Area C splits + Area A JS splits
# + Area B splits (cdp_client, history_bridge, history_query_search).
# Area A + Area B + Area C files added with current low coverage to ratchet up.
RATCHET: Dict[str, float] = {
    "backend/cdp_client.py": 63.1,
    "backend/cdp_client_events.py": 56.8,
    "backend/cdp_client_transport.py": 89.9,
    "backend/history_query_search.py": 14.7,
    "bridge/collector_bridge.py": 72.1,
    "bridge/history_bridge.py": 62.3,
    "bridge/history_bridge_delete.py": 90.2,
    "bridge/history_bridge_media.py": 65.9,
    "bridge/history_bridge_read.py": 14.2,
    "bridge/history_bridge_settings.py": 100.0,
    "bridge/label_bridge.py": 78.0,
    "bridge/layout_bridge.py": 67.3,
    "bridge/people_bridge.py": 76.1,
    "services/collector_archive.py": 0.0,
    "services/collector_probe.py": 0.0,
    "services/collector_tick.py": 60.0,
    "services/db_deletion_flow_detach.py": 78.8,
    "services/db_deletion_flow_remove.py": 69.3,
    "services/db_deletion_scan.py": 70.9,
    "services/db_registry.py": 70.5,
    "services/history/legacy.py": 0.0,
    "services/history/mutate.py": 63.2,
    "services/history/settings.py": 0.0,
    "services/window_preset_service.py": 60.2,
    "stores/history_repo_append.py": 66.9,
    "stores/history_repo_lifecycle.py": 66.7,
    "stores/history_repo_restore.py": 30.6,
    "stores/history_repo_slots.py": 35.0,
    "stores/history_schema_legacy.py": 17.2,
    "stores/history_schema_repair.py": 54.3,
    "stores/media_fetch.py": 51.1,
    "stores/media_network.py": 24.5,
}

# Area B owns these; they are in RATCHET but their fix lands in B.
AREA_B_OWNED = {
    "bridge/history_bridge.py",
    "backend/cdp_client.py",
}


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _is_prod(rel: str) -> bool:
    return any(rel.startswith(p) for p in PROD_PREFIXES)


def _check_one(rel: str, summary: dict, ratchet_val: float | None) -> dict:
    stmts = summary.get("num_statements", 0)
    covered = summary.get("covered_lines", 0)
    pct = summary.get("percent_covered", 0.0)
    missing = summary.get("missing_lines", 0)
    # coverage.py's missing_lines is count, but we also compute
    result = {
        "file": rel,
        "statements": stmts,
        "covered": covered,
        "percent": round(float(pct), 1),
        "missing": missing,
        "ratchet": ratchet_val,
        "below_floor": pct < FLOOR,
        "regressed": False,
        "ratchet_breath": None,
    }
    if ratchet_val is not None and pct + 0.05 < ratchet_val:
        result["regressed"] = True
        result["ratchet_breath"] = round(ratchet_val - pct, 1)
    return result


def run(coverage_path: str) -> dict:
    data = _load(coverage_path)
    files = data.get("files", {})
    rows: List[dict] = []
    breaches: List[str] = []
    below: List[dict] = []

    for full_path, info in sorted(files.items()):
        # coverage.json keys are absolute or relative; normalize to repo-rel
        rel = full_path
        if os.path.isabs(full_path):
            try:
                rel = os.path.relpath(full_path, ROOT)
            except ValueError:
                rel = full_path
        # also handle keys that already are repo-rel but with leading ./
        rel = rel.lstrip("./").replace(os.sep, "/")
        if not _is_prod(rel):
            continue
        summary = info.get("summary", {})
        stmts = summary.get("num_statements", 0)
        if stmts < MIN_STMTS:
            continue
        ratchet_val = RATCHET.get(rel)
        row = _check_one(rel, summary, ratchet_val)
        rows.append(row)
        if row["regressed"]:
            breaches.append(
                f"{rel}: {row['percent']}% < ratchet {ratchet_val}% "
                f"(regressed by {row['ratchet_breath']}%)"
            )
        if row["below_floor"] and rel not in RATCHET:
            # New file dropped below floor without being ratcheted
            breaches.append(
                f"{rel}: {row['percent']}% < floor {FLOOR}% "
                f"and not in ratchet — add to RATCHET or raise coverage"
            )
        if row["below_floor"]:
            below.append(row)

    # Ratchet entries that no longer exist (file deleted or renamed) are stale
    existing = {r["file"] for r in rows}
    stale = [f for f in RATCHET if f not in existing]

    total = len(rows)
    at_floor = sum(1 for r in rows if not r["below_floor"])
    return {
        "coverage_path": coverage_path,
        "floor": FLOOR,
        "min_stmts": MIN_STMTS,
        "total_files": total,
        "at_floor": at_floor,
        "below_floor": sorted(below, key=lambda x: x["percent"]),
        "rows": sorted(rows, key=lambda x: x["percent"]),
        "breaches": breaches,
        "stale_ratchet": stale,
        "ratchet": RATCHET,
    }


def _print_human(report: dict) -> None:
    print(f"Per-file floor: {report['floor']}% for ≥{report['min_stmts']} stmts")
    print(f"Scanned {report['total_files']} prod files, "
          f"{report['at_floor']} at floor, "
          f"{len(report['below_floor'])} below")
    if report["below_floor"]:
        print("\nBelow floor (lowest first):")
        for r in report["below_floor"][:20]:
            tag = " [B]" if r["file"] in AREA_B_OWNED else ""
            print(f"  {r['percent']:5.1f}% {r['file']} ({r['statements']} stmts){tag}")
    if report["breaches"]:
        print("\nBREACHES:")
        for b in report["breaches"]:
            print(f"  {b}")
    else:
        print("\nNo ratchet regression, no new below-floor file.")
    if report["stale_ratchet"]:
        print("\nStale ratchet entries (file gone — delete from RATCHET):")
        for s in report["stale_ratchet"]:
            print(f"  {s}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--coverage", default=os.path.join(ROOT, "coverage.json"),
                    help="path to coverage.json (default: repo root)")
    ap.add_argument("--json", dest="json_out", metavar="PATH",
                    help="write machine-readable report")
    ap.add_argument("--gate", action="store_true",
                    help="exit 1 on any breach")
    args = ap.parse_args(argv)

    # Fallback: /tmp/coverage_h.json from the repro command
    cov_path = args.coverage
    if not os.path.exists(cov_path):
        alt = "/tmp/coverage_h.json"
        if os.path.exists(alt):
            cov_path = alt
    if not os.path.exists(cov_path):
        print(f"coverage file not found: {cov_path}", file=sys.stderr)
        return 2

    report = run(cov_path)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)

    _print_human(report)
    if args.gate and report["breaches"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
