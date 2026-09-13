# Round 4 steps 8–9 — general changed-code gate and new priorities

Written 2026-09-13. Scope is tooling/tests/docs; do not silently start another
production refactor while closing this round. Previous full baseline:
2837 passed, 3 skipped, 1 deselected, 1 xfailed; line 13534/14838 (91.21175%),
branch 3125/3634 (85.99340%). Work stays on `arena/01a093f4-chat-v-bot`.

## Research

`tools/metrics/rule16_gate.py` checks ten OWNED feature functions, two ratcheted
classes and limited smell scopes. It does not discover arbitrary changed code.
Its missing tools are reported but do not fail its CLI. The hook runs against
the working tree, not necessarily the staged content. The CI file is a template
under `tools/ci/`, deliberately inactive after a recorded GitHub workflow-permission
rejection. Do not claim hosted enforcement or activate it blindly.

The old feature walker also misses positional-only parameters and match nesting,
counts nested methods as direct class methods, and cannot distinguish equal
function names in different scopes. The repository-wide audit already has
isolated-function/depth helpers aligned with the documented AST counting rules.
Use those helpers, import the existing LIMITS/CLASS_LIMITS as the sole thresholds,
and test the missing AST cases explicitly; leave historical feature tests intact.

Fresh production audit: Collector 518 LOC/39 methods; ScrollParser 507/37;
HistoryBridge 474/31; UndoService 460/30. Largest file is now scroll_parser.py
(674), followed by db_deletion.py (665). CC > 10 and nesting > 4 are zero;
router remains the sole cognitive offender. Step 9 must combine these numbers
with behavior/lifecycle risk, not merely sort physical file lengths.

## Step 8 design

Create a cohesive tools/metrics/changed_code package and a CLI entry point.
No application imports. Tools are out of production-size scope but still use
small, named responsibilities: snapshots, symbols/measurements, policy/overrides,
inspections, test/coverage verification, CLI orchestration.

### Source selection and matching

* Default: HEAD vs tracked working files plus non-ignored untracked production
  Python. Explicit `--base REV`, `--head REV` for commit comparisons.
* `--staged`: inspect Git index blobs, including partial staging; unstaged fixes
  cannot hide a staged breach. No checkout/stash/reset or index mutation.
* Paths come from NUL-delimited Git output. Only main.py and the seven production
  package prefixes qualify. Report deletions. Reject missing/invalid revisions,
  conflicts, symlinked production sources and broken syntax rather than passing.
* Read snapshots without importing production. Enumerate nested definitions,
  repeated property/overload names and direct methods with stable scoped keys.
  Compare AST content plus measurements, so comments/blank lines can still
  trigger a physical-LOC increase. Never key functions by bare name alone.
* Treat only unique one-to-one exact-AST relocations from removed definitions
  as moves. Copies do not inherit a legacy allowance; ambiguous/renamed/rewritten
  moves conservatively face new-code limits.

### Policy

* New/fitting symbols obey all hard limits. For an edited legacy offender,
  no measured axis may worsen, including an axis currently below its hard limit.
* New classes are limited to 150 LOC/15 direct methods. Nested classes/methods
  are measured separately, not accidentally charged twice.
* Parse real comment tokens attached to a definition, never strings/docstrings.
  Per-metric overrides require exact current values, >=20-character reasons,
  supported metrics, and no duplicates. Reject malformed/orphan/stale comments.
  An override never masks legacy worsening. A JS/HTML LOC exception uses the
  existing explicit override syntax and must have a single literal accounting
  for the excess; all control-flow checks remain active. No blanket exemption
  for any long string. Human review still evaluates whether a reason is real.
* Missing radon/cognitive-complexity, and missing smell tools when requested,
  are errors (exit 2), not successful skips. Breaches exit 1; checked scope fits
  exits 0 with skipped optional checks stated explicitly.

### Quality beyond structural metrics

* Default changed-code checks compare Vulture >=90% and Pylint unused-import
  findings against the same base/target snapshots, ignoring line drift only.
  Materialize temporary sources for Pylint; never inspect unstaged bytes when
  the selected target is the index. Tool errors/invalid output are errors.
* `--with-clones` uses the persisted exact-AST window scanner against both
  snapshots. Compare occurrence budgets, not only file-pair labels: an extra
  clone in an already-known pair must fail. No editing clone baselines to pass.
* `--structure-only` is explicitly a partial check for fast local diagnostics;
  the hook uses the default including unused-code/import checks.
* `--run-tests` (working tree only) runs real full production branch coverage
  and verifies the source snapshot did not change during execution. Do not
  accept an arbitrary stale coverage JSON as proof. Enforce machine-readable
  previous-slice line/branch ratios and reject zero-hit new functions, including
  ambiguous one-line def/body coverage. Mutation remains explicitly separate.
  The hook does not run the multi-minute suite; CI's suite job invokes this mode.

### Wiring and tests

Keep the historical feature gate as an additional hook; add the new index-aware
hook. Update the inactive CI template to full fetch history, safe environment
variables for event SHAs, explicit base resolution (including new-branch push
fallback), and the same general CLI plus coverage. Record activation as pending
workflow permission rather than claiming a hosted run.

Tests must execute real Git snapshots in disposable fixture repos, independent
of this checkout's index. Exercise staged-invalid/unstaged-valid and the reverse,
untracked files, commit comparisons, additions/deletions/renames/copies, invalid
bases/conflicts/symlinks, duplicate names/nested definitions, every threshold,
legacy ratchets, overrides/JS, missing/broken tools, clone growth, unused imports,
and coverage failures. No source-string-only proof that a gate is wired.

## Step 9 and acceptance

Re-run the production audit and full suite; produce a concise current priority
queue with a bounded first Collector lifecycle slice, plus safety/coverage
reasons and deferred risks. Do not pad the already-complete sync package.
Update current docs/map without growing the system-of-record context file.
Report all validation and CI/mutation limitations honestly in
`reports/REFACTOR_ROUND4_STEPS_8_9_2026-09-13.md`.
