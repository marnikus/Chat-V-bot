# Code quality audit — 2026-09-10 (post max-CC tail extraction, round 2)

Snapshot: branch `arena/01a08c5b-chat-v-bot`, parent `5393a76`
("Decompose _delete_unlocked (CC 143)"). Scope of the change:
`services/db_deletion.py`, `services/db_media_scan.py`,
`services/db_registry.py`, `services/run/coordinator.py` plus two new
modules `services/run/cycle_loop.py` and `services/run/run_lifecycle.py`,
plus design docs and `tools/metrics/clone_scan.py`. **Zero test files
were modified.**

Design (written first): `docs/archive/2026-09-10-safety-refactor/CC_TAIL_EXTRACTION_DESIGN_2026-09-10.md`.
Next-round proposal (newly exposed problems):
`docs/archive/2026-09-10-safety-refactor/CC_REMAINING_TAIL_DESIGN_2026-09-10.md`.

## Executive summary

The seven remaining max-complexity giants of the deletion/run areas were
decomposed into named, gate-compliant units with byte-identical observable
behavior (proven by differential harnesses, not just tests). The project
maximum cyclomatic complexity dropped from **42 to 28 — below the
pre-refactor project ceiling of 31** — and the maximum cognitive score
from **55 to 40**. All 2,467 tests pass; line and branch coverage rose; no
new clone, dead-code finding, or gate violation was introduced.

### Before → after (this round)

"Before" = commit `5393a76` (`/tmp/audit_now.json`); "after" = this
change (`/tmp/audit_tail_done.json`); same walker
(`tools/metrics/current_audit.py`).

| Metric | before | after | Δ |
|---|---:|---:|---:|
| Project max cyclomatic CC | **42** | **28** | −14 (33 %) |
| Project max cognitive complexity | 55 | 40 | −15 |
| Project max nesting depth | 6 | 6 | 0 (leader moved; see §3) |
| Longest function (physical LOC) | 124 | 122 | −2; both times the §1.5 JS-exempt `build_probe` |
| Functions CC > 10 | 73 | **64** | −9 |
| Functions cognitive > 15 | 29 | **21** | −8 |
| Functions nesting > 4 | 6 | **3** | −3 |
| Functions > 30 LOC | 83 | **75** | −8 |
| Functions > 4 params | 71 | 71 | 0 (frozen signatures kept verbatim) |
| Mean cyclomatic CC | 3.40 | **3.31** | −0.09 |
| Mean cognitive complexity | 2.57 | **2.45** | −0.12 |
| Mean function LOC | 10.56 | **10.32** | −0.24 |
| Production Python files (metrics walker) | 139 | 141 | +2 mixins |
| Production physical LOC | 24,423 | 24,783 | +360 (named-unit overhead) |
| Mean Radon MI (per file, `multi=True`) | 65.02 | **65.06** | +0.04 |
| God classes > 300 LOC / > 15 methods | 11 / 24 | 11 / 24 | method counts unchanged |
| Exact-AST clone groups / physical lines | 12 / 90 | 12 / 90 | no new clones (persisted scanner) |
| Vulture findings ≥ 90 % | 7 | 7 | same set (one unused import, six signature args) |
| Tests | 2,467 pass | **2,467 pass** | 0 edits |
| Coverage line / branch | 90.23 % / 84.18 % | **90.41 % / 84.38 %** | +0.18 / +0.20 |

## 1. Complexity and size against RULE 16

Scope: all 141 production Python files in `core`, `actions`, `backend`,
`bridge`, `services`, `stores`, `app`, and `main.py`; nested definitions
scored separately. Definitions are the frozen ones in
`docs/archive/2026-09-10-agent-rules-v1/AGENT_RULES_CODE_QUALITY.md` §1–§2 (inclusive AST spans, kwargs
count individually, nesting = max ancestry of `if`/loops/`with`/`try`/
`match`, cognitive-complexity 1.3 defaults).

### 1.1 The seven target functions

| Function | CC | cognitive | nesting | LOC |
|---|---:|---:|---:|---:|
| `services/db_deletion.py build_deletion_inventory` | 42 → **2** | 55 → **1** | 6 → **0** | 112 → **16** |
| `services/run/coordinator.py RunCoordinator.execute` | 36 → **9** | 50 → **12** | 5 → **3** | 103 → **29** |
| `services/db_media_scan.py scan_world_media` | 29 → **4** | 30 → **3** | 4 → **2** | 124 → **21** |
| `services/db_deletion.py classify_candidate` | 28 → **5** | 36 → **5** | 4 → **2** | 71 → **23** |
| `services/db_registry.py deletion_inventory_sources` | 23 → **4** | 31 → **3** | 6 → **1** | 48 → **22** |
| `services/db_deletion.py plan_deletion` | 20 → **4** | 20 → **3** | 2 → **0** | 50 → **25** |
| `services/db_deletion.py prune_empty_dirs` | 20 → **3** | 37 → **2** | 4 → **1** | 53 → **13** |

Every extracted unit passes every hard gate (CC ≤ 10, cognitive ≤ 15,
nesting ≤ 4, LOC ≤ 30, params ≤ 4). The complete per-unit gate dump for
the six touched/new modules:

| Module | units | max CC | max cog | max nest | max LOC | MI |
|---|---:|---:|---:|---:|---:|---:|
| `services/db_deletion.py` | 29 fns + dataclasses | 9 | 11 | 4 | 25 | 20.54 |
| `services/db_media_scan.py` | 13 | 6 | 5 | 2 | 21 | 52.77 |
| `services/db_registry.py` (legacy `info` CC12 untouched) | — | 12 legacy | 11 legacy | 3 | 43 legacy | 42.45 |
| `services/run/coordinator.py` (legacy `__init__` 8 params untouched) | — | 9 | 12 | 3 | 29 | 40.87 |
| `services/run/cycle_loop.py` (new) | 4 | 5 | 5 | 2 | 18 | 75.43 |
| `services/run/run_lifecycle.py` (new) | 9 | 8 | 8 | 2 | 19 | 59.62 |

**Param-cap note (RULE 16 §0 legacy clause).** The frozen public
keyword-only signatures `classify_candidate` (7 kwargs) and
`plan_deletion` (9 kwargs) still exceed the ≤ 4 param gate, exactly as
they did before; arity is byte-for-byte unchanged (**not worsened**), and
both functions are now CC 5 / CC 4. Collapsing them into an options
object would break the frozen keyword API; an internal `_PathPolicy`
already absorbs the wide internal bookkeeping.

**Structural-pin note.** The shipped source-inspection test
`test_engine_execute_is_called_without_a_parser` asserts
`inspect.getsource(ActionEngine.execute)` textually contains
`_execute_cycle`. The cycle loop therefore remains inside `execute`
(CC 9, 29 LOC); two drafted helpers (`_run_one_cycle`, `_run_all_cycles`)
were inlined back after the test surfaced this. Only named decisions
(gate, banner, transition, done-marking, begin, teardown, cleanup
precedence) moved out.

### 1.2 Current project hotspots (post-fix)

| Location | CC | cognitive | nest | LOC | Note |
|---|---:|---:|---:|---:|---|
| `stores/label_state.py:74 _normalized` | **28** | 25 | 3 | 50 | New project max; normalization decisions |
| `actions/wait_page.py:40 execute` | 25 | **40** | 3 | 92 | Max cognitive; wait/timeout ladder |
| `backend/history_query.py:80 _item` | 22 | 22 | 2 | 34 | Dense row construction |
| `backend/tab_matcher.py:70 score_tab` | 20 | 26 | 3 | 36 | Heuristic scoring ladder |
| `actions/cancellation.py:119 await_with_stop` | 19 | 35 | **5** | 75 | CC + nesting hotspot in shared stop core |
| `services/layout_service.py:42 normalize_grid_tree` | 19 | 20 | 2 | 36 | Tree normalization |
| `stores/migration.py:39 migrate_legacy_config` | 19 | 14 | 2 | 79 | One-shot migration ladder |
| `services/history/mutate.py:102 _merge_legacy_queue` | 18 | 17 | 2 | 22 | Merge branches |
| `services/run/error_recovery.py:127 _execute_for_user` | 18 | 26 | 3 | 67 | Highest remaining run-engine CC |
| `stores/history_repo_identity.py:262 _same_conversation` | 18 | 12 | 1 | 23 | 6 params |
| `services/run/error_recovery.py:66 _run_collect_phase` | 17 | 15 | 3 | 54 | Collect-phase branches |
| `services/history/runtime.py:141 switch_db` | 16 | 18 | **4** | 60 | DB switching lifecycle |

Full CC > 10 inventory: **64 functions** (`/tmp/audit_tail_done.json`);
all are pre-existing legacy functions — none was introduced or worsened
by this change. Longest function remains `dom_probe.build_probe`
(122 LOC, CC 7), exempted explicitly by RULE 16 §1.5 (embedded JS).
Widest constructor remains `actions/scroll_parse.py __init__` (20 params,
legacy).

## 2. Coupling and cohesion

From `tools/metrics/metrics.py` on both trees (internal edges only):

- The two new run modules are leaves: each has Ca = 1 (only
  `run/coordinator.py` imports them), Ce = 1; they keep
  `actions.cancellation` imports function-local, preserving the
  "`import services.run` stays light" convention.
- `run/coordinator.py`: Ce 12 → 14 (the two mixins), Ca 0 (internal
  package users import via `services.run`), LOC 285 → 214, class body
  254 → 181 with the same 17 direct methods.
- `services/db_deletion.py` became the shared low-level kernel for the
  deletion area: Ca 1 → 6 (`db_deletion_flow`, `db_deletion_scan`,
  `db_registry`, and the lifecycle path reuse `_append_db_files`,
  `_registry_active_dir`, predicates and the policy dataclasses). It has
  Ce 0 internal outgoing imports (function-local imports of its callers
  keep the import direction acyclic).
- `db_registry.py`: Ca 1 → 2, LOC 272 → 288, class body 249 → 223 with
  the same 14 methods (raw-source logic moved to two module helpers).

No new import cycle was introduced (full import check
`python -c "import services.run, services.db_registry, services.db_lifecycle"`
passes; all suites import cleanly).

## 3. Code smells, nesting, duplication, dead code

- **Nesting > 4 — three sites remain, all legacy and outside this
  round's scope:** `bridge/collector_bridge.py:97 collector_command`
  (nest 6, CC 9), `actions/cancellation.py:119 await_with_stop`
  (nest 5, CC 19), `backend/cdp_client.py:187 fetch_tabs` (nest 5,
  CC 5). This round removed the three deletion/run nesting offenders
  (`build_deletion_inventory` 6, `deletion_inventory_sources` 6,
  `execute` 5).
- **Duplication:** the previously ad-hoc exact-AST scanner was not
  persisted; a reproducible implementation now lives at
  `tools/metrics/clone_scan.py` (consecutive statement windows ≥ 6
  physical lines, identical `ast.dump`, cross-file only, greedy
  longest-non-overlapping selection). On both the `5393a76` tree and
  this tree it reports **12 clone groups / 90 unique physical lines**
  (~0.36 % of production physical LOC). The extraction added **zero**
  clones; the largest pre-existing group is a 15-line block shared by
  `actions/click_back.py` and `actions/click_main_tab.py`. The
  round-1 report's "4 groups / 66 lines" came from an unsaved scanner
  variant and is **not directly comparable**; future reports use the
  persisted tool.
- **Dead code (Vulture 2.16, ≥ 90 %):** unchanged **7 findings** — one
  unused import (`actions/registry.py:18 Iterator`), one unused
  `scroll_parser` signature argument on `RunCoordinator.execute`
  (line moved with the method), three unused `coordinator` hook args in
  `run/hooks.py`, and two locals in `backend/cdp_client.py:35`. No new
  finding from the extracted modules.
- **Frozen raw API:** `DbRegistry.deletion_inventory_sources` has no
  production callers by design (documented raw inventory-source facade)
  and therefore zero automated coverage; its behavior was nevertheless
  pinned this round by a differential comparison (see §4). It remains a
  candidate for either explicit tests or removal in a future round.

## 4. Tests and behavior preservation

- **Full suite:** 2,467 passed, 3 skipped, 1 deselected, 1 xfailed,
  771 subtests passed (one pre-existing unawaited-coroutine warning in
  `test_services_history.py`, unchanged since the round-1 report).
- **Coverage** (`--branch --source=core,actions,backend,bridge,services,
  stores,app,main`; coverage JSON's own totals): statement line
  **90.41 %** (90.23 %), branch **84.38 %** (84.18 %) — both above the
  RULE 16 §3 floors (80 / 75) and above the recorded baselines.
  Touched files: `db_deletion.py` 99 %, `db_media_scan.py` 100 %,
  `db_registry.py` 70 % (the gap is the un-called raw facade and
  pre-existing GUI/stats methods), `run/coordinator.py` 92 %,
  `run/cycle_loop.py` 83 %, `run/run_lifecycle.py` 91 %. The only
  uncovered new branches are defensive paths whose inline predecessors
  were equally uncovered (between-cycle cooperative stop; dual run/post
  fault log warnings; guarded tracer-note swallows).
- **Differential harnesses** (built ad hoc against `git show HEAD`; not
  shipped, methodology recorded in the design doc §6.3):
  - **13 run-engine scenarios** executed against the HEAD
    `RunCoordinator.execute` and the refactored one: empty stack,
    worked cycle, cooperative stop inside a block, external task cancel,
    post-hook raises, post-hook cancelled, cancel landing inside the
    post hook, pre-hook raises, empty user queue, pause→stop at the
    between-cycle gate, two-cycle run, external cancel combined with a
    faulty post hook, and "empty first of two cycles". Compared: raised
    exception type, final `RunState`, every log and debug message, every
    trace record (`type`/`reason`/status fields), `post_run` outcomes,
    `stack_complete` counts, `_running`/`_ctx` reset — **all identical**.
  - **7 registry raw-facade scenarios**: victim outside/inside the active
    directory, empty `victim_abs`, `existing_worlds` raising,
    `active_path` raising, `known_paths` raising, and the empty-active
    edge that exercises the `active_dir or vdir + "_x"` fallback —
    **returned dicts identical**.
- Pinned strings/keys/reasons survived verbatim (`DeletionOutcome`
  keys; media reason codes; "active folder scan failed" family;
  exactly one terminal `run_end`; `post_run` awaited exactly once even
  on cancel; `✅ Stack execution complete` once; the frozen
  `DbManager`/`DbBridge` facades).
- JS: the frontend toolchain is not installed in this workspace and no
  JS file changed; status stays 20/20 from the round-1 run.

## 5. Maintainability

Mean per-file Radon MI rose slightly to **65.06** (65.02). Lowest now:
`backend/chat_sync.py` 11.86, `services/history/mutate.py` 19.02,
`services/db_deletion.py` **20.54 (new in the bottom tier)**,
`services/undo_service.py` 21.45, `bridge/history_bridge.py` 23.45,
`backend/history_query.py` 27.62, `services/history/query.py` 27.71,
`services/collector_service.py` 28.28, `backend/scroll_parser.py` 28.74,
`services/run/progress.py` 29.74. The `db_deletion.py` MI drop
(25.22 → 20.54) comes entirely from added named-unit/signature/
docstring volume (514 → 665 physical LOC); the module contains no
complex unit anymore (worst CC 9), and its cohesion increased (Ca 1 → 6
as the deletion area funnels through it). It is the leading candidate
for the *module-level* split proposed in the follow-up design doc.
`run/coordinator.py` MI improved 29.12 → 40.87 and
`db_registry.py` 40.99 → 42.45.

## 6. Newly exposed problems (detected by this round)

These are the problems this refactor surfaced or made binding; fixes are
designed in `docs/archive/2026-09-10-safety-refactor/CC_REMAINING_TAIL_DESIGN_2026-09-10.md`, not applied:

1. **The next CC ceiling is a broad 16–28 legacy tail** across
   `stores`, `actions`, `backend`, and `services/run` (12 functions
   ≥ CC 16 listed in §1.2; 64 above CC 10). With the deletion/run
   giants gone, `stores/label_state.py _normalized` (28) is the project
   maximum; `actions/wait_page.py execute` holds the cognitive maximum
   (40) and the runner-up nesting (5).
2. **Three nesting > 4 sites** remain (`collector_command` 6,
   `await_with_stop` 5, `fetch_tabs` 5); `await_with_stop` is shared
   hot-path cancellation core and needs the careful differential method
   used this round.
3. **`services/db_deletion.py` module volume** (665 LOC, MI 20.54):
   all units are small, but four responsibilities (inventory
   collection, candidate classification, deletion planning/policy,
   pruning/unlinking) now coexist in one file and a package split is
   overdue.
4. **Two edited legacy classes still exceed class gates**:
   `RunCoordinator` 181 LOC / 17 methods (was 254 / 17) and
   `DbRegistry` 223 LOC / 14 methods (was 249 / 14). Method counts were
   not worsened; further reduction needs moving cycle/user-run machinery
   out of `coordinator.py` into the existing mixins and splitting the
   registry stats/raw-source responsibilities.
5. **Two frozen wide signatures** (`classify_candidate` 7 kwargs,
   `plan_deletion` 9 kwargs) remain param-cap legacy; reducing them
   requires a deliberate facade-versioning decision, not a silent
   signature change.
6. **Coverage pockets in the new named units** (between-cycle stop gate,
   cleanup-precedence warning branches, guarded trace swallows) and the
   entirely untested raw facade `deletion_inventory_sources`: small
   characterization tests would lock the differential behavior proven
   ad hoc this round.
7. Pre-existing non-CC findings from the round-1 report (bridge
   coverage, stale JS registration test, unawaited-coroutine warning,
   widest constructors, largest god classes) were **not regressed** and
   stay queued behind the CC work per the task scope.

## Reproduction

Dependencies: Python 3.11; Radon 6.0.1, cognitive-complexity 1.3.0,
coverage 7.16.0, pytest 9.1.1, Vulture 2.16 (installed in `.venv`).

```bash
# audit snapshots
.venv/bin/python tools/metrics/current_audit.py > /tmp/audit_tail_done.json
# coupling / class / volume tables (writes file_stats.json/coupling.json)
.venv/bin/python tools/metrics/metrics.py
# exact-AST duplication (new, persisted)
.venv/bin/python tools/metrics/clone_scan.py
# full suite with branch coverage
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
COVERAGE_FILE=/home/user/analysis/.coverage .venv/bin/python -m coverage run \
  --branch --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
COVERAGE_FILE=/home/user/analysis/.coverage .venv/bin/python -m coverage json \
  -o /home/user/analysis/coverage.json
.venv/bin/vulture core actions backend bridge services stores app main.py --min-confidence 90
```

Raw evidence this round: `/tmp/audit_now.json` (before),
`/tmp/audit_tail_done.json` (after), `/home/user/analysis/coverage.json`,
`/tmp/diff/` (HEAD run package copy + 13-scenario differential matrix),
`/tmp/baseline_tree` (`git archive HEAD` tree used for clone/MI/
coupling comparisons). No production behavior changed beyond the
decomposition; no test was edited.
