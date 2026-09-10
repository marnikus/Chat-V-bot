# Code quality audit — 2026-09-10

Snapshot: `a49dd2a`, branch `arena/01a08b46-chat-v-bot`. No production code changed for this audit.

## Executive summary

**Your fixes materially improved test health and reduced the worst complexity hotspots. Global Python coverage now passes both requested thresholds.** Remaining work is concentrated in bridge coverage, large classes, and a small tail of complex functions. This is not a claim that the desktop application or live Chrome workflow has been fully validated.

### Before → now

Previous values are recorded in `docs/archive/2026-09-09-four-area-refactor/REFACTOR_2026-09-09_FOUR_AREA_PLAN.md`; the old checkout was not rerun. Only one commit is available in this shallow checkout.

| Metric | Previous documented audit | Current | Interpretation |
|---|---:|---:|---|
| Python test results | 983 passed / 377 failed in documented run | **2,129 passed / 0 failed** | Strong improvement; suite and execution scope changed |
| Python line coverage | 80.0% | **88.44%** | +8.44 percentage points |
| Python branch coverage | 69.7% | **81.32%** | +11.62 percentage points |
| Maximum legacy AST complexity | 130 | **31** | 76.2% reduction using the same legacy measure |
| Functions above legacy CC 10 | 75 (7.3%) | **67 / 1,532 (4.4%)** | Fewer hotspots despite more functions |
| Mean legacy CC | 4.2 | **3.31** | Lower average |
| Production Python files | 108 | **133** | Extraction increased module count |
| Production physical LOC | 18,251 | **22,373** | +22.6%; smaller functions do not imply less total code |
| Nonblank, non-comment lines, legacy definition | 15,322 | **18,499** | Includes docstrings and embedded JavaScript |

Historical coverage excluded a problematic test module; current coverage includes it. These are snapshot improvements, not a controlled same-test benchmark. Legacy CC is a custom AST decision count, not Radon CC. Do not compare the Radon violation count below directly to the old custom count.

## 1. Complexity and size against your thresholds

Scope: all 133 production Python files in `core`, `actions`, `backend`, `bridge`, `services`, `stores`, `app`, and `main.py`. Includes compatibility shims and nested definitions; excludes tests, tools, saved HTML/assets, frontend JavaScript and generated caches.

| Metric | Current result | Your upper threshold | Assessment |
|---|---|---|---|
| Cyclomatic complexity, Radon | Mean **3.25**, max **31**; **64 / 1,532** functions over 10 | ≤10 | 95.8% within threshold |
| Cognitive complexity | Mean **2.34**, max **28**; **22 / 1,532** over 15 | ≤15 | 98.6% within threshold; tool-specific |
| Maximum block nesting | **6**; **3 / 1,532** over 4 | ≤3–4 | Almost all within upper limit |
| Function physical length | Mean **9.98**, max **122 LOC**; **73 / 1,532** over 30 | ≤20–30 | 95.2% within upper limit |
| Class physical length | Max **504 LOC**; **11 / 180** over 300 | ≤200–300 | Remaining large-class candidates |
| Parameters | Max **20**; **69 / 1,532** over 4 | ≤3–4 | Some wide compatibility APIs remain |
| Direct methods per class | Max **44**; **23 / 180** over 15 | ≤10–15 | Responsibility review needed |
| Production volume | **22,373 physical LOC; 15,779 Radon SLOC** | No project-wide limit | Not intrinsically a quality score |

Definitions: function/class LOC is the inclusive AST source span, including blank lines, docstrings, and embedded JS, excluding decorators. Functions include constructors, nested functions, and async functions, not lambdas. Parameter counts exclude leading `self`/`cls`, include keyword-only arguments and each variadic collector. Class method counts include direct definitions, not inherited methods. Upper ends of your suggested ranges are used consistently.

Cognitive complexity uses `cognitive-complexity` 1.3.0, not a certified Sonar analysis. Nested definitions are assessed separately for function complexity and nesting. The corrected nesting traversal measures maximum ancestry, counts `if`/loops/with/try/match, and represents `elif` as nested AST `if`. The old `deep.py`/`area_d.py` nesting implementation incorrectly accumulates sibling depths; historical nesting numbers are **not comparable**.

### Current hotspots

| Location | Radon CC | Cognitive | LOC | Why prioritize |
|---|---:|---:|---:|---|
| `services/run/coordinator.py:90` `_execute_cycle` | 31 | 25 | 37 | Highest remaining CC, critical execution path |
| `stores/label_state.py:74` `_normalized` | 28 | 25 | 50 | Complex normalization decisions |
| `backend/history_query.py:80` `_item` | 22 | 22 | 34 | Dense item construction/branching |
| `services/db_lifecycle.py:103` `delete` | 21 | 25 | 72 | Destructive lifecycle path |
| `backend/tab_matcher.py:70` `score_tab` | 20 | 26 | 36 | Dense matching decisions |
| `actions/wait_page.py:33` `execute` | 18 | 28 | 43 | Highest cognitive score |

Largest classes include `ScrollParser` (**504 LOC / 36 methods**), `Collector` (**503 / 36**), `HistoryBridge` (**490 / 31**), and `UndoService` (**444 / 26**). These are review candidates, not proof of a god-class defect. Compatibility facades may intentionally retain many methods.

Longest function: `backend/dom_probe.py:39 build_probe`, **122 LOC**, CC **7**; embedded JavaScript makes raw length a poor standalone refactoring trigger. The widest constructor remains `actions/scroll_parse.py:40 __init__`, **20 parameters** under the audit definition.

## 2. Coupling and cohesion

Ca/Ce count distinct internal module imports, including conditional/type-only imports. External libraries, dynamic imports and runtime call dependencies are not included. Relative imports are resolved against package context. I is undefined for isolated modules rather than forced to zero.

| Module | Ca | Ce | I = Ce / (Ca + Ce) |
|---|---:|---:|---:|
| `bridge.router` | 1 | 15 | **0.938** |
| `services.run.coordinator` | 1 | 10 | **0.909** |
| `app.bootstrap` | 2 | 9 | **0.818** |
| `backend.config_manager` | 3 | 9 | **0.750** |
| `core.events` | 19 | 0 | **0.000** |
| `backend.cdp_client` | 16 | 0 | **0.000** |
| `actions.base_action` | 13 | 2 | **0.133** |

High Ca on shared abstractions is often desirable reuse; high Ce on a composition root/router is expected. Lower instability is not universally better, and I=0 here means no *internal* outgoing imports, not no dependencies at all.

**LCOM\*:** mean **0.645** across **118 eligible classes**; **88** are ≥0.5. Henderson–Sellers formula `(m − total field references / distinct fields) / (m − 1)` uses distinct direct `self` attributes per method, excludes direct method names, includes constructors, and omits classes with ≤1 method or no observed fields. Higher means less shared state. Delegation-heavy classes, properties, inheritance, and dynamic attributes limit its usefulness; this is not proof that 88 classes require splitting. This definition differs from the old script, so no before/after cohesion claim is made.

## 3. Test quality

**Python:** 2,129 passed, 3 skipped, 1 deselected, 1 expected failure; 771 subtests passed; **0 failures**, one runtime warning, **281.61 seconds**. Subtests are reported separately, not added to the test total.

| Metric | Current | Target | Result |
|---|---:|---:|---|
| Line/statement coverage | **88.44%** — 10,709 / 12,109 | ≥80% | Pass |
| Branch coverage | **81.32%** — 2,420 / 2,976 | ≥75% | Pass |
| Mutation score | **Not measured** | ≥70% | Unknown, not zero |
| Test-to-code ratio | **1.50:1** — 27,693 / 18,499 lines | ~1:1 | Substantial test volume; not proof of effectiveness |

Ratio uses the same nonblank, non-comment line definition for Python tests/support files and production. Radon raw analysis failed on three valid test files, so a mixed-definition Radon ratio was deliberately avoided. Includes 123 Python test/support files. Coverage.py's combined line-and-branch percentage is **87.03%**; that is neither line coverage nor branch coverage. There are **1,400 uncovered statements** and **556 uncovered branch destinations**; 73 excluded lines follow coverage pragmas/default exclusions.

| Package | Line coverage | Branch coverage |
|---|---:|---:|
| core | 100.00% | 91.67% |
| actions | 95.89% | 83.33% |
| stores | 93.37% | 87.80% |
| services | 91.12% | 85.35% |
| backend | 89.02% | 84.20% |
| app | **79.69%** | **61.76%** |
| bridge | **67.44%** | **48.43%** |
| main.py | 97.37% | 50.00% (1 / 2 branches) |

**Global success hides the main testing gap: bridge.** `bridge/stack_bridge.py` has 92/242 statements and 2/32 branches covered; `app/lifecycle.py` has 19/53 statements and 0/8 branches covered.

**JavaScript:** ran all 20 `tests/test_*.js` entrypoints separately with Node; **19 passed, 1 failed**. `tests/test_bridge_router.js` reports 2 assertions passed and 1 failed because it searches `main.py` for `registerObject("bridge")`; registration now resides at `app/window.py:122`. This is a stale source-location assertion, not evidence that registration disappeared. No JavaScript line/branch/mutation coverage was collected. The 22 frontend JS files / 8,377 physical LOC are outside the Python metric denominator, as is execution coverage of JS embedded in Python strings.

**Environment limitations:** real PySide6 imports with the repository's generated headless shared-library shims, `QT_QPA_PLATFORM=offscreen`. Deselected only `tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine`, documented previously to abort in this environment. This is not real GUI/GL validation. The runtime warning is an unawaited `Collector.handle_push` coroutine created by `test_push_binding_ignores_other_bindings`; investigate test/callback ownership before deciding whether it represents production behavior.

## 4. Code smells

- **Duplication:** conservative exact-AST cross-file statement scan (source span ≥6 lines) found **4 clone groups, 66 unique physical lines**, approximately **0.30%** of production physical LOC. This intentionally detects only exact copies; it misses renamed/similar logic and excludes JS. It is **not comparable** with the older normalized/token-window duplication estimate. Do not interpret it as 99.7% DRY compliance.
- **Dead-code candidates:** Vulture 2.16 at ≥90% confidence found **7 findings**: one unused import (`Iterator`, `actions/registry.py:18`) and six unused arguments/variables (`backend/cdp_client.py:35`, `services/run/coordinator.py:54`, `services/run/hooks.py:68,71,74`). Protocol/callback signatures can require unused arguments. No confirmed dead-code defect count is claimed.
- **Long methods:** 73 exceed 30 physical LOC; prioritize high complexity and weak coverage, not length alone.
- **God-class candidates:** 11 exceed 300 LOC; 23 exceed 15 direct methods. Review responsibility boundaries before further extraction.
- **Feature envy:** not reliably measured. No validated foreign-data access/call-graph analysis was run; delegation alone is not a smell.

## 5. Maintainability

- **Maintainability Index:** unweighted per-file Radon mean **65.42 / 100**, using `mi_visit(..., multi=True)` across all 133 production files, including empty modules/shims. Not a project-wide MI and sensitive to comments/docstrings and module size. Lowest: `backend/chat_sync.py` **11.86**, `services/run/progress.py` **18.88**, `services/history/mutate.py` **19.02**, `services/run/coordinator.py` **21.01**. Radon's ranking scale differs from classic MI bands; do not apply an arbitrary universal pass/fail threshold.
- **Technical debt ratio:** unavailable. Requires a specified remediation model and development-effort denominator; no invented percentage.
- **Code churn:** unavailable from this one-commit shallow history. A root-commit diff is not a churn trend.
- **Bug density:** unavailable. Requires confirmed defects over a defined period/scope; test failures, Vulture warnings, and threshold violations are not interchangeable with bugs.

## 6. Structured next phases — before further refactoring

1. **Lock the measurement baseline:** retain this report and audit script; use identical definitions and source scope in future runs. Capture frontend coverage separately.
2. **Repair test signals:** update the stale JS registration test to execute/verify current behavior, investigate the unawaited coroutine warning, and retain a real-WebEngine test in a suitable desktop/CI environment.
3. **Characterize risky boundaries:** prioritize bridge stack/undo/CDP and app lifecycle branches. Add behavioral tests for destructive DB/media operations, cancellation and error paths before changing implementation.
4. **Targeted extraction:** start with `_execute_cycle`, label normalization and DB deletion; review large class responsibilities. Preserve existing facade signatures and serialization contracts. Do not refactor low-CC embedded-JS builders merely to meet a line-count target.
5. **Verify effectiveness:** rerun Python and JS suites, keep ≥80% line / ≥75% branch coverage, and start mutation testing on bounded pure logic (normalization/filtering/tab scoring), targeting ≥70% with explicit timeout/equivalent-mutant reporting. Then expand.

## Reproduction

Dependencies used: Python 3.11; Radon 6.0.1, cognitive-complexity 1.3.0, coverage 7.16.0, pytest 9.1.1, Vulture 2.16; Node 22.22.3. Analysis dependencies were installed in ignored `.venv`, not added to application requirements.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt pytest pytest-asyncio pytest-cov radon cognitive-complexity vulture
mkdir -p /home/user/analysis
.venv/bin/python tools/metrics/current_audit.py > /home/user/analysis/current.json
# Historical-comparison outputs (these scripts write to /home/user/analysis):
.venv/bin/python tools/metrics/metrics.py
.venv/bin/python tools/metrics/deep.py
.venv/bin/python tools/build_stubs.py .venv /tmp/stublibs
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
COVERAGE_FILE=/home/user/analysis/.coverage .venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
COVERAGE_FILE=/home/user/analysis/.coverage .venv/bin/python -m coverage json \
  -o /home/user/analysis/coverage.json
.venv/bin/vulture core actions backend bridge services stores app main.py --min-confidence 90
for f in tests/test_*.js; do node "$f"; done
```

Raw evidence for this session is outside the Git checkout in `/home/user/analysis/`: `current.json`, `coverage.json`, `pytest.txt`, `js-tests.json`, `vulture.txt`, `deep.json`, `deep.txt`, `metrics.txt`, `file_stats.json`, and `coupling.json`. Four synthetic sanity assertions passed for sibling nesting, nested nesting, nested-definition isolation, and isolated cyclomatic complexity. No mutation run or frontend complexity analysis was performed.
