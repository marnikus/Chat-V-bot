# Round 4 — steps 8 and 9 (2026-09-13)

**Delivered:** the general changed-code gate, index-safe pre-commit hook, updated
CI template, and a fresh risk-ranked follow-up queue. **Hosted CI remains
inactive** pending authorized workflow activation. Steps 8–9 changed tooling,
tests and docs only; the completed production changes from steps 1–7 are retained.

Branch: `arena/01a093f4-chat-v-bot`; comparison base: current HEAD `59f45eb7`.
Design: `docs/archive/2026-09-13-refactor-round4/STEPS_8_9_DESIGN.md`.
[Operating notes](../docs/archive/2026-09-13-refactor-round4/CHANGED_CODE_GATE.md) ·
[New priorities](../docs/archive/2026-09-13-refactor-round4/FOLLOW_UP_PRIORITIES.md).

## 1. General gate, not a fixed feature list

Entry point: `tools/metrics/changed_code_gate.py`. Its seven-file support package
owns snapshots, scoped measurements, policy/overrides, inspections, coverage
verification and CI base resolution. It imports no application code.

* HEAD → working tree by default, including non-ignored untracked production
  Python. Explicit base/head commits and **Git index blobs** are supported.
  Partial staging does not substitute unstaged bytes for staged content.
* Scope is all seven production packages plus `main.py`. NUL-delimited Git paths,
  additions/deletions and scoped duplicate names are handled. Missing revisions,
  conflicts, selected production symlinks and invalid Python fail closed.
* Thresholds come from the existing `LIMITS`/`CLASS_LIMITS`; none were raised.
  Counts include positional-only/keyword-only/variadic parameters, real receiver
  exclusion, match nesting, isolated nested functions and direct class methods.
* New/fitting symbols must fit. Legacy offenders may not worsen **any** axis,
  even one below its cap. AST **and physical measurements** are compared.
* Only unique, exact-AST relocations from removed definitions inherit a baseline.
  Copies, ambiguous matches and renamed/rewritten moves get new-code treatment.
* Real comment tokens supply per-symbol structural overrides with exact values,
  non-whitespace reasons >=20 characters and duplicate/stale/orphan validation.
  No string-spoofed or blanket JS length waiver; no waiver of legacy worsening.
* Default Vulture >=90% and Pylint unused-import checks compare the same snapshots.
  Clone mode compares occurrence budgets, catching new clones in an existing file
  pair. Neither clone baselines nor golden API snapshots were rewritten.
* Exit 0 = requested checks passed, 1 = breach/test failure, 2 = tool/input error.
  Optional checks are explicitly listed as **not checked**, not silently green.

The accumulated steps 1–7 production diff now receives general coverage:

| Classification | Functions | Classes |
|---|---:|---:|
| New | 37 | 4 |
| Exact moves | 38 | 5 |
| Changed in place | 1 | 1 |
| **Total checked definitions** | **76** | **10** |

All **86** pass. The sole structural override is the already documented frozen
five-parameter `backend/sync/session.py::run_sync`; no new exception was added.
All 37 conservatively classified new function bodies have execution evidence.

## 2. Real tests and fresh coverage

Added **61 focused gate tests** in three files. Coverage includes real disposable
Git repositories, both partial-staging directions, committed comparisons,
untracked/ignored files, renames/copies, deletions, missing history, conflicts,
symlinks, every structural axis, strict ratchets, override/JS cases, missing/broken
tools, real unused imports, clone growth and CI base resolution. Smell identity
includes lexical scope: a new function cannot consume a removed function’s
warning budget in the same file; ordinary line drift remains allowed.

Coverage tests run actual pytest/coverage subprocesses in fixture repositories,
not only mocks. Additional unit cases reject missing sources, line/branch ratio
regression, definition-only hits, ambiguous inline function bodies, source drift,
unsupported index/commit coverage and failing suites.

**A real defect was found and fixed during validation.** The first full run had
one failure: a same-size test rewrite within the cached timestamp reused stale
pytest bytecode. A deterministic red regression reproduced it. The runner now
uses a unique Python bytecode cache for each run; merely passing `-B` would not
prevent stale reads. Tests cover stale **test and production** bytecode, and
inherited pytest selection filters cannot silently narrow the run. No production
behavior or old test expectation was changed to make this pass.

`--run-tests` invokes the full branch-coverage suite itself, checks production
content after pytest **and** after export, and accepts no arbitrary external
coverage JSON. Exact prior-slice ratio floors are stored in
`reports/quality/coverage_baseline.json`; combined coverage percentages are not
used as the line/branch gate. Strict marker/no-cacheprovider behavior is retained.

### Final validation

| Check | Final result |
|---|---|
| Full Python suite through the new gate | **2,898 passed**, 3 skipped, 1 deselected, 1 xfailed; 774 subtests; 432.54 s |
| New focused gate tests | **61 passed** |
| JavaScript DOM harnesses | **25 files passed** |
| General structure + unused code/imports + clones + tests/coverage | **All passed**, zero breaches/errors |
| Historical RULE 16 CLI with clones | Pass; zero new clones/stale baseline entries |
| Real configured pre-commit hook in disposable repo | Bad staged/good working rejected; good staged/bad working accepted; index/worktree unchanged |
| Pre-commit configuration / CI YAML | Validated locally; **not a hosted CI run** |
| Pylint unused imports on new tooling/tests | Clean |

| Coverage | Previous steps 6–7 | Final steps 8–9 |
|---|---:|---:|
| Lines | 13534 / 14838 = 91.21175% | **13534 / 14838 = 91.21175%** |
| Branches | 3125 / 3634 = 85.99340% | **3125 / 3634 = 85.99340%** |
| Zero-hit/ambiguous new functions | — | **0** |

The one pre-existing unawaited `Collector.handle_push` warning remains. Its direct
caller in a test discards the coroutine; production's CDP dispatcher does schedule
awaitables. This warning alone is not proof that production drops push events.
Real WebEngine is excluded by exact test node ID, not by excluding its whole file.
Live Chrome/WebEngine and changed-module mutation remain unvalidated here.

## 3. Hook and CI status

`.pre-commit-config.yaml` now runs the general staged gate in an isolated Python
environment with pinned analysis dependencies, followed by the historical feature
hook. Actual configured-hook executions, not source-string assertions, prove the
staged selection behavior. This checkout's index was not modified for testing.

`tools/ci/quality-gate.yml` remains an **inactive template** after the recorded
GitHub workflow-permission rejection. It uses full Git history, event-head
checkout, environment-based SHA handling, PR merge-base/normal push-before and
explicit new-branch handling. An absent/unrelated new-branch baseline conservatively
checks all code; missing normal/PR revisions error rather than passing a zero diff.
The suite job invokes actual fresh coverage; the other job adds clone checks.

An authorized maintainer must activate the workflow and branch protection.
A local `--no-verify` bypass is still not guarded by hosted checks. No permission
change, hosted run, commit or push is claimed.

## 4. Step 9: re-measured debt and the next decision

The fresh audit has **155 files, 1,933 functions, 206 classes**. Every production
measurement is unchanged from the pre-step-8 audit. Only test inventory grew:
185 Python test files, 36,366 nonblank/noncomment test lines versus 22,335 production
lines. CC >10 and nesting >4 remain **zero**. Router cognition 17 remains the one
cognitive offender; 44 functions exceed 30 lines, 36 classes exceed 150 lines and
26 classes exceed 15 methods. These are legacy inventories, not relaxed gates.

| Next large classes | LOC / direct methods | Why not just split by size? |
|---|---:|---|
| Collector | 518 / 39 | Queue ownership, stop/task state, push and world switching |
| ScrollParser | 507 / 37 | Virtual scrolling, progress and filter-purge invariants |
| HistoryBridge | 474 / 31 | Frozen named Qt slots and wire payloads |
| UndoService | 460 / 30 | One global timeline and persistent undo semantics |
| SchemaMigrator / PersonLifecycle | 386 / 25; 370 / 19 | More cohesive, transaction/deletion-sensitive code |

**New top priority: Collector violates RULE 14/I-12 today.**
`CollectorArchive.open_person` calls `_remember_partner`, which inserts unknown
partners into `UserMemory.users`; existing `TestRememberPartner` cases explicitly
expect that behavior. The current rule says collectors must not add to the queue.
This established behavior conflicts with the current ownership contract and
outranks another size extraction. It is documented, **not silently fixed** here.

Next: a bounded queue-ownership correctness patch with real-world DB assertions
for unknown/filtered-out partners and unchanged existing queue/archive state.
Then take the bounded heartbeat/cadence slice across Collector and CollectorRuntime,
with explicit task ownership and stop/restart characterization. The detailed
follow-up document names the candidate boundary, acceptance matrix and separate
push/world-swap investigations. No further sync padding or obsolete CC-tail work.

## 5. RULE 16 / RULE 18 final review and limits

No production source changed in steps 8–9. Hard caps, historical feature checks,
API goldens and clone baselines are preserved. The tooling package has **seven
cohesive files (5–142 lines)** plus an 89-line CLI; three test files are 157–215
lines. Short leaves are intentional, not padded to reach 150. A few tooling-only
validation/orchestration functions exceed the 20-line ideal so their error
boundary, temporary resources and ordered checks remain readable in one place;
they do not introduce production overrides or hide decisions in dispatch lambdas.

SYSTEM_OF_RECORD stays at **305 lines**, the documentation map at **81**, and the
rules file does not grow. Deep detail lives in the dated archive. The current
record marks the Collector ownership discrepancy instead of presenting I-12 as
fully enforced.

Limitations are explicit: hosted activation pending; feature-envy and truth of
exception reasons still require review; coverage is not proof of meaningful
assertions; ambiguous moves/inline bodies intentionally err toward rejection.
Only structural waiver metrics are implemented—coverage/Vulture/clone waiver
comments fail closed pending separate per-finding semantics. Mutation remains a
separate configured history_query job, not a score for this round's changed code.

## Reproduce / artifacts

```bash
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python tools/metrics/changed_code_gate.py --with-clones --run-tests --json
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
.venv/bin/python -m pytest --noconftest -q tests/test_changed_code_gate.py \
  tests/test_changed_code_policy.py tests/test_changed_code_inspections.py
for test in tests/test_*.js; do node "$test"; done
.venv/bin/python tools/metrics/current_audit.py
```

Workspace evidence is retained outside Git under `/home/user/round4-step89/`:
`before.json`, `after.json`, `full-gate.json`, `full-gate-first-failed.json`,
`freshness-red.log`, `smell-scope-red.log`, `focused.log`, `hook-final.log`, `historical-gate.log`,
`node.log`, plus the disposable hook exerciser/fixture. Temporary coverage files
are deliberately private to each run and removed afterward; the final result
retains separate ratios, source-binding status and the real pytest summary.
