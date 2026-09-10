# Safety-first improvement design: three independently implementable areas

Date: 2026-09-10 · Baseline production commit: `a49dd2a`
Status: **Design proposal ready for implementation review; no production changes made.**
Current session branch: `arena/01a08b46-chat-v-bot`.

## 1. Problem, priorities and evidence

Goal: prevent destructive mistakes, improve protection of UI/backend boundaries, fix reproduced stop behavior, then simplify cycle orchestration without changing action/preset contracts.

This is not a repo-wide rewrite or a campaign to reduce LOC. Read `docs/archive/2026-09-10-agent-rules-v1/AGENT_RULES.md` first, especially rules 2, 4, 7, 8, 9, 11, 12 and 13. Relevant contracts are in `docs/archive/2026-09-08-one-db-one-world/DB_CREATION_DELETION_REDESIGN_DESIGN_2026-09-08.md`, `docs/archive/2026-09-07-labels-and-collector/PRIVATE_GATE_AND_MEDIA_TREE_2026-09-07.md`, and the existing run/DB contract tests. Audit baseline: `reports/CODE_QUALITY_METRICS_2026-09-10.md`.

### Evidence collected for this design

| Finding | Evidence | Classification |
|---|---|---|
| Shared media can be removed despite being protected | Executed real `DbLifecycle._delete_world_media` in a temporary directory with a file inside the victim world's folder included in both `footprint` and `keep`. File did not survive. The per-file check is bypassed by the later unconditional `shutil.rmtree(world_folder)`. | **Reproduced helper-level defect**, not yet a full two-world regression test |
| Unreadable media scan looks empty | Real `_media_references` against a temporary corrupt DB returned `set()`. Exceptions are caught and the return type contains no completeness flag. | **Reproduced loss of error information**; destructive consequence requires integration regression |
| Wait action ignores an already requested stop | Real `WaitPageLoad.execute` with `_stop_requested=True`, fake CDP returning not-found, 30 ms timeout and no pre-delay made two probes and returned `fail`. | **Reproduced action-level defect**; run-level propagation still needs tests |
| Scan happens too late | `delete` unlinks SQLite files before `_other_references` runs. | Code-inspection risk |
| Partial failures can be misleading | DB main file is first in `SUFFIXES`; media unlink failures are swallowed. `_forget` occurs only after cleanup. | Code-inspection risk; fault-injection required |
| Stop after pause and final action may cross a side-effect boundary | Engine checks stop before `_wait_if_paused`, but not consistently immediately after it; successful final action can reach marking without another check. | Code-inspection candidates, not reproduced yet |
| Single-target path masks stop outcome | `_run_single_target_cycle` returns `worked` after `_execute_for_user`, even if its status is `stop`. | Code-inspection candidate; reproduce before altering behavior |
| Cancellation cleanup may be incomplete | Outer `finally` awaits `post_run` before mandatory cleanup; per-action restoration is not in a `finally`. | Code-inspection candidates; tests first |

Temporary-directory probes touched no real user data. No fixes have been made in this design phase.

### Measured baseline to preserve

Python: 2,129 passed, 3 skipped, 1 deselected, 1 xfailed; 771 subtests passed; one unawaited-coroutine warning. Python line coverage 88.44%, branch 81.32%. Bridge: 67.44% line / 48.43% branch. JS: 19/20 test entrypoints pass; the failure expects WebChannel registration in `main.py`, but it lives in `app/window.py`.

## 2. Three-area structure and dependency boundary

```text
A — deletion safety                         B — bridge protection
DbManager (existing public API)             Router / StackBridge / UndoBridge / CdpBridge
  -> DbLifecycle                           real Qt signal/slot + EventBus tests
      -> strict reference scan             dependency fakes at service boundaries
      -> deletion plan                     no DB implementation / no run implementation
      -> bounded execution + outcome
  -> DbBridge handles partial outcomes

C — stop correctness, then cycle design
RunCoordinator (same public API and Qt signals)
  -> existing execution / queue mixins
  -> private cancellation support
  -> stack facts + cycle decision helpers
WaitPageLoad -> cooperative cancellation
```

**Independence means no shared write ownership and no dependency on another area's implementation.** It does not mean runtime subsystems cannot affect each other. Full integration tests remain mandatory.

| Area | Exclusive production ownership | Exclusive test/doc ownership |
|---|---|---|
| **A: deletion safety** | `services/db_lifecycle.py`, `services/db_service.py`, `services/db_registry.py`; proposed `services/db_deletion.py`, `services/db_media_scan.py`; **`bridge/db_bridge.py`**; `ui/js/db-panel.js` only if existing error UI cannot render the frozen result contract | New `tests/integration/safety_deletion/`; `tests/test_db_panel_js.js`; `docs/archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_A_2026-09-10.md` |
| **B: bridge protection** | `bridge/stack_bridge.py`, `bridge/undo_bridge.py`, `bridge/cdp_bridge.py`, `bridge/router.py` only for a reproduced boundary defect | New `tests/unit/bridge_safety/`; new `tests/unit/app/test_webchannel_registration_contract.py`; `tests/test_bridge_router.js`; `docs/archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_B_2026-09-10.md` |
| **C: stop + cycles** | `services/run/coordinator.py`, `services/run/error_recovery.py`, `services/run/progress.py`, `services/run/state_machine.py`; proposed `services/run/cycle_plan.py`; `actions/wait_page.py`; proposed private `actions/cancellation.py` | New `tests/integration/run_safety/`; new `tests/unit/actions/test_wait_page_cancellation.py`; `docs/archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_C_2026-09-10.md` |

Frozen for all three: public compatibility shims under `backend`, `actions/base_action.py`, `actions/base.py`/`ActionResult`, stores, `core/events.py`, `core/result.py`, `bridge/context.py`, existing shared fixtures including `tests/conftest.py`, existing public API snapshots, `requirements.txt`, `pytest.ini`, audit scripts and baseline report. `services/undo_service.py` and `services/history/*` are not part of this change. Existing regression tests are run but not rewritten to accommodate changed behavior. If a frozen file is genuinely necessary, stop and assign it explicitly before editing; do not independently change it in multiple areas.

The three area documents are single-owner implementation journals. The master plan is frozen after approval; only the integration owner updates aggregate results.

## 3. Shared contracts to freeze before dispatch

### 3.1 Public behavior

- Same Qt slot names, signatures, object name `bridge`, signals and existing payload keys/types.
- Same `DbManager.delete(path) -> dict`; successful permanent deletion never creates an undo entry. Clean DB remains reversible and is not redesigned.
- Same run entrypoints, action serialization, `ActionResult.OK/FAIL/SKIP`, block IDs, retired-key handling and preset formats.
- Same cycle outcomes `worked`, `empty`, `empty_stack`, `stopped`; same per-user statuses `ok`, `skip`, `fail`, `stop`.
- Automatic post-run marking only for successfully completed real-user work, never standalone, skipped or stopped work. An explicit `MARK_MESSAGED` action already completed before stop is not rolled back.
- One global undo timeline; bridge aliases must not create another one.
- No new global Qt fakes, fixture poisoning, global scheduler replacement, schema migration or dependency needed.

### 3.2 Deletion result extension (A owns producer and consumer)

Keep existing success keys. Add structured fields only when needed; document and test them at the A-owned DB bridge boundary:

```text
ok: bool                       true only if requested deletion fully completed
op: "delete"
path: str
error: str                     readable explanation when ok is false
phase: str                     validate / scan / switch / detach / database / media / finalize
partial: bool                  some irreversible requested work happened, but not all
world_changed: bool            app switched/detached or live world state requires refresh
active_path: str                observed current connection/config target, not guessed fallback
removed_paths: list[str]        exact known completed filesystem removals
retained_paths: list[str]       retained candidates, including safety exclusions
failed_paths: list[str]         known failed candidates
media_files_removed: int       actual file removal count, not attempted count
```

`world_changed` and `partial` are different: a fallback switch can succeed before any deletion. A refused deletion can therefore require a world/UI refresh without being a partially deleted database. DB bridge refresh must not be conditioned solely on `ok`. No success log on partial failure. No claim of atomicity across filesystem/config/SQLite operations. Existing JS can display `error`; include a behavioral test of partial payload rendering and refresh.

B does not assert exact equality on these additive DB fields, call new A helpers, or modify DbBridge. C does not import any new DB types.

### 3.3 Stop boundary

B proves `stop_stack()` calls `engine.stop()` exactly once and does not execute additional work itself. C owns what engine stop does. This makes the B tests valid before and after C.

C must not add a public STOP result to `ActionResult`. Use a private cooperative-stop mechanism handled at run execution boundaries; external `asyncio.CancelledError` remains task cancellation and must be propagated after cleanup. See area C for details.

## 4. Execution order and parallel branches

### Stage 0 — shared design baseline

Approve this plan, freeze ownership, preserve the baseline commit/report and distribute the same documents to each implementation session. Run collection/import health before starting. Record actual branch/head in each area's implementation journal.

### Stage 1 — parallel safety work

- A writes failing deletion regressions and fixes data-safety issues.
- B adds bridge behavior tests; fixes only boundary defects proved by those tests.
- C reproduces stop/pause/cancel defects and fixes them **before** cycle restructuring.

### Stage 2 — controlled structural work

A extracts deletion phases only behind green regressions. C extracts cycle planning only after its cancellation gates are green. B remains test-first, not a bridge architecture rewrite.

A and C safety work need not wait for B coverage work to finish. Review/release safety fixes before accepting cosmetic complexity reductions.

### Stage 3 — integration

Preferred merge/review order: A safety → B tests/boundary fixes → C stop fixes → C cycle-only refactor. C can supply separate commits within its one work branch. Every intermediate merged state must pass tests. Run all three area's tests together plus the complete suite after each merge. Never resolve a conflict by deleting coverage or relaxing expected behavior.

**Branch constraint:** this Arena session can work only on `arena/01a08b46-chat-v-bot`; it will not create/switch/push other branches. For three actual parallel branches, open three separate Arena sessions from the same approved baseline and assign one area to each session's platform-provided branch. The integration owner integrates their reviewed changes using the permitted workflow in its own session. A/B/C are work-area labels, not branch names to create here. No branches or PRs were created in this planning turn.

Suggested commit boundaries per area: (1) reproducer/behavior tests, (2) smallest safety or boundary fix, (3) structure extraction if applicable, (4) gate results and documentation. If failing tests are preserved in a standalone intermediate commit, mark it explicitly and do not release that commit alone.

## 5. Shared validation and acceptance gates

Use the audit environment and exclusions exactly; measure production Python including shims/unimported modules, not just executed files. The headless shared-library shims are not a substitute for real QtWebEngine validation.

```bash
# Setup from audit: ignored .venv, real PySide6 and headless native shims.
.venv/bin/python tools/build_stubs.py .venv /tmp/stublibs
export QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs
.venv/bin/python -m pytest tests --collect-only -q
# Area-local runs once their directories exist:
.venv/bin/python -m pytest tests/integration/safety_deletion -q
.venv/bin/python -m pytest tests/unit/bridge_safety tests/unit/app/test_webchannel_registration_contract.py -q
.venv/bin/python -m pytest tests/integration/run_safety tests/unit/actions/test_wait_page_cancellation.py -q
# Complete release gate (same excluded real-WebEngine test as baseline):
COVERAGE_FILE=/home/user/analysis/.coverage .venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
COVERAGE_FILE=/home/user/analysis/.coverage .venv/bin/python -m coverage json -o /home/user/analysis/coverage.json
# Run every JS entrypoint and retain failures (do not rely on last exit only):
status=0; for f in tests/test_*.js; do node "$f" || status=1; done; test "$status" -eq 0
.venv/bin/python tools/metrics/current_audit.py > /home/user/analysis/current.json
git diff --check
```

Acceptance:

- All newly specified safety tests pass; demonstrate that key tests fail against the baseline behavior.
- Existing passing tests remain passing; no added unexplained skip/xfail/exclusion.
- Global coverage never falls below 80% line / 75% branch; also explain any reduction from the 88.44% / 81.32% baseline rather than hiding behind the minimum.
- A: new deletion/scan modules ≥90% line / ≥85% branch; every destructive safety invariant tested regardless of percentage; DbBridge ≥85% line / ≥80% branch.
- B: bridge aggregate ≥80% line / ≥75% branch; each owned Stack/Undo/CDP bridge ≥85% line / ≥80% branch. Verify whether owned-file coverage can meet aggregate target; if not, produce the missing-branch inventory and request an explicit follow-up, not out-of-scope edits.
- C: modified execution/cycle/cancellation code ≥90% line / ≥85% branch; original coordinator already has high branch coverage, so preserve behavioral strength and review any apparent regression caused by extraction.
- New/rewritten cycle helpers aim for CC ≤10, cognitive ≤15, nesting ≤4. Do not scatter conditions into meaningless one-line helpers to satisfy a metric. Compatibility wrappers and embedded payloads get documented exceptions, not blanket exclusions.
- Final combined JS gate is 20/20 passing entrypoints or more if tests were added. A and C running alone may retain the known baseline stale-registration failure until B lands; no new JS failures allowed.
- No new unawaited tasks/coroutines, leaked file handles or Qt module contamination. The existing history push warning is tracked separately and is **not fixed by suppressing it**; its ownership is outside these three areas unless separately assigned.
- Actual desktop smoke gate before release: create two disposable worlds; switch/delete/cancel a wait; verify people/labels/undo refresh; run real-WebEngine test on supported display/GL. Never use the user's valuable databases for destructive testing.

## 6. Scope limits and handoff

No guaranteed atomic deletion across process crashes; no cross-process global lock; no recoverable trash for permanent delete; no redesign of world storage, tab matching, normalization, feature envy or all large classes. Unreadable scans must be refused safely even if this blocks deletion of a corrupt world; an explicit force/recovery UI is a separate product decision, not a hidden bypass.

Each owner hands off: owned-file diff, demonstrated failing-before/passing-after cases, targeted/full suite results, line and branch coverage separately, known limitations, exact public contract changes (ideally none beyond A's additive payload), and remaining risks. The integration owner reviews inter-area behavior even when Git reports no textual conflicts.

Detailed tasks: [Area A](SAFETY_REFACTOR_AREA_A_2026-09-10.md), [Area B](SAFETY_REFACTOR_AREA_B_2026-09-10.md), [Area C](SAFETY_REFACTOR_AREA_C_2026-09-10.md).
