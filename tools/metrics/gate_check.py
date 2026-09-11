#!/usr/bin/env python3
"""RULE 16 / RULE 18 gate check for the files you just edited.

`tests/test_rule16_new_code.py` enforces the gates for one feature's owned
list; this is the same measurement without the list, so an agent can answer
"does *this* file fit?" while iterating, and a reviewer can see the whole
picture — including the legacy offenders that are already accepted, and which
of them carries a written reason.

Counting rules are the frozen ones (docs/AGENT_RULES_CODE_QUALITY.md §1–§2):

  * function LOC    — inclusive AST source span, decorators excluded,
                      nested defs counted separately;
  * params          — excluding `self`/`cls`, `*args`/`**kwargs` one each;
  * CC              — radon (falls back to an AST decision count if absent);
  * cognitive       — `cognitive-complexity` (skipped when absent);
  * nesting         — max ancestry of if/loops/with/try/match, siblings no;
  * class LOC/methods — inclusive class-body span, direct+nested defs counted
                      (that is how `tests/test_rule16_new_code.py::_classes`
                      counts, so a nested helper inside a method does count).

Accepted legacy (docs/AGENT_RULES_CODE_QUALITY.md §5) sits in a trailing
comment on the `def`/`class` line:

    def wide(a, b, c, d, e):  # quality-override: params=5 reason=CDP wire ...

The marker goes on the `def`/`class` line or anywhere in the signature
header, and names the metric, the value it accepts and a reason of at least
20 characters. A marker whose value no longer matches the measurement
is reported as stale (shrink it) or drift (worse than accepted), never as
accepted, so an override can not hide a new problem.

Usage:
    python3 tools/metrics/gate_check.py backend/tab_matcher.py
    python3 tools/metrics/gate_check.py stores/ actions/wait_page.py   # a dir works
    python3 tools/metrics/gate_check.py stores/label_state.py --only _normalized
    python3 tools/metrics/gate_check.py services/run --strict          # exit 1
    python3 tools/metrics/gate_check.py services --quiet --classes     # one line

Exit code: 0 when nothing is over the limit, 1 with --strict when something is
over *without* an accepted override, 2 on a bad path. This repo has no CI, so
this tool and tests/test_quality_override_format.py are what keeps §5 honest.
"""
from __future__ import annotations

import argparse
import ast
import os
import sys

LIMITS = {"loc": 30, "params": 4, "cc": 10, "cognitive": 15, "nesting": 4}
CLASS_LIMITS = {"loc": 150, "methods": 15}
OVERRIDE_KEY = "quality-override:"
OVERRIDE_METRICS = ("loc", "class-loc", "params", "methods", "cc", "cognitive",
                    "nesting", "coverage", "vulture", "dup")
# Marker token -> measured key, per symbol kind. Tokens absent here belong
# to another stage (coverage, vulture, duplication) and are left alone.
MINE = {"function": {"loc": "loc", "params": "params", "cc": "cc",
                     "cognitive": "cognitive", "nesting": "nesting"},
        "class": {"class-loc": "loc", "methods": "methods"}}
MIN_REASON = 20
BLOCK = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith,
         ast.Try, ast.Match)
FUN = (ast.FunctionDef, ast.AsyncFunctionDef)

try:
    from radon.complexity import cc_visit
except ImportError:                                        # pragma: no cover
    cc_visit = None
try:
    from cognitive_complexity.api import get_cognitive_complexity
except ImportError:                                          # pragma: no cover
    get_cognitive_complexity = None


def nesting(node, depth=0):
    best = depth
    for child in ast.iter_child_nodes(node):
        d = depth + 1 if isinstance(child, BLOCK) else depth
        best = max(best, nesting(child, d))
    return best


def params_of(node):
    a = node.args
    named = [x for x in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)
             if x.arg not in ("self", "cls")]
    return len(named) + bool(a.vararg) + bool(a.kwarg)


def _cc_map(src):
    """{lineno: cc} from radon (keyed by line, so names never collide)."""
    if cc_visit is None:
        return {}
    try:
        return {b.lineno: b.complexity for b in cc_visit(src)}
    except Exception:
        return {}


def span(node):
    """Inclusive AST source span of a node, decorators excluded."""
    return (node.end_lineno or node.lineno) - node.lineno + 1


def cognitive(node):
    return (get_cognitive_complexity(node) if get_cognitive_complexity
            else None)


def function_metrics(node, cc):
    """The gates RULE 16 measures on a def."""
    return {"loc": span(node), "params": params_of(node),
            "cc": cc.get(node.lineno), "cognitive": cognitive(node),
            "nesting": nesting(node), "methods": None}


def class_metrics(node):
    """The gates RULE 16 measures on a class (the rest are not defined)."""
    return {"loc": span(node), "params": None, "cc": None, "cognitive": None,
            "nesting": None,
            "methods": sum(1 for b in ast.walk(node) if isinstance(b, FUN))}


def measure(node, cc, kind):
    """One row of gate numbers for a def/class AST node.

    Unmeasured fields stay None so nothing prints a 0 that means "not
    measured"; `header_end` is where a signature's last line sits, which is
    as far as a marker comment is looked for.
    """
    row = {"name": node.name, "line": node.lineno, "kind": kind,
           "header_end": node.body[0].lineno - 1 if node.body else node.lineno}
    row.update(class_metrics(node) if kind == "class"
               else function_metrics(node, cc))
    return row


def rows_for(path, only=None, want_classes=False):
    """Every def/class in `path`, measured, functions sorted by CC."""
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    cc = _cc_map(src)
    rows = [measure(n, cc, "function") for n in ast.walk(tree)
            if isinstance(n, FUN) and (not only or n.name in only)]
    rows.sort(key=lambda r: -r["cc"] if r["cc"] else 0)
    if want_classes:
        rows += [measure(n, cc, "class") for n in tree.body
                 if isinstance(n, ast.ClassDef)]
    return rows, src


def breaking(row, limits):
    """[(metric, value, cap)] this row is over, in `limits` order."""
    return [(m, row[m], cap) for m, cap in limits.items()
            if row.get(m) is not None and row[m] > cap]


# ── RULE 16 §5 overrides ───────────────────────────────────────────

def parse_override(text):
    """Parse a `quality-override:` comment body; None when there is none.

    Returns {"pairs": {metric: accepted value}, "reason": str} on success or
    {"error": what breaks §5} — a marker that cannot be parsed never
    suppresses anything.
    """
    if OVERRIDE_KEY not in text:
        return None
    body = text.split(OVERRIDE_KEY, 1)[1].strip()
    head, sep, reason = body.partition("reason=")
    if not sep:
        return {"error": "no reason= (RULE 16 §5 requires one)"}
    reason = reason.strip().rstrip(".,")
    if len(reason) < MIN_REASON:
        return {"error": f"reason is {len(reason)} chars, needs >= {MIN_REASON}"}
    pairs = {}
    for token in head.replace(",", " ").split():
        metric, eq, value = token.partition("=")
        if not eq or metric not in OVERRIDE_METRICS or not value.isdigit():
            return {"error": f"'{token}' is not metric=value from §5's list"}
        if metric in pairs:
            return {"error": f"{metric} is listed twice (one per symbol)"}
        pairs[metric] = int(value)
    if not pairs:
        return {"error": "no <metric>=<value> before reason="}
    return {"pairs": pairs, "reason": reason}


def header_comment(src_lines, start, end):
    """The first `#` comment in a def/class signature header, or ""."""
    for line in range(start, min(end, len(src_lines)) + 1):
        text = src_lines[line - 1]
        pos = text.find("#")
        if pos >= 0 and OVERRIDE_KEY in text:
            return text[pos + 1:].strip()
    return ""


def apply_marker(pairs, measured, owned):
    """(accepted, notes, covered) for one marker against one symbol.

    A token naming a metric this tool does not measure (coverage, vulture,
    duplication) is left to its own stage. A token that does not match the
    measured value is a note, never an acceptance — drift can not hide behind
    an override written for a smaller number.
    """
    accepted, notes, covered = [], [], set()
    for token, value in sorted(pairs.items()):
        key = owned.get(token)
        if key is None:
            continue
        if key not in measured:
            notes.append(f"{token}: gate is not broken, override can go")
        elif value < measured[key]:
            notes.append(f"{token}: measured {measured[key]} > accepted {value}")
        elif value > measured[key]:
            notes.append(f"{token}: stale, measured {measured[key]}")
        else:
            accepted.append(f"{token}={value}")
            covered.add(key)
    return accepted, notes, covered


def judge(row, src_lines, limits=LIMITS):
    """(unexplained, accepted, notes, reason) for one measured symbol."""
    open_items = breaking(row, limits)
    marker = parse_override(header_comment(src_lines, row["line"],
                                           row["header_end"]))
    if marker is None:
        return open_items, [], [], ""
    if "error" in marker:
        return open_items, [], [marker["error"]], ""
    measured = {m: v for m, v, _cap in open_items}
    accepted, notes, covered = apply_marker(marker["pairs"], measured,
                                            MINE[row["kind"]])
    rest = [item for item in open_items if item[0] not in covered]
    return rest, accepted, notes, marker["reason"]


def flag(unexplained, accepted, notes, reason=""):
    """The one-line verdict a row gets, or "" when nothing is wrong."""
    parts = []
    if unexplained:
        parts.append("<-- " + ",".join(f"{m}={v}>{c}" for m, v, c in unexplained))
    if accepted:
        parts.append("accepted: " + ",".join(accepted) + " — " + reason)
    if notes:
        parts.append("override " + " / ".join(notes))
    return ("  " + "  ".join(parts)) if parts else ""


def print_table(rows, verdicts):
    print(f"  {'line':>5} {'name':32s} {'LOC':>4} {'p':>3} {'CC':>4} "
          f"{'cog':>4} {'nest':>4}")
    for row in rows:
        v = verdicts.get((row["kind"], row["line"]), ([], [], [], ""))
        print(f"  {row['line']:5d} {row['name']:32s} {row['loc']:4d} "
              f"{str(row['params']):>3} {str(row['cc']):>4} "
              f"{str(row['cognitive']):>4} {str(row['nesting']):>4}"
              f"{flag(*v)}")


def py_paths(targets):
    out = []
    for t in targets:
        full = t if os.path.isabs(t) else os.path.join(ROOT_HINT, t)
        if os.path.isdir(full):
            for base, dirs, files in os.walk(full):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                out += [os.path.join(base, f) for f in sorted(files)
                        if f.endswith(".py")]
        elif os.path.isfile(full):
            out.append(full)
        else:
            print(f"not found: {t}", file=sys.stderr)
            sys.exit(2)
    return out


ROOT_HINT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_file(path, args):
    """(rows, verdicts, unexplained, accepted) for one file."""
    rows, src = rows_for(path, args.only, args.classes)
    lines = src.splitlines()
    limits = CLASS_LIMITS
    verdicts = {}
    for row in rows:
        cap = limits if row["kind"] == "class" else LIMITS
        v = judge(row, lines, cap)
        if v[0] or v[1] or v[2]:
            verdicts[(row["kind"], row["line"])] = v
    tally = (sum(len(v[0]) for v in verdicts.values()),
             sum(len(v[1]) for v in verdicts.values()))
    return rows, verdicts, tally


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--only", nargs="*", default=None,
                    help="restrict to these function names")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when a violation has no accepted override")
    ap.add_argument("--classes", action="store_true",
                    help="also report class size/method count")
    ap.add_argument("--quiet", action="store_true", help="only the summary line")
    args = ap.parse_args(argv)

    bad = good = 0
    for path in py_paths(args.targets):
        rows, verdicts, tally = check_file(path, args)
        bad += tally[0]
        good += tally[1]
        if args.quiet:
            continue
        print(f"\n{os.path.relpath(path, ROOT_HINT)}  ({len(rows)} functions)")
        print_table(rows, verdicts)
        if not verdicts:
            print("  all functions inside the RULE 16 gates")
    if cc_visit is None:
        print("\nNOTE: radon is not installed — CC column is empty, "
              "complexity checks skipped.", file=sys.stderr)
    print(f"\nviolations: {bad + good} "
          f"(accepted with reason: {good}, unexplained: {bad})")
    return 1 if (args.strict and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
