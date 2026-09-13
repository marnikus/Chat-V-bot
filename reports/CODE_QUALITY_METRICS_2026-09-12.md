# Code quality audit — 2026-09-12

Snapshot: `e4ef002`, branch `arena/01a09227-chat-v-bot`. No production code was
changed to produce this audit; every number below was re-measured from the tree
with the commands in **Reproduction**.

Organised against the six requested categories: complexity, size,
coupling/cohesion, tests, smells, maintainability.

## Executive summary

**Complexity is solved. Size is now the whole debt.**

Across 1,997 production functions there is **not one** above cyclomatic
complexity 10, and **not one** nested deeper than 4. Only 2 functions exceed
cognitive complexity 15, and both are recorded frozen exemptions. Every previous
audit in `reports/` led with complexity hotspots; that category is now clean and
this one does not.

What remains is structural mass: **10 files over 500 lines**, **38 classes over
the 150-LOC gate line**, **70 functions taking more than 4 parameters**, and a
maintainability-index floor of **11.1** on a single 800-line file. These are not
"complex" in the branch-count sense — they are *big*, and bigness is what RULE 18
governs.

Test health is strong and improved: **2,710 passed / 0 failed**, **90.41% line**,
**86.30% branch**, ratio **1 : 1.56** production-to-test. This audit also adds
the project's **first mutation measurement** (previous audits performed none):
**94.34%** kill rate on mutants reachable by the configured suite, with 9 named
survivors.

One finding changes the remediation plan and is documented in §6: **the two worst
files in the project cannot be split by the ordinary recipe**, because the frozen
AREA D public-API snapshot skips packages outright and only counts symbols a
module *owns*. Five of the ten oversized files sit behind that contract.

### Before → now

Previous column is `reports/CODE_QUALITY_METRICS_2026-09-10.md` (snapshot
`a49dd2a`). **Caution:** that audit reported a *legacy custom AST decision
count*, not Radon CC, and warned against comparing the two directly. The CC rows
below are therefore indicative of direction, not like-for-like.

| Metric | 2026-09-10 | 2026-09-12 | Interpretation |
|---|---:|---:|---|
| Python test results | 2,129 passed / 0 failed | **2,710 passed / 0 failed** | +581 tests, still zero failures |
| Python subtests | not reported | **777 passed** | newly recorded |
| Python line coverage | 88.44% | **90.41%** | +1.97 pp; threshold ≥80% met |
| Python branch coverage | 81.32% | **86.30%** | +4.98 pp; threshold ≥75% met |
| Mutation score | not measured | **94.34%** (reachable) | first ever measurement; ≥70% met |
| Max complexity (legacy count) | 31 | — | measure retired; see next row |
| Max Radon CC | not reported | **10** | exactly at the ceiling, none above |
| Functions above CC 10 | 67 / 1,532 (4.4%) | **0 / 1,997 (0.0%)** | category closed |
| Mean Radon CC | 3.31 (legacy) | **3.09** | lower mean on 30% more functions |
| Production Python files | 133 | **154** | extraction continues to add modules |
| Production nonblank/noncomment | 18,499 | **23,136** | +25.1% |
| Test nonblank/noncomment | not reported | **36,178** | ratio 1 : 1.56 |
| Mean maintainability index | not reported | **64.85** | newly recorded baseline |
| JS test entrypoints | 19 / 20 passed | **26 / 26 passed** | stale `bridge_router` assertion since fixed |

Function count grew 30% (1,532 → 1,997) while mean CC fell — the codebase got
*more* functions and *simpler* ones, which is the intended direction of travel
for RULE 18.

## 1. Complexity and size against your thresholds

Scope: all 154 production Python files under `core`, `actions`, `backend`,
`bridge`, `services`, `stores`, `app`, plus `main.py`. Excludes tests, tools,
vendored assets, frontend JavaScript and generated caches.

### 1a. Complexity

| Measure | Your threshold | Measured | Verdict |
|---|---|---:|---|
| Cyclomatic complexity (max) | ≤ 10 | **10** | ✅ met exactly, none above |
| Functions with CC > 10 | 0 | **0 / 1,997** | ✅ closed |
| Mean CC | — | 3.09 (median 2, p95 8) | healthy |
| Cognitive complexity (max) | ≤ 15 | **17** | ⚠️ 2 functions, both frozen |
| Functions with cognitive > 15 | 0 | **2 (0.1%)** | ⚠️ recorded exemptions |
| Nesting depth (max) | ≤ 3–4 | **4** | ✅ met at the loose bound |
| Functions with nesting > 4 | 0 | **0** | ✅ closed |

Mean cognitive complexity is 2.15 with p95 of 8 — the distribution is flat, not
just capped. The two cognitive outliers are the embedded-JavaScript builders
(`backend/dom_probe.py::build_probe`, 122 LOC), which are string-payload
constructors: their length is data, not decision logic. They are the same
exemptions recorded in `reports/CODE_QUALITY_METRICS_2026-09-10_cc-tail.md`.

### 1b. Size — this is where the debt lives

| Measure | Your threshold | Measured | Verdict |
|---|---|---:|---|
| Function length (max) | ≤ 20–30 LOC | **122** | ❌ outlier, see above |
| Mean / median function LOC | — | 9.68 / 7 | ✅ far inside threshold |
| Functions > 30 LOC | few | **42 (2.1%)** | ⚠️ tail |
| Class size (max) | ≤ 200–300 LOC | **532** | ❌ 1.8× the loose bound |
| Classes > 300 LOC | 0 | **11** | ❌ |
| Classes > 150 LOC (the gate line) | 0 | **38 (18.3%)** | ❌ |
| Parameters (max) | ≤ 3–4 | **20** | ❌ 5× the bound |
| Functions > 4 params | few | **70 (3.5%)** | ❌ |
| Methods per class (max) | ≤ 10–15 | **44** | ❌ |
| Classes > 15 methods | 0 | **25** | ❌ |
| File size (max) | ≤ ~300 | **800** | ❌ 2.7× |
| Files > 500 lines | 0 | **10** | ❌ |
| Files > 300 lines | few | **29** | ⚠️ |

`CLASS_LIMITS` in `tools/metrics/rule16_gate.py` is `{loc: 150, methods: 15}`,
and the gate itself notes that this loop "is decoration: declared, reported,
never enforced." So the 38 oversized classes are *reported* debt that no gate
currently blocks — which is exactly how it accumulated.

### Current hotspots

**Ten files over 500 physical lines** (SLOC in brackets), worst maintainability
first among them:

| Lines | SLOC | MI | File | Splittable? |
|---:|---:|---:|---|---|
| 800 | 536 | **11.1** | `backend/chat_sync.py` | ❌ frozen (§6) |
| 699 | 492 | 28.3 | `backend/scroll_parser.py` | ❌ frozen (§6) |
| 665 | 479 | **20.5** | `services/db_deletion.py` | ✅ |
| 601 | 466 | 27.2 | `services/collector_service.py` | ✅ (QObject) |
| 596 | 417 | 35.0 | `backend/history_query.py` | ❌ frozen (§6) |
| 573 | 413 | 24.1 | `services/undo_service.py` | ✅ |
| 542 | 453 | 24.2 | `bridge/history_bridge.py` | ✅ ratcheted |
| 527 | 388 | 55.3 | `backend/dom_highlight.py` | ❌ frozen (§6) |
| 509 | 382 | 31.5 | `services/db_deletion_flow.py` | ✅ |
| 502 | 315 | 40.5 | `backend/config_manager.py` | ❌ frozen (§6) |

**Biggest classes** (LOC / methods / LCOM\*):

| LOC | Methods | LCOM\* | Class |
|---:|---:|---:|---|
| 532 | 39 | 0.88 | `backend/scroll_parser.py::ScrollParser` |
| 526 | 40 | 0.93 | `services/collector_service.py::Collector` |
| 471 | 31 | 0.87 | `bridge/history_bridge.py::HistoryBridge` |
| 418 | 28 | 0.92 | `services/undo_service.py::UndoService` |
| 406 | 25 | 0.13 | `stores/history_schema_repair.py::SchemaMigrator` |
| 374 | 19 | 0.06 | `stores/history_repo_lifecycle.py::PersonLifecycle` |
| 340 | 18 | 0.18 | `stores/history_repo_append.py::AppendPlanner` |
| 310 | 14 | 0.74 | `backend/history_query.py::HistoryQuery` |
| 308 | 31 | 0.89 | `bridge/stack_bridge.py::StackBridge` |
| 306 | 14 | 0.92 | `actions/scroll_parse.py::ScrollParse` |

Note the LCOM split in that table. The four largest classes have LCOM\* 0.87–0.93
— genuinely low cohesion, several responsibilities sharing one namespace. The
next three are large but *cohesive* (0.06–0.18): `SchemaMigrator`,
`PersonLifecycle` and `AppendPlanner` are already single-responsibility units
that happen to be long. Size and cohesion are separate problems here and need
different treatments — the cohesive ones need extracting into helper modules, the
incohesive ones need decomposing by responsibility first.

**Most methods on one class** (the facade problem, distinct from size):

| Methods | LOC | Class |
|---:|---:|---|
| 44 | 225 | `stores/history_repo.py::HistoryRepo` |
| 40 | 526 | `services/collector_service.py::Collector` |
| 39 | 532 | `backend/scroll_parser.py::ScrollParser` |
| 38 | 222 | `stores/label_store.py::LabelStore` |
| 33 | 215 | `stores/media_store.py::MediaStore` |

`HistoryRepo` at 44 methods / 225 LOC is a deliberate facade over the
`history_repo_*` family — its methods are one-line delegations. That is the
correct shape for a facade and should not be "fixed" by splitting it.

**Widest parameter lists** (RULE 19 §19.4 says use a parameter object, as
`PersonPageRequest` already does):

| Params | LOC | Function |
|---:|---:|---|
| 20 | 49 | `actions/scroll_parse.py:40 __init__` |
| 19 | 29 | `backend/scroll_parser.py:171 __init__` |
| 14 | 33 | `backend/chat_parser.py:409 sync_conversation` |
| 13 | 29 | `actions/click_user.py:45 __init__` |
| 13 | 53 | `stores/history_repo_append.py:45 append` |
| 12 | 30 | `backend/visual_click.py:237 find_and_click` |

**Longest functions:** `dom_probe.py::build_probe` 122 (embedded JS payload),
`message_injector.py::_run_type_strategies` 70, `history_db.py::init` 54,
`history_query.py::page` 53, `history_repo_append.py::append` 53,
`router.py::_build_router_class` 51.

## 2. Coupling and cohesion

### Stability (Ca = used-by, Ce = depends-on, I = Ce/(Ca+Ce))

**Most depended-upon — these are correctly stable (I ≈ 0):**

| Module | Ca | Ce | I |
|---|---:|---:|---:|
| `core.events` | 23 | 0 | 0.00 |
| `backend.cdp_client` | 16 | 0 | 0.00 |
| `actions.base_action` | 13 | 2 | 0.13 |
| `core.result` | 12 | 0 | 0.00 |
| `stores.history_models` | 10 | 0 | 0.00 |
| `services.run` | 9 | 5 | 0.36 |

This is the healthy end of the graph: the most-used modules depend on nothing.
`core.events` and `core.result` at Ce = 0 with Ca 23 and 12 are textbook stable
abstractions, and the dependency arrows point the right way.

**Most dependent — correctly unstable leaves (I ≈ 1):**

| Module | Ca | Ce | I |
|---|---:|---:|---:|
| `bridge.router` | 1 | 17 | 0.94 |
| `services.run.coordinator` | 1 | 15 | 0.94 |
| `backend.config_manager` | 3 | 10 | 0.77 |
| `services.history` | 2 | 10 | 0.83 |
| `services.undo_service` | 3 | 10 | 0.77 |
| `app.bootstrap` | 2 | 9 | 0.82 |

Every module with I ≥ 0.77 is a composition root, coordinator or router —
i.e. something whose *job* is to depend on many things and be depended on by
almost nothing. No stable abstraction is being used as a dumping ground, and no
leaf is accidentally load-bearing. **The dependency graph does not need repair**;
this category passes.

### Cohesion (LCOM\*)

Measured over the 132 classes with ≥2 methods and ≥1 field: **mean 0.650**, with
**96 (72.7%) at or above 0.5**.

Read this number with care, because a raw LCOM ranking is misleading here. The
highest-scoring classes are mostly *correct*:

| LCOM\* | Methods | Class | Reading |
|---:|---:|---|---|
| 1.00 | 5 | `actions/base.py::FindClickBlock` | value block — no shared state by design |
| 1.00 | 6 | `actions/context.py::ActionContext` | context object — a bag, intentionally |
| 1.00 | 7 | `backend/history_query.py::PersonPageRequest` | **parameter object** — RULE 19 §19.4's own remedy |
| 1.00 | 6 | `core/result.py::Err` | result variant |
| 1.00 | 21 | `services/history/export.py::HistoryExportService` | ⚠️ real: 21 independent methods |
| 0.96 | 17 | `services/run/coordinator.py::RunCoordinator` | ⚠️ real: coordinator with disjoint steps |
| 0.94 | 13 | `backend/chat_parser.py::ChatParser` | ⚠️ real |

`PersonPageRequest` scoring LCOM\* 1.00 is the clearest example: it is the
pattern the rules *recommend* for killing 13-parameter functions, and LCOM
punishes it for exactly the property that makes it useful. So LCOM\* is reported
here as a **triage signal, not a gate** — it is only meaningful for classes that
hold mutable state and implement behaviour. On that filtered reading the genuine
cohesion problems are the four god classes in §1b (`Collector` 0.93,
`ScrollParser` 0.88, `HistoryBridge` 0.87, `UndoService` 0.92), which are large
*and* incoherent, plus `HistoryExportService` (21 methods, LCOM 1.00).

## 3. Test quality

| Measure | Your threshold | Measured | Verdict |
|---|---|---:|---|
| Python tests passing | all | **2,710 passed / 0 failed** | ✅ |
| Skipped / deselected / xfailed | — | 3 / 1 / 1 | documented below |
| Subtests | — | **777 passed** | ✅ |
| Line coverage | ≥ 80% | **90.41%** (13,928 / 15,235) | ✅ +10.4 pp |
| Branch coverage | ≥ 75% | **86.30%** (3,224 / 3,736) | ✅ +11.3 pp |
| Mutation score | ≥ 70% | **94.34%** (reachable) | ✅ first measurement |
| Test : production ratio | ~1 : 1 | **1 : 1.56** | ✅ exceeds |
| JS test entrypoints | all pass | **26 / 26** | ✅ |

**Mutation — how to read the two numbers.** The configured job
(`setup.cfg [mutmut]`) mutates `backend/history_query.py` only and runs three
sort-path test files. It generated **1,141 mutants**: 150 killed, 9 survived,
982 reported "no tests". `setup.cfg` states the convention explicitly — mutants
no test can reach are excluded, and narrowing the suite cannot inflate the result
because an untested mutant is never counted as killed. On that basis the score is
**150/159 = 94.34%**. Counting all 1,141 mutants it would be 13.15%, which
measures the *narrowness of the configured job*, not the strength of the tests.
Both are reported so neither can be quoted selectively.

The 9 survivors are a concrete, actionable test-gap list — all in
`backend/history_query.py`:

| Mutants | Location |
|---:|---|
| 4 | `HistoryQuery.list_persons` (18, 21, 22, 29) |
| 2 | `_like_escape` (13, 14) |
| 2 | `HistoryQuery._clamp` (4, 9) |
| 1 | `HistoryQuery._my_nicks` (7) |

`list_persons` is the single largest survivor cluster and is also an `OWNED`
function in the RULE 16 gate — worth closing first.

**Skips:** 1 deselected is `tests/test_sash_webengine.py::test_grid_in_real_webengine`
(needs a real WebEngine, unavailable headless). 3 skips and 1 xfail are
pre-existing conditional/environment guards.

**Coverage caveats, stated plainly.** 90.41% line and 86.30% branch are Python
only. There is **no JavaScript coverage instrumentation** — the 23 frontend JS
files / 9,237 LOC and the JavaScript embedded in Python string payloads are
outside both denominators. Passing tests plus high coverage is also **not** a
claim that the desktop application or the live Chrome workflow has been validated
end-to-end; the same caveat the 2026-09-10 audit carried still applies.

## 4. Code smells

**Duplication.** Two scanners, two answers, both reported:

| Tool | Groups | Duplicated lines |
|---|---:|---:|
| `tools/metrics/current_audit.py` (exact clone) | 4 | 66 |
| `tools/metrics/clone_scan.py` (AST window ≥ 6 lines) | 11 | 83 |

All 11 `clone_scan` groups are exactly the frozen `CLONE_BASELINE` set in
`rule16_gate.py` — **no new clone groups, none stale**. Inspecting them, every
one is a shared *import header* (`from __future__` / stdlib / PySide6), not
copied logic; the baseline comment documents this and verifies one with
`git log -L`. Duplication of behaviour is effectively zero, which is the number
that matters.

**Dead code.** `vulture` at ≥90% confidence: **7 findings**, unchanged from the
previous audit — `actions/registry.py:18` (`Iterator` import),
`backend/cdp_client.py:35`, `services/run/coordinator.py:61`, and
`backend/hooks.py:68/71/74`. Small, stable, and mostly protocol/typing surface
that vulture cannot see being called.

**Long methods / god classes.** The 42 functions over 30 LOC and 11 classes over
300 LOC tabulated in §1b. The four genuine god classes — `ScrollParser`,
`Collector`, `HistoryBridge`, `UndoService` — are large *and* low-cohesion, and
all four are named §16.5 landmines requiring a design doc before anyone
"quickly fixes" them.

**Feature envy / boundary violations.** No tool in this repo measures feature
envy directly, so this is inspection-based rather than a number. One concrete
instance found while mapping §6: `services/db_registry.py:289` reaches across a
module boundary for a **private** name, `db_deletion._append_db_files(...)`. A
private function called from another module is a boundary smell — either it is
public and should be named so, or the caller should not need it. Recorded for
Round F rather than silently fixed.

## 5. Maintainability

**Maintainability index** (radon, 0–100, higher is better) over 154 files:
**mean 64.85**, minimum **11.1**. 22 files (14.3%) score below 40; 2 below 20.

| MI | Lines | File |
|---:|---:|---|
| **11.1** | 800 | `backend/chat_sync.py` |
| 16.1 | 287 | `services/window_preset_service.py` |
| 20.5 | 665 | `services/db_deletion.py` |
| 24.1 | 573 | `services/undo_service.py` |
| 24.2 | 542 | `bridge/history_bridge.py` |
| 27.2 | 601 | `services/collector_service.py` |
| 27.8 | 248 | `services/run/progress.py` |
| 28.3 | 699 | `backend/scroll_parser.py` |

> **Rank caveat.** `radon mi -s` prints a *letter* band (A ≥ 20, B 10–19,
> C 0–9) that is far looser than the classic 0–100 MI scale used throughout this
> report (≥ 85 good, 65–85 moderate, < 65 high risk). `services/db_deletion.py`
> scores MI **20.54** and radon labels it **A**. Every number in this section is
> the raw score, not the letter.

> **Rank caveat.** `radon mi -s` prints a *letter* band (A ≥ 20, B 10–19, C 0–9)
> that is far looser than the classic 0–100 MI scale used throughout this report
> (≥ 85 good, 65–85 moderate, < 65 high risk). `services/db_deletion.py` scores
> MI **20.54** and radon labels it **A**. Every number in this section is the raw
> score, not the letter.

`chat_sync.py` at MI 11.1 is roughly half the next-worst score and a sixth of the
project mean — a single file accounts for most of the maintainability risk in the
codebase.

`window_preset_service.py` is the interesting outlier: MI 16.1 in only **287**
lines. It is not big, it is *dense* — low comment ratio and high complexity per
line. Same for `run/progress.py` (MI 27.8, 248 lines). These need explanation
and decomposition, not splitting; a size-driven refactor would miss them
entirely. They are the reason §6 does not simply sort by line count.

**Technical debt ratio, churn, bug density — not honestly measurable here.**

* **TDR:** no tool in this repo produces a remediation-cost estimate; MI is the
  available proxy and is reported above.
* **Churn:** this checkout is **shallow — 9 commits total**. The most-changed
  production files have at most 3 touches, which is not enough history for a
  churn signal to mean anything. Reporting a ranking from 9 commits would be
  false precision, so none is given.
* **Bug density:** requires defect attribution (issue/bug-fix labelling) that
  does not exist in this history. Not reported rather than invented.

If churn and bug density are wanted for real, they need a full clone with
complete history and a bug-fix commit convention — a tooling task, not an
analysis one.

## 6. Structured next phases — Round F

### The blocking finding

`tools/metrics/dump_public_api.py` builds the frozen AREA D snapshot that
`tests/unit/backend/test_backend_api_snapshot.py` enforces. Two properties of it
decide what can be refactored:

1. `module_names()` does `if info.ispkg: continue` — **packages are skipped
   entirely.** Converting `backend/chat_sync.py` into a `backend/chat_sync/`
   package makes the qualname `backend.chat_sync` vanish from the snapshot, and
   `test_no_module_disappeared_or_failed_to_import` fails.
2. `dump_module()` keeps a symbol only when `obj.__module__ == qualname` —
   **re-exports do not count as owned.** Moving `SyncSession` into a sibling
   module and re-exporting it makes the snapshot report it as *removed*.

So the standard remedy used elsewhere in this repo — turn the module into a thin
re-export shim over a prefix family, as was done for `stores/history_repo.py`
(20-line shim + 11 files) and `services/db_deletion*` — is **not available inside
`backend/` or `actions/`**. That is precisely why the already-split families live
in `stores/` and `services/`: the snapshot covers only `backend` and `actions`
(`dump_public_api.py:204`), and no golden file exists over `services/`,
`stores/` or `bridge/`.

Consequence: **5 of the 10 oversized files are structurally frozen**, including
the #1 and #2 offenders. The test's own docstring sanctions a refresh —
*"Refresh the snapshot only when a change is intentional and coordinated"* — so
this is a decision, not a dead end. But it weakens a golden file whose stated
purpose is proving no public API moved, and it should not be taken unilaterally
inside a size-cleanup round.

### Prioritised steps

Ordered by (impact × feasibility), which is why the biggest file is *not* step 1.

| # | Step | Target | Why here |
|---|---|---|---|
| **F1** | Split `services/db_deletion.py` 665 → prefix family | MI 20.5 | Largest **unfrozen** file, worst unfrozen MI, pure functions (no Qt), and the file's own banner comments already mark the seams. Also continues an existing family. |
| F2 | Decompose `services/collector_service.py::Collector` | 526 LOC / 40 methods / LCOM 0.93 | Largest unfrozen god class, §16.5 landmine. QObject + signals ⇒ needs its own design doc first. |
| F3 | Decompose `services/undo_service.py::UndoService` | 418 / 28 / LCOM 0.92 | Same class of problem, already partially split (`undo_timeline.py`). |
| F4 | Split `bridge/history_bridge.py` | 542, MI 24.2 | Ratcheted at 493/45 in the gate — may shrink, may not grow. QWebChannel pins the slot set. |
| F5 | Parameter objects for the wide tail | 70 functions > 4 params | §19.4 pattern; `scroll_parse.__init__` 20 params is worst. |
| F6 | Close the 9 mutation survivors | `history_query.py` | Cheapest test-quality win available; `list_persons` cluster first. |
| F7 | Density pass on small low-MI files | `window_preset_service.py` 287/16.1, `run/progress.py` 248/27.8 | Not size problems — invisible to a lines-only sort. |
| F8 | Promote `stores/` (37 files) to sub-packages | RULE 18.3 | Module-count debt, lowest urgency. |
| **F0** | *Decision required:* refresh the AREA D snapshot? | `chat_sync.py` 800/MI 11.1, `scroll_parser.py` 699 | Unblocks the true #1 and #2 offenders. Needs an explicit, coordinated go-ahead. |

Round F begins with **F1**, designed in
`docs/archive/2026-09-12-round-f-size-tail/ROUND_F_DESIGN_2026-09-12.md` — the
location RULE 16 §16.6 step 2 and RULE 17 prescribe for a design that moves
complexity across files.

> **F1 was executed in the same session as this audit.** Every number above is
> the pre-split snapshot at `e4ef002` and stays accurate as such. After the
> split, re-measured: **159 files** (was 154), **9 over 500 lines** (was 10),
> mean MI **65.27** (was 64.85), 21 files below MI 40 (was 22), production
> nonblank/noncomment 23,215 (was 23,136 — the five new module docstrings).
> `services/db_deletion.py` is gone; its six successors run 45–205 lines at MI
> 49.59–100.00, and the six are covered at 99–100%. Suite unchanged at
> **2,710 passed / 0 failed**, line 90.42%, branch 86.30%. One new clone group
> appeared (a shared 6-line import header) and was baselined with a recorded
> reason rather than dodged. Full before/after, including a target that was
> missed by 0.41 MI points and the monkeypatch defect the equivalence gate
> caught, is in that design doc §8.

## Reproduction

```bash
# environment (in-repo venv; gitignored)
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

# static audit -> /tmp/audit3.json  (complexity, size, LCOM, coupling, MI, clones)
.venv/bin/python tools/metrics/current_audit.py

# full suite + coverage (headless Qt)
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine

# mutation score (scoped by setup.cfg; ~2 min; delete mutants/ afterwards)
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/mutmut run
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/mutmut results

# gates and smells
.venv/bin/python tools/metrics/rule16_gate.py
.venv/bin/python tools/metrics/clone_scan.py .
.venv/bin/vulture --min-confidence 90 core actions backend bridge services stores app

# JavaScript suite (26 entrypoints)
for f in tests/test_*.js; do node "$f"; done
```

Raw evidence for this session is deliberately kept **outside** the Git checkout
(`/tmp/audit3.json`, `/tmp/cov2.log`, `/tmp/coverage2.json`, `/tmp/mutmut.log`):
coverage and mutmut artifacts are not gitignored, so writing them into the tree
would pollute the commit. `mutmut` leaves an untracked `mutants/` directory that
must be removed after each run.
