"""JavaScript coverage instrumentation (Round G, step G7).

Why this exists: the 2026-09-12 audit §3 found the frontend JS files — 9 237
LOC across `ui/js/` plus `backend/js/chat_agent.js` — and the JS payloads
embedded in Python strings sitting outside every quality denominator. The
Python side has coverage floors (RULE 16 §16.3); the JS side had no
measurement at all. This tool produces the measurement:

1. Mirror the repo into a temp tree and append a `//# sourceURL=cvb://<rel>`
   pragma to every attributed `.js` file. The 28 Node tests load their sources
   with `readFileSync` + `new Function`/`vm`, and V8's `NODE_V8_COVERAGE`
   skips eval'd scripts unless the source carries a sourceURL. Appending
   (never prepending) keeps every original byte offset valid.
2. Run each `tests/test_*.js` under `NODE_V8_COVERAGE` and merge the range
   data per file (union of covered lines across runs). Offsets are UTF-16
   code units — the mapper accounts for non-BMP characters.
3. Inventory (not coverage — V8 cannot see these): the JS payloads embedded
   in Python string constants, located by AST with their line spans.

Reproduce:
    .venv/bin/python tools/metrics/js_coverage.py [--json PATH]

Nothing is written inside the repo; the mirror and the coverage dirs are
temp directories removed on exit.
"""
from __future__ import annotations

import argparse
import ast
import bisect
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIRROR_IGNORE = {".git", ".venv", "mutants", "node_modules", "__pycache__",
                 ".pytest_cache", ".arena", "dist", "build", "coverage"}
JS_MARKERS = ("function", "=>", "document.", "window.", "addEventListener",
              "querySelector")
PYTHON_ROOTS = ("actions", "app", "backend", "bridge", "core", "services",
                "stores", "ui")


# ── mirror + pragma ────────────────────────────────────────────────
# The Node suites only ever read ui/**, bridge/** (test_bridge_router),
# backend/js/** and their own tests/ directory — mirror just those. The
# full-repo copy was ~116 MB; this is a few MB, and the mirror is what
# every parallel Node worker starts from.
MIRROR_PARTS = (("ui", "ui"), ("bridge", "bridge"),
                ("tests", "tests"), (os.path.join("backend", "js"),
                                     os.path.join("backend", "js")))


def mirror_repo(dst: str) -> None:
    for src, dst_rel in MIRROR_PARTS:
        full = os.path.join(dst, dst_rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        shutil.copytree(os.path.join(ROOT, src), full, symlinks=True,
                        ignore=lambda _d, names: [n for n in names
                                                  if n in MIRROR_IGNORE])


def attributed_js_files(root: str) -> list:
    out = []
    for base in ("ui", os.path.join("backend", "js")):
        for dirpath, dirnames, filenames in os.walk(os.path.join(root, base)):
            dirnames[:] = [d for d in dirnames if d not in MIRROR_IGNORE]
            for name in sorted(filenames):
                if name.endswith(".js"):
                    full = os.path.join(dirpath, name)
                    out.append(os.path.relpath(full, root).replace(os.sep, "/"))
    return out


def append_pragmas(root: str, rel_paths: list) -> None:
    for rel in rel_paths:
        with open(os.path.join(root, rel), "a", encoding="utf-8") as fh:
            fh.write("\n//# sourceURL=cvb://%s\n" % rel)


# ── running the Node tests ─────────────────────────────────────────
def _run_one_suite(args: tuple) -> tuple:
    mirror, name, cov_dir = args
    proc = subprocess.run(["node", os.path.join("tests", name)],
                          cwd=mirror,
                          env=dict(os.environ, NODE_V8_COVERAGE=cov_dir),
                          timeout=120,
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE)
    return (name, proc.returncode,
            proc.stderr.decode("utf-8", "replace")[-300:])


def run_node_tests(mirror: str, cov_dir: str) -> list:
    os.makedirs(cov_dir, exist_ok=True)
    failures = []
    tests_dir = os.path.join(mirror, "tests")
    names = sorted(n for n in os.listdir(tests_dir)
                   if n.startswith("test_") and n.endswith(".js"))
    # Independent processes, PID-unique V8 coverage filenames — run them
    # in parallel; on a 2-core box the wall time roughly halves.
    from concurrent.futures import ProcessPoolExecutor
    workers = max(1, min(4, os.cpu_count() or 1, len(names)))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for name, code, err in pool.map(_run_one_suite,
                                        [(mirror, n, cov_dir)
                                         for n in names]):
            if code != 0:
                failures.append((name, code, err))
    return failures


# ── V8 range data -> line coverage ─────────────────────────────────
def utf16_line_starts(src: str) -> tuple:
    """(line-start JS offsets, total UTF-16 units); non-BMP chars count two."""
    starts, off = [0], 0
    for ch in src:
        off += 2 if ord(ch) > 0xFFFF else 1
        if ch == "\n":
            starts.append(off)
    return starts, off


def offset_counts(src_len: int, functions: list) -> tuple:
    """Apply V8 ranges in emission order (nested ranges come after their
    parent and override it). Returns (counts, touched) over UTF-16 offsets."""
    counts = [0] * (src_len + 1)
    touched = bytearray(src_len + 1)
    for fn in functions:
        for rng in fn.get("ranges", []):
            start, end = rng["startOffset"], min(rng["endOffset"], src_len)
            count = rng.get("count", 0)
            for i in range(start, end):
                counts[i] = count
                touched[i] = 1
    return counts, touched


def lines_from_counts(counts: list, touched: bytearray, starts: list,
                      total_lines: int) -> tuple:
    covered, executable = set(), set()
    for line in range(total_lines):
        lo, hi = starts[line], (starts[line + 1] if line + 1 < len(starts)
                                else len(counts))
        if any(touched[lo:hi]):
            executable.add(line + 1)
            if any(counts[lo:hi]):
                covered.add(line + 1)
    return covered, executable


def merge_coverage(cov_dir: str, sources: dict) -> dict:
    """sources: rel -> (mirror_src_text, original_total_lines). Union of
    covered lines across every run; executable lines from the range spans."""
    acc = {rel: [set(), set()] for rel in sources}
    for name in sorted(os.listdir(cov_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(cov_dir, name), encoding="utf-8") as fh:
            data = json.load(fh)
        _merge_one_report(data, sources, acc)
    return acc


def _merge_one_report(data: dict, sources: dict, acc: dict) -> None:
    for entry in data.get("result", []):
        url = entry.get("url", "")
        if not url.startswith("cvb://"):
            continue
        rel = url[len("cvb://"):]
        if rel not in sources:
            continue
        src, total_lines = sources[rel]
        starts, units = utf16_line_starts(src)
        counts, touched = offset_counts(units, entry["functions"])
        covered, executable = lines_from_counts(counts, touched, starts,
                                                total_lines)
        acc[rel][0] |= covered
        acc[rel][1] |= executable


# ── embedded JS payload inventory (Python side) ────────────────────
def _looks_like_js(text: str) -> bool:
    return sum(1 for m in JS_MARKERS if m in text) >= 2


def _python_files(root: str) -> list:
    out = []
    for base in PYTHON_ROOTS:
        for dirpath, dirnames, filenames in os.walk(os.path.join(root, base)):
            dirnames[:] = [d for d in dirnames if d not in MIRROR_IGNORE]
            for name in sorted(filenames):
                if name.endswith(".py"):
                    out.append(os.path.join(dirpath, name))
    out.append(os.path.join(root, "main.py"))
    return out


def _docstring_ids(tree: ast.AST) -> set:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc and node.body and isinstance(node.body[0], ast.Expr):
                ids.add(id(node.body[0].value))
    return ids


def inventory_embedded_js(root: str) -> list:
    """AST scan: string constants >= 8 lines that look like JS, and f-string
    (JoinedStr) payloads, which are dynamic and can never be instrumented.
    Docstrings are excluded — prose that mentions JS is not a payload."""
    found = []
    for path in _python_files(root):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:
            continue
        docstrings = _docstring_ids(tree)
        for node in ast.walk(tree):
            if id(node) in docstrings:
                continue
            item = _classify_payload(node, rel)
            if item:
                found.append(item)
    return sorted(found, key=lambda d: (d["file"], d["line"]))


def _classify_payload(node: ast.AST, rel: str):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        span = (node.end_lineno or node.lineno) - node.lineno + 1
        if span >= 8 and _looks_like_js(node.value):
            return {"file": rel, "line": node.lineno, "span": span,
                    "dynamic": False}
    if isinstance(node, ast.JoinedStr):
        span = (node.end_lineno or node.lineno) - node.lineno + 1
        text = "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
        if span >= 8 and _looks_like_js(text):
            return {"file": rel, "line": node.lineno, "span": span,
                    "dynamic": True}
    return None


# ── report ─────────────────────────────────────────────────────────
def build_report(acc: dict, totals: dict, failures: list, embedded: list) -> dict:
    files = {}
    for rel, (covered, executable) in sorted(acc.items()):
        lines = totals[rel]
        files[rel] = {"lines": lines, "executable": len(executable),
                      "covered": len(covered),
                      "pct": round(100.0 * len(covered) / len(executable), 2)
                      if executable else 0.0}
    exe = sum(f["executable"] for f in files.values())
    cov = sum(f["covered"] for f in files.values())
    return {"files": files,
            "totals": {"files": len(files),
                       "lines": sum(f["lines"] for f in files.values()),
                       "executable": exe, "covered": cov,
                       "pct": round(100.0 * cov / exe, 2) if exe else 0.0},
            "never_loaded": sorted(r for r, f in files.items()
                                   if f["covered"] == 0),
            "test_failures": [{"test": t, "exit": e, "stderr": s}
                              for t, e, s in failures],
            "embedded_js": embedded}


def print_report(report: dict) -> None:
    print("%-34s %6s %6s %6s %7s" % ("file", "lines", "exec", "cov", "%"))
    for rel, f in report["files"].items():
        print("%-34s %6d %6d %6d %6.1f%%" % (rel, f["lines"], f["executable"],
                                             f["covered"], f["pct"]))
    t = report["totals"]
    print("%-34s %6d %6d %6d %6.1f%%" % ("TOTAL (%d files)" % t["files"],
                                          t["lines"], t["executable"],
                                          t["covered"], t["pct"]))
    if report["never_loaded"]:
        print("never loaded by any Node test: " + ", ".join(report["never_loaded"]))
    if report["test_failures"]:
        print("NODE TEST FAILURES: " + ", ".join(
            f["test"] for f in report["test_failures"]))
    emb = report["embedded_js"]
    loc = sum(e["span"] for e in emb)
    dyn = sum(1 for e in emb if e["dynamic"])
    print("embedded JS payloads in Python: %d (%d lines, %d dynamic/f-string)"
          % (len(emb), loc, dyn))
    for e in emb:
        print("  %s:%d  %d lines%s" % (e["file"], e["line"], e["span"],
                                       "  (dynamic)" if e["dynamic"] else ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", help="write the machine-readable report here")
    args = ap.parse_args(argv)

    work = tempfile.mkdtemp(prefix="cvb-js-cov-")
    try:
        mirror, cov_dir = os.path.join(work, "mirror"), os.path.join(work, "cov")
        mirror_repo(mirror)
        js_files = attributed_js_files(mirror)
        append_pragmas(mirror, js_files)
        failures = run_node_tests(mirror, cov_dir)
        sources = {}
        for rel in js_files:
            mirror_src = open(os.path.join(mirror, rel), encoding="utf-8").read()
            orig_lines = open(os.path.join(ROOT, rel),
                              encoding="utf-8").read().count("\n") + 1
            sources[rel] = (mirror_src, orig_lines)
        acc = merge_coverage(cov_dir, sources)
        report = build_report(acc, {r: s[1] for r, s in sources.items()},
                              failures, inventory_embedded_js(ROOT))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print_report(report)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1, sort_keys=True)
        print("wrote " + args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
