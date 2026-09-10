# Area A — permanent deletion safety

Parent: [master plan](SAFETY_REFACTOR_2026-09-10_PLAN.md). Status: designed, not implemented.
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

Implementation journal (owner fills): actual branch/head; changed files; baseline reproductions; test commands/results; coverage; API compatibility; deferred risks.
