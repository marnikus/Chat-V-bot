# Area B reconstruction design — 2026-09-19

Status: implemented and verified; design recorded before production edits. Source: supplied 21-file
`seam/bridge-humble-shell` manifest; integrated onto the current Area A branch.
No upstream branch merge or source performance numbers are claimed.

## Seams and invariants

1. Extract Qt-free wire codec, DB outcome policy and undo projections. Keep
   all existing QObject slots/signals and compatibility helper names. Keep
   stack-history normalization before trimming and saving. No store redesign.
2. Introduce Scheduler/ManualScheduler, AsyncioScheduler and WorldGate;
   retain historical world-event facade signatures and patchable WAIT_S.
   Inject scheduler into PeopleBridge. Preserve timeout-then-work behavior
   and two-argument error callback; cancellation propagates. Reject nonpositive
   polling steps rather than hang a manual clock.
3. Announcer distinguishes synchronous label intent from confirmed outcomes.
   DB calls it only after a successful, online, changed-world result. Existing
   undo reporting remains intact; shared intent policy may be imported without
   changing command execution or claiming all reporting has been migrated.
4. Generate the COMPLETE Router metaobject schema (not the partial supplied
   snapshot); verify exact artifact parity and pre/post name/type/return parity.
   Add JS diagnostic loader/guard; do not silently install a production interceptor.
5. Add pure tests with an independent import blocker proving no transitive Qt
   requirement. Mark real Qt smoke/schema tests needs_qt. Do not claim all old
   bridge tests are Qt-free: root conftest still optionally seeds Qt.

## Verification and risks

Run new seam tests, frozen bridge/undo/router contracts, RULE16 including clones,
Node schema tests and full coverage suite; compare known 70 baseline failures.
Measure coverage and mutation on extracted pure policies; do not lower historical
floors or refresh frozen API snapshots. Report any unmet gate explicitly.
Pasted defects to reconcile: missing HistoryBridge slots, omitted undo cleaning,
non-list stack rejection tuple mismatch, callback-arity mismatch, incomplete
schema. Archive integration adjustments and measured evidence, not copied claims.

Measured outcome: [verification report](../../../reports/AREA_B_TRANSFER_2026-09-19.md).
