# Refactoring round 4 — first slice results (2026-09-12)

**Status: stages 1–3 complete; stages 4–9 remain queued.** This is not a claim
that all legacy code now meets RULE 18.

Design, priority rationale and step-by-step queue:
`docs/archive/2026-09-12-refactor-round4/ROUND4_DESIGN.md`.
Baseline commit: `59f45eb7`; working branch: `arena/01a093f4-chat-v-bot`.
Measurements use the working tree after this slice, not an older report's totals.

## Highest-priority findings

The September 11 ideal-size snapshot preceded completion of CC round 3. Fresh
measurement confirms **zero CC > 10 and zero nesting > 4**. Repeating the old
CC queue would be wasted work. Two cognitive offenders remained, and the largest
file was `backend/chat_sync.py` (791 lines), in the archive-writing path.

The other systemic problem is incomplete automation: RULE 16's fixed OWNED
list does not cover arbitrary production edits, and the CI template under
`tools/ci/` is not active. This slice adds executable checks for its own scope;
a general base-SHA-aware gate remains explicitly queued, not claimed solved.

## What changed

1. **Simplified settings fallback after characterization tests.** The missing
   overlay path's defaults-tree traversal is now `_default_value`; explicit
   null/scalar intermediates still block fallback, falsy values survive, no-key
   reads retain identity, and the file persists only the overlay.
2. **Extracted a real planning boundary.** `backend/sync/planning.py` holds
   immutable options, read plans and pure decisions together. It imports no
   parser/runtime, Qt, store or service. Runtime and all existing callers still
   use the same class objects through `backend.chat_sync` re-exports.
3. **Fixed API-audit treatment of explicit facade exports.** The initial API
   check flagged the three re-exported classes as removed because their defining
   module changed. The audit now recognizes explicit `__all__` exports; tests
   prove it still detects removed symbols and changed signatures and excludes
   incidental imports. No golden snapshot, existing test, method signature,
   class metadata or behavior was rewritten to hide the issue.
4. **Scoped quality checks are executable.**
   `tests/test_refactor_round4_quality.py` enumerates all planning methods and
   classes and measures the two changed settings functions with the existing
   RULE 16 engine. It rejects missing complexity tools rather than going green
   without measurement. Rule 18 ideals are reviewed, not turned into fail lines.

## Before / after metrics

| Metric | Before | After |
|---|---:|---:|
| `SettingsStore.get`: LOC / CC / cognitive / nesting | 17 / 7 / 17 / 4 | **10 / 4 / 6 / 2** |
| `_default_value`: LOC / CC / cognitive / nesting | — | **8 / 4 / 5 / 2** |
| `backend/chat_sync.py` physical lines | 791 | **600** |
| New `backend/sync/planning.py` physical lines | — | **221** |
| Planning maximum function LOC / CC / cognitive / nesting / params | unchanged algorithms | **21 / 8 / 7 / 1 / 4** |
| Planning class LOC / direct methods | — | options **73 / 6**, plan **38 / 4**, planner **82 / 7** |
| Project cognitive > 15 | 2 | **1** (legacy Qt router factory, 17) |
| Project CC > 10 / nesting > 4 | 0 / 0 | **0 / 0** |
| Project functions > 30 LOC | 44 | **44** (remaining legacy, including JS exceptions) |
| Project files > 500 LOC | 10 | **10** (runtime extraction deliberately incomplete) |
| Production files / functions | 148 / 1921 | **150 / 1922** |

RULE 19 order: simplify the remaining settings cognition before file-size
work. The sync code already has small named decisions, so this is RULE 19.5's
long-and-flat case: move a responsibility, do not invent more decision helpers.

RULE 18 review: planning is in the 150–300 file band; classes are below the
120-line preference. Its 21-line `plan` has an inline `ideal-size:` explanation
for the immutable four-mode return contract. Existing four-argument planner
signatures remain intact for compatibility. Settings functions are 8 and 10
lines; settings file is 164 lines. The six-line package initializer is only a
boundary doc. A two-file package is the first real slice toward 5–7 cohesive
files, not an excuse to generate empty modules. The residual runtime's shared
session lifecycle needs stages 4–7 before it can honestly fit the file ideal.

## Validation

| Check | Result |
|---|---|
| Full suite before production edits | **2653 passed**, 3 skipped, 1 deselected, 1 xfailed; 774 subtests |
| Full suite after | **2697 passed**, 3 skipped, 1 deselected, 1 xfailed; 774 subtests |
| Standalone `tests/test_rule16_new_code.py` | **23 passed**, no skipped measuring tools |
| New round-specific quality checks | **20 passed** (included in full suite) |
| Node harnesses | **25 files passed**, zero failures |
| Existing backend + stores API snapshots | pass unchanged |
| Sync extraction AST comparison against base commit | every class/function body unchanged, including moved definitions |
| Exact-AST clone gate | zero new groups, zero stale baseline entries |
| Vulture >= 90% | same seven pre-existing findings, none in changed production code |
| Pylint unused-import check on changed production | zero findings |
| `git diff --check` | clean |

### Coverage (separate line and branch percentages)

| Scope | Before | After |
|---|---:|---:|
| Overall lines | 13437 / 14761 = **91.03042%** | 13446 / 14768 = **91.04821%** |
| Overall branches | 3112 / 3628 = **85.77729%** | 3112 / 3628 = **85.77729%** |
| Extracted planning | covered through old sync module | **118 / 118 lines; 16 / 16 branches (100%)** |

Every extracted/new production function executes under assertions; both changed
settings functions have all executable lines covered. No legacy metric worsened
on edited functions. New classes fit all hard limits. No quality overrides were
added. Overall coverage does not decrease against either this round's measured
baseline or the recorded 90.44% / 84.38% floors. Combined coverage.py percentage
is deliberately not used as the acceptance metric.

### Limits / known debt

* Real WebEngine rendering was deselected in this headless environment, using
  the documented repository command. Qt imports used `tools/build_stubs.py`.
* One pre-existing unawaited collector-push coroutine warning occurs both
  before and after; it is not a new regression or silently fixed here.
* Mutation testing is configured only for untouched `backend/history_query.py`.
  No mutation score is claimed for this slice; wiring touched pure modules
  remains a follow-up. Existing behavior tests and 100% planning coverage are
  not presented as substitutes for mutation testing.
* This is a structural refactor, not a production Chrome smoke test. Stop during
  slice retries, async progress callbacks, session lifecycle and the remaining
  oversized classes need their own behavior review before the next extraction.

## Reproduction

Install `requirements-dev.txt` into `.venv`. On a host missing Qt system libs,
run `.venv/bin/python tools/build_stubs.py .venv /tmp/stublibs` first.
Keep generated reports and logs outside Git, e.g. under `/home/user/`.

```bash
.venv/bin/python tools/metrics/current_audit.py > /home/user/round4-audit.json
.venv/bin/radon cc -s backend/sync/planning.py stores/settings_store.py
.venv/bin/python tests/test_rule16_new_code.py
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
.venv/bin/python -m coverage json -o /home/user/round4-coverage.json
for f in tests/test_*.js; do node "$f" || exit 1; done
.venv/bin/pylint --disable=all --enable=unused-import \
  backend/chat_sync.py backend/sync stores/settings_store.py
```

**Next bounded step:** characterize cursor/gap/media-write ordering, then move
`SyncPersister` plus live-result aggregation into `backend/sync/persistence.py`.
Do not move the remaining runtime wholesale or bundle a cancellation change
into that behavior-preserving extraction.
