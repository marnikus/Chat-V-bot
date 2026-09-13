# After round 4 — risk-ranked follow-up (2026-09-13)

Step 9 of `docs/archive/2026-09-12-refactor-round4/ROUND4_DESIGN.md`.
This is a fresh queue, not another production refactor. Steps 8–9 change only
quality tooling, tests and documentation. The completed sync family stays put.

## Measured debt, not the obsolete September 11 queue

`tools/metrics/current_audit.py` measures 155 production Python files, 1,933
functions and 206 classes. No function exceeds CC 10 or nesting 4. Only the
Qt router factory remains above cognitive 15 (17). There are 44 functions above
30 physical lines, 70 above four parameters, 36 classes above 150 lines and
26 above 15 direct methods. These counts include legacy/wire/JS constraints;
they are an inventory, not instructions to delete behavior or raise thresholds.

| Class | LOC | Direct methods | LCOM* | Ca / Ce of module |
|---|---:|---:|---:|---:|
| Collector | 518 | 39 | .929 | 3 / 7 |
| ScrollParser | 507 | 37 | .870 | 2 / 5 |
| HistoryBridge | 474 | 31 | .873 | 1 / 2 |
| UndoService | 460 | 30 | .918 | 3 / 7 |
| SchemaMigrator | 386 | 25 | .125 | 1 / 2 |
| PersonLifecycle | 370 | 19 | .056 | 1 / 2 |
| MediaFetcher | 342 | 18 | .294 | 1 / 3 |

LCOM* is a static field-sharing estimate, not a failure threshold. Qt signal
adapters and delegation can inflate it. Low-LCOM storage code is often cohesive
but safety-sensitive; splitting it because it is long can make it harder to
reason about transactions and file ownership.

Largest files: scroll_parser 674, db_deletion 665, history_query 606,
collector_service 593, undo_service 579, history_bridge 537, dom_highlight 523,
db_deletion_flow 509, config_manager 502, media_handler 478. Nine exceed 500
lines. Embedded JS is not a reason to split a single payload.

## New highest-priority correctness finding

**Collector currently violates the archive/queue ownership rule.**
RULE 14 says “no collector may add anyone to the queue.” Yet:

1. `services/collector_tick.py::CollectorArchive.open_person` invokes
   `Collector._remember_partner` before the author verification step.
2. `services/collector_service.py::_remember_partner` ensures archive metadata,
   then calls `memory.upsert_user(UserRecord(nick=clean))` for an unknown partner.
3. `tests/integration/services/test_services_collector_gaps.py::TestRememberPartner`
   explicitly expects the queue-add/notification behavior. It is established
   behavior, not a speculative inference from LOC or a newly introduced change.

This conflicts with SYSTEM_OF_RECORD invariant I-12 and RULE 14; the current
rules win over older collector designs. It can bypass the intended queue writer
and admission/filter path. No production fix or test-expectation rewrite is
bundled into this round. Creating empty `persons` metadata is not itself evidence
of message-gate bypass: RULE 15 specifically protects message writes.

**Next bounded correctness patch:** remove collector-driven queue admission,
retain archive ownership and legitimate archive notifications, and prove with
real world databases that an unknown or previously filtered-out partner does
not appear in `users`. Existing queue rows, messaged flags/counts, archive rows
and private-message gate behavior must remain correct. Update the historical
queue-add expectation explicitly as a behavior correction, not as “refactoring.”
Trace signal consumers before deciding which private return/status details change.

## Updated order

| Priority | Work | Why / boundary |
|---|---|---|
| P0 correctness | Collector queue ownership above | Confirmed rule/implementation conflict outranks another size extraction. |
| P0 enforcement | Activate hosted quality checks with an authorized maintainer | Local general gate is ready; inactive template is not branch protection. |
| P1 lifecycle | Collector heartbeat/task ownership | Stop/pause, slow CDP calls, exceptions, restart and DB-world changes interact; bound the first extraction below. |
| P2 correctness investigation | Push tasks versus close/world switch | CDP dispatcher schedules returned awaitables; heartbeat cancellation alone does not establish ownership of push tasks. Reproduce races before changing policy. |
| P2 cohesion | ScrollParser (507/37), then UndoService (460/30) | Virtual-scroll progress/filter-purge and global undo/persistence need characterization before moving shared state. |
| P2 adapter context | HistoryBridge (474/31) | Preserve named Qt slots, payload schemas and signal routing; avoid “one wrapper class per method.” |
| P3 constrained tails | Router cognition 17; typing/query length | Router's frozen slot factory has an existing wire constraint. Typing needs ordered fallback/read-back tests. Follow RULE 19 within each chosen target. |
| P3 safety storage | SchemaMigrator, PersonLifecycle, MediaFetcher, deletion | More cohesive and higher irreversible-I/O risk; take a real change request/differential safety proof, not a LOC quota. |

## First lifecycle slice — after the ownership correction

Characterize `Collector.start/stop/pause/resume/run`, `next_interval_ms` and
`note_probe_duration`, together with `services/history/runtime.py::CollectorRuntime`
start/stop/restart. This is the bounded heartbeat/cadence responsibility, not a
rewrite of all 39 methods or a second CollectorTick state machine.

Candidate ownership: one small `CollectorLoop` collaborator controls heartbeat
cadence and cooperative waits; Collector retains its existing public API,
compatibility state and Qt signals; CollectorRuntime alone owns service task
creation/cancellation/awaiting. Confirm this boundary against callers/tests before
implementation. Do not invent a parallel state copy or an abstract scheduler
framework just to obtain smaller classes.

Required characterization matrix:

* start, stop before/after task admission, repeated start/stop and restart;
* pause/resume, disabled/disconnected admission and no duplicate heartbeat task;
* idle/active cadence, throttle factor, slow-probe penalty clamping, stop while
  waiting and a tick exception followed by another tick;
* external cancellation, in-flight CDP operations and `_busy` cleanup;
* service close/swap awaits owned heartbeat completion before changing the DB;
* unchanged status/signal payloads, parser/store/lease seams and queue isolation.

Use events/barriers, not timing sleeps, to prove ordering. Do not assert a desired
new shutdown policy as if it were already implemented. Any discovered behavior
fix gets its own explicit decision and failing regression before extraction.
Target new classes <=120 LOC/10 methods where practical; hard caps stay 150/15,
functions 30, params 4, CC 10, cognitive 15, nesting 4. Legacy axes must not worsen.
A compatibility adapter is acceptable only because its existing API is required,
not to conceal unchanged large bodies elsewhere.

## Deferred evidence and hazards

The known unawaited `Collector.handle_push` warning comes from a test that calls
`_on_binding` directly and discards its coroutine. Production
`CDPClient._dispatch_event` does schedule awaitables; the warning is **not** proof
that production drops all push events. Separately investigate task tracking,
listener rebinding and world-swap admission before claiming shutdown safety.

Sync retains its existing in-flight operation and finalization/restoration
semantics. No “finally always writes cursor” or stop-wins-over-completed-chunk
policy was introduced. Real WebEngine/live Chrome remains unvalidated here.
Mutation configuration still targets untouched `backend/history_query.py`; no
changed-module mutation score is claimed. Do not keep padding the finished sync
package or revisit the cleared CC tail to avoid these actual next decisions.
