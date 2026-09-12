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
