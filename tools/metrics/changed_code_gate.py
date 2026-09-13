#!/usr/bin/env python3
"""General RULE 16 gate: real base/worktree/index snapshots, not a feature list."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--base", default="HEAD", help="Git revision, or EMPTY for an unborn repository")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--head", help="compare a committed revision, not working files")
    target.add_argument("--staged", action="store_true", help="read Git index blobs, ignoring unstaged bytes")
    parser.add_argument("--structure-only", action="store_true", help="explicitly skip unused-code/import checks")
    parser.add_argument("--with-clones", action="store_true")
    parser.add_argument("--run-tests", action="store_true", help="run full working-tree branch coverage (not index/head)")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def evaluate(args):
    # Import inside the error boundary: absent analysis packages must exit 2,
    # never crash before a machine-readable 'not checked' error is emitted.
    from tools.metrics.changed_code import policy, snapshots, symbols

    pair = snapshots.load(args.root, args.base, args.head, args.staged)
    before, after = symbols.collect(pair.before), symbols.collect(pair.after)
    result = policy.compare(before, after)
    new_functions = result.pop("new_functions")
    result.update(base=pair.base, target=pair.target, changed_files=pair.changed_files,
                  deleted_files=pair.deleted_files, errors=[], not_checked=[], checks={})
    result["checks"]["structure"] = "passed" if not result["breaches"] else "failed"
    if args.structure_only:
        result["not_checked"].append("unused code/imports (--structure-only)")
    else:
        from tools.metrics.changed_code.inspections import unused
        findings = unused(pair)
        result["breaches"].extend(findings)
        result["checks"]["unused"] = "failed" if findings else "passed"
    if args.with_clones:
        from tools.metrics.changed_code.inspections import clones
        findings = clones(pair)
        result["breaches"].extend(findings)
        result["checks"]["clones"] = "failed" if findings else "passed"
    else:
        result["not_checked"].append("clones (use --with-clones)")
    if args.run_tests:
        from tools.metrics.changed_code.testing import run_tests
        test_result = run_tests(args.root, pair, new_functions)
        result["tests"] = test_result
        result["breaches"].extend(test_result["breaches"])
        result["checks"]["tests/coverage"] = "failed" if test_result["breaches"] else "passed"
    else:
        result["not_checked"].append("tests/coverage (use --run-tests on working tree)")
    result["not_checked"].append("mutation (separate configured job)")
    return result


def main(argv=None):
    args = arguments(argv)
    try:
        result = evaluate(args)
        code = 1 if result["breaches"] else 0
    except Exception as exc:  # CLI boundary: any broken tool is ERROR, never a policy pass
        result = {"errors": [f"{type(exc).__name__}: {exc}"], "breaches": [],
                  "not_checked": ["requested checks incomplete; install requirements-dev.txt or fix the input/tool error"]}
        code = 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Changed-code RULE 16: {len(result.get('rows', []))} symbols; exit {code}")
        for name, status in result.get("checks", {}).items():
            print(f"  {name}: {status}")
        for message in result["breaches"] + result["errors"]:
            print(f"  FAIL: {message}")
        for message in result["not_checked"]:
            print(f"  NOT CHECKED: {message}")
    return code


if __name__ == "__main__":
    sys.exit(main())
