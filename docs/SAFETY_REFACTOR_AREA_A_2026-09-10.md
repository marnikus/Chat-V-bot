# Area A — permanent deletion safety

Parent: [master plan](SAFETY_REFACTOR_2026-09-10_PLAN.md). Status: implemented, all gates green (2026-09-10).
Design record: [AREA A design](SAFETY_REFACTOR_AREA_A_DESIGN_2026-09-10.md) (structure decided before tests; tests written before refactor).
Priority: highest potential irreversible impact. Exclusive ownership includes DbBridge; B must not edit it.

## A1. Understand the current flow

`bridge/db_bridge.py:db_delete` → `_db_action` → `DbManager.delete` → `DbLifecycle.delete`.

Current order: resolve/list → footprint → switch active world → detach remaining connections → unlink main/WAL/SHM → scan other references → unlink media → recursively delete entire world folder → forget world → return success.

Problems to protect:

1. Scan failures become empty reference sets (`services/db_service.py:_media_references`).
2. Cross-world references are scanned after irreversible DB removal.
3. Folder deletion ignores the per-file keep set. This was reproduced during design.
4. Main-file and sidecar deletion is not atomic; later errors can leave partial work.
5. Media errors can be swallowed while the bridge logs complete success.
6. An active-world switch can succeed before later deletion failure, but bridge refresh currently depends on `ok`.
7. `existing_worlds()` scans the active database folder plus the active file, while `known_paths()` can describe additional paths. A complete safety scan needs an explicitly defined inventory, not blind trust in this one list.

## A2. Proposed structure

Keep `DbManager` facade and existing lifecycle entrypoints. Do not relocate create/load/clean/restore wholesale.

- `services/db_media_scan.py`: strict, read-only media scan with an internal result carrying `references`, `complete`, and diagnostic information. A corrupt/locked DB is not empty. Correct SQLite URI escaping must handle spaces, `?`, `#`, and Unicode paths.
- `services/db_deletion.py`: internal deletion plan/result types plus bounded filesystem helpers. Candidate data, preserved data, actual removals and failures are explicit. Avoid a new framework or generic transaction abstraction.
- `DbLifecycle.delete`: orchestrates validation → full scan/plan → safe switch/detach → revalidate → remove DB group → media cleanup → reconcile → result.
- `DbBridge`: emits the existing result signal, refreshes world state when it actually changed even on partial failure, never records delete in undo, never logs false complete success.

Maintain `_media_references(path) -> set` if existing callers/tests rely on it. Destructive deletion must use the new strict scan, not the legacy best-effort wrapper. Do not silently change all info/clean consumers at once. Correct misleading comments about failed scans being conservative.

### Scan and inventory policy

Before **any DB/media removal**, scan the victim and all supported existing worlds: include active, normal folder discoveries, existing remembered in-root paths, and victim's directory as needed by `resolve` semantics; deduplicate canonical identities. Test a known world outside the active folder. Inventory failure is incomplete, not an empty inventory. Reject an unregistered/unsupported target rather than asserting all references are known.

State the supported-world boundary in the result/docs. Arbitrary unregistered external files cannot be discovered reliably; never claim protection of every SQLite file on disk. If current app contract allows undiscoverable worlds to share media, block this deletion design until ownership/discovery is clarified.

Default safe policy: **any required scan incomplete → refuse deletion before switching/unlinking**, report which world could not be verified. A DB genuinely lacking a media table is not automatically treated as a valid empty world: prove a supported schema/version rule first. No force-delete fallback in this work.

### Media ownership and path policy

- Build per-file candidates; subtract protected references before removal.
- Never blanket-`rmtree` a world folder. Remove eligible files individually; prune only verified empty directories.
- An unreferenced file in the victim's exclusive world folder can be a candidate, but only after complete scans and proof that the folder is not also another world's folder (same-stem databases are possible). Ambiguous ownership means retain, not guess.
- Never remove media root, another world's folder, or paths outside root.
- Use canonical identity/containment appropriate to the platform; `abspath` string prefix alone is insufficient for symlinks/junctions. Do not traverse directory symlinks. Test the policy for a symlink inside root pointing outside; skip on platforms without symlink permissions only with an explicit reason.
- Keep counters truthful: count actual file removals, including eligible files discovered in the victim folder. Known safety-retained shared files are not cleanup failures.

### Concurrency and irreversible boundary

Serialize overlapping lifecycle create/load/delete/clean/restore operations for a single manager using a non-reentrant boundary and internal unlocked delegates (delete calling load must not deadlock). Before approving the implementation, trace whether multiple DbManager instances or direct `HistoryService.switch_db` calls can bypass that boundary. If so, serialize at an already shared owner or explicitly reject destructive work while conflicting operations/background media writes are active. An instance-local lock is not a solution to multiple independent owners.

Reference scans followed by deletion have a TOCTOU window. Quiesce/revalidate in-app writers and live handles before removal; add a test that changes references/world inventory between planning and execution. If this cannot be achieved within the owned files, stop for ownership/design review. Do not introduce a cross-layer lock protocol unilaterally or pretend external processes are protected.

SQLite group deletion is not atomic. First ensure connections are safely released; define and test suffix handling for main/WAL/SHM and supported rollback-journal mode. Do not blindly reorder sidecars before the main file without proving the DB is checkpointed and closed. On partial failure, preserve remaining files/media, record exact completed operations, reconcile the actual active path, and report incomplete work. Never claim rollback recreated a deleted file.

Use `try/finally` for mandatory state reconciliation after irreversible work. Cancellation before removal performs no removal; cancellation after partial work still reconciles and logs known partial state, then propagates cancellation. Do not continue arbitrary destructive cleanup under blanket shielding.

## A3. Tests before implementation

Create `tests/integration/safety_deletion/` with independent local fixtures. Use temp directories, real SQLite and real DbManager/DbLifecycle. Mock only specific fault boundaries, not the whole method under test.

| Test group | Required assertions |
|---|---|
| Last world, invalid/missing/out-of-root target | No unlink, no switch, no config mutation, clear refusal |
| Shared file inside victim folder | Other world references it; file and bytes survive full `DbManager.delete`; victim DB gone on successful permitted deletion |
| Shared file outside victim folder but inside media root | Retained; unrelated folders untouched |
| Corrupt/locked/unsupported other DB | Incomplete scan distinguished from empty; **no victim/media unlink** |
| Valid empty reference set | Normal unshared cleanup still works; prevents fail-safe from becoming universal no-op |
| Inventory and URI edges | Known in-root world in another folder, duplicate paths, same-stem worlds, scan failure, spaces/Unicode/URI metacharacters |
| Switch failure | Original world remains usable and victim files/media untouched |
| Detach/memory-close failure | No unlink; accurate connected state and error |
| Partial SQLite removal | Inject failure at every group element; exact surviving files and truthful partial result |
| Media unlink/prune failure | No false success; shared data intact; completed/failed counts and path lists correct |
| Config/finalization failure | Files already removed remain reported removed; stale active path not silently presented as valid |
| Traversal/symlink/ambiguous ownership | No escaping removal, no root removal, no sweeping another world's data |
| Cancellation/concurrency | Before/after destructive boundary; overlapping deletes cannot remove last two worlds; reference changes invalidate stale plan |
| Bridge result handling | Success/scan refusal/switch-only change/partial failure: correct `db_changed` payload, log level, refresh, and no delete undo entry |
| Clean/load/create regression | Existing reversible clean and fail-closed switching remain unchanged |

Begin with the shared-file test that must fail on baseline and unreadable-scan refusal. Fault-injection tests must inspect bytes/state and emitted events, not only `ok`.

Relevant existing gates: `tests/test_db_manager.py`, `test_db_manager_corrupt.py`, `test_db_switch_e2e.py`, `test_db_switch_restart.py`, `test_db_unified_world.py`, `test_media_recovery*.py`, `test_archive_delete_undo.py`, `tests/integration/services/test_db_manager_contract.py`, `test_services_db_gaps.py`; full suite is authoritative.

## A4. Steps and completion

1. Write regressions; record failing baseline outcomes.
2. Implement strict scan + safe keep-aware cleanup, preserving public contracts.
3. Implement truthful partial results and DbBridge handling; prove no false success.
4. Address inventory/path/concurrency gates; explicitly escalate cross-owner needs.
5. Extract clear phases only after behavior is protected; avoid expanding scope into clean/recovery redesign.
6. Run targeted, full Python, relevant JS and coverage gates from master plan.
7. Record supported-world inventory and external-process/crash limitations. No promise of rollback or cross-process atomicity.

## Implementation journal (owner filled 2026-09-10)

Branch/head: `arena/01a08b7b-chat-v-bot`, branched from `3820136` (master-plan
commit; `main` at start of work). All AREA A work is on this branch; no commits
to `main`.

Changed files (production):

- `services/db_media_scan.py` (new, 178 lines): strict read-only media scan.
  `MediaScanResult(references, complete, reason, detail, schema_version)`;
  `scan_world_media()` opens the target with an RO SQLite URI
  (`sqlite_ro_uri()`; spaces/`?`/`#`/`%`/Unicode escaped, `mode=ro`), requires
  the `media` table, accepts schema versions `{"6"}` (missing `schema_meta`
  with a `media` table present is legacy-complete), and reports
  `missing_file`/`missing_media_table`/`unsupported_schema`/`locked`/
  `query_error`/`corrupt`/`io_error` as *incomplete*, never empty. One proven
  exception: a zero-byte file is complete/empty (no pages can hide a
  reference); any non-empty unreadable file refuses.
- `services/db_deletion.py` (new, ~514 lines): deletion inventory
  (`build_deletion_inventory()` from active-folder scan + active path +
  victim-directory `*.db` scan + remembered in-root `*.db` + victim itself;
  any source failure → `complete=False`), per-file plan
  (`collect_discovered_files()` never follows/returns symlinks;
  `classify_candidate()` verdicts `remove` vs `retain:<reason>` for symlink /
  outside-root / root / other-world-folder / shared / ambiguous-folder /
  missing / not-file), bounded filesystem helpers (`unlink_one()` refuses
  symlinks/dirs, missing is success; `prune_empty_dirs()` verified-empty dirs
  strictly inside base, never base/others, never `rmtree`), and
  `DeletionOutcome.as_dict()` (truthful `ok/phase/partial/world_changed`,
  path lists, counters, no rollback claims).
- `services/db_lifecycle.py` (rewritten delete path, 376 → 917 lines):
  global + instance locks (a module-global non-reentrant boundary plus the
  per-manager lock, so two `DbManager` instances cannot delete concurrently);
  `_load_unlocked` delegate so delete→switch cannot deadlock; phased
  `_delete_unlocked` (validate → inventory → strict scan/plan → quiesce →
  switch/detach → revalidate inventory+plan → remove DB group main/WAL/SHM →
  media per-file → reconcile/finalize). Any incomplete scan, inventory gap,
  revalidation drift, switch/detach failure, or partial removal refuses or
  reports partial with exact surviving files; `try/finally` reconciles the
  real active path; cancellation before the irreversible boundary removes
  nothing, after partial work reconciles/logs then propagates. Dead legacy
  fail-open helpers (`_world_footprint`, `_other_references`,
  `_delete_world_media`, which used best-effort `_media_references`) were
  deleted, not kept.
- `services/db_service.py`: `_media_references()` kept for compat but
  documented as legacy fail-open; deletion must use the strict scan.
  Misleading "conservative" comments corrected.
- `services/db_registry.py`: added `deletion_inventory_sources()` exposing
  the raw source lists the inventory is built from.
- `bridge/db_bridge.py`: `_db_action` refreshes world state on
  `world_changed` even when `ok` is false (switch-only change), sets the
  `switched` flag, never logs false complete success (warn-level partial
  log), never records delete in undo.
- `tests/test_db_panel_js.js`: +3 AREA A payload tests (partial/switch-only/
  scan-refusal). No production `ui/js/db-panel.js` change was needed: the
  existing error+refresh rendering already handles partial payloads.

New tests: `tests/integration/safety_deletion/` (19 files, 129 tests) covering
every row of the A3 table, plus unit/defensive suites for the new modules.
See the design doc for the test→invariant map.

Baseline reproductions (failing before, passing after; no existing test was
rewritten to change asserted behavior):

- Shared file inside the victim folder was deleted with the victim (folder
  `rmtree` ignored the keep set). Now retained byte-identical; victim DB
  still removed on permitted deletion.
- Corrupt/unreadable other-world DB scanned as "empty" (`_media_references`
  swallowed errors), so deletion proceeded and removed shared media. Now any
  incomplete scan refuses before switching/unlinking, naming the unverifiable
  world.
- Stale plan: a world created between plan and execution was missed. Now
  revalidation refuses on inventory drift.
- Two overlapping deletes could remove the last two worlds (instance-local
  lock only). Now the global boundary serializes them; exactly one succeeds.
- Bridge showed success while media cleanup failed, and did not refresh after
  a switch-only change. Now partial/switch-only payloads are truthful.

Process followed: design doc first → full red test suite (26 failed/16 passed
on first safety run) → implementation → green. Two red→green iterations are
recorded here, not hidden: (1) the finalize test first mocked only
`cfg.save`, but the non-active-victim `_forget` path persists via
`set_state`→`settings.save`, so the mock never fired — fixed by failing both
persist calls; (2) the strict scan initially refused a zero-byte neighbour DB
(`missing_media_table`), breaking the pre-existing
`test_delete_a_non_active_world` expectation — fixed with the proven-empty
zero-byte exception (non-empty corrupt files still refuse).

Test commands/results (2026-09-10, `QT_QPA_PLATFORM=offscreen`,
`LD_LIBRARY_PATH=/tmp/stublibs`):

- Safety suite: `pytest tests/integration/safety_deletion/ -q` →
  **129 passed**.
- Full Python suite: `pytest tests -q -p no:cacheprovider --deselect
  tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine`
  → **2258 passed, 3 skipped, 1 deselected, 1 xfailed, 771 subtests passed**,
  1 pre-existing unawaited-coroutine warning. The single deselect is a real-
  WebEngine grid test that **aborts the interpreter on the clean base commit
  too** (verified via detached worktree at `3820136`), i.e. a pre-existing
  sandbox/environmental failure unrelated to AREA A; it is flaky (it passed
  in an earlier full run) and owned outside A. The earlier
  `--deselect ...test_real_cleanup` flag matched no existing test and was
  dropped.
- JS: `node tests/test_db_panel_js.js` → **21 passed, 0 failed**; all other
  `tests/test_*.js` pass except the pre-existing `test_bridge_router.js`
  stale-registration failure (baseline, owned by AREA B — bridge router
  registration, untouched by A).

Coverage (`coverage run --branch
--source=core,actions,backend,bridge,services,stores,app,main`, JSON at
`/home/user/analysis/coverage.json`, audit baseline 88.44% line / 81.32%
branch, minimums 80% / 75%):

- Global: **86.62% line (11298/12863), 81.72% branch (2592/3172)** — branch
  coverage is *above* the audit baseline; line is −1.82pp, explained below.
- `services/db_media_scan.py`: **100% / 100%** (target ≥90% / ≥85%).
- `services/db_deletion.py`: **99.11% / 99.09%** (target ≥90% / ≥85%; only
  uncovered lines are a defensive second root-identity check unreachable
  because `is_within → True` already implies inequality).
- `bridge/db_bridge.py`: **87.63% / 91.67%** (target ≥85% / ≥80%).
- `services/db_lifecycle.py`: 71.81% / 77.92% (no AREA A percentage target —
  it is modified, not new; the ≥90% execution-code target belongs to AREA C).
  The file grew 376 → 917 lines with fail-closed deletion phases; the
  remaining gap is non-deletion paths (create/load/clean/restore) plus
  defensive `except` branches. Deleting the three dead legacy fail-open
  helpers lifted it from 66% and removed the misleading code entirely.

Line-coverage reduction (−1.82pp) is fully explained: ~540 net new
fail-closed statements (strict scan, inventory/plan/policy, phased lifecycle
with revalidation/cancellation/partial paths) plus the lifecycle growth
above; every destructive safety invariant is directly tested regardless of
percentage, and branch coverage improved on baseline.

API compatibility: `DbManager.delete`, `DbLifecycle.delete`, bridge
`db_changed` payload shape, and `_media_references()` are preserved;
payloads only *add* truthful `phase/partial/world_changed` fields and path
lists. Clean/load/create behavior unchanged (regression suite green).
Supported-world boundary: active-folder scan + active path + victim-directory
`*.db` + remembered in-root `*.db`, canonical-deduped; arbitrary unregistered
external files are out of scope by design and never claimed protected.

Deferred risks / explicit non-promises: no cross-process atomicity (external
writers can still race the TOCTOU window; only in-app writers are
quiesced/revalidated); no crash-atomicity across the DB group (partial
results report exact survivors, never claim rollback recreated a file); no
force-delete fallback; `services/db_registry.py` 66.98% line coverage is
outside A's owned percentage targets. AREA B owns the bridge-router
registration failure; AREA C owns execution/cancellation percentage targets.
