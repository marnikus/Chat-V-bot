# Area C — service decomposition (2026-09-10)

## Scope and research

Implements §6.3 of `REFACTOR_2026-09-09_FOUR_AREA_PLAN.md` on the current
checkout. Public signatures, Qt signals, EventBus payloads, and persistence
formats remain compatible. No changes to stores, actions, bridges, core, app,
main, or Area A's coordinator/progress and test-harness files.

Inspected the service implementations, repository rules, existing service
integration tests, private-gate tests, world-switch tests, and undo tests.
The checkout differs from the plan's measurements: the focused baseline is
357 passed / 10 failed, not the old 223-failure backlog. See validation report
for commands and the retained external failures.

Important existing contracts:

* Collector lifecycle/busy guards precede probing; failed private gates disarm
  push. The parser remains the single source of private-chat verification.
* Cursor comparisons, low-priority leases, backfill flags, idle media draining,
  payload shapes, and per-session nick detection survive extraction.
* Undo has one chronological sequence, split between app snapshots and world
  commands. Migration retains sequence identities and copies mutable values.
* DB switching parks collection, flushes the previous world, rebinds all DB
  consumers, restores the previous DB on open failure, and restarts collection.
* Existing collector queue-refresh behavior conflicts with Rule 14's prose;
  changing that product behavior is NOT part of this refactor. Existing tests
  explicitly require it; this work preserves it rather than silently choosing
  a new queue policy.

## New structure

### Collector

`Collector` remains the QObject facade and sole owner of mutable session state.
`CollectorProbe` implements probe/self-heal, page classification, identity
adoption, and the private gate. `CollectorArchive` implements conversation
preparation, cursor decisions, sync result handling, and media draining.
These are stateless internal collaborators: methods receive the facade as the
context, so there is no mirrored state or generic attribute proxy. The tick
coordinator explicitly sequences probe -> classify -> identify -> prepare ->
verify -> archive. Existing `_sync`, `_remember_partner`, and notification
methods stay available. Backend dependencies are injected from the existing
facade imports; new modules add no backend imports.

### Undo

`UndoProjection` owns normalization/migration and kind projections.
`UndoWorldStore` owns timeline persistence and world-state merging. These are
explicit internal mixins sharing the facade's single timeline (the project
already uses this pattern for run/history). `UndoService` retains wiring,
push, command application, undo and redo. Migration is split into modern-entry
validation, legacy snapshot collection and index selection. Equality ignores
sequence bookkeeping. A same-value push after undo must persist redo truncation.

### Database

`DbRegistry` owns paths, discovery, remember/prune, reporting, and load/switch.
`DbLifecycle` owns create/delete/clean/restore and file/media operations.
`DbManager` is the stable facade with constructor/wiring only. Shared filesystem
helpers live in `services/db/paths.py` and are re-exported by `db_service.py`.
Lifecycle and registry use the same facade state, never a second service/config.
Create accepts a name, not an arbitrary destination path: containment is pinned
by existing failing tests before repair.

### History

Retain query and mutation API surfaces. Split the export mixin into
`HistoryLifecycle` (init/close/switch/rollback), `HistoryBinding` (push connection
and collector task control), `HistoryMigration` (independent install migration
steps), and `HistoryExportService` (format rendering). Methods still resolve on
`HistoryService`; callers and test injection seams remain stable.

### Small services and run helpers

Share the identical EventBus log forwarding method through a small `StatusEvents`
mixin. Preserve message text/level semantics. Allow idle -> paused explicitly:
pause can be requested before start, and start clears stale pause. Test the full
transition matrix, retry policy/backoff, hook events and error paths directly,
without modifying Area A's engine coordinator.

### Alias ownership conflict

Actual import search finds more importers than the plan's count. Backend shims
already import canonical packages. Repoint Area C-owned tests to canonical
packages and remove `history_service`. Keep the `run_service` compatibility shim
until Area A repoints `test_run_service_paths.py`: §6.5 expressly forbids Area C
from editing that test. Deleting it now would break another area's tests.

## Test-first sequence

1. Record baseline against unchanged production code.
2. Add behavioral contracts using real service facades, temporary SQLite worlds,
   parser/page fakes, EventBus capture and controlled failure injection. Run
   these BEFORE extraction. Regression tests for intended fixes may be red.
3. Extract collaborators; retain and rerun the same tests. Add structure tests
   only after behavior is pinned, to enforce complexity/import limits.
4. Run Area C suite and broad regression suite excluding documented Area A
   collection poisoners and sandbox-incompatible WebEngine test. Report failures
   by ownership, not as passes. Measure line and branch coverage separately.
5. Run scoped mutation checks on C-owned run modules; do not claim a score for
   unmodified Area A files. Record killed/survived mutants and exact scope.

## Acceptance

* `_tick`: <=60 lines, CC <=15; migration coordinator CC <=10.
* Services line coverage >=85%; undo facade >=70%, with extracted modules also
  measured (moving uncovered code must not count as improved testing).
* C-owned run-module mutation score >=60%; disclose full run-package limitation.
* No added backend dependencies; public signatures and payloads unchanged.
* No new Area C test failures; external failures documented with baseline.

## Implementation outcome

Implemented and validated; see
[`reports/REFACTOR_AREA_C_2026-09-10.md`](../reports/REFACTOR_AREA_C_2026-09-10.md)
for the final structure, test-first evidence, coverage, mutation scope and
remaining cross-area limitations. The run alias is intentionally retained
until its Area A-owned importer is repointed.
