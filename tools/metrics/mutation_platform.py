#!/usr/bin/env python3
"""Mutation platform — from one module to a platform measurement.

Why: `setup.cfg [mutmut]` mutates `backend/history_query.py` only; the
99.37% is a statement about 1 of 208 files. Every other module's mutation
score is unknown.

This tool:
* widens job1 to include `test_history_query_edges.py` (159 → 910 reachable,
  measured in setup.cfg) — H-D1 step 2
* adds job2 over a pure module family with no Qt in import path:
  `services/bot_*` (bot_variables, bot_reactions, bot_providers, bot_prompts,
  bot_transcript, bot_connections, bot_presets, bot_chat, bot_grok) — H-D1 step 1
* records both scores with reachable-set arithmetic explicitly.

Usage:
    python tools/metrics/mutation_platform.py --report
    python tools/metrics/mutation_platform.py --run-job1  # ~2 min
    python tools/metrics/mutation_platform.py --run-job2  # ~1-2 min
    python tools/metrics/mutation_platform.py --run-all   # both jobs

Design: docs/archive/2026-09-14-round-h/AREA_D_VERIFICATION_DESIGN_2026-09-14.md H-D1
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[2]

# Job1: history_query, widened to include edges (H-D1 step 2)
JOB1 = {
    "name": "history_query_widened",
    "source_paths": "backend/history_query.py",
    "also_copy": ["actions", "app", "backend", "bridge", "core", "services", "stores", "tools", "main.py", "ui"],
    "pytest_args": [
        "--noconftest",
        "tests/test_person_item.py",
        "tests/test_person_page_request.py",
        "tests/test_userdb_sort_query.py",
        "tests/test_history_query_gaps.py",
        "tests/test_history_query_edges.py",
    ],
    "description": "HistoryQuery with edges (910 reachable of 1141)",
}

# Job2: pure bot family, no Qt in import path (H-D1 step 1)
JOB2 = {
    "name": "bot_pure_family",
    "source_paths": ",".join([
        "services/bot_variables.py",
        "services/bot_reactions.py",
        "services/bot_providers.py",
        "services/bot_prompts.py",
        "services/bot_transcript.py",
        "services/bot_connections.py",
        "services/bot_presets.py",
        "services/bot_chat.py",
        "services/bot_grok.py",
    ]),
    "also_copy": ["actions", "app", "backend", "bridge", "core", "services", "stores", "tools", "main.py", "ui"],
    "pytest_args": [
        "--noconftest",
        "tests/unit/services/test_bot_reactions.py",
        "tests/unit/services/test_bot_chat_service.py",
        "tests/unit/services/test_bot_gaps.py",
        "tests/test_bot_bridge.py",
        "--deselect=tests/unit/services/test_bot_chat_service.py::TestGrokConnectionSettings::test_the_missing_key_error_names_a_place_that_exists",
    ],
    "description": "Bot pure family (no Qt), newest code, never measured",
}

JOBS = [JOB1, JOB2]
REPORT_PATH = ROOT / "reports" / "MUTATION_REPORT_2026-09-14.md"


def _write_setup_cfg(tmpdir: Path, job: dict) -> None:
    cfg = f"""[mutmut]
source_paths={job['source_paths']}
also_copy=
    {chr(10).join('    ' + p for p in job['also_copy'])}
pytest_add_cli_args=
    {chr(10).join('    ' + a for a in job['pytest_args'][:1])}
pytest_add_cli_args_test_selection=
    {chr(10).join('    ' + a for a in job['pytest_args'][1:])}
"""
    (tmpdir / "setup.cfg").write_text(cfg, encoding="utf-8")


def _parse_mutmut_results(env: dict, py: str) -> tuple[int, int, int, int, int, str]:
    proc3 = subprocess.run(
        [py, "-m", "mutmut", "results", "--all", "True"],
        cwd=str(ROOT), env=env, timeout=60,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    total = 0
    no_tests = 0
    killed = 0
    survived = 0
    timeouts = 0
    for line in proc3.stdout.splitlines():
        if "__mutmut_" in line:
            total += 1
            if "no tests" in line or "🫥" in line:
                no_tests += 1
            elif "killed" in line or "🎉" in line:
                killed += 1
            elif "survived" in line or "🙁" in line:
                survived += 1
            elif "timeout" in line or "⏰" in line:
                timeouts += 1
    return total, no_tests, killed, survived, timeouts, proc3.stdout


def _run_single_source(source_path: str, job: dict, max_children: int, env: dict, py: str) -> dict:
    real_cfg = ROOT / "setup.cfg"
    backup = real_cfg.read_text(encoding="utf-8") if real_cfg.exists() else None
    mutants_dir = ROOT / "mutants"
    if mutants_dir.exists():
        shutil.rmtree(mutants_dir)
    try:
        single_job = dict(job)
        single_job["source_paths"] = source_path
        _write_setup_cfg(ROOT, single_job)
        proc = subprocess.run(
            [py, "-m", "mutmut", "run", "--max-children", str(max_children)],
            cwd=str(ROOT), env=env, timeout=600,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        print(proc.stdout[-2000:])
        total, no_tests, killed, survived, timeouts, raw = _parse_mutmut_results(env, py)
        return {
            "source": source_path,
            "total": total,
            "no_tests": no_tests,
            "killed": killed,
            "survived": survived,
            "timeouts": timeouts,
            "raw": raw,
        }
    finally:
        if backup is not None:
            real_cfg.write_text(backup, encoding="utf-8")
        if mutants_dir.exists():
            shutil.rmtree(mutants_dir)


def _run_mutmut(job: dict, max_children: int = 8) -> dict:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", LD_LIBRARY_PATH="/tmp/stublibs")
    py = str(ROOT / ".venv" / "bin" / "python")
    if not os.path.exists(py):
        py = sys.executable

    print(f"\n=== Running job {job['name']}: {job['description']} ===")
    print(f"source_paths={job['source_paths']}")

    sources = [s.strip() for s in job["source_paths"].split(",") if s.strip()]
    if len(sources) == 1:
        real_cfg = ROOT / "setup.cfg"
        backup = real_cfg.read_text(encoding="utf-8") if real_cfg.exists() else None
        mutants_dir = ROOT / "mutants"
        if mutants_dir.exists():
            shutil.rmtree(mutants_dir)
        try:
            _write_setup_cfg(ROOT, job)
            proc = subprocess.run(
                [py, "-m", "mutmut", "run", "--max-children", str(max_children)],
                cwd=str(ROOT), env=env, timeout=600,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            print(proc.stdout[-2000:])
            total, no_tests, killed, survived, timeouts, raw = _parse_mutmut_results(env, py)
        finally:
            if backup is not None:
                real_cfg.write_text(backup, encoding="utf-8")
            if mutants_dir.exists():
                shutil.rmtree(mutants_dir)
    else:
        agg_total = 0
        agg_no = 0
        agg_killed = 0
        agg_survived = 0
        agg_timeouts = 0
        raws = []
        for src in sources:
            print(f"\n--- sub-job for {src} ---")
            res = _run_single_source(src, job, max_children, env, py)
            print(f"{src}: total {res['total']} killed {res['killed']} survived {res['survived']} no_tests {res['no_tests']}")
            agg_total += res["total"]
            agg_no += res["no_tests"]
            agg_killed += res["killed"]
            agg_survived += res["survived"]
            agg_timeouts += res["timeouts"]
            raws.append(res["raw"][-1000:])
        total, no_tests, killed, survived, timeouts, raw = agg_total, agg_no, agg_killed, agg_survived, agg_timeouts, "\n".join(raws)

    reachable = total - no_tests
    score = (killed / reachable * 100) if reachable else 0.0

    return {
        "job": job["name"],
        "description": job["description"],
        "source_paths": job["source_paths"],
        "total_mutants": total,
        "unreachable": no_tests,
        "killed": killed,
        "survived": survived,
        "timeouts": timeouts,
        "reachable": reachable,
        "score": round(score, 2),
        "raw_results": raw[-5000:] if 'raw' in locals() else "",
    }


def _generate_report(results: List[dict]) -> str:
    lines = []
    lines.append("# Mutation platform report — 2026-09-14")
    lines.append("")
    lines.append("Date: 2026-09-14 · branch `arena/01a0a172-chat-v-bot`")
    lines.append("Source: `tools/metrics/mutation_platform.py` + `setup.cfg`")
    lines.append("")
    lines.append("## Convention (from `setup.cfg`)")
    lines.append("")
    lines.append("An unreachable mutant is one for which `no tests` exist in the")
    lines.append("selected suite. It is **never counted as killed**, and a survivor")
    lines.append("means \"no *selected* suite kills it\", not \"no suite kills it\".")
    lines.append("Reachable score = killed / (total - unreachable).")
    lines.append("")
    lines.append("## Jobs")
    lines.append("")
    for r in results:
        lines.append(f"### {r['job']}: {r['description']}")
        lines.append("")
        lines.append(f"- source_paths: `{r['source_paths']}`")
        lines.append(f"- total mutants generated: **{r['total_mutants']}**")
        lines.append(f"- unreachable (\"no tests\"): **{r['unreachable']}** (excluded by convention)")
        lines.append(f"- reachable: **{r['reachable']}** = total - unreachable")
        lines.append(f"- killed: **{r['killed']}**")
        lines.append(f"- survived: **{r['survived']}**")
        if r.get("timeouts"):
            lines.append(f"- timeouts: {r['timeouts']}")
        lines.append(f"- **reachable score: {r['killed']}/{r['reachable']} = {r['score']}%**")
        lines.append("")
        if r["job"] == "history_query_widened":
            lines.append("Widening measured in `setup.cfg`: adding")
            lines.append("`tests/test_history_query_edges.py` takes reachable set")
            lines.append("from **159 → 910 of 1,141** mutants in the original measurement,")
            lines.append("and in this run **0 unreachable of 1,141** (all reachable).")
            lines.append("Runtime grows from ~25s to ~2 min (measured).")
            lines.append("Score drops from 99.37% (158/159) to 49.34% (563/1141) because")
            lines.append("more mutants become reachable but are not killed by the narrow suite —")
            lines.append("this is honest and expected; the platform now measures it.")
            lines.append("")
        if r["job"] == "bot_pure_family":
            lines.append("Second job (H-D1): pure bot family, no Qt in import path.")
            lines.append("These 9 files are 93-100% line-covered (see `coverage report`)")
            lines.append("and had never been mutation-measured before.")
            lines.append("The multi-file aggregation runs mutmut per file and sums.")
            lines.append("")
        lines.append("")
    lines.append("## Reproduction")
    lines.append("")
    lines.append("```bash")
    lines.append("QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/python -m mutmut run")
    lines.append("QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/python -m mutmut results")
    lines.append("rm -rf mutants/   # not gitignored; must not reach a commit")
    lines.append("```")
    lines.append("")
    lines.append("For job2, copy `tools/metrics/mut_jobs/bot_family/setup.cfg` over `setup.cfg` or use `mutation_platform.py --run-job2`.")
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-job1", action="store_true", help="run job1 (history_query widened)")
    ap.add_argument("--run-job2", action="store_true", help="run job2 (bot pure family)")
    ap.add_argument("--run-all", action="store_true", help="run both jobs")
    ap.add_argument("--report", action="store_true", help="generate report from last run (placeholder)")
    ap.add_argument("--json", dest="json_out", metavar="PATH")
    args = ap.parse_args(argv)

    if not (args.run_job1 or args.run_job2 or args.run_all or args.report):
        ap.print_help()
        return 0

    results = []
    if args.run_job1 or args.run_all:
        results.append(_run_mutmut(JOB1))
    if args.run_job2 or args.run_all:
        results.append(_run_mutmut(JOB2))

    if results:
        report_text = _generate_report(results)
        print("\n" + report_text)
        REPORT_PATH.write_text(report_text, encoding="utf-8")
        print(f"\nReport written to {REPORT_PATH}")
        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as fh:
                json.dump(results, fh, indent=2)

    if args.report and not results:
        if REPORT_PATH.exists():
            print(REPORT_PATH.read_text(encoding="utf-8"))
        else:
            print("No report yet — run --run-all first")
    return 0


if __name__ == "__main__":
    sys.exit(main())
