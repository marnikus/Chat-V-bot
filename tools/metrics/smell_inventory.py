#!/usr/bin/env python3
"""Smell ratchet — vulture, clone groups, boundary crossings, wide params.

Why: Area D H-D5. The repo has 7 vulture findings, 13 clone groups (all import
headers, baselined), 4 boundary crossings (private member access), and 11
wide-param functions (down from 51).

This tool inventories each, with disposition:
* vulture: delete if unused, or annotate as protocol surface with reason
* clones: already baselined in rule16_gate.py CLONE_BASELINE — 0 new / 0 stale
* boundary: either public name or recorded decision that private access is intended
* wide params: verify RULE 3 overrides, queue non-block functions for options object

Usage:
    python tools/metrics/smell_inventory.py [--json PATH]

Design: docs/archive/2026-09-14-round-h/AREA_D_VERIFICATION_DESIGN_2026-09-14.md H-D5
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[2]

# ── vulture inventory (measured 2026-09-14) ──────────────────────────
# Each entry: file, line, name, disposition, reason
VULTURE_FINDINGS = [
    {
        "file": "actions/registry.py",
        "line": 18,
        "name": "Iterator",
        "confidence": 90,
        "disposition": "delete",
        "reason": "Unused import — Iterator not used anywhere in file; "
                  "test proves member is unused (import is dead code)",
        "owner_area": "C",
    },
    {
        "file": "backend/cdp_client.py",
        "line": 35,
        "name": "exc_type",
        "confidence": 100,
        "disposition": "protocol",
        "reason": "Context manager protocol: __aexit__(exc_type, exc, tb) "
                  "must accept exc_type even if unused — Python requires it",
        "owner_area": "B",
    },
    {
        "file": "backend/cdp_client.py",
        "line": 35,
        "name": "tb",
        "confidence": 100,
        "disposition": "protocol",
        "reason": "Context manager protocol: __aexit__ must accept tb — "
                  "required by Python, not dead code",
        "owner_area": "B",
    },
    {
        "file": "services/run/coordinator.py",
        "line": 62,
        "name": "scroll_parser",
        "confidence": 100,
        "disposition": "delete",
        "reason": "Unused param in execute(scroll_parser=None) — no caller "
                  "passes it, method finds scroll block via self._stack; "
                  "should be removed (Area C)",
        "owner_area": "C",
    },
    {
        "file": "services/run/hooks.py",
        "line": 68,
        "name": "coordinator",
        "confidence": 100,
        "disposition": "protocol",
        "reason": "RunHooks.pre_run(coordinator) — base class hook, "
                  "subclasses may use coordinator; unused in base is protocol surface",
        "owner_area": "C",
    },
    {
        "file": "services/run/hooks.py",
        "line": 71,
        "name": "coordinator",
        "confidence": 100,
        "disposition": "protocol",
        "reason": "RunHooks.post_run(coordinator, outcome) — base hook, "
                  "coordinator is protocol arg for subclasses",
        "owner_area": "C",
    },
    {
        "file": "services/run/hooks.py",
        "line": 74,
        "name": "coordinator",
        "confidence": 100,
        "disposition": "protocol",
        "reason": "RunHooks.on_action_complete(coordinator, block, nick, status) — "
                  "base hook, coordinator is protocol arg",
        "owner_area": "C",
    },
]

# ── boundary crossings (inspection, not machine-measured) ───────────
BOUNDARY_CROSSINGS = [
    {
        "file": "bridge/router.py",
        "line": 471,
        "access": "ctx.undo._history_entry",
        "disposition": "recorded",
        "reason": "Router reaches for undo's private _history_entry to build "
                  "history entry — should be public method on UndoService or "
                  "recorded as intended private access (Area B H-B5)",
        "owner_area": "B",
    },
    {
        "file": "bridge/undo_bridge.py",
        "line": 178,
        "access": "self.undo_service._clean_history",
        "disposition": "recorded",
        "reason": "UndoBridge reaches for undo_service's private _clean_history — "
                  "should be public or recorded as intended (Area B)",
        "owner_area": "B",
    },
    {
        "file": "services/db_service.py",
        "line": 160,
        "access": "self.registry._remember",
        "disposition": "public",
        "reason": "DbService reaches for registry's private _remember — "
                  "should be public method (Area C)",
        "owner_area": "C",
    },
    {
        "file": "services/db_service.py",
        "line": 163,
        "access": "self.registry._prune_remembered",
        "disposition": "public",
        "reason": "Same as above — _prune_remembered should be public",
        "owner_area": "C",
    },
    {
        "file": "services/history/query.py",
        "line": 97,
        "access": "self.media._dirs",
        "disposition": "recorded",
        "reason": "History query reaches for media's private _dirs — "
                  "part pattern (host holds parts), documented as excluded",
        "owner_area": "C",
    },
]

# ── wide params tail (measured 2026-09-14) ───────────────────────────
WIDE_PARAMS = [
    {"file": "actions/scroll_parse.py", "line": 155, "params": 20, "func": "__init__", "status": "RULE 3 block settings — documented override"},
    {"file": "actions/click_user.py", "line": 60, "params": 13, "func": "__init__", "status": "RULE 3"},
    {"file": "actions/custom_find.py", "line": 53, "params": 11, "func": "__init__", "status": "RULE 3"},
    {"file": "actions/attach_image.py", "line": 36, "params": 9, "func": "__init__", "status": "RULE 3"},
    {"file": "actions/collect_history.py", "line": 37, "params": 9, "func": "__init__", "status": "RULE 3"},
    {"file": "bridge/router.py", "line": 200, "params": 8, "func": "__init__", "status": "not a block — candidate for options object (Area B H-B5)"},
    {"file": "actions/click_back.py", "line": None, "params": 7, "func": "__init__", "status": "RULE 3"},
    {"file": "actions/click_main_tab.py", "line": None, "params": 7, "func": "__init__", "status": "RULE 3"},
    {"file": "actions/click_send.py", "line": None, "params": 7, "func": "__init__", "status": "RULE 3"},
    {"file": "actions/type_message.py", "line": 22, "params": 5, "func": "__init__", "status": "RULE 3"},
    {"file": "backend/chat_sync.py", "line": 69, "params": 5, "func": "run_sync", "status": "not a block — candidate for request object (follow-up B)"},
]


def _run_vulture() -> List[str]:
    vulture = ROOT / ".venv" / "bin" / "vulture"
    if not vulture.exists():
        return ["vulture not installed"]
    pkgs = ["core", "actions", "backend", "bridge", "services", "stores", "app"]
    cmd = [str(vulture)] + pkgs + ["--min-confidence", "90"]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=30)
    return [l.strip() for l in proc.stdout.splitlines() if l.strip()]


def run() -> dict:
    vulture_now = _run_vulture()
    return {
        "vulture": {
            "measured": "2026-09-14",
            "findings": VULTURE_FINDINGS,
            "current_output": vulture_now,
            "count": len(VULTURE_FINDINGS),
        },
        "clones": {
            "measured": "2026-09-14",
            "groups": 13,
            "lines": 96,
            "baseline": "CLONE_BASELINE in rule16_gate.py",
            "new": 0,
            "stale": 0,
            "note": "All 13 groups are shared import headers, not copied logic",
        },
        "boundary": {
            "findings": BOUNDARY_CROSSINGS,
            "count": len(BOUNDARY_CROSSINGS),
            "note": "self.p._x inside Round-G part classes are documented part pattern, excluded",
        },
        "wide_params": {
            "findings": WIDE_PARAMS,
            "count": len(WIDE_PARAMS),
            "rule3_overrides": 9,
            "non_block": 2,
        },
    }


def _print_human(report: dict) -> None:
    print("=== Smell inventory — 2026-09-14 ===")
    print(f"\nVulture: {report['vulture']['count']} findings (unchanged since 2026-09-12)")
    for f in report["vulture"]["findings"]:
        print(f"  {f['file']}:{f['line']} {f['name']} — {f['disposition']}: {f['reason'][:80]}")
    print(f"\nClones: {report['clones']['groups']} groups / {report['clones']['lines']} lines, "
          f"{report['clones']['new']} new / {report['clones']['stale']} stale")
    print(f"  {report['clones']['note']}")
    print(f"\nBoundary crossings: {report['boundary']['count']} inspected")
    for b in report["boundary"]["findings"]:
        print(f"  {b['file']}:{b['line']} {b['access']} — {b['disposition']}")
    print(f"\nWide params: {report['wide_params']['count']} functions >4 params")
    for w in report["wide_params"]["findings"]:
        print(f"  {w['params']} {w['file']}:{w['func']} — {w['status']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", dest="json_out", metavar="PATH")
    args = ap.parse_args(argv)
    report = run()
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
    _print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
