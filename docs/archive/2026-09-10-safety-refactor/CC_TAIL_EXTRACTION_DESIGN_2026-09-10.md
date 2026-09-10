# Remaining max-CC tail — extraction design (post `_delete_unlocked` fix)

Date: 2026-09-10. Scope: **max cyclomatic complexity only** — after the
first fix (`docs/archive/2026-09-10-safety-refactor/DELETE_FLOW_EXTRACTION_DESIGN_2026-09-10.md`, commit that
took the global max from 143 to 42), the project maximum is set by the
audit's documented "Area A tail" plus the run-engine outer wrapper. This
doc designs the decomposition of every function still above the baseline
project maximum (CC 31), so that after this change **no function in the
project is worse than the pre-fix baseline maximum** and every *new*
function passes the RULE 16 gates (CC ≤ 10, cognitive ≤ 15, nesting ≤ 4,
LOC ≤ 30, params ≤ 4; new classes ≤ 150 LOC / ≤ 15 methods).

Status: implemented, full suite green, metrics re-measured — see §6.

## 1. Problem (measured on this checkout)

| # | Function | CC | Cognitive | Nest | LOC | Origin |
|---|---|---:|---:|---:|---:|---|
| 1 | `services/db_deletion.py:90 build_deletion_inventory` | **42** | 55 | 6 | 112 | Area A (this round) |
| 2 | `services/run/coordinator.py:57 execute` | **36** | 50 | 5 | 103 | run engine outer wrapper |
| 3 | `services/db_media_scan.py:53 scan_world_media` | **29** | 30 | 4 | 124 | Area A |
| 4 | `services/db_deletion.py:262 classify_candidate` | **28** | 36 | 4 | 71 | Area A |
| 5 | `services/db_registry.py:136 deletion_inventory_sources` | **23** | 31 | 6 | 48 | Area A |
| 6 | `services/db_deletion.py:335 plan_deletion` | **20** | 20 | 2 | 50 | Area A |
| 7 | `services/db_deletion.py:415 prune_empty_dirs` | **20** | 37 | 4 | 53 | Area A |

(#1–#4, #7 are exactly the audit report's Phase-4 list: "new code from
this round, so decisions are still fresh in context". #2 exists on this
branch in its pre-Area-C-CC-follow-up form — the other audit snapshot had
already split it; here it still holds CC 36. #5 and #6 complete the same
subsystem.)

After these, the largest function is `stores/label_state.py:_normalized`
CC 28 — unchanged-from-baseline legacy code — so the project maximum
returns **below the baseline's 31** without touching unrelated modules.

## 2. Frozen contracts (verified against the tests)

- `services.db_deletion` public names keep identical signatures and
  return values: `build_deletion_inventory` (returns
  `DeletionInventory` with `worlds / complete / diagnostics /
  victim_abs / victim_in_scope / all_worlds`), `classify_candidate`
  (verdict strings incl. every `retain:<reason>`), `plan_deletion`
  (`DeletionPlan`), `prune_empty_dirs` (removed-dir list),
  `collect_discovered_files`, `unlink_one`, `canonical`, `is_within`,
  `is_same_file`, `DeletionOutcome`, `DB_GROUP_SUFFIXES`.
- Diagnostic message strings stay verbatim — tests assert
  `"victim directory handling"`, `"victim directory scan failed"`,
  `"remembered-paths scan failed"`, `"active folder scan failed"`,
  `"active path read failed"` via `diagnostics`, and the defensive
  suite mocks `services.db_deletion.canonical`, `os.path.*` with
  specific fall-through expectations (`test_deletion_defensive.py`,
  `test_deletion_unit.py`, `test_inventory_and_uri.py`).
- `scan_world_media(path, timeout_s=2.0)` keeps signature, the
  `MediaScanResult(path, references, complete, reason, detail,
  schema_version)` shape, every `reason` code
  (`ok / missing_file / missing_media_table / unsupported_schema /
  corrupt / locked / io_error / query_error`) and exact detail text
  pinned by `test_scan_unit.py` (incl. global `aiosqlite.connect`
  mocks, URI escaping via `sqlite_ro_uri`, zero-byte shortcut).
- `RunCoordinator.execute(scroll_parser=None)` keeps: re-entry guard
  message; state transitions (`mark_running/mark_done/mark_error`);
  tracer records in the same order (`run_start`, optional `repeat`,
  `cycle_start`, exactly one terminal `run_end`); cycle outcomes
  (`worked / stopped / empty / empty_stack`); post-run hook always
  invoked exactly once; `stack_complete` exactly once; final
  "✅ Stack execution complete"; error-resolution precedence
  (cancel-during-run + post failure → warning, original cancel wins;
  post cancel → raised; success + post failure → raised; contained
  body error + post failure → post error raised). Pinned by all five
  files in `tests/integration/run_safety/` plus
  `test_run_engine_p0_pins.py`.
- `deletion_inventory_sources(victim_abs="")` keeps its raw-dict
  shape (`active_folder / victim_folder / remembered / active`).
- Zero test files edited; no public name added to any frozen facade.

## 3. New structure

### 3.1 `services/db_deletion.py`

`build_deletion_inventory` becomes a thin driver (parse victim path,
run the collector, render the result). Internals:

- `@dataclass _InventoryCollector(registry, victim_abs)` with fields
  `collected / diagnostics / complete` and one method per **named
  source** from the docstring boundary (each is a real inventory
  concept, not a metric shard):
  `add_active_folder`, `add_active_path`, `add_victim_directory`,
  `add_remembered`, `add_victim`, `build`;
- module helpers `_registry_active_dir`, `_append_db_files`,
  `_registry_root`, `_known_db_in_root`.
  The deep nesting (the audit measured depth 6) disappears because the
  two nested directory walks become functions of depth ≤ 4.

`classify_candidate` becomes a verdict ladder over named policy
predicates, each returning `retain:<reason>` or `None`, in the exact
current order: `_symlink_reason`, `_outside_root_reason`,
`_exact_root_reason` (the post-within defensive root re-check),
`_other_folder_reason`, `_shared_reference_reason`,
`_ambiguous_folder_reason`, `_non_file_reason`. Each reason is already
a named verdict in the current code; this is extraction, not new logic.

`plan_deletion` keeps its keyword signature; the two classify loops
become one `_classify_file_group(group, is_discovered, policy, buckets)`
driven by a frozen `_PathPolicy` (base/vfolder/exclusive/keep/others +
`verdict(ap, is_discovered)`) and a mutable `_PolicyBuckets`
(candidates/retained). All helpers ≤ 4 parameters.

`prune_empty_dirs` becomes: `_prune_roots(base_abs, others)` (guard
sets, failure-tolerant), `_prune_blocked(folder_c, folder, guard)`
(the five stop conditions), `_prune_one_start(start, guard, seen,
removed)` (the bounded upward walk). Never-rmtree semantics and log
text unchanged.

### 3.2 `services/db_media_scan.py`

`scan_world_media` becomes a thin driver: `_early_scan_result(apath,
raw)` (missing / zero-byte), open the read-only URI, delegate to
`_scan_connection(conn, apath)` (the open timeout stays on the URI
connection); any failure is rendered by
`_classify_scan_exception(msg)` + `_outer_fault(apath, exc)`.
Inside a connection: `_read_media_table`, `_read_schema_version`,
`_read_media_rows`, `_reference_set`. Failure results propagate through a
private `_ScanFault(MediaScanResult)` (same internal-control-flow
pattern as `db_deletion_flow._PhaseRefusal` — narrow, caught in one
place; `CancelledError` is a `BaseException` and can't be caught by
it). Constructors `_fault(...)` / `_ok(...)` keep result building
uniform (≤ 4 params each); `_looks_corrupt` carries the message heuristic.

### 3.3 `services/db_registry.py`

`deletion_inventory_sources` becomes a thin 4-source assembler; the
two nested walks move to module-level `_victim_folder_db_files` /
`_remembered_existing_dbs`. `_victim_folder_db_files` reuses
`db_deletion._append_db_files` (identical sorted listing) but keeps
the active-directory resolution **inline** (`os.path.dirname(abspath(
active)) if active else ""` inside a guarded try): the shared
`_registry_active_dir` helper treats a falsy active path as the CWD
parent, which would change the quirky `active_dir or vdir + "_x"`
comparison in an edge case. The fallback, guard scopes and broad
swallows are preserved verbatim (proven by the 7-case facade
differential).

### 3.4 run engine — two new mixins (same seam the package already uses)

`services/run/` already decomposes the coordinator via mixins
(`RunExecutionMixin`, `RunQueueMixin`, `RunHooksMixin`). `execute` is
split along its two natural responsibilities:

- **`services/run/cycle_loop.py` — `CycleLoopMixin`** (repeat-loop
  iteration): `_gate_before_cycle` (stop/pause/stop — the boundary
  note is emitted inline and intentionally unguarded, exactly like
  the old inline gate), `_announce_cycle_start`, `_cycle_transition`
  (stopped/empty_stack/empty/worked decisions), `_mark_run_done`.
- **`services/run/run_lifecycle.py` — `RunLifecycleMixin`** (one run's
  begin/teardown): `_begin_run` (flags, state, progress, tracer,
  start announcements; returns cycle count), `_announce_repeat`,
  `_note_run_cancelled`, `_note_run_exception`, `_note_hook_error`,
  `_run_post_hook(outcome) -> post_error`, `_finish_signals`
  (tracer close / reset / `stack_complete` / completion log with the
  nested-finally order preserved), `_mark_error_quiet`,
  `_resolve_cleanup_failure(run_error, post_error)`.
- `coordinator.execute` keeps the skeleton AND the cycle loop:
  guard → begin → pre-hook + the `for cycle` loop (gate, banner,
  `_execute_cycle`, cooperative-stop mapping, transition) →
  `_mark_run_done` → cancel/exception bookkeeping → finally
  (post hook, signals, error resolution). The loop stays textually in
  `execute` because the shipped structural-pin test
  `tests/test_merge_undo_enabled.py::test_engine_execute_is_called_without_a_parser`
  asserts `inspect.getsource(ActionEngine.execute)` contains
  `_execute_cycle` ("execute drives each run cycle itself"). Two
  helpers drafted for this design (`_run_one_cycle`, `_run_all_cycles`)
  were therefore inlined back; extracted only the named decisions.
  Every observable effect stays in the same order as today (proven by
  a 13-case HEAD-vs-refactor differential harness — see §5).

No class exceeds 150 LOC / 15 methods; no function exceeds the gates.
Lazy `actions.cancellation` imports follow the existing run-package
convention so `import services.run` stays light.

## 4. What is deliberately NOT changed

- `stores/label_state.py _normalized` (28), `actions/wait_page.py
  execute` (25), `backend/history_query.py _item` (22),
  `backend/tab_matcher.py score_tab` (20), `actions/cancellation.py
  await_with_stop` (19), `layout_service` / `migration` /
  `history/mutate` / `error_recovery` / `history/runtime` tail —
  baseline-legacy functions, out of scope for this CC regression;
  listed in the follow-up doc.
- No behavior, message, reason, trace-record or signal is reworded.
- The dead-ish `deletion_inventory_sources` is kept (documented raw
  source API), just thinned and de-duplicated.

## 5. Verification

1. Before: deletion suites (129 + 64 manager tests), run-safety +
   engine pins (109) green.
2. After each module: its suites green with zero test edits.
3. Full suite with branch coverage (audit reproduction command),
   all 20 JS entrypoints, Vulture ≥ 90%.
4. `tools/metrics/current_audit.py`: no new function/class over a
   RULE 16 gate; project max CC below 31.

## 6. Measured results

Tools: `tools/metrics/current_audit.py` (AST, nested defs stripped),
`cognitive-complexity`, `radon mi_visit(multi=True)`, coverage JSON,
Vulture 2.16 ≥ 90 %. "Before" = checkout at commit `5393a76`
(snapshot `/tmp/audit_now.json`); "after" = this change
(`/tmp/audit_tail_done.json`).

### 6.1 The seven target functions

| Function | CC | cognitive | nesting | LOC |
|---|---:|---:|---:|---:|
| `db_deletion.build_deletion_inventory` | 42 → **2** | 55 → **1** | 6 → **0** | 112 → **16** |
| `run/coordinator.RunCoordinator.execute` | 36 → **9** | 50 → **12** | 5 → **3** | 103 → **29** |
| `db_media_scan.scan_world_media` | 29 → **4** | 30 → **3** | 4 → **2** | 124 → **21** |
| `db_deletion.classify_candidate` | 28 → **5** | 36 → **5** | 4 → **2** | 71 → **23** |
| `db_registry.deletion_inventory_sources` | 23 → **4** | 31 → **3** | 6 → **1** | 48 → **22** |
| `db_deletion.plan_deletion` | 20 → **4** | 20 → **3** | 2 → **0** | 50 → **25** |
| `db_deletion.prune_empty_dirs` | 20 → **3** | 37 → **2** | 4 → **1** | 53 → **13** |

Every replacement unit passes all hard gates (CC ≤ 10, cognitive ≤ 15,
nesting ≤ 4, LOC ≤ 30, params ≤ 4). The only > 4-param flags are the two
FROZEN public keyword-only signatures `classify_candidate` (7 kwargs) and
`plan_deletion` (9 kwargs); they are byte-for-byte unchanged in arity
(legacy-edit clause §0: not worsened), and grouping kwargs would break
the frozen keyword API for no complexity gain.

### 6.2 Project aggregates

| Metric | before | after |
|---|---:|---:|
| Project max cyclomatic CC | 42 | **28** (was 31 before round 1) |
| Project max cognitive | 55 | 40 (legacy `wait_page.execute`) |
| Project max nesting | 6 | 6 (legacy `collector_bridge.collector_command`) |
| Longest function (LOC) | 124 | 122 (`dom_probe.build_probe`, RULE 16 §1.5 JS exemption) |
| Functions CC > 10 | 73 | **64** |
| Functions cognitive > 15 | 29 | **21** |
| Functions nesting > 4 | 6 | **3** |
| Functions > 30 LOC | 83 | **75** |
| Functions > 4 params | 71 | 71 |
| God classes > 300 LOC / > 15 methods | 11 / 24 | 11 / 24 (method counts unchanged; `RunCoordinator` 254→181 LOC, `DbRegistry` 249→223 LOC) |
| Mean Radon MI (all production files) | 65.02 | **65.06** |
| Exact-AST clone groups / lines (persisted scanner) | 12 / 90 | 12 / 90 (no new clones) |
| Coverage line / branch | 90.23 % / 84.18 % | **90.41 % / 84.38 %** |
| Vulture ≥ 90 % findings | 7 | 7 (same baseline set) |
| Test result | 2467 pass | **2467 pass, zero test edits** |

Per-file Radon MI: `run/coordinator.py` 29.12 → **40.87**;
`db_registry.py` 40.99 → **42.45**; new `run/cycle_loop.py` **75.43**,
`run/run_lifecycle.py` **59.62**. `db_deletion.py` 25.22 → 20.54 and
`db_media_scan.py` 60.91 → 52.77 decreased purely from the added named
units/docstrings/module length (MI has no complexity content for these
anymore — worst CC is 9/6); the project mean still rose.

### 6.3 Behavior preservation evidence

- All **129** deletion tests, **64** DbManager contract tests, the full
  run-safety + engine suites, and the full **2467-test** suite pass with
  **no test file modified**.
- A 13-scenario HEAD-vs-refactor differential harness for
  `RunCoordinator.execute` (empty stack / worked / cooperative stop in
  block / external cancel / post hook raises / post hook cancelled /
  cancel inside post hook / pre hook raises / empty users / pause→stop at
  the gate / 2-cycle run / cancel + post fault / empty first of 2 cycles)
  produced identical raised exceptions, final run state, log+debug
  messages, trace records (types/reasons), `post_run` outcomes,
  `stack_complete` counts, `_running`/`_ctx` reset.
- A 7-case differential for `DbRegistry.deletion_inventory_sources`
  (victim elsewhere / victim inside active dir / no victim arg / worlds
  raises / active raises / known_paths raises / empty active path with
  the `active_dir or vdir + "_x"` fallback) produced identical dicts.
- Pinned strings/keys/reasons (`active folder scan failed`, …,
  `ok/missing_file/...`, one terminal `run_end`, post hook exactly once,
  etc.) unchanged.

The new report `reports/CODE_QUALITY_METRICS_2026-09-10_cc-tail.md`
records the post-fix inventory; the next-round proposal (new CC tail +
nesting legacy + god classes) is
`docs/archive/2026-09-10-safety-refactor/CC_REMAINING_TAIL_DESIGN_2026-09-10.md`.
