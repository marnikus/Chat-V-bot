#!/usr/bin/env python3
"""Tiered test runner — from 387 s to ~30 s.

Design: docs/archive/2026-09-14-test-arch-redesign/TEST_ARCH_REDESIGN_2026-09-14.md

Tiers:
* pure: no Qt, no DB — 70% of tests, <10 s
* db: pure + HistoryDB memory — ~15 s (was 140 s with file DB)
* qt: pure + db + Qt — ~40 s (Qt needs -n0, QApplication singleton)
* gate: rule16/clone/vulture — ~20 s, cached clone scan ~2 s
* full: all with xdist -n auto + parallel coverage — ~60 s vs 475 s

Usage:
    python tools/metrics/run_tiers.py --quick          # pure only, ~5 s
    python tools/metrics/run_tiers.py --with-db        # pure+db, ~15 s
    python tools/metrics/run_tiers.py --with-qt        # pure+db+qt, ~40 s
    python tools/metrics/run_tiers.py --full           # all + coverage parallel, ~60 s
    python tools/metrics/run_tiers.py --full --with-clones  # + clone scan

This runner replaces the single `pytest -q` that took 387 s.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], env=None, timeout=600) -> tuple[int, str, float]:
    if env is None:
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", LD_LIBRARY_PATH="/tmp/stublibs")
    start = time.time()
    proc = subprocess.run(
        cmd, cwd=str(ROOT), env=env, timeout=timeout,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    elapsed = time.time() - start
    return proc.returncode, proc.stdout[-5000:], elapsed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true", help="pure only, ~5 s")
    ap.add_argument("--with-db", action="store_true", help="pure+db, ~15 s")
    ap.add_argument("--with-qt", action="store_true", help="pure+db+qt, ~40 s")
    ap.add_argument("--full", action="store_true", help="all + coverage parallel, ~60 s")
    ap.add_argument("--with-clones", action="store_true", help="run clone scan (adds ~15 s, cached ~2 s)")
    ap.add_argument("--coverage", action="store_true", help="with coverage (adds ~20% overhead)")
    ap.add_argument("-k", dest="k", metavar="EXPR", help="pytest -k filter")
    ap.add_argument("-n", dest="workers", metavar="N", default="auto", help="xdist workers (default auto, qt tier uses 0)")
    args = ap.parse_args(argv)

    # Default to quick if no tier specified
    if not (args.quick or args.with_db or args.with_qt or args.full):
        args.quick = True

    py = str(ROOT / ".venv" / "bin" / "python")
    if not os.path.exists(py):
        py = sys.executable

    overall_code = 0
    total_elapsed = 0.0

    # Tier 0: pure
    if args.quick or args.with_db or args.with_qt or args.full:
        print("\n=== Tier 0: pure (no Qt, no DB) — expected <10 s ===")
        cmd = [py, "-m", "pytest", "-m", "pure", "-q", "--tb=short"]
        if args.workers != "0":
            cmd.extend(["-n", str(args.workers)])
        if args.k:
            cmd.extend(["-k", args.k])
        if args.coverage and args.full:
            cmd = [py, "-m", "coverage", "run", "--parallel", "--branch", "--source=core,actions,backend,bridge,services,stores,app,main"] + cmd[1:]
        code, out, elapsed = _run(cmd, timeout=120)
        print(out[-2000:])
        print(f"Tier 0 done in {elapsed:.1f}s, exit {code}")
        total_elapsed += elapsed
        overall_code = max(overall_code, code)
        if args.quick and not (args.with_db or args.with_qt or args.full):
            print(f"\nQuick done in {total_elapsed:.1f}s")
            return overall_code

    # Tier 1: db (memory)
    if args.with_db or args.with_qt or args.full:
        print("\n=== Tier 1: db (pure+db memory) — expected ~15 s ===")
        cmd = [py, "-m", "pytest", "-m", "db or pure", "-q", "--tb=line", "--durations=10"]
        if args.workers != "0":
            cmd.extend(["-n", str(args.workers)])
        if args.k:
            cmd.extend(["-k", args.k])
        code, out, elapsed = _run(cmd, timeout=180)
        print(out[-3000:])
        print(f"Tier 1 done in {elapsed:.1f}s, exit {code}")
        total_elapsed += elapsed
        overall_code = max(overall_code, code)
        if args.with_db and not (args.with_qt or args.full):
            print(f"\nWith-DB done in {total_elapsed:.1f}s")
            return overall_code

    # Tier 2: qt (needs -n0 because QApplication singleton not fork-safe)
    if args.with_qt or args.full:
        print("\n=== Tier 2: qt (pure+db+qt, single process) — expected ~30 s ===")
        cmd = [py, "-m", "pytest", "-m", "qt or db or pure", "-q", "--tb=line", "-n", "0"]
        if args.k:
            cmd.extend(["-k", args.k])
        code, out, elapsed = _run(cmd, timeout=300)
        print(out[-3000:])
        print(f"Tier 2 done in {elapsed:.1f}s, exit {code}")
        total_elapsed += elapsed
        overall_code = max(overall_code, code)
        if args.with_qt and not args.full:
            print(f"\nWith-Qt done in {total_elapsed:.1f}s")
            return overall_code

    # Tier 3: gate (rule16, clone, vulture) — slow, cached
    if args.full:
        print("\n=== Tier 3: gate (rule16/clone/vulture) — expected ~20 s, cached ~2 s ===")
        # rule16_gate without clones first (fast)
        code, out, elapsed = _run([py, "tools/metrics/rule16_gate.py"], timeout=60)
        print(out[-2000:])
        total_elapsed += elapsed
        overall_code = max(overall_code, code)

        if args.with_clones:
            # clone scan with cache
            code, out, elapsed = _run([py, "tools/metrics/clone_scan.py", "--cache", "/tmp/clone_cache.json"], timeout=60)
            print(out[-2000:])
            total_elapsed += elapsed
            overall_code = max(overall_code, code)

        # vulture
        code, out, elapsed = _run([py, "-m", "vulture", "--min-confidence", "90", "backend", "bridge", "services", "stores", "actions", "core", "app"], timeout=30)
        print(out[-1000:])
        total_elapsed += elapsed

        if args.coverage:
            # Combine parallel coverage
            code, out, elapsed = _run([py, "-m", "coverage", "combine"], timeout=30)
            print(out)
            code, out, elapsed = _run([py, "-m", "coverage", "json", "-o", "coverage.json"], timeout=10)
            print(out)
            code, out, elapsed = _run([py, "-m", "coverage", "report", "--include=backend/*,actions/*,app/*,bridge/*"], timeout=10)
            print(out[-1000:])

        print(f"\nFull done in {total_elapsed:.1f}s (was 475 s with old single-process coverage)")
        print(f"Speedup: {475/total_elapsed:.1f}×")

    return overall_code


if __name__ == "__main__":
    sys.exit(main())
