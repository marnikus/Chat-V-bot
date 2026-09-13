# Changed-code quality gate — operating notes (2026-09-13)

The general gate implements the structural/differential parts of RULE 16 across
production Python, rather than relying on a feature's fixed `OWNED` list.
The old feature gate/tests remain additional historical invariants.

## Commands

Install `requirements-dev.txt` into the Python environment used below. Runtime
requirements are unchanged. Missing analysis packages cause exit **2**, not a
successful skip.

```bash
.venv/bin/python tools/metrics/changed_code_gate.py
.venv/bin/python tools/metrics/changed_code_gate.py --staged
.venv/bin/python tools/metrics/changed_code_gate.py --base BASE --head TARGET
.venv/bin/python tools/metrics/changed_code_gate.py --base BASE --with-clones
.venv/bin/python tools/metrics/changed_code_gate.py --structure-only --json
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python tools/metrics/changed_code_gate.py --with-clones --run-tests
```

`BASE`/`TARGET` are real local Git revisions; fetch missing history first.
Default base is HEAD. For an unborn repository, explicitly use `--base EMPTY`.
Do not use EMPTY as a way to grant legacy allowances: it checks everything as new.
`--head` and `--staged` are mutually exclusive. `--run-tests` accepts only the
working tree, never claims that tests against unstaged bytes validate the index.

| Target | Source read |
|---|---|
| Default | Index-tracked working files plus non-ignored untracked files |
| `--staged` | Git index blobs, including partial staging |
| `--head REV` | Committed tree blobs, regardless of dirty working files |

Only `main.py` and Python files beneath `core`, `actions`, `backend`, `bridge`,
`services`, `stores`, `app` qualify. Paths are read NUL-delimited. Selected
production symlinks, unresolved conflicts, bad syntax and missing revisions fail
closed. The gate never stashes, checks out, resets or writes the index.

Exit **0** means requested checks passed; **1** means a policy breach/test failure;
**2** means an input/tool error prevented a complete check. JSON includes changed
files, deletions, scoped measurements, classifications, breaches and explicit
`not_checked` items. Base/committed target identifiers are resolved Git **trees**.

## Policy and review

* Thresholds are imported from `tools/metrics/rule16_gate.py`, not copied into
  another independently maintained limit table.
* Definitions include nested functions/classes and repeated property/overload
  names. Physical LOC changes matter even when the AST does not change.
* Positional-only, keyword-only, variadic arguments count. Only a real leading
  method receiver named self/cls is excluded; static/nested/standalone parameters
  cannot hide behind those names. Nested control flow is scored in its own scope;
  match nesting and direct class methods are measured explicitly.
* Fitting/new definitions obey every cap. Editing a legacy offender may not
  worsen **any** measured axis, even one still below its cap.
* Only unique, exact-AST relocations from removed definitions inherit a baseline.
  Copies and ambiguous/renamed/rewritten moves face new-code limits. Move reports
  name their source symbol. This intentionally favors conservative false alarms
  over granting unrelated new code a legacy allowance.
* Overrides are actual comment tokens attached to a definition: numeric measured
  value, supported structural metric, reason of at least 20 characters, no
  duplicate/malformed/orphan/stale entries. They never excuse legacy worsening.
  JS/HTML LOC reasons require one literal accounting for the excess, not a blanket
  long-string exemption. Other axes still apply.
* This release supports structural override metrics only. `coverage`, `vulture`
  and `dup` waiver comments fail closed rather than silently waiving checks;
  their per-finding semantics need separate design. Review still determines
  whether a reason states a real constraint and whether tests assert behavior.

Default smells compare Vulture >=90% and Pylint unused imports on the **same**
base/target snapshots. Pylint gets temporary materialized files with encoding
cookies preserved, not application imports. Findings ignore line-number drift,
not filename/identity/count changes. Relocating an existing smell may therefore
require actually removing it. Broken tools/output cannot produce a clean result.

`--with-clones` uses the existing exact-AST window scanner on both trees and
compares occurrence budgets. Another clone in an already-known file pair is
still new debt. Baseline files are not regenerated to make a change pass.
`--structure-only` explicitly skips smells; it is **not** the commit hook mode.

## Coverage provenance

`--run-tests` runs the real full pytest suite under branch coverage, using unique
coverage data/output paths and a **fresh bytecode cache**. Same-size/same-mtime
source or test changes must not reuse old `.pyc` files. Inherited pytest selection
filters are removed; the repository's strict-markers/no-cacheprovider behavior is
retained explicitly. Production content is checked after pytest and again after
coverage export. Arbitrary externally supplied coverage JSON is not accepted.

Line and branch ratios are separate; exact previous-slice counts live in
`reports/quality/coverage_baseline.json`. A definition-line hit alone is not proof
that a new function ran. Ambiguous inline bodies, including multiline signatures
with same-line bodies, fail the zero-hit check conservatively.

The real-WebEngine GL test is deselected by exact node ID, not by whole module.
Live Chrome/WebEngine validation and mutation are separate and explicitly not
claimed by this gate. `setup.cfg` still configures mutation only for history_query.

## Hook and hosted enforcement

```bash
.venv/bin/pre-commit install
.venv/bin/pre-commit validate-config
```

The new local hook has its own Python environment with pinned analysis tools.
The original feature hook remains alongside it. A real configured-hook smoke
check in a disposable Git repo tested both partial-staging directions without
changing this checkout's index. Full suites/clones are omitted from the hook and
reported as not checked; `--no-verify` can bypass local hooks.

**Hosted CI is NOT active.** `tools/ci/quality-gate.yml` remains a template after
a recorded workflow-permission rejection. An authorized maintainer must activate
it under `.github/workflows/` and configure branch protection. No hosted run or
changed GitHub App permission is claimed.

The template fetches full history and checks out the actual event head. The
resolver accepts SHAs via environment variables, verifies checkout identity,
uses PR merge-base/normal push-before, and handles all-zero new-branch pushes.
New feature branches use the default branch merge-base; initial default-branch
or unavailable/unrelated default history checks all code via EMPTY. Missing
normal/PR revisions fail rather than quietly comparing HEAD with itself.
