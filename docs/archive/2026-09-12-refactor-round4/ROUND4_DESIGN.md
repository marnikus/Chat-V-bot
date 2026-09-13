# Refactoring round 4 — verified debt, then archive-sync boundaries

Written 2026-09-12 against `59f45eb7` on `arena/01a093f4-chat-v-bot`.
The requested 09.11.2026 reports are interpreted as September 11, matching
repository dates. This is a design snapshot; outcomes go in a separate report.

## 1. Research and priorities

Read `docs/current/AGENT_RULES.md`, `docs/current/SYSTEM_OF_RECORD.md`,
`reports/IDEAL_SIZE_BASELINE_2026-09-11.md`,
`reports/CODE_QUALITY_METRICS_2026-09-10_cc-tail.md`, and
`docs/archive/2026-09-11-cc-tail/CC_TAIL_FIXES_DESIGN_2026-09-11.md`.
The September 11 size snapshot predates the completed CC round. Do not work
through its obsolete function list again. Fresh `current_audit.py` results:

* No functions CC > 10 or nesting > 4.
* Two cognitive > 15: router factory and settings lookup, both 17.
* 44 functions > 30 LOC (includes documented JS/wire/legacy exceptions).
* Largest file: `backend/chat_sync.py`, 791 LOC, MI 10.78. This is not one
  giant decision: already-named phases still occupy one physical module.
* Largest class: `Collector`, 518 LOC / 39 direct methods; next
  `ScrollParser`, 507 / 37. They require separate lifecycle designs.
* Ten files > 500 LOC, not the nine in the earlier snapshot.

Risk-ranked queue (not just a descending LOC list):

| Priority | Problem | Why / safe next action |
|---|---|---|
| P0 validation | RULE 16 gate owns only a fixed sortable-columns list; CI template is inactive | A green gate is not proof about new code. Explicitly gate every changed/extracted symbol this round; subsequently design a base-SHA-aware gate with legacy ratchets and missing-tool failure. Do not activate a workflow blindly: template documents a GitHub permission constraint. |
| P1 cognitive | `SettingsStore.get` nested fallback walk, cognitive 17 | RULE 19 says simplify this before size work. Extract the defaults-tree lookup, preserve missing-vs-scalar/None semantics. |
| P1 archive boundary | `chat_sync.py` 791 LOC | Largest reader-context burden; owns archive writes and partial-read cursors. Start with pure planning, not concurrent I/O or mutation. |
| P2 class cohesion | Collector / ScrollParser / UndoService | Large shared-state classes with cancellation, persistence and Qt contracts. Plan per responsibility; do not just add mixins to conceal method counts. |
| P2 safety code size | `db_deletion.py` 665; deletion flow 509 | Irreversible path already has safety tests; extract value types/policy only after differential evidence. |
| P3 remaining tails | message typing ladder 70 LOC, query paging 53, router cognitive 17 | Typing needs attempt/read-back tests; router has frozen named Qt slots. No splitting embedded JS or loosening snapshots. |

Baseline suite before edits: **2653 passed, 3 skipped, 1 deselected,
1 xfailed**, 774 subtests; one pre-existing unawaited collector-push warning.
Line coverage **91.03042%**, branch **85.77729%** (higher than the old frozen
90.44 / 84.38 floors). Existing standalone RULE 16 gate: 23 tests pass.
Qt imports need repository-built `/tmp/stublibs`; real WebEngine excluded.

## 2. Staged implementation and exit criteria

1. **Measure / characterize** (this slice): record fresh baseline, pin settings
   overlay edge cases before editing. Preserve all existing tests.
2. **Settings fallback** (this slice): move only the defaults-tree traversal to
   `_default_value(keys, default)`. Target cognitive <= 10, nesting <= 2, LOC
   <= 20 per function. No merged-data persistence, no new store methods.
3. **Sync planning boundary** (this slice): promote the growing chat-sync family
   to `backend/sync/`; move `SyncOptions`, `ReadPlan`, `SyncPlanner` and mode
   constants together into `planning.py` (~220 LOC). Keep their names as
   identical re-exports from `backend.chat_sync`; no facade wrappers or new
   duplicate definitions. Keep all read, gate, retry and write order unchanged.
4. **Persistence boundary** (next slice): move `SyncPersister` and live-result
   aggregation to `backend/sync/persistence.py`. Characterize incomplete cursor
   writes, gap marking and failed media recovery before moving anything.
5. **Read/alignment boundary**: move `ChunkReader` and `DeltaAligner` together
   after stop-during-retry and cancellation characterization. `_window` currently
   checks no stop inside retries: investigate as a separate behavior fix, not
   a claimed behavior-preserving extraction.
6. **Session lifecycle**: split preparation/viewport responsibilities from
   `SyncSession` (currently itself over class size/method limits). Explicit
   collaborators, no cross-package private-state grab bag; preserve gate-before-
   write and restore/finalization ordering. Target classes <= 120 LOC / 10 methods.
7. **Compatibility facade**: move orchestration last, leave `chat_sync.py` only
   public re-exports. Target cohesive package 5–7 files, each <= 300 LOC. A small
   initial package is intentional; do not create empty future modules.
8. **Gate coverage**: independently design changed-symbol discovery, new vs
   legacy classification, class ratchets, JS exceptions, and missing dependency
   behavior. Test synthetic breaches outside OWNED before wiring hook/CI.
9. **Re-prioritize**: rerun measurements; take Collector's lifecycle next unless
   tests expose a higher-risk defect. Do not claim round 4 complete after slice 3.

## 3. Design constraints and rejected shortcuts

`backend/sync/planning.py` owns options + pure read-window decisions and imports
only standard library and `backend.chat_text`. It must not import Qt, the
parser, a service, or a store. Runtime continues to import planning; planning
never imports runtime. Keeping options and plans together avoids a two-file
cycle and artificial micro-modules.

Planning's largest function is `plan` (21 physical LOC, CC 8, cognitive 7,
nesting 1); largest class is well below 150. Re-measure exact numbers before
acceptance. Four-argument public planner helpers remain unchanged, rather than
breaking callers for the preferred three-parameter target. An explicit
`ideal-size:` reason documents the immutable multi-mode return contract on
`plan`; no hard-limit override is needed.

Settings semantics are intentionally asymmetric: an absent overlay key retries
the *entire* path in defaults, but an explicit scalar/null intermediate blocks
traversal and returns the caller default. `get()` with no keys returns the
actual overlay; defaults are not persisted or copied implicitly. Preserve even
the existing identity-based early stop in the fallback walk.

Rejected: moving all 791 lines into a new file; numbered helpers; dispatch
lambdas hiding decisions; raising baseline caps; adding 20 unused future files;
rewriting API snapshots; folding cancellation changes into a file move.

## 4. Acceptance / reproduction

* Existing full suite is the equivalence gate, unchanged.
* Add behavior tests for settings misses, scalar/null paths, fallback identity,
  explicit falsy values, and overlay-only persistence; run before the refactor.
* Add execution-based import-boundary and facade-identity tests for planning;
  existing sync plan/phases suites still call the real public entry points.
* Use `tools/metrics/rule16_gate.py` measurement functions explicitly for every
  extracted/new function and class, not only the fixed OWNED list. New symbols
  must fit all hard limits. Remaining legacy runtime must not worsen.
* Run standalone RULE 16 tests, full branch coverage, all Node harnesses,
  `rule16_gate.py --with-clones`, unused-import checks and fresh global audit.
* Coverage must not fall below this round's measured baseline; every new helper
  gets assertions. Mutation job is configured only for `backend/history_query.py`
  (untouched); report that limitation instead of claiming a mutation score.
* Publish measured outcomes and pending stages in
  `reports/REFACTOR_ROUND4_2026-09-12.md`; update current doc/map without expanding
  the already-over-budget system-of-record file.

## 5. Compatibility discovery during slice 3

The unchanged API test caught a measurement limitation: `dump_public_api.py`
only counts classes whose `__module__` equals the facade module, so identical
re-exported objects look removed. Do not rewrite the golden snapshot or falsify
`__module__` (which would also affect type-hint resolution). Before proceeding,
make the facade's intended exports explicit with `__all__`, and let the audit
include explicitly exported functions/classes as well as locally owned ones.
Test real imported symbol removal, signature drift, and exclusion of incidental
imports. This preserves the original snapshot and strengthens the audit for
future facade extractions. Class/module metadata is not a frozen signature;
old pickles still resolve the same attributes through the original module.
