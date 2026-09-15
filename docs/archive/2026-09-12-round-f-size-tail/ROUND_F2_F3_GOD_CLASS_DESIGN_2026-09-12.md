# Round F steps F2 + F3 — decomposing the two remaining god classes

Date 2026-09-12 · branch `arena/01a09227-chat-v-bot` · base `95cb38b`
Companion to [`ROUND_F_DESIGN_2026-09-12.md`](ROUND_F_DESIGN_2026-09-12.md),
which prioritised the round and lists F2 and F3 as steps 2 and 3.

Both targets are named §16.5 landmines — "need a design doc before 'quickly
fixing'" — so this doc precedes the edits, per RULE 16 §16.6 step 2.

## 1. Targets, measured

| | F2 `Collector` | F3 `UndoService` |
|---|---|---|
| File | `services/collector_service.py` | `services/undo_service.py` |
| File lines / MI | 601 / 27.2 | 573 / 24.1 |
| Class span | 526 LOC | 418 LOC |
| Methods | **40** | 28 |
| Instance attributes | **34** | 16 |
| LCOM\* | **0.93** | **0.92** |
| Gate status | landmine | landmine |

Both are the incoherent kind of large, not the cohesive kind: LCOM\* ≈ 0.93 means
almost no two methods share a field. That is several responsibilities wearing one
class name, which is the case §18.2 says to decompose *by responsibility first*.
(Contrast the cohesive large classes — `SchemaMigrator` LCOM 0.13,
`PersonLifecycle` 0.06 — which only need extracting, not decomposing.)

`Collector` is the second-largest class in the project and has the most methods
of any class not behind the frozen AREA D snapshot.

## 2. The pattern is already in the repo, and already tested

This does not invent a decomposition style. `stores/history_repo.py` is a
44-method / 225-LOC facade over a `history_repo_*` family, and
`tests/unit/stores/test_stores_structure.py` *enforces* the shape:

> `test_a_collaborator_takes_the_aggregate_and_nothing_else` —
> `params[:2] == ["self", "owner"]`, because
> **"a collaborator is built from the aggregate only — state stays on the
> aggregate."**

and `test_the_facade_builds_each_collaborator_from_itself` — the facade's
`__init__` composes the parts, passing `self`.

That single rule resolves the main design tension in both targets.

### 2.1 Why state must stay on the aggregate here

The obvious alternative — move the 34 attributes into a state object — is
**blocked by the tests**, and the block is worth stating precisely because it
decides the design:

| Private attribute | test references |
|---|---:|
| `collector._nick` | 15 |
| `collector._added` | 7 |
| `collector._total` | 5 |
| `collector._verified` | 2 |
| `collector._last_sync_reason` | 2 |
| `collector._last_sync_count`, `._last_sync_added` | 1 each |

Roughly 33 assertions across `test_collector_state.py`,
`test_collector_tick_phases.py`, `test_services_collector_gaps.py`,
`test_private_gate.py`, `test_history_bridge.py` and `test_media_recovery_e2e.py`
read or set those attributes directly. Moving them would require editing all of
those tests **in the same commit as the refactor**, which is exactly how an
equivalence gate gets weakened — and F1 proved that gate is what catches real
defects (it caught the patch-transparency bug that 5 tests passed straight
through). So state stays put, behaviour moves. `UndoService` is poked far less
(`_archive` 3, `_undo_pendings` 2, `_timeline_commit`, `_seq_next`, `_people`),
and gets the same treatment for consistency.

### 2.2 What else is pinned

**F2 — `Collector`:**

* Four Qt signals must stay on the `QObject`: `status_changed`,
  `history_appended`, `people_changed`, `collector_log`. Collaborators emit them
  through `owner.<signal>.emit(...)`, which Qt permits from any object holding
  the reference.
* Constructed in exactly one place, `services/history/__init__.py:39`.
* Production callers use: `configure`, `settings`, `my_nick`, `enabled`, `state`,
  `state_payload`, `start`, `stop`, `pause`, `resume`, `run`, `tick`,
  `reset_state`, `person_cleared`, `handle_push`, `backfill_older`, plus the
  private `_nick` and `_last_sync_reason`.
* `services/collector_service.py` is in a `CLONE_BASELINE` group with
  `bridge/stack_bridge.py` (shared import header). Changing its imports may
  dissolve that group, which the gate reports as a **stale** entry that must then
  be deleted. Expected, and allowed: baseline groups "may disappear".

**F3 — `UndoService`:**

* `bridge/undo_bridge.py` holds the `@Slot` wire contract, so `UndoService`'s own
  method set is *not* frozen — the bridge is. That gives F3 more room than F2.
* Imported names that must keep resolving from `services.undo_service`:
  `UndoService` (bridge/context, bridge/router, 5 test files), `emit_db_change`
  and `restart_world` (bridge/db_bridge, test_world_events), and **`_values_equal`
  (bridge/router:154)**.
* `_values_equal` being imported cross-module while private is the same boundary
  smell F1 found in `db_deletion._append_db_files`. Recorded as **F3b**, not fixed
  inside the move, for the same reason: keep the refactor behaviour-preserving.
* `WriteTurn.held` (stores/world_lock.py) is one flag per connection, so two
  concurrent writers on one `HistoryDB` can desynchronise it from the gate's
  depth and leak the writer turn — the mechanism behind the flake settled in
  §8.10. Fixing it means a nesting count per task, which changes the boolean
  `turn.held` that `tests/test_world_write_gate.py` (817 lines) pins. Recorded as
  **F3c**, not bundled into the flake fix.
* `services/undo_service.py` is in a `CLONE_BASELINE` group with
  `services/history/query.py`; same stale-entry caveat as F2.

## 3. F2 decomposition — `Collector` → facade + 5 collaborators

Method-to-responsibility mapping came from an AST pass recording, per method, the
line span and exactly which instance attributes it touches. The clusters are
clean: five groups touch almost disjoint attribute sets, which *is* the LCOM 0.93.

| New module | Class | Methods moved | ≈LOC | Attributes it owns logically |
|---|---|---|---:|---|
| `services/collector_pacing.py` | `Pacing` | `note_probe_duration`, `next_interval_ms`, `on_run_started`, `on_run_finished` | 21 | `_throttled`, `_probe_penalty` |
| `services/collector_push.py` | `PushPath` | `_refuse`, `_gate_status`, `_push_ready`, `_gate_check`, `_append_push`, `_announce_push`, `handle_push` | 81 | `_verified` (gate), `_added`/`_total` (announce) |
| `services/collector_partner.py` | `PartnerMemory` | `_remember_partner`, `_notify_appended` | 59 | `memory`, `repo` |
| `services/collector_loop.py` | `RunLoop` | `run`, `tick`, `_tick`, `_sync`, `backfill_older` | 89 | `_stop_event`, `_busy`, `_running`, `_force_backfill`, `_backfill_pending` |
| `services/collector_view.py` | `StateView` | `state_payload`, `reset_state`, `_payload`, `_records`, `_notify_people`, `_no_new_text` | 100 | reads ~20 attributes, writes none but `_last_emitted` |

**Stays on `Collector`** (identity, configuration, lifecycle flags, and the two
shared emitters everything needs): `__init__`, `configure`, `settings`,
`my_nick`, `enabled`, `running`, `paused`, `state`, `start`, `stop`, `pause`,
`resume`, `person_cleared`, `_log`, `_set`, `_emit`.

`state_payload` (27 LOC, reads 20 attributes) is the single biggest LCOM
contributor — one method touching two-thirds of the state. Moving it to
`StateView` is the largest single cohesion win available.

Public names keep working through one-line delegators on the facade, so
`collector.tick()`, `collector.handle_push()`, `collector.state_payload()`,
`collector.run()` and `collector.backfill_older()` are unchanged for every
caller and every test.

Expected result: class 526 → **≈150 LOC** (at the gate's own `CLASS_LIMITS`
line), methods 40 → **≈26** (16 kept + ~10 delegators), file 601 → **≈270
lines**, inside RULE 18.2's 150–300 band.

### 3.1 Naming collisions to avoid

`Collector` already has a public `state()` method *and* a `_state` attribute, and
`CollectorState` is an existing constants class in the same file. So the
collaborator attributes are named to not shadow any of them: `_pacing`, `_push`,
`_partner`, `_loop`, `_view`. `LabelStore` hit the same problem and solved it the
same way (its four part-objects live on private names — see the comment in
`test_stores_structure.py`).

## 4. F3 decomposition — `UndoService` → facade + 4 collaborators

`undo_service.py` already extracted its pure helpers to module level
(`_values_equal`, `_same_entry`, `_position_of`, `emit_db_change`,
`restart_world`, `_apply_people_command`, `_apply_labels_command`,
`_log_command`) and already has an `undo_timeline.py` sibling. F3 continues that
direction rather than starting a new one.

| New module | Class / contents | Methods moved | ≈LOC |
|---|---|---|---:|
| `services/undo_db.py` | `DbCommands` | `_db_delete_op`, `_db_op_forward`, `_db_switch_op`, `_apply_db_command` | 68 |
| `services/undo_history.py` | `HistoryProjection` | `history`, `set_history`, `migrate_global_history`, `_migrated_entry`, `_history_entry`, `_next_seq`, `stack_projection`, `set_stack_projection`, `kind_projection`, `push_stack` | 61 |
| `services/undo_apply.py` | `ApplyCommand` + the command helpers `_values_equal`, `_same_entry`, `_position_of`, `_apply_people_command`, `_apply_labels_command`, `_log_command` | `apply_command`, `_apply_archive_command`, `_apply_entry`, `undo`, `redo`, `rewind_after_failure` | 128 + 45 |
| `services/undo_world.py` | `emit_db_change`, `restart_world`, `WorldSync` | `sync_world_state`, `_schedule_world_undo_save` | 49 + 31 |

**Stays on `UndoService`:** `__init__`, `attach`, `_log`, `push`,
`push_stack`-facing delegators, `_clean_blocks`, `_clean_history`, and the
re-exports existing importers rely on.

`services/undo_service.py` keeps re-exporting `emit_db_change`, `restart_world`
and `_values_equal` so that `bridge/db_bridge.py`, `bridge/router.py`,
`tests/unit/services/test_world_events.py` and `tests/test_world_write_gate.py`
are untouched. Both constants and re-exports live in the facade, and no
collaborator imports the facade, so there is no cycle — the same arrangement F1
used.

Expected result: class 418 → **≈190 LOC**, file 573 → **≈240 lines**.

## 5. Risks, and how each is checked rather than assumed

| Risk | Mitigation |
|---|---|
| A collaborator silently fails to reach state, as F1's re-export shim failed to be patch-transparent | State stays on the aggregate by rule (§2.1); collaborators receive `owner` and touch `owner._x` — the same attribute objects the tests poke |
| Signal emission from a non-`QObject` collaborator | Verified by probe before relying on it: `owner.status_changed.emit(...)` from a plain object. If Qt rejects it, `_emit`/`_log` stay on the facade and collaborators call `owner._emit(...)` |
| `async` methods moving between modules | Moved verbatim with `await owner.…` for anything left behind; the async call graph is not restructured |
| Tests that patch a method on `Collector`/`UndoService` stop reaching the moved body | Same trap as F1. Grep every `patch.object` / `mock.patch("services.…")` targeting these two modules **before** moving anything, and repoint to the owning module, never to an assertion |
| New files form a clone group on their import headers | Run `clone_scan.py` after; `MIN_SPAN = 6` and headers differ by their real import sets. If a group appears, baseline it with a recorded reason as F1 did — do not shrink spans cosmetically |
| A baseline clone group dissolves, becoming "stale" | Expected for both files; delete the stale entry, which the gate explicitly permits |

## 6. Dishonest reductions rejected

* **Moving the 34 attributes into a state object.** Would improve LCOM most, but
  requires editing ~33 assertions in the same commit as the refactor. Rejected:
  it spends the gate that caught F1's real defect. §2.1.
* **`Collector_part1.py` / `_part2.py`, or splitting by method count** to hit a
  number. Forbidden by §18.5; the five groups above are responsibilities with
  disjoint state, not arbitrary halves.
* **Turning the delegators into `__getattr__` magic.** Would shrink the facade
  further and hide the public surface from readers and tooling. Explicit
  one-line delegators are the `HistoryRepo` shape and stay greppable.
* **Making collaborators free functions instead of classes.** The tested
  convention is `__init__(self, owner)`; free functions would satisfy nothing in
  `test_stores_structure.py` and would diverge from the four existing families.
* **Fixing F3b (`_values_equal` imported privately by `bridge/router.py`) in the
  same commit.** Real smell, 1-line fix, but it is an API change inside a
  behaviour-preserving move. Deferred, exactly as F1 deferred `_append_db_files`.
* **Padding docstrings to lift MI.** Both files score MI 27.2 and 24.1 and will
  rise on their own once 350 and 250 lines of dense logic leave; comments go in
  only where §18.2 requires them (what the file owns, which way imports point).

## 7. Verification (per step, cheap gates first)

1. `radon cc -s` on every new and changed file — no block may reach C.
2. Undefined-name AST sweep per new module (this caught F1's missing
   `is_within` import before the suite did).
3. Probe: signals emittable from a collaborator; every public name still
   reachable on the facade; private attributes tests poke still present.
4. `rule16_gate.py --with-clones` — limits, ratchets, smells, clone baseline.
5. `clone_scan.py .` — compare against the baseline, add or delete entries with
   a recorded reason.
6. Targeted suites first (`test_collector_state`, `test_collector_tick_phases`,
   `test_private_gate`, `test_services_collector_gaps`, `test_services_undo`,
   `test_undo_support_contract`, `test_undo_wire`), then the **full suite with
   coverage** as the equivalence gate: must stay at 2,710 passed / 0 failed with
   line ≥ 90.42% and branch ≥ 86.30%.
7. Re-measure LCOM\*, class LOC/methods, file lines and MI, and record achieved
   against target in §8 — including anything missed, as F1 recorded its 0.41 MI
   shortfall rather than padding it away.

## 8. Outcome — F2 executed

`Collector` is decomposed. Achieved against every target in §3, including the
three that missed.

### 8.1 Numbers

| Measure | Before | Planned | Achieved | |
|---|---:|---:|---:|---|
| `Collector` class LOC | 526 | ≈150 | **239** | miss, see §8.3 |
| `Collector` methods | 40 | ≈26 | **40** | miss, deliberate, see §8.3 |
| `Collector` LCOM\* | 0.92 | down | **0.97** | miss, see §8.3 |
| `collector_service.py` lines | 601 | ≈270 | **281** | inside RULE 18.2's band |
| `collector_service.py` MI | 27.2 | up | **53.5** | +26.3, roughly doubled |
| files over 500 lines (repo) | 9 | 8 | **8** | F2 removes one |
| production files | 159 | — | **166** | +7 leaves |
| mean MI (repo) | 65.27 | — | **65.93** | +0.66 |
| production SLOC | 23,215 | — | **23,391** | +176, the cost of §8.3 |
| clone baseline groups | 12 | ≤12 | **12** | one dissolved, one added, §8.4 |

All measured with `tools/metrics/current_audit.py`, not by hand, so the before
and after columns come from the same instrument. `Collector` no longer appears
in the repo's six biggest classes at all; the list is now `ScrollParser` 532,
`HistoryBridge` 471, `UndoService` 418, `SchemaMigrator` 406, `PersonLifecycle`
374, `AppendPlanner` 340.

The +176 SLOC is not padding. It is 24 delegators, seven module docstrings
saying which way the imports point (§18.2 requires them), and six
`__init__(self, owner)` lines. That is the real price of a
backward-compatible facade, and it is why §8.3 reports the class-LOC target as
missed instead of claiming ≈150.

New modules, final: `collector_report.py` 154, `collector_push.py` 115,
`collector_partner.py` 104, `collector_loop.py` 69, `collector_states.py` 53,
`collector_pacing.py` 44, `collector_settings.py` 42. All are leaves in the
150–300 band or below it, which §18.2 calls normal and good for pure-data
modules and parts. Their MI runs 61.3–100.0 against the facade's old 27.2.

The cohesion win is in the parts, measured the same way as the aggregate:
`Reporter` 0.22, `PushPath` 0.14, `Pacing` / `PartnerMemory` / `TuningKnobs` /
`RunLoop` 0.00.

### 8.2 Deviations from the §3 plan, and why

* **Six collaborators, not five.** `services/collector_settings.py::TuningKnobs`
  was added (`configure`, `settings`). Without it the facade came to 322 lines —
  over the band — and RULE 18.2 says over 300 means go find the second
  responsibility rather than accept the number. Validating and coercing knobs
  against `DEFAULTS` and pushing chunk settings to the parser is that
  responsibility. This took the file to 292.
* **`StateView` became `Reporter`, and took `_log`/`_set`/`_emit`.** §3 left the
  three emitters on the facade. They are the outward-reporting plumbing, and
  leaving them behind would have split one responsibility across two files —
  `state_payload` describes exactly the state `_set`/`_emit` publish.
* **`_tick`, `_sync` and `backfill_older` did NOT move to `RunLoop`.** `_sync`
  stays because `test_collector_tick_phases.py:259` patches
  `services.collector_service.sync_conversation`; moving it makes that patch
  vacuous while the test still passes — the F1 trap, avoided rather than fixed
  after the fact. `_tick` stays as the existing seam into `collector_tick.py`.
  `backfill_older` stays because once `TuningKnobs` brought the file inside the
  band, moving it would only have stretched `RunLoop`'s "the loop and nothing
  else" responsibility for no gain.
* **`person_cleared` moved to `PartnerMemory`** (§3 left it on the facade). It is
  "forget this partner" — resetting that person's totals and reason — which is
  `PartnerMemory`'s job, not the supervisor's.
* **`services/collector_states.py` is new** (not in §3). `CollectorState`,
  `IDLE_STATES`, `DEFAULTS` and `MAX_PROBE_PENALTY` are pure data that the six
  parts and the pre-existing `collector_tick.py` all need. Giving them a leaf
  module means no part imports the facade and no part imports another part, so
  there is no cycle to work around. `collector_service.py` still re-exports
  `CollectorState` and `DEFAULTS` because `backend/collector.py` and
  `services/history/__init__.py` import them from there.

### 8.3 The three misses, stated plainly

The ≈150 LOC / ≈26 methods estimate assumed delegators were free. They are not:
24 one-line delegators cost ~72 lines, and keeping all 40 names is not
optional — `bridge/collector_bridge.py`, `services/history/{query,mutate,runtime,
export}.py` and instance-level patches in the tests all call them, and
`collector_tick.py` reaches 32 of them as `host.<name>`.

So the facade is measured against the repo's own decomposed facades rather than
against the estimate, since those are the accepted shape of this pattern:

| Facade | class LOC | methods | LCOM\* |
|---|---:|---:|---:|
| `HistoryRepo` | 225 | 44 | 0.89 |
| `HistoryDB` | 232 | 30 | 0.86 |
| `LabelStore` | 222 | 38 | 0.89 |
| `MediaStore` | 215 | 33 | 0.93 |
| `UserMemory` | 202 | 21 | 0.53 |
| **`Collector` (after F2)** | **239** | **40** | **0.97** |

`Collector` sits at the top of that range on methods and LCOM\* and just above
it on LOC (239 against `HistoryDB`'s 232) — inside the house shape, not outside
it.

The LCOM rise is structural, not a regression in cohesion. Henderson-Sellers
LCOM\* measures how many of a class's methods touch each attribute it owns. A
delegation shell still *owns* all 34 state attributes (they must stay — §2.1)
but its methods now touch each of them less, because the touching moved next
door. The metric penalises exactly the shape the house convention prescribes,
which is why four of the five accepted facades score 0.86–0.93. Per §18.5 this
is recorded rather than gamed: the fix would be to move state into the parts,
which would break the 32-name host protocol and ~30 test pokes.

Worth stating plainly, because the audit makes it obvious: LCOM\* on its own is
a poor god-class detector. The eight worst scores in this repo are all 1.0, and
they are 32–78 LOC dataclasses in `actions/` with two to six methods and no
shared state — `BlockField`, `MarkerBlock`, `ClickSend`, `ActionContext`. A
perfect 1.0 there means "a value object", not "a god class". `Collector` was
flagged in the Round F report on the *combination* (526 LOC, 40 methods, 0.93),
and it is the combination that improved: 239 LOC and the behaviour now sitting
in six parts at 0.00–0.22. The 0.97 is what a facade costs, and the same cost
is already paid and accepted four times over in `stores/`.


### 8.4 Two frozen contracts this touched

* **Clone baseline: one group dissolved, one appeared — net unchanged at 12.**
  Both halves were verified separately rather than assumed, and the gate
  enforces both directions (a vanished entry is reported *stale* and must be
  deleted; a new one is a breach).

  *Removed:* `('bridge/stack_bridge.py', 'services/collector_service.py')`. It
  was header noise — both files opened `from __future__ / asyncio / json /
  logging / datetime` — and moving the payload shaping to `collector_report.py`
  left the facade with no `json` use at all. pylint W0611 flagged the dead
  import, it was pruned, and the header shrank to four statements. The entry is
  deleted from `CLONE_BASELINE` with that reason recorded above it, which is
  what the gate's own message instructs.

  *Added:* `('services/collector_partner.py', 'services/collector_report.py')`,
  span 6 at line 9 of each: `from __future__ import annotations` / `import json`
  / `import logging` / `from typing import Optional`. §5 predicted the new
  modules would differ "by their real import sets" and that prediction was
  wrong: this group only appeared once both modules were given PEP8-grouped
  imports, because the generator's first pass sorted import statements
  alphabetically as text, which put `from typing import Optional` above `import
  json` and failed pylint C0411. Fixing the lint put the two headers in the same
  honest order every other module here uses, and they collided.

  It is baselined with a recorded reason, per §5's own instruction and the F1
  precedent, not dissolved cosmetically. Checked rather than assumed: `MIN_SPAN`
  is a **line** span (`chunk[-1].end_lineno - chunk[0].lineno + 1`), so four
  statements across six lines qualify; each of the four names is genuinely used
  in *both* files (`json.dumps` on the emitted payloads, `log.debug` in the
  emit-failure handlers, `Optional` on the `nick` parameter); and `vulture
  --min-confidence 90` reports no dead code in either module, so there is no
  unused import whose removal would legitimately dissolve the window. Reverting
  to the C0411-failing order to break the group would be the cosmetic
  span-shrinking §18.5 forbids.

  For completeness, the six collaborators' shared `def __init__(self, owner)`
  does *not* form a group: it spans two lines, under `MIN_SPAN`.

* **The `stores/` import pin stayed at 40 — no bump needed.** The first pass
  grew it to 43 and failed
  `test_stores_public_api.py::test_stores_imports_outside_the_package_are_untouched`.
  That pin counts textual `from stores…` lines across `services/`, `backend/`,
  `actions/`, `bridge/` and `app/`, and its own comment permits a bump only when
  "another area legitimately grows the surface". Duplicating an import the
  monolith already had does not grow any surface, so the count was brought back
  rather than bumped: two of the three new lines were **docstring-only
  mentions** (`HistoryRepo` and `UserMemory` appear in `collector_partner.py`'s
  prose, never in its code) — an artifact of resolving imports with a regex over
  text, fixed by resolving them from the AST's loaded names instead — and the
  facade's own `from stores.user_memory import UserMemory, UserRecord` became
  dead once `_remember_partner` moved, so it was pruned. Net: the collector
  family still has exactly the two `from stores` lines it started with.

### 8.5 Two bugs the gates caught, which the tests alone would not have

* **Every method of every generated collaborator was nested inside its
  `__init__`.** The extracted segments already carried their 4-space class-body
  indent and the emitter added 4 more. All modules imported cleanly and
  `hasattr(Collector, …)` passed for all 38 names, because the facade delegators
  existed and nothing had been instantiated yet. Only `pylint --enable=E`
  caught it, as 19 `E1101 no-member` errors. An import probe is not a structure
  probe.
* **`__init__` calls `self.configure(...)` mid-construction**, so wiring the six
  parts at the *end* of `__init__` raised `AttributeError: 'Collector' object
  has no attribute '_knobs'` and failed 148 tests. Constructing a part only
  stores `owner`, so the wiring is spliced in immediately after
  `super().__init__(parent)` — before anything delegated can be called.

### 8.6 New guard

`tests/unit/services/test_collector_structure.py` — 7 tests, 77 subtests,
mirroring `tests/unit/stores/test_stores_structure.py` for the two invariants
that convention already pins (the facade builds each part from `self`; a part
takes the aggregate and nothing else), plus three gates specific to this split:

* the host protocol is read **live** out of `collector_tick.py` — every
  `host.<name>` must resolve on `Collector` as a method/property or as state
  assigned in `__init__`, so the gate follows the protocol instead of freezing a
  copy of it;
* `_sync` must still call the module-level `sync_conversation`, and must not
  have become a delegator — the patch target stays live;
* every moved name must be a single `return` on the facade and real code in its
  part, so the split cannot be quietly undone one method at a time.

Negative-checked rather than assumed green: deleting the `_no_new_text`
delegator fails the host-protocol gate with `SUBFAILED(host='_no_new_text')`;
padding the file past 300 lines fails the size gate; re-inlining `configure`
fails the delegator gate with `SUBFAILED(name='configure')`. The facade is also
ratcheted at 300 lines (RULE 18.2's ceiling) and 239 class LOC (the F2
measurement) — it may shrink, it may not grow.


### 8.7 Equivalence evidence stronger than "the tests pass"

A green suite shows the split did not break what is tested; it does not show the
moved code is the *same* code. So the move was also proven at the AST level.
Each of the 27 moved methods was parsed out of the pre-extraction file and out
of its new collaborator, the collaborator copy was normalised by rewriting
`self._o` back to `self`, and the two executable bodies were compared as
`ast.dump()` trees — docstrings excluded, because prose is allowed to be
re-wrapped, and `async`/`def` kind and decorator set compared alongside.

Result: **27 identical, 0 differing.**

The same check was run over the facade from the other side. All 40 original
method names are still present, and they partition exactly as designed:

| Kind | Count | Names |
|---|---:|---|
| thin delegator to a part | 27 | one per moved method |
| kept `@property` | 5 | `my_nick`, `enabled`, `running`, `paused`, `state` |
| kept real body | 8 | `__init__`, `_sync`, `_tick`, `backfill_older`, `start`, `stop`, `pause`, `resume` |

For every delegator, the parameter list is byte-identical to the original
signature (so `inspect.signature` and every keyword caller are unaffected), the
arguments forwarded are exactly its own parameters, and `async` parity holds.

Two consequences worth keeping: the five line-wraps done by hand after the move
(§8.4) changed formatting only — the AST comparison was run *after* them and
still reported zero differences — and `_sync` is confirmed present as a real
body, not a delegator, which is what keeps the
`services.collector_service.sync_conversation` patch biting.

## 8.8 RULE 16 and RULE 18 recheck

Measured, not assumed. Every function in the nine-file family (99 of them) was
re-measured with radon CC, `cognitive_complexity`, the gate's own nesting
function and a parameter count that excludes `self`/`cls`, as §16.1 requires.

### §16.7 acceptance checklist

| Item | Result |
|---|---|
| No new function > 30 physical LOC | ✅ none new; one pre-existing offender grew, see below |
| No new class > 150 LOC or > 15 methods | ✅ largest is `Reporter` at 136 / 10 |
| No new function with > 4 params (excl. `self`/`cls`) | ✅ widest delegator is `_notify_appended` at exactly 4 |
| radon CC ≤ 10, cognitive ≤ 15, nesting ≤ 4 | ⚠️ CC max **9**, cognitive max **12** — clean; nesting **one** breach, `configure` at 5, relocated verbatim |
| Line coverage ≥ 80% and not below baseline; branch ≥ 75% | ✅ line **91.49%** (14,033/15,339) vs 90.41%; branch **86.31%** (3,223/3,734) vs 86.30% |
| Every new function has a test that would fail if deleted | ✅ moved bodies keep 79.7–100% per-module coverage; the seven structure tests were negative-checked in §8.6 |
| No new vulture unused-import findings; no new duplication groups | ✅ `vulture --min-confidence 90` silent on all eight files; gate reports **0 new** clone groups |
| Quality-override comments used only with a real constraint | ✅ none used — `OVERRIDES` is keyed to `OWNED`, which covers only the sortable-columns feature, so it is not the mechanism available here |
| Did not game metrics with dummy helpers | ✅ §8.3 records an LCOM *increase*; §8.4 baselines a clone group instead of re-ordering imports to dissolve it |
| New code aims at the RULE 18 ideals | ✅ see below |
| Remediation followed the RULE 19 order | ✅ see below |
| SYSTEM_OF_RECORD.md + docs updated | ✅ `AGENT_RULES.md` §18.2 and §18.3 measured notes updated in the same commit |

### §16.5 deviation, recorded: `Collector.__init__` grew 40 → 51 LOC

§16.5 forbids increasing the LOC of a legacy offender, and `__init__` was
already over the 30-line limit at 40. It grew by 11: six `self._x = X(self)`
constructions, three comment lines, two blank separators. The comment was cut
from four lines to three for exactly this reason. It stays because "built
first, because `__init__` calls the delegated `configure()`" is a constraint a
future reader would otherwise break by moving the wiring down — the
148-test failure in §8.5 is what that looks like.

The six constructions cannot be avoided or compressed. Both
`tests/unit/stores/test_stores_structure.py` and the new
`test_collector_structure.py` assert, by regex over `__init__`'s own source,
that each part is built from `self` *inside* `__init__`; a factory function or a
lazy property would fail the house convention's own test. One line per part is
the minimum, and `__getattr__` magic is rejected in §6.

The rest of the 51 lines is ~30 attribute assignments that §2.1 requires to
stay on the aggregate, plus 8 parameters that are the frozen construction
contract (`services/history/__init__.py:39` and the tests both call it). So the
growth is the price of the convention, it is bounded at +11, and it is recorded
here rather than offset by chaining assignments (`self._added = self._total =
0`), which would be gaming §18.5 to buy back a number.

### Relocated pre-existing breaches — five, none created by F2

| Function | Breach | Status |
|---|---|---|
| `Collector.__init__` | LOC 51 (>30), 8 params (>4) | pre-existing offender, +11 LOC, see above |
| `PartnerMemory._remember_partner` | LOC 35 (>30) | verbatim from `Collector`, AST-identical (§8.7) |
| `TuningKnobs.configure` | nesting 5 (>4) | verbatim, AST-identical |
| `collector_tick.maybe_rename` | 6 params (>4) | file untouched by F2 |
| `collector_tick.cursor_check` | 6 params (>4) | file untouched by F2 |

Recorded so the next reader knows these were carried, not created. Two of them
improved in *fixability*: `configure` and `_remember_partner` now sit in a 42-
and a 104-line file, where reducing nesting or length is a small local change
instead of an edit to a §16.5 landmine.

### RULE 19 order respected

F2 is a size-and-cohesion remediation and RULE 19 puts size last, so complexity
was measured on the original `Collector` first and none of it was the binding
problem: worst CC 9 against a limit of 10, worst cognitive 12 against 15, one
nesting breach at 5. The binding problems were the two §16.5/§18.2 measures —
526 class LOC, and LCOM 0.93 driven substantially by one method
(`state_payload`) reading 20 attributes. Size was addressed last, and the single
nesting breach was relocated verbatim rather than fixed in the same commit, the
same way §6 defers F3b: a behaviour-preserving move should not also be a
behaviour-adjacent rewrite.

### RULE 18.2 and 18.3

* **Files.** The facade and all seven new modules are ≤ 300 lines. Six are under
  150, which §18.2 calls normal and good for leaves and pure-data modules
  (`collector_states.py` at 53 is pure data). Every one has a docstring naming
  what it owns and which way its imports go, which is the sentence §18.2 says
  keeps a split from rotting back into a monolith: no part imports the facade,
  no part imports another part, and all of them import `collector_states`.
* **Modules.** The `collector_*` prefix family is now **9 files**, inside
  §18.3's 5–15 band, and passes its cohesion test — the nine share the
  `CollectorState` vocabulary and the host protocol, and change together.
* **One deviation left in the family, deliberately: `collector_tick.py` at 425
  lines**, over §18.2's 300 ceiling. It predates F2 and was not touched by it.
  It holds `CollectorProbe` (123 LOC), `CollectorArchive` (185 LOC) and
  `CollectorTick` (33 LOC) plus four dataclasses, so it has a real second and
  third responsibility and would split naturally into probe and archive modules.
  F2 did not do that: the file has 98% line coverage and its own suite
  (`test_collector_tick_phases.py`), it sits next to a §16.5 landmine, and §16.6
  wants a design doc before decomposing a hotspot. It is recorded here as the
  next candidate in this family instead of being papered over with an
  `ideal-size:` comment — §18.5 requires that comment to name a *constraint*,
  and there is none to name here, only scope.

### 8.9 One intermittent failure, recorded rather than waved away

`tests/test_db_switch_restart.py::TestUndoNeverCrossesAWorldSwitch::test_world_undo_is_invisible_from_the_other_world`
failed in two of five full-suite runs during F2 execution and passed in three.
It is not left unmentioned, because "the suite is green" would otherwise be
true only of the runs I chose to quote.

What is known:

| Run | Result | Conditions |
|---|---|---|
| A | 1 failed — `test_stores_imports_outside_the_package_are_untouched` | the real §8.4 pin breach, since fixed |
| B | 2717 passed | quiet |
| C | 1 failed — the undo test | **explained**: the extraction script was re-run mid-suite and briefly wrote a syntactically invalid `collector_service.py` (the `wrap_def` comma bug, §8.5), so modules imported late in the run were broken |
| D | 1 failed — the undo test | quiet, no concurrent edits; no traceback captured (the command piped through `tail`) |
| E, F, G | 2717 passed each | quiet, full output saved |

Baseline (HEAD `95cb38b`, pre-F2, in a separate worktree): one quiet full run,
**2707 passed / 0 failed**; a second run under concurrent load was killed at 62%
by a sandbox disconnect, so it is not evidence either way.

The test passes 8/8 in isolation and 41/41 when run directly after the collector
suites. It is timing-sensitive by construction: `drain_world_undo()` polls
300 × 10 ms for `_undo_pendings` to clear, and `bridge_load()` waits on a Qt
signal. F2 changes nothing in that path except that constructing a `Collector`
now also builds six small objects — and all 27 moved bodies are AST-identical
(§8.7), so there is no candidate mechanism in the diff.

The honest conclusion: run C is explained, run D is a single unexplained
occurrence against three clean passes, and the balance of evidence points at a
pre-existing timing fragility rather than an F2 regression — but it is **not
proven**, because the one failure that would have settled it did not have its
traceback captured. Two things follow from that:

* any future full run should redirect output to a file with `--tb=long -rf`
  instead of piping through `tail`, so a failure is diagnosable after the fact;
* this test sits in **F3's** domain (`UndoService`, world switching, the undo
  timeline). F3 will touch exactly this code, so the flake must be settled there
  — capture the assertion, and if it reproduces on a pre-F3 baseline, fix the
  test's timing rather than the code under test.

**Settled in §8.10 — and the prediction above was wrong.** It was not test
timing and not pre-existing fragility in the test: it was a product bug, a
leaked world write gate, and the fix is in `services/undo_support.py`.

### 8.10 Settled: the flake was a leaked write gate, not test timing

**Reproduction.** Sequential full-suite runs are a poor sampler — one sample of
this test per five minutes. Three clean runs (2717 passed each) produced
nothing, so the test was run repeatedly inside ONE process instead: the
condition a long suite creates (accumulated module state, asyncio churn, Qt
allocation, GC pressure) sampled every few seconds. It failed **3 times in 37
iterations (~8%)**, always with the same traceback:

```
tests/test_db_switch_restart.py:291  await self.bridge_load(self.db_path)
tests/test_db_switch_restart.py:266  self.assertTrue(self.changes, "a world switch must signal the UI")
AssertionError: [] is not true
```

Always the third switch, always `changes == []`: `db_changed` never arrived
inside the test's 300 × 10 ms budget.

**Diagnosis, in four probes, each ruling out a guess.**

| Probe | Finding |
|---|---|
| pending tasks at the timeout | `DbBridge._run_async.<locals>.guarded` still running, plus a task parked in `Lock.acquire`. `_undo_pendings` was empty, so there was nothing to settle — the wait was not the test's `drain_world_undo` |
| the gate table (`stores/world_lock._GATES`) | `history.db depth=1 locked=True waiters=1 holder=HistoryDB@36624 is_open=False` — a **closed** connection still holding the world's writer turn, plus three more gates leaked by earlier iterations |
| `WAIT_S` | 15.0. The gate deliberately fails **open** after 15 s; the test waits 3 s. The switch was never lost, only late |
| an enter/leave journal with call stacks | the unmatched enter, below |

The journal is the proof. For one token on `history.db`:

```
LEAVE depth=1->0  commit     mutate.py:294 _write_world_undo
LEAVE depth=0->0  commit     mutate.py:294 _write_world_undo   <- a second, concurrent save
ENTER depth=1     execute    mutate.py:288 _write_world_undo
ENTER depth=2     executemany mutate.py:289                    <- re-entered: `held` was already clear
LEAVE depth=2->1  commit     mutate.py:294                     <- never returns to 0
```

ENTER and LEAVE counts balance (23/23) while depth ends at 1 — one LEAVE was a
no-op and one ENTER was extra. An earlier probe had already ruled out the
obvious suspect: `_closed()`'s unguarded `turn.drop()` after `await
conn.close()`, which never raised in 61 iterations.

**Root cause.** `UndoWorldStore.schedule_save` appended a task per save, so two
saves could be in flight on ONE connection — routine, because a push during a
switch schedules a second save before the first lands. Two consequences:

* `save_world_undo` is DELETE-all-then-INSERT-all, so overlapping saves can
  leave the table holding half of one timeline and half of another;
* `WriteTurn` tracks "held" with a **single flag per connection**. The first
  save's `commit()` cleared it while the second was still between statements, so
  the second re-entered the gate (depth 1→2) and its own commit decremented only
  once. The turn stayed held for good, owned by a connection already closed.

Every later writer on that file then waited `WAIT_S` (15 s) and **failed open** —
writing without the exclusion the gate exists to provide. That is the exact bug
class the gate was added for (2026-09-11: a Ctrl+Z reported success while the
person stayed deleted), reintroduced by a leak rather than by absence.

So the test's 3 s budget being shorter than the product's documented 15 s
fail-open is *why this looked like a flaky test* rather than a 15 s stall.
Raising the timeout — the fix §8.9 predicted — would have hidden a real defect
and left write exclusion silently off.

**Fix.** `schedule_save` queues instead of starting a second save: newest
timeline wins, the one task in flight picks it up before finishing, and
`settle()` still waits for it because the task it gathers is the task that
performs the write. There is no `await` between the queue check and the task
ending, so nothing can be queued into a gap.

**Negative check.** `test_two_saves_never_share_the_connection`
(`tests/integration/services/test_undo_support_contract.py`) fails on the
pre-fix file with `AssertionError: 2 != 1 : two saves must never be in flight on
one connection`, and passes with the fix.

**Result.** **0 failures in 200** in-process iterations after the fix (was 3/37);
at the pre-fix rate P(0 in 200) ≈ 5×10⁻⁸. Full suite **2718 passed / 0 failed**
(2717 + the new test), 854 subtests. Line coverage 91.50% (was 91.49%), branch
86.36% (was 86.31%). RULE 16 gate rc=0; clone scan 0 new / 0 stale. The pylint
message profile of both changed files is identical to HEAD's (no new messages)
and vulture's findings are a subset of HEAD's.

**Residual risk, deliberately not fixed here.** `WriteTurn.held` is still one
flag per connection, so *any* two concurrent writers on one `HistoryDB` — a gaze
save against a collector append, say — can desynchronise it from the gate's
depth the same way. Removing the undo-save overlap removes the only source this
evidence shows actually occurring. Fixing `WriteTurn` properly means a nesting
count per task, which changes an 817-line pinned contract
(`tests/test_world_write_gate.py` asserts `turn.held` as a boolean), so it is
recorded as **F3c** instead of being bundled into a flake fix.
**RESOLVED 2026-09-13 — fixed as Round G step G1**: `WriteTurn` now holds the
gate for the union of a *set of writer tasks* (a per-task count would leak,
because `_gated` begins per statement but ends per commit), `held` became a
property so the two boolean pins above read unchanged, and six tests in
`TestWriteTurnUnion` pin the union — three of them fail against the pre-fix
flag version. The design, the rejected variants and the measurements are in
docs/archive/2026-09-13-round-g-write-gate/ROUND_G_DESIGN_2026-09-13.md §5.

### 8.11 F3 executed — `UndoService` → facade + 4 collaborators

Same method as F2 and the same rule that made F2 safe: state stays on the
aggregate, a part takes `owner` and nothing else, every name stays reachable on
the facade, and the move is *proven* rather than assumed from a green suite.

#### 8.11.1 Numbers

| | §4 target | achieved |
|---|---|---|
| `services/undo_service.py` | ≈240 lines | **241** (was 573) |
| `UndoService` class | ≈190 LOC | **179** LOC / 28 methods (was 418 / 29) |
| facade MI | up from 24.1 | **56.25**, grade A (was 24.08) |
| `undo_history.py` · `HistoryProjection` | ≈61 | **109 lines**, 77 LOC, 10 methods |
| `undo_apply.py` · `ApplyCommand` + 6 helpers | ≈128 + 45 | **241 lines**, 143 LOC, 7 methods |
| `undo_db.py` · `DbCommands` | ≈68 | **101 lines**, 77 LOC, 5 methods |
| `undo_world.py` · `WorldSync` + 2 module funcs | ≈49 + 31 | **126 lines**, 42 LOC, 3 methods |

Repo-wide, measured on F2's basis (product `.py`, excluding `tests/` and
`tools/`), HEAD being `0b61302`:

| | HEAD | after F3 |
|---|---|---|
| files | 166 | **170** |
| median lines | 137 | **134** |
| files over 500 lines | 8 | **7** |
| SLOC (non-blank) | 24,442 | **24,624** (+182) |
| mean MI | 65.95 | **66.11** |

The HEAD column reproduces F2's recorded 166 / 137 / 8 exactly, which is the
check that the two steps are being measured the same way. Its mean MI reads
65.95 rather than the 65.93 F2 recorded because the flake fix `0b61302` touched
`services/undo_support.py` in between; the median *fell* (137 → 134) because all
four new modules sit between 101 and 241 lines.

Suite and gates: **2726 passed / 0 failed / 894 subtests** (was 2718 / 854 — the
+8 tests and +40 subtests are the new guard, no behaviour test was added or
removed). Line coverage **91.51%** (14,114/15,423) against a 91.50% baseline;
branch **86.36%** (3,228/3,738) against 86.36%. `rule16_gate.py --with-clones`
rc=0 with 0 new and 0 stale clone groups. `vulture --min-confidence 90` is
silent on all five files.

#### 8.11.2 LCOM\*, and why the parts' score means nothing

Under the convention this doc has used throughout — Henderson-Sellers over every
`self.X` a class references, which is the variant that yields the "34
attributes" F2 §6 quotes — the facade reads:

| | methods | attributes | LCOM\* |
|---|---|---|---|
| HEAD `UndoService` | 28 | 35 | **0.9323** |
| F3 `UndoService` | 28 | 25 | **0.9541** |
| each of the four parts | 3–10 | **1** | 0.0000 |

The facade's rise is the same structural effect F2 §8.3 recorded and not a loss
of cohesion: a delegation shell references every attribute it forwards plus the
four part handles, while each attribute is now touched by *fewer* methods
because the methods that touched it moved out together.

The parts' 0.0000 is **degenerate, and reporting it as "perfect cohesion" would
be a lie**. Each part owns exactly one attribute, `_o`; with a single attribute
every method touches it and the formula returns 0 by construction, whatever the
code does. The parts' cohesion argument is the responsibility split and the
disjointness of their method groups — the timeline and its projections, applying
one entry, reversing a DB-connection entry, rebuilding after a world change —
not the metric. This is F2's "LCOM\* on its own is a poor god-class detector"
finding again, now with a concrete failure mode named: **the metric saturates at
0 for any collaborator built on the `owner` convention this repo uses**, so it
cannot be used to compare a facade with its parts.

#### 8.11.3 Deviations from the §4 plan

1. **`_history_entry` stayed on the facade**; §4 listed it among
   `HistoryProjection`'s ten moves, so nine moved. Three concrete reasons, all
   found by grep before the move rather than by a red suite afterwards:
   `bridge/router.py:159` does `ns["_history_entry"] =
   staticmethod(UndoService._history_entry)`, pulling it off the *class* by
   attribute; `router.py:456` calls `ctx.undo._history_entry(kind, value)`; and
   `undo_service.py:93` constructs the pre-existing
   `UndoProjection(self._history_entry)` from the **bound** method inside
   `__init__`, so it must exist on the facade before any part is built.
   `HistoryProjection` reaches it as `self._o._history_entry` at two call sites.
2. **§4's method counts excluded `__init__`.** Each part has one, so the achieved
   counts read 10 / 7 / 5 / 3 against the planned 10 / 6 / 4 / 2.
3. **`undo_apply.py` landed at 241 lines against ≈173 planned, and
   `undo_world.py` at 126 against ≈80.** Composition measured rather than
   guessed: `undo_apply.py` is 158 code + 45 docstring + 32 blank + 6 comment;
   `undo_world.py` is 78 + 29 + 17 + 2. §4's estimates were code-shaped and did
   not carry §18.2's required module docstring (what the file owns, which way
   its imports point). Both files stay inside §18.2's 150–300 band and no logic
   was padded to fill it. `undo_db.py` (101) and `undo_history.py` (109) are
   *under* 150, which §18.2 allows for a single-responsibility leaf; growing
   them to the band floor would have been the dishonest reduction.
4. **`__init__` grew 19 → 24 LOC**, a §16.5 deviation on a legacy offender
   (`__init__` was already over at 8 params). The growth is four part
   constructions plus one comment line and is irreducible — the facade has to
   build its parts somewhere — and the comment was cut from three lines to one
   for exactly that reason, the same move F2 made cutting `Collector.__init__`'s
   comment. `__init__`'s param count is unchanged at 8.
5. **A docstring made `push` a new offender, and was removed.** The first draft
   added five lines to `push`'s docstring explaining why the body must stay in
   this module. `push` was 30 physical LOC — exactly at the limit, not over —
   and became **35**, a new >30 violation. The note duplicated the module
   docstring, which already says it (lines 21–24), so it was deleted and `push`
   is now byte-identical to HEAD. Recorded rather than left silent because
   moving prose to satisfy a physical-LOC count is precisely what §18.5 watches
   for: here it was *also* the better placement on the merits (why a body lives
   in a module is a module-level fact, not an implementation detail of `push`),
   and it restored exact equivalence for all five retained bodies. Had the note
   been load-bearing and unique, the honest outcome would have been to keep it
   and record a §16.5 deviation, as item 4 does.

#### 8.11.4 The misses, stated plainly

* **LCOM\* rose** 0.9323 → 0.9541 on the facade (§8.11.2), and the parts' score
  is meaningless rather than good.
* **The pylint message profile got worse in three counts.** Family (5 files)
  against HEAD's single file, `--disable=E0611` for the PySide6 stub
  false-positive, message types rather than a score:

  | message | HEAD | F3 family | why |
  |---|---|---|---|
  | `protected-access` | 9 | **91** | every `self._x` in a moved body became `self._o._x` |
  | `missing-function-docstring` | 5 | **17** | the 12 *public* delegators carry no docstring; pylint exempts `_`-prefixed names, so the 9 private ones do not count |
  | `too-few-public-methods` | 0 | **2** | two of the four part classes |
  | `unused-import` | 2 | **0** | improved — the re-exports are named in `__all__` |
  | `broad-exception-caught` | 4 | 4 | unchanged |
  | `too-many-arguments` / `-positional-` | 3 / 3 | 3 / 3 | unchanged |
  | `unused-argument`, `too-many-instance-attributes`, `superfluous-parens`, `import-outside-toplevel` | 1 each | 1 each | unchanged |

  **No complexity message moved at all**, which is what a pure move should look
  like: the three increases are the structural cost of the delegation pattern,
  not of new logic. F2's already-accepted parts carry the same shape (72
  `protected-access` across three `collector_*` modules), so this is the house
  pattern's known price rather than a regression F3 introduced. Delegator
  docstrings were *not* added to buy the count back: 12 one-line "forwards to X"
  docstrings would be noise the module docstring already covers.
* **Net size grew**: +182 SLOC and +4 files, to take one file off the >500 list
  and lift its MI from 24.08 to 56.25. The same trade F2 made, and the reason
  §18.2 measures a band rather than a total.
* **`services/undo_db.py` is 45.68% covered** — see §8.11.8, which treats it as
  the finding it is rather than as a rounding error.

#### 8.11.5 The five frozen contracts this touched

Each was found by grep *before* the move, and each is now an assertion in the
guard rather than a comment:

1. **`push` must stay a real body in `services/undo_service.py`.**
   `tests/test_world_write_gate.py:709-738` monkeypatches the module global
   `undo_service.MAX_STACK_HISTORY` to shrink the cap; `push` is its only
   reader. Moving `push` would leave that patch silently vacuous with the test
   still green — the exact trap F1 fell into with the re-export shim (§8.1) and
   the same shape as F2's `_sync`.
2. **`emit_db_change`, `restart_world` and `_values_equal` are re-exported** with
   `__all__`, and the guard asserts they are the **same objects** (`assertIs`),
   not copies. `tests/unit/bridge_safety/test_bridge_results.py` patches
   `bridge.db_bridge.restart_world`, so a re-definition in the facade would
   break it while a re-export does not.
3. **`UndoService.push` is patched on the class** at
   `tests/unit/bridge_safety/test_undo_wire.py:259`, so it has to remain a real
   method on the facade, not a delegator.
4. **`svc.push_stack` is patched on the instance**, which a delegator survives —
   instance patches resolve through the instance, so this one needed no special
   handling and is recorded to show the two cases were distinguished rather than
   treated alike.
5. **`bridge/router.py:159` pulls `staticmethod(UndoService._history_entry)` off
   the class** (§8.11.3 item 1).

#### 8.11.6 New guard, and the hole the negative check found in it

`tests/unit/services/test_undo_structure.py` — **8 tests, 40 subtests**:

1. every collaborator module exists and exports its public class;
2. the facade's `__init__` builds each part from `self`;
3. each part's `__init__` takes `(self, owner)` and nothing else;
4. the 21 moved names are **bare one-statement delegators**, with async-ness
   matching the target (a delegator that quietly became `async` or quietly
   stopped being `async` would change the call graph);
5. `push` is still a real body and still resolves `MAX_STACK_HISTORY` in *this*
   module;
6. the three re-exports are identical objects;
7. **no collaborator imports the facade** (cycle guard);
8. the facade stays inside the size band — ≤300 lines (the §18.2 ceiling, left
   loose so prose can still be added) and ≤**179** class LOC, ratcheted at the
   measured value rather than the planned one. Docstrings inside the class count
   against the 179 deliberately; §8.11.3 item 5 is what happens otherwise.

The cycle guard had a hole, and the negative check found it rather than a
reading of the code: it collected module names from `import X` and
`from X import Y` but not from the `from services import undo_world` form, so a
part written that way would have passed a gate whose whole job is to fail. Fixed
by expanding dotted aliases into the checked set before the assertion.

**Negative check** (`/home/user/f3_negative.py`, mutation-based, restores the
tree and re-verifies the baseline afterwards): **5 of 5 mutations caught**, each
failing with the culprit named — delete a delegator; re-inline `history`'s logic
into the facade; turn `push` into a delegator (loses the `MAX_STACK_HISTORY`
patch target); shadow `restart_world` with a local copy instead of re-exporting
it; make a collaborator import the facade.

#### 8.11.7 Equivalence evidence stronger than "the tests pass"

* **AST comparison, HEAD against the family: all 21 moved methods and all 8
  module-level functions are AST-identical** after normalising `self._o` back to
  `self`. No body was edited during the move (`/home/user/f3_verify.py`).
* **Method count 28 before → 28 after**; nothing lost, nothing added, no name
  quietly renamed. The gate's own class counter reads 29 → 28 for the very same
  fact, because `classes()` walks nested defs as well: `_apply_db_command`'s
  inner `async def work()` moved to `undo_db.py` with its method, so the facade
  no longer contains a nested function. Recorded so that a future reader does not
  mistake the counter's drop for a vanished method.
* **The five bodies that stayed are byte-identical line-for-line to HEAD**:
  `push` (30 lines), `attach` (16), `_clean_history` (5), `_clean_blocks` (3),
  `_history_entry` (2). Only `__init__` differs, by the four constructions and
  one comment (§8.11.3 item 4).
* Every delegator was AST-shape-checked as a single forwarding statement, so no
  logic can hide in the facade between the delegators.
* No behaviour test was added, removed or edited — the suite delta is exactly the
  new guard's 8 tests / 40 subtests. With bodies AST-identical and the test set
  a strict superset of HEAD's, per-body coverage can only be ≥ HEAD's.
* Full suite as the equivalence gate: 2726 passed / 0 failed / 894 subtests,
  line 91.51%, branch 86.36%.

#### 8.11.8 A finding F3 exposed: the DB delete undo/redo path has no test

Per-module coverage of the family: `undo_service.py` 91.93%, `undo_apply.py`
87.82%, `undo_history.py` 85.71%, `undo_world.py` 84.34%, **`undo_db.py`
45.68%** (29/55 statements).

This is **not** coverage F3 lost. All four bodies are AST-identical to HEAD's, no
test was touched, and nothing outside the method bodies is uncovered — the same
statements were equally uncovered inside the 573-line file, where they were
diluted below visibility by the other 500 lines scoring 92%. Splitting the file
made an existing gap measurable, which is the useful direction of that trade.

What is actually untested, line by line:

| body | uncovered | what it means |
|---|---|---|
| `_db_delete_op` | **37–49, the entire body** | both halves of DB-delete undo/redo: the forward re-delete (including the "nothing to re-delete, the file is already gone" warning) and the reverse restore-from-backup (including the "database deletions are permanent, no backup exists" warning) |
| `_db_op_forward` | **53–57, the entire body** | the re-do half of `create` / `load` / `clean`, and the unknown-op `None` |
| `_apply_db_command` | 83–91, 94 | the `op == "delete"` branch end-to-end (`restart_world` on success, `emit_db_change`, the `None` early return) and the unknown-op early return. The *switch* branch (92, 95–99) **is** covered |

So the DB-connection **delete** path — the one half of the DB-undo-restore
feature that destroys and restores a world file — is exercised by no test at any
level, while its sibling switch path is. F3 deliberately did not write those
tests: adding behaviour tests inside a behaviour-preservation commit spends the
equivalence evidence that makes the move trustworthy (§8.11.7), which is the
same scope discipline F1 applied to `_append_db_files` and F2 to `_sync`. It is
recorded here as the next named target, and it is cheap — 26 statements, four
call paths, and `tests/integration/services/test_undo_support_contract.py`
already builds the fixture shape they need.

**Corrected by F3d, on the record.** Two things above were wrong, and writing the
tests is what showed it:

* **The framing.** This is *not* "the half of the ported DB-undo-restore feature
  that destroys and restores a world file". `bridge/db_bridge.py` guards its only
  `dbconn` push with `if op != "delete"`, so **no current product path records a
  delete entry at all** — D4 makes a world delete permanent, and
  `test_db_manager.py::test_a_delete_is_not_an_undo_step` already pinned that. The
  delete branch is reachable *only* from an entry a previous version persisted
  into a world's `undo_history` table, which `sync_world_state` merges into the
  live timeline untouched. That is what `_apply_db_command`'s own docstring means
  by "legacy entries" — a phrase that was in the code all along and that a
  coverage number alone did not force anyone to read.
* **The count.** "26 statements, four call paths" described the delete half only.
  Closing the module also needed `_db_switch_op`'s forward branch, which nothing
  re-did either, and which was the file's last uncovered line.

The gap was real and worth closing; the *reason* it was uncovered was not the one
§8.11.8 guessed. §8.12 records what was written and what it found.

#### 8.11.9 RULE 16 and RULE 18 recheck

Every function in the five-file family (61 of them) re-measured with the gate's
own `measure_function`, `nesting`, `params` and `classes`, not with a separate
tool that might disagree.

| | HEAD | F3 family |
|---|---|---|
| function-level violations | 3 | **3** |
| class-level violations | 1 | **1** |
| max CC | 9 | **9** (`ApplyCommand.undo`) |
| max cognitive | 14 | **14** (`DbCommands._apply_db_command`) |
| max nesting | 3 | **3** (`ApplyCommand._apply_entry`) |
| max params | 8 | **8** (`UndoService.__init__`) |
| max function LOC | 32 | **32** (`restart_world`) |

The four remaining violations are the *same four* HEAD had, none of them new:
`UndoService` at 179 LOC / 28 methods (was 418 / 29 — improved, still over both
caps because a facade that keeps 28 names is over 15 by construction);
`__init__` at 8 params; `attach` at 7 params; `restart_world` at 32 LOC / 6
params, relocated verbatim. §16.5's "never grow a legacy offender" holds
everywhere except `__init__`'s five lines, recorded as a deviation in §8.11.3
item 4 with F2's `Collector.__init__` as the precedent.

### §16.7 acceptance checklist

| Item | Result |
|---|---|
| No new function > 30 physical LOC | ✅ none; `push` briefly became one via a docstring and was restored byte-identical (§8.11.3 item 5) |
| No new class > 150 LOC or > 15 methods | ✅ largest part is `ApplyCommand` at 143 / 7; the facade at 179 / 28 is the pre-existing offender, halved |
| No new function with > 4 params (excl. `self`/`cls`) | ✅ none new; the two widest are HEAD's `__init__` (8) and `attach` (7), unchanged |
| radon CC ≤ 10, cognitive ≤ 15, nesting ≤ 4 | ✅ maxima 9 / 14 / 3 — all three unchanged from HEAD |
| Line coverage ≥ 80% and not below baseline; branch ≥ 75% | ✅ line **91.51%** vs 91.50%; branch **86.36%** vs 86.36%. ⚠️ one module at 45.68%, a pre-existing gap now visible — §8.11.8 |
| Every new function has a test that would fail if deleted | ✅ no function is new; the 21 moved ones are covered by the 8-test guard plus the existing undo suites, and the guard was negative-checked 5/5 (§8.11.6) |
| No new vulture findings | ✅ `--min-confidence 90` silent on all five files; `unused-import` went 2 → 0 |
| No new duplication groups | ⚠️ one, baselined with a recorded reason, and one stale entry deleted (§8.11.10) |
| Quality-override comments used | ✅ none — no `ideal-size:` or metric override was needed anywhere in the family |
| Metrics not gamed | ✅ §8.11.2 refuses to report the parts' degenerate LCOM\* 0.0000 as cohesion; §8.11.3 item 5 records a prose move that *raised* a measured number back into line instead of hiding it; §8.11.4 reports a pylint profile that got worse; §8.11.8 reports a 45.68% module in the family F3 created |
| RULE 18 ideals | ✅ see below |
| RULE 19 order respected | ✅ nesting (3), CC (9) and cognitive (14) were already inside the limits; size was taken last, as §19 prescribes |
| Current docs updated (RULE 17) | ✅ `AGENT_RULES.md` §18.2 and §18.3 measured notes, `SYSTEM_OF_RECORD.md`'s Undo/redo row, `docs/archive/README.md` |

### RULE 18.2 and 18.3

* **Files.** All five are ≤ 300 lines: 241, 241, 126, 109, 101. Two are under
  150, which §18.2 treats as normal for a single-responsibility leaf
  (`undo_db.py` reverses exactly one kind of entry, `undo_history.py` owns the
  timeline and its three projections). Every file's docstring names what it owns
  and which way its imports point — the sentence §18.2 says keeps a split from
  rotting back: no part imports the facade, no part imports another part, and all
  four import only `stores`/`backend`/`core` leaves plus the module-level helpers
  that moved with them.
* **Modules.** The `undo_*` prefix family in `services/` is now **8 files**
  (`undo_service`, `undo_history`, `undo_apply`, `undo_db`, `undo_world`,
  `undo_timeline`, `undo_support`, `undo_archive`), inside §18.3's 5–15 band and
  cohesive by the same test F2 applied to `collector_*`: all eight share the
  timeline-entry vocabulary and the `owner` protocol, and they change together.
  Top-level `services/` is 37 files, still over the band and still held by
  prefix families, now including `undo_*` 8 alongside `history_*` 9,
  `collector_*` 9 and `db_deletion_*` 8.
* **§16.5's landmine list in `AGENT_RULES.md` still names `UndoService`, and F3
  left it there deliberately.** The god class is gone, but the family still
  contains three pre-existing offenders (`__init__`, `attach`, `restart_world`)
  and five frozen contracts that a casual edit can break silently (§8.11.5) —
  which is what "landmine" means operationally. F2 left `Collector` on the same
  list for the same reason; removing either would need the list's meaning
  changed first, and that is a rules decision, not a refactor's.

#### 8.11.10 The clone baseline, moved rather than dodged

One entry deleted, one added, both recorded in `rule16_gate.py` with their
evidence:

* **Deleted** `('services/history/query.py', 'services/undo_service.py')`. The
  facade's header went with the code that used it — `json`, `os` and `logging`
  all left for `undo_apply.py` and `undo_world.py` — so the shared window no
  longer exists. The gate reported it stale; deleting it is the ratchet working
  *down*, which is the direction §18.5 exists to protect.
* **Added** `('services/history/query.py', 'services/undo_world.py')`, span 6 at
  `query.py:1` and `undo_world.py:17`: `from __future__ import annotations` /
  `copy` / `json` / `logging` / `os`, with `log = logging.getLogger("chatbot")`
  immediately below in both. No logic is copied — it is the standard header of a
  leaf service module. All five names are genuinely used in `undo_world.py`
  (`copy.deepcopy` in `sync_world_state`, `json.dumps` in `emit_db_change`,
  `logging` for the module logger, `os.path.abspath` / `os.path.basename` in
  `restart_world`, `annotations` for the `Result[None]` / `list[dict]` hints),
  and vulture reports nothing in that file at any confidence, so there is no
  unused import whose honest removal would dissolve the window. Reordering or
  splitting the imports to break the span was rejected: it is the cosmetic
  span-shrinking §18.5 forbids and it would reintroduce pylint C0411.

### 8.12 F3d executed — the seams `services/undo_db.py` exposed

A **test-only** step: `git status` for it is one new file and no product line
changed, so the equivalence evidence in §8.11.7 is untouched and the family's
RULE 16 numbers are exactly §8.11.9's.

#### 8.12.1 Numbers

| | before F3d | after |
|---|---|---|
| `services/undo_db.py` line coverage | 45.68% (29/55) | **100.00%** (55/55) |
| repo line coverage | 91.51% | **91.69%** (14,142/15,423) |
| repo branch coverage | 86.36% | **86.84%** (3,246/3,738) |
| suite | 2726 passed / 894 subtests | **2748 passed / 0 failed** / 894 subtests |
| clone scan / RULE 16 gate | 0 new, 0 stale, rc=0 | unchanged |

`tests/integration/services/test_services_undo_gaps.py` — 22 tests, 452 lines, in
the `*_gaps.py` convention already used by `test_services_db_gaps.py` and
`test_services_collector_gaps.py`: a file that exists because a *seam* was
untested, whose docstring names what the other suites already cover so the next
reader does not duplicate it.

The fixture is the missing piece §8.11.8 could not name: **no test anywhere
constructed an `UndoService` with a `dbs=`**, which is why the whole module was
cold. `FakeDbs` records every `delete` / `load` / `clean` / `restore_backup` call
and returns a canned result, so each test asserts the call that was made and not
merely that something happened.

#### 8.12.2 What the tests lock

* **`_db_delete_op`, both directions**, including the two warnings that make a
  permanent delete say so instead of pretending ("Nothing to re-delete — the file
  is already gone", "Database deletions are permanent — no backup exists to
  restore"), and the `str(value.get("backup") or "")` coercion that makes a
  *missing* key behave like a missing backup. Legacy entries are exactly the ones
  whose shape cannot be assumed, so the coercion is contract, not detail.
* **`_db_op_forward`**: `create` loads with `create=True`, `load` with
  `create=False`, `clean` empties the *live* world and ignores the entry's path,
  an unknown op returns `None` and calls nothing.
* **`_db_switch_op`, both ways**: forward to `path`, backward to `before_path`
  (or to the clean's `backup`). Direction *is* the contract here — backwards and
  the app reopens the wrong world.
* **`_apply_db_command`'s delete branch end to end**: restart the world only on
  `ok`; announce on any result, with `switched=True` only when the live world
  really moved and with the DbManager's own error reaching the Log Console; and
  on `None` do neither.

#### 8.12.3 The guard is a negative check, and one mutation taught something

Nine mutations of `services/undo_db.py`, each required to fail a named test
(`/home/user/f3d_negative.py`; restores the file and re-verifies the baseline
afterwards): **9 of 9 caught** — swapping the delete op's directions, re-deleting
a file that is already gone, pretending a permanent delete can be restored,
creating on a plain load, dropping the clean branch, announcing only successes,
rebuilding the world after a failure, announcing an op that never ran, and
sending a redo backwards to `before_path`.

The eighth **missed on the first run**, and the miss was the useful part.
Deleting the `if result is None: return` guard changes nothing a bus-only recorder
can see: the resulting `AttributeError` dies inside the spawned task, and
`TimelineCommit._crash_log` reports it through the `chatbot` **logger**, not the
EventBus. So "the op declined cleanly" and "the op raised in a background task"
looked identical to the test — while looking very different to a user reading the
log. The suite now attaches a WARNING-level handler to that logger and asserts no
"db command failed", which is what turned the miss into a catch.

#### 8.12.4 Two findings locked rather than fixed

Both are product decisions, and a test-only step has no business making either.
Each is asserted by a test whose docstring says so, so the behaviour cannot drift
without someone reading the reason.

1. **The D4 tension.** D4 says a deleted world stays deleted and no Ctrl+Z brings
   it back, and `test_a_delete_is_not_an_undo_step` pins that nothing writes such
   an entry. But a legacy entry already sitting in a world's `undo_history` table
   is merged into the live timeline by `sync_world_state` and, undone, **restores
   the deleted file from its backup** —
   `test_a_legacy_delete_entry_still_restores_the_world`, with
   `test_redo_of_a_legacy_delete_deletes_the_file_again` for the other direction.
   Both behaviours are true today and neither is obviously wrong: honouring an
   undo step the user was once promised is defensible, and so is treating every
   delete as permanent from D4 onwards. Choosing means either dropping
   `dbconn`/`delete` entries when a world loads (a migration decision, and it
   would silently rewrite a persisted timeline) or documenting that pre-D4 worlds
   keep one undoable delete. **Not decided here; it needs the owner.**
   **RESOLVED 2026-09-13 — the owner ruled that the functionality is fine as it
   works today**: no migration drops those entries, and a pre-D4 world keeping
   its one undoable delete is intended behaviour rather than a contradiction of
   D4. Recorded in SYSTEM_OF_RECORD §3.3 and in §8.16 below.
2. **`dbconn` announces success from the intent.** `_apply_db_command` returns
   `True` after spawning, so `_log_command` writes "↩ Undo — database restored"
   synchronously and the op runs afterwards. `_log_command` suppresses exactly
   that line for `archive` — "archive ones report themselves later, with the
   database state they actually produced" — because announcing the intent is what
   let a locked database keep a person deleted while the log said "archive
   restored" (bug 2026-09-11, SYSTEM_OF_RECORD I-18). `dbconn` never got the same
   fix. `test_success_is_announced_before_the_work_runs` pins the worst case: an
   entry with no backup logs "database restored" and only *then* admits the delete
   is permanent. The fix is small — suppress `dbconn` in `_log_command` and let
   `emit_db_change` report the outcome, as archive does — but it changes
   user-visible log text, so it is named here instead of being slipped into a
   test commit. **RESOLVED — the owner chose it as the next step; see §8.13.**
   The line is suppressed for `dbconn` and re-said from the DbManager's result,
   which also retired the test that pinned the wrong behaviour.

#### 8.12.5 RULE 16 / RULE 18 notes for the step

* No product function changed; the family's maxima stay CC 9, cognitive 14,
  nesting 3, params 8, function LOC 32, and its four violations are still HEAD's
  four (§8.11.9).
* The new file is a test module: 452 lines, no product logic, `vulture
  --min-confidence 90` silent on it, and no `unused-argument` left once the
  restart fake's unused parameters were underscored. Its 19 `protected-access`
  hits are the point rather than a smell — it drives `_db_delete_op`,
  `_db_op_forward` and `_db_switch_op` directly, which is what a seams file does
  (`test_services_db_gaps.py` does the same to `DbManager`).
* §18.2's band governs product modules; the repo's test files run to 817 lines
  (`tests/test_world_write_gate.py`) and this one is not given an `ideal-size:`
  note, because there is no constraint to name and §18.5 forbids inventing one.
* Remaining coverage gaps in the family, attributed per function rather than per
  impression — §8.11.8 is what a plausible-sounding guess costs. None is a new
  gap; all are now *measurable per module*, which is the point of having split
  the file.
  * `undo_world.py` 84.34% — `restart_world`'s three failure paths (66-68 the
    queue that did not follow the switch, 72-73 a failed undo sync, 79-80 the
    guarded nick broadcast), `_schedule_world_undo_save` (98 — **no test calls
    this method at all**), and `sync_world_state`'s "the world table is the
    truth" skip (113).
  * `undo_history.py` 85.71% — `_migrated_entry` (54-58), i.e. the seq-preserving
    legacy rebuild is entirely unexercised, which is the function whose bug
    "pushed every app entry ahead of the world entries and issued duplicate
    seqs".
  * `undo_apply.py` 87.82% — `_values_equal`'s exception fallback (40-41),
    `_position_of`'s found path (60), `_apply_labels_command` (80),
    `_apply_archive_command`'s two refusal returns (133, 135),
    `rewind_after_failure`'s non-dict early return (149), `_apply_entry`'s
    command-kind branch (164-165) and people branch (170-173), and `redo`'s
    "cannot re-apply" `Err` (226).

---

## §8.13 F3e — the `dbconn` intent log: I-18's missing half (2026-09-13)

§8.12.4 named two things needing the owner. The owner chose the second, so this
step is that fix and nothing else: no product logic moved, no signature changed,
and no entry kind gained or lost a behaviour other than *when its log line is
written*.

### 8.13.1 What was wrong

`undo()` and `redo()` both call `_log_command(entry, forward)` and only then
apply the entry. Applying a `dbconn` entry means spawning a task and returning
`True`, so the line was written from the **intent** and survived every outcome:

| what the op actually did | what the user read |
|---|---|
| restored the world | `↩ Undo — database restored` — correct, by luck |
| refused (`ok: False`) | `↩ Undo — database restored` **and** `⚠ <error>` |
| delete, backup gone | `↩ Undo — database restored` **and** `⚠ Database deletions are permanent` |

The last row is the archive bug of 2026-09-11 wearing a different entry kind: a
line promising the opposite of what happened, written before anything happened.
I-18 fixed it for `archive` by making `_log_command` skip that kind and letting
the task report what it read back. `dbconn` kept the old ordering.

### 8.13.2 The fix

1. **`services/undo_apply.py::_log_command`** — `if kind == "archive"` becomes
   `if kind in ("archive", "dbconn")`, and the docstring now names both halves
   and says where each reports itself.
2. **`services/undo_db.py::_announce(host, forward, result)`** — a new
   module-level function, called from both of `_apply_db_command`'s branches
   immediately before `emit_db_change`:

   ```python
   if not result.get("ok"):
       return
   host._log(f"{'↪ Redo' if forward else '↩ Undo'} — "
             + host.UNDO_LABELS.get("dbconn", "database restored"), "info")
   ```

   Same words, same label table, same level, same arrow logic as the line it
   replaces, so no user-visible vocabulary changed — only *whether and when* the
   line appears. `UNDO_LABELS` stays on the facade, which matters because
   `bridge/router.py:151` copies it by attribute name.

Two decisions worth recording, both reached by reading rather than assuming:

* **Not folded into `emit_db_change`.** That helper is shared with
  `bridge/db_bridge.py`'s live-action path, which logs its own success line
  naming the world; announcing inside it would double-log every
  create/load/clean the user does by hand.
* **Failures stay silent here.** `emit_db_change` already emits
  `LogMessage("⚠ " + error, "warn")`, and every `{"ok": False}` the DbManager
  returns carries an `"error"` key — **12 of 12** in `services/db_lifecycle.py`,
  counted with grep rather than trusted, because §8.11.8 is what a
  plausible-sounding guess costs. A second line would only repeat the warning.

### 8.13.3 What deliberately did not change

* **`_apply_db_command` still answers from the intent.** It returns `True` once
  the task is spawned, the timeline moves at once, and a refused dbconn op does
  **not** rewind. That is the asymmetry still standing against `archive`, whose
  `_refuse` calls `rewind_after_failure` so the entry stays retryable and its
  "press Ctrl+Z to try again" is true. Copying it would mean passing `entry`
  into `_apply_db_command` (whose signature is `value, forward`) *and* deciding
  whether a legacy delete entry deserves to be retryable at all — §8.12.4
  decision 1's territory, not a log fix. **Named, not done.** For the same
  reason `_announce` offers no retry hint: with the pointer already moved,
  Ctrl+Z would undo the *previous* entry, so "press Ctrl+Z" would be a second
  lie.
* **Decision 1, the D4 tension, is still open.** Undoing a legacy delete entry
  still restores the deleted world from its backup. This step only stops the log
  claiming that before it happens. *(Resolved the same day — the owner ruled the
  behaviour correct as it stands; see §8.16.)*
* **`people` announces from the intent too — found while writing the test that
  pins the surviving announcement.** `_apply_entry`'s people branch does not
  restore anything itself; it spawns `people_service.apply`, which logs its own
  *verified* outcome — `"↩ People list restored — {count} person(s)"` built from
  what the store reports landed, or `"❌ People-list restore failed: {exc}"` at
  error level. So undoing a people entry writes **two** lines: the intent line
  from `_log_command` and, later, the verified one — and when the restore fails
  the intent line still claims success ahead of the error. That is the dbconn
  shape a third time. It is *less* harmful than dbconn's was, because a truthful
  line always follows it, but it is the same wart, and fixing it means changing
  user-visible log text for a kind that — unlike dbconn — already tells the
  truth a moment later. **Not done
  here**: the owner chose the dbconn line, and this one needs its own sign-off.
  `labels` is the only command kind left that is genuinely synchronous
  (`_apply_labels_command` restores, emits and returns), so its intent line is
  accurate. `TestLogCommandSkipsTheSelfReportingKinds` pins today's wording for
  both, which is what a future fix would have to change deliberately.
  **Done in §8.15 (F3f)** — and that fix is also why the class named in the last
  sentence no longer exists: it pinned wording that is no longer today's, which
  is exactly what it said it was for.

### 8.13.4 RULE 16 / RULE 18

* `_announce` — 4 statements, 3 params, cognitive 1, nesting 1. Module-level
  rather than a method on purpose: `_apply_db_command` is an offender sitting at
  cognitive **14 of 15** and LOC **25 of 30**, so an inline
  `if result.get("ok"): host._log(...)` in each of its two branches would have
  spent its last point of headroom on a log line. As written the offender gains
  2 LOC (27/30) and 0 cognitive, and the gate reports no breach.
* `_log_command` — one membership test replaces one equality test; statement
  count and cognitive unchanged. Its docstring grew, and §8.11's docstring trap
  was checked rather than assumed: the function is still 4 statements, and
  §16.5 counts code lines, not prose.
* `rule16_gate.py --with-clones` — **rc=0**, `breaches: []`, `not_checked: []`,
  `clone scan: 0 new group(s), 0 stale baseline entr(ies)`. Offenders unchanged
  at 10 function rows + 1 class row, every one of them in
  `backend/history_query.py` or `bridge/history_bridge.py` — F4's targets — and
  none in the `undo_*` family. The shared log-format string between `_announce`
  and `_log_command` did not register as a clone.
* **RULE 18** — `services/undo_db.py` 101 → **124** lines, still under 150,
  which §18.2 calls "normal and good for leaves"; `services/undo_apply.py`
  241 → **247**, inside the 150–300 band. The test file 452 → **570** gets no
  `ideal-size:` note, per §18.5 and the reasoning already recorded in §8.12.5.
* `vulture --min-confidence 90` is silent on all three touched files. `pylint`
  emits **nothing at all** for `undo_db.py`, and for `undo_apply.py` only the
  pre-existing `protected-access` / `missing-function-docstring` messages at
  lines ≥ 179 (`ApplyCommand`) — none at `_log_command`. No new message type.

### 8.13.5 Tests, including a gap the negative check found

`test_success_is_announced_before_the_work_runs` existed to pin the *wrong*
behaviour on purpose (§8.12.4). It is gone, replaced by two classes in
`tests/integration/services/test_services_undo_gaps.py` (22 → **28** tests):

`TestTheOutcomeAnnouncement`
* `test_success_is_announced_only_after_the_op_succeeded` — `infos()` is empty
  immediately after `undo()` returns, the line appears only once the task has
  run, and the `restore_backup` call really happened.
* `test_a_delete_with_no_backup_never_claims_a_restore` — the worst case from
  §8.12.4: the permanent-deletion warning is there, no `restored` line, no
  DbManager call, no `DbChanged`.
* `test_a_failed_op_reports_the_error_once_and_no_success` — a refusal produces
  the `emit_db_change` warning and nothing else.
* `test_redo_of_a_delete_announces_the_re_delete_too` — the forward direction
  reads `↪ Redo`, so the arrow follows `forward` rather than being hardcoded.
* `test_a_switch_op_announces_from_its_result_too` — the create/load/clean
  branch announces as well, and the world restarted.

`TestLogCommandSkipsTheSelfReportingKinds` — **found by the negative check, not
by the design.** The mutation "`_log_command` drops `archive` instead of
`dbconn`" survived the entire suite: I-18's suppression had never been pinned by
any test anywhere. Two tests now hold both names plus the label wording and the
arrow, so removing either kind from the tuple fails.

### 8.13.6 Negative check

`/home/user/f3e_negative.py` — 8 mutations against the two touched modules,
**8/8 caught**:

| mutation | caught by |
|---|---|
| announce even when `ok` is false | `test_a_failed_op…`, `test_a_delete_with_no_backup…` |
| arrows swapped (`↩` for redo) | `test_redo_of_a_delete…`, `test_success_is_announced…` |
| level `info` → `warn` | every test reading `infos()` |
| label replaced with `"restored"` | the `database restored` assertions |
| `_log_command` reverted to archive-only | `test_success_is_announced…` |
| `_log_command` drops archive instead | `TestLogCommandSkipsTheSelfReportingKinds` (new) |
| delete branch stops announcing | `test_success_is_announced…` |
| switch branch stops announcing | `test_a_switch_op_announces…` |

The first pass reported 6/8, and both misses are worth more than the clean
sweep. The archive mutation was a genuine MISS — a real hole in the suite, now
closed by a test class that would not have been designed without it. The other
was the harness's own fault: the anchor `            _announce(self._o, …)`
matched twice, because a 12-space-indented line is a substring of the 16-space
one; the anchor now carries its preceding line. Same lesson as §8.12 — a
negative check that reports a clean sweep without ever having been seen to fail
is not evidence.

### 8.13.7 Verification

* Suite: **2754 passed** (was 2748), 3 skipped, 1 deselected, 1 xfailed,
  **894 subtests**, 8m04s — no failures, no new warnings.
* Coverage, product-only (`actions/ app/ backend/ bridge/ core/ services/
  stores/ ui/`): line **91.69%** (14147/15429), branch **86.82%** (3247/3740).
  Line is exactly where F3d left it; branch moved 86.84% → 86.82%, i.e. two arcs
  in a denominator of 3740, and the cause is visible rather than mysterious: the
  new code adds branch arcs to `undo_apply.py`, whose partial branches were
  already the family's worst.
* `services/undo_db.py` — line **100%** (61/61) and branch **100%** (28/28),
  **0 partial branches**. It was 100% (55/55) after F3d; the six new statements
  are all covered, so the module did not trade its full coverage for the fix.
* `services/undo_apply.py` — 87.82% → **89.93%** (125/139), because the new
  `_log_command` tests exercise both the skip and the announce path for the
  first time.

### 8.13.8 Records updated

* **SYSTEM_OF_RECORD** — new invariant **I-21** (a world action undone from the
  timeline reports only what the DbManager returned; a refusal is not restated
  because `emit_db_change` already warned), and the Undo / redo row's guarantee
  now names it beside I-18. I-18 itself is untouched: its mechanics — read back,
  error on refusal, restore the list half, rewind, emit `failed` — are
  archive's, and dbconn does not claim them.
* §8.12.4 decision 2 marked **RESOLVED** with a pointer here; decision 1 (the D4
  tension) remains open and still needs the owner.
* Archive README — F3e row.

---

## §8.14 Reapplied from `arena/01a099fd-chat-v-bot`: the boot-wait fix (2026-09-13)

The owner asked for an already-implemented fix from another Arena branch to be
reapplied here. That branch is an **unrelated history** — 254 commits, and
`git merge-base` between the two is empty — so nothing could be merged. The two
commits were cherry-picked instead, which works because a cherry-pick applies a
diff against the commit's own parent and needs no common ancestor.

What was actually missing here was established by comparing blobs, not by reading
commit subjects: `a0a8a65` (the boot broadcast, `announce_world_live`) was
already in this tree via `main`; the two commits on top of it were not.

| commit | what it does | reapplied as |
|---|---|---|
| `93ff3ca` | the first page request WAITS for the world and is answered — `wait_for_world_open` / `run_when_world_open` in `services/world_events.py`, `HistoryBridge._run_async` reduced to a 4-line call, `people_bridge._refresh_users_async` waits on `ctx.memory` | `1c83717` |
| `7e9e80a` | the person list fills itself on start — `initApp` re-asks HistoryDb/DbPanel once the listeners exist, and `HistoryDb.onError` un-sticks the loader with a bounded retry | `35d164c` |

Three conflicts, each resolved by keeping both sides' truths:

* **`bridge/history_bridge.py`** — this tree has `_qt_clipboard` / `_copy_file_to`
  (a media feature the other branch never saw) sitting in the region their commit
  touched. Kept them, took the fix. Their commit also added a third blank line
  before `class HistoryBridge`; that was dropped rather than propagated.
* **`docs/current/SYSTEM_OF_RECORD.md`** — three regions. Kept this branch's
  Undo / redo row (the F3 module family, I-21) and took their Boot / world-ready
  row (the wait semantics); took their extended **I-20** ("never swallows a
  request") and kept **I-21**; kept this branch's module counts (`bridge/` 14,
  `services/` 55, `stores/` 37 — the other branch predates F1–F3 and says
  12/36/36) while adopting their description of `world_events.py` as "the world's
  clock: wait for it, announce it live".
* **`ui/js/app.js`** — kept both their re-ask block and this tree's
  `WindowPresets.refresh()` line.

**The ratchet was then re-frozen (`dbbcc48`).** The fix moves `_run_async`'s
guard out of the class, so `HistoryBridge` measures **467 LOC / 44 methods**
here, down from the frozen 493/45 — and not the 482/44 their branch reported,
because this tree's file also carries the clipboard helpers. RATCHET says "may
shrink, may not grow", which lets a shrink pass silently, and a gain nobody
re-freezes is a gain the next feature can spend. It also lowers F4's starting
point: `bridge/history_bridge.py` is F4's named target and this ratchet is the
constraint F4 has to respect (the file is now 539 lines, was 542).

Evidence re-run here rather than trusted from the other branch: the fix's own
**147 tests** pass (`tests/unit/bridge_safety/`, `test_world_events.py`,
`test_app_lifecycle.py`), and **26 of the 27** runnable `tests/*.js` suites are
green. The exception, `tests/js_harness.js`, is a stdin-driven DOM stub rather
than a suite — it exits non-zero when run directly, and did so before these
commits too.

The reapplied code arrives fully covered by the tests that came with it:
`services/world_events.py` measures **100% line (36/36) and 100% branch (10/10)**
in this tree, so `wait_for_world_open` and `run_when_world_open` needed nothing
written for them here.

---

## §8.15 F3f — the people double line: the third instance (2026-09-13)

§8.13.3 found this and deliberately left it alone. The owner then asked for it,
so this is that fix.

### 8.15.1 What was wrong

A people undo wrote **two** lines:

1. `_log_command` — `↩ Undo — people list restored`, synchronously, from the
   entry, before the restore had run;
2. `people_service.apply` — `↩ People list restored — N person(s)`, from the
   count `replace_all` says actually landed.

So a success said the same thing twice, and a failure said "restored" and *then*
`❌ People-list restore failed: …`. On a redo the two lines even disagreed about
direction: line 1 read `↪ Redo`, line 2 always read `↩`, because `apply` had no
idea which way it was being asked to go.

### 8.15.2 The fix

* **`undo_apply._log_command` is now a whitelist.**
  `_ANNOUNCED_FROM_INTENT = ("labels",)` — the only command kind that applies
  synchronously (`_apply_labels_command` restores, emits, returns), so the only
  one whose intent is its outcome. `people`, `archive` and `dbconn` each report
  themselves from what they verified. A kind nobody has declared synchronous gets
  **no** line, and that is the point: this bug was found three times running
  (I-18 archive, I-21 dbconn, I-22 people), each time as one more name added to a
  skip list after the fact. A missing line is recoverable and visible; an intent
  line over an async kind is a lie the user reads as a success.
* **`people_service.apply(rows, forward=False)`** — the arrow follows the
  direction, because this is now the only line. Wording, level and the count are
  untouched, so it still matches `UNDO_LABELS` and `undo_db._announce`.
* **Direction reaches it from every call site**: `_apply_people_command` passes
  `forward`; `undo_archive._people_half(rows, forward)` takes it, so `run()`
  passes the command's direction and `_put_people_back` passes `not forward` —
  the repair genuinely goes the other way, and now says so.

### 8.15.3 Two blocks of `_apply_entry` were unreachable, and are gone

Wiring the direction through `_apply_entry`'s people branch produced a mutation
no test could catch, and the reason is that the branch cannot run:

* `_apply_entry` has exactly two callers, `undo()` and `redo()`;
* both reach it only from their `else` path, i.e. when
  `entry["kind"] not in COMMAND_KINDS`;
* `COMMAND_KINDS = ("people", "labels", "archive", "dbconn")` and
  `HISTORY_KINDS = ("stack", "grid") + COMMAND_KINDS`.

So neither `if kind in ("labels", "archive", "dbconn")` nor `elif kind ==
"people"` was reachable — and both were already on F3d's uncovered list (§8.12.5
names them as `undo_apply.py` 164-165 and 170-173). `_apply_entry` is now `grid`
or the stack `else`, which is every input that can reach it; an unknown kind
still falls to the stack branch exactly as before. Deleting them rather than
pinning them is also why the eighth mutation in §8.15.6 has no target.

### 8.15.4 Tests

`tests/integration/services/test_services_undo_gaps.py` 28 → **34**:

* `TestLogCommandSkipsTheSelfReportingKinds` becomes `TestWhatLogCommandAnnounces`
  — labels announced in both directions, the three self-reporting kinds silent,
  and an undeclared kind (`media`) silent instead of claiming a restore. The old
  class was written to pin wording a fix would have to change on purpose; this is
  that fix, so it is gone.
* `TestThePeopleAnnouncement` — a real `UndoService` + a real `PeopleService`
  over a real `UserMemory` (a SQLite file, nothing faked in the path): one
  Ctrl+Z writes exactly one line, `↩ People list restored — 2 person(s)`, and the
  queue really changed; a Ctrl+Y writes `↪`; a restore that fails writes only
  the ❌.
* `TestTheArchiveHalfsDirection` — drives the real `ArchiveCommands` over the
  real PeopleService, which needs no archive because the queue half touches only
  `host._people`: the direction given is the direction reported, and a refused
  redo puts the queue back with a ↩.

Two tests outside that file changed as well, in `tests/test_world_write_gate.py`:
its `slow_apply` and `refuse` doubles take the new `forward` parameter, and its
real-flow delete/undo/redo pair now asserts the arrow the queue half reports
(§8.15.6). That file is 817 → 826 lines; §18.5 gives test files no invented
note, and it remains the repo's largest.

### 8.15.5 Two things the new tests found about the old ones

* **`wait_for` was being handed a computed list.** It polls the object it was
  given, and `self.warnings()` / `self.errors()` build a *new* list per call, so
  those waits could never observe anything: they always slept the full timeout,
  and the assertions passed only because the real logs had reached `self.logs` in
  the meantime. Three call sites, two of them committed in F3d. Every wait is now
  on a stable list, and the file went from **27.5 s to 0.47 s** — the waits are
  real, so they pin ordering instead of acting as a sleep.
* **The failure test's first version cost 20.8 s**, because closing the world
  makes `world_transaction` spend the write gate's 15 s patience before it fails.
  What that test pins is the logging, not the cause, so the world stays open and
  the `users` table is dropped instead: a real SQLite error, immediately.

### 8.15.6 Negative check

`/home/user/f3f_negative.py` — 7 mutations, **7 caught**, though the first run
reported 6 and the seventh is the interesting one:

| mutation | caught by |
|---|---|
| `people` announced from the intent again | `TestWhatLogCommandAnnounces`, `TestThePeopleAnnouncement` |
| whitelist widened to all four kinds | the undeclared-kind test |
| whitelist dropped entirely | the one-line assertions |
| `apply`'s arrow hardcoded to ↩ | the redo test |
| snapshot picked without regard to direction | the undo test (wrong count) |
| refusal repair puts the list back the wrong way | `TestTheArchiveHalfsDirection` |
| `run()`'s people half reports the wrong direction | the two arrow assertions in `test_world_write_gate.py` (added after the first run missed it — see below) |

The miss is recorded rather than papered over — and so is the wrong explanation
first written for it, because the correction is the useful part.

That call site is inside `ArchiveCommands.run()`. The first draft of this section
claimed **no test in the repo drives `run()` with a people service present**, on
the evidence that `tests/test_archive_delete_undo.py`'s fixture wires
`br._memory = None` — and concluded that I-18's two-half flow had never been
integration-tested with both halves. **That claim was false.** One file had been
checked and the answer generalised to the repo, which is precisely the §8.11.8
failure mode.

The suite disproved it within the hour: changing `apply`'s signature broke two
tests in `tests/test_world_write_gate.py`, whose `TestUndoProvesItself` drives
the real `history_delete_person` → `undo()` → `redo()` flow over a real
`HistoryService`, a real `UserMemory` and a real `PeopleService` — the both-halves
path, already integration-tested, in the file that pins I-17. What was missing
was never the flow but one assertion: nobody had checked which *arrow* the queue
half reports.

So the fix is two assertions in the tests that were already there —
`test_delete_then_undo_restores_person_and_history` now requires a
`↩ People list restored` line, `test_redo_hides_them_again_and_says_so` a `↪`
one — plus the two doubles in that file (`slow_apply`, `refuse`) updated to the
new signature. Mutation 7 is caught, and the count is **7/7**.

Two things to carry forward. A signature change is itself a probe for who depends
on you, and it found a real integration path faster than reading did. And a claim
about "no test anywhere" is only admissible after grepping the whole suite — the
check that would have caught this is `grep -rn "ArchiveCommands\|history_delete_person" tests/`,
which names `test_world_write_gate.py` immediately.

An eighth mutation — flipping the direction in `_apply_entry`'s people replay —
missed on the first run and led straight to §8.15.3: unreachable code was
deleted instead of pinned.

### 8.15.7 RULE 16 / RULE 18

* `_log_command` 4 statements, cognitive 1, and `_ANNOUNCED_FROM_INTENT` is data
  with the reasoning attached to it. `apply` 2 params / 17 LOC (inside §18.1's
  4–20 band); `_people_half` 2 params; `_apply_entry` lost 7 lines and a branch.
* `rule16_gate --with-clones` **rc=0**, breaches `[]`, clone scan 0 new / 0
  stale, offenders unchanged at 10 function rows + 1 class row and still none in
  the `undo_*` family.
* Files: `undo_apply.py` 247 → **259**, `people_service.py` 220 → **226**,
  `undo_archive.py` 230 → **235** — all inside §18.2's 150–300 band, and the
  repo-wide figures re-measured after the deletions are unchanged at **170
  files, median 134, 7 over 500**. The test file 570 → **728**: §18.5 gives it
  no invented note, but it is now within 100 lines of the repo's largest test
  file (`test_world_write_gate.py`, 826) and carries five concerns, so the split
  points are visible if it grows again.
* `vulture --min-confidence 90` reports nothing on the three product files. It
  had flagged `people_service.py`'s unused `Any` import, which predates this
  step; removing it exposed a second — `Optional` was unused on the same line,
  hidden behind `Any` — so the whole `typing` import is gone and pylint now
  reports no `unused-import` in that file (score 9.07/10). The two findings
  vulture still makes in `tests/test_world_write_gate.py` (242, 245) are
  pre-existing `**k` lambda parameters this step did not touch, and
  `undo_archive.py`'s single `try-except-raise` (167) is the deliberate
  `except asyncio.CancelledError: raise` that stops a cancellation being
  reported as a refusal — also pre-existing, also correct.
* Repo-wide §18.2 numbers re-measured and unchanged: **170 files, median 134,
  7 over 500**.

### 8.15.8 Verification

* Suite: **2776 passed**, 0 failed, 3 skipped, 1 deselected, 1 xfailed, **894
  subtests**, 8m09s. Against F3e's 2754 that is +22 — the 16 tests the
  cherry-picked boot fix brought with it (§8.14) and 6 net new here.
* Coverage, product-only: line **91.75%** (14164/15438, was 91.69%), branch
  **86.96%** (3254/3742, was 86.82%). Both up, and the branch figure by more
  than the line one, because what left the module was uncoverable.
* `services/undo_apply.py` 89.93% → **93.94%** (124/132): the module lost seven
  statements and every one was a statement no test could ever reach. The eight
  lines still missing are exactly the ones §8.12.5 already attributed — minus the
  two deleted `_apply_entry` blocks, which is the point — at their new line
  numbers: `_values_equal`'s exception fallback (40-41), `_position_of`'s found
  path (60), `_apply_labels_command`'s guard (81), `_apply_archive_command`'s two
  refusal returns (151, 153), `rewind_after_failure`'s non-dict early return
  (167) and `redo`'s "cannot re-apply" `Err` (244).
* `services/people_service.py` **95.00%** line (133/140) / 96.43% branch,
  `services/undo_archive.py` **98.37%** (unchanged by this step), and
  `services/undo_db.py` still **100%** line and branch.

---

## §8.16 D4 ruled: the legacy delete entry stays undoable (2026-09-13)

§8.12.4's first open decision is closed by the owner: **"the functionality is
fine how it works right now."** No code changes. The record does change, because
the tension has now been raised twice (§8.12.4 and §8.13.3) and a third reader
should not have to re-derive it:

* D4 (`DB_CREATION_DELETION_REDESIGN_DESIGN_2026-09-08.md`) makes deleting a
  world permanent, and it is honoured: `bridge/db_bridge.py` guards its only
  `dbconn` push with `if op != "delete"`, so **no delete made from now on is
  undoable** — pinned by `test_a_delete_is_not_an_undo_step` and by
  `test_nothing_in_the_product_records_a_delete_entry`.
* A world whose `undo_history` table holds a delete entry from *before* that
  guard keeps its one undoable delete: undone, it restores the file from the
  entry's backup. Intended, not a contradiction — it honours an undo step a
  pre-D4 world was once promised.
* No migration drops those entries and none is planned.
* The one thing that *was* wrong here is already fixed: the restore used to be
  announced before it happened, and a backup-less delete announced a restore it
  could never perform (§8.13, I-21).

Recorded in SYSTEM_OF_RECORD §3.3, as a bullet under "Deleting a world (the only
irreversible path)", next to the behaviour it qualifies.
