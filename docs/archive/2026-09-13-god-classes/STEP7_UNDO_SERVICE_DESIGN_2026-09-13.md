# Step 7 — extract the `UndoService` god class into `services/undo_service/`

Done 2026-09-13. Target: the round plan's step 7 — `services/undo_service.py`
(**564 LOC**, MI **23.3**, `UndoService` **409 LOC / 28 methods**, LCOM\*
**0.92**; the plan's table says 27 methods, the AST count on the pre-split blob
is 28). The plan's success metric: *class 409/27 → ≤150/≤15*.

At **0.92** this was the second-least-cohesive class in the tree (only
`Collector` at 0.93 scored worse, and step 4 already split it): 28 methods that
share almost no state, because they are eight different jobs wearing one name.

## Why it is one step

AREA C (2026-09-09) already lifted the *collaborators* out of this class into
`services/undo_support.py` (`UndoProjection`, `UndoWorldStore`),
`services/undo_archive.py` (`ArchiveCommands`) and `services/undo_timeline.py`
(`TimelineCommit`). What was left is the service itself, and it still holds
eight vocabularies in one body:

1. entry identity (what makes two entries the same edit);
2. the timeline's contents (entry shape, cleaning, seq, read/write, migration);
3. the two-store merge after a world change;
4. committing an edit (`push`, its dedupe and its cap);
5. the four stack-era compatibility projections;
6. applying the COMMAND kinds, and rewinding when one refuses;
7. the DB Connection ops and the world they announce;
8. the two pointer walks (`undo` / `redo`).

It is also a §16.5 landmine: RULE 12 (one global timeline) and the invariants
I-10 / I-18 / I-19 are all pinned through this class, and its failure mode is
the worst kind — announcing "restored" over data that is still deleted.

## The seam to preserve (the three risks)

**1. Names imported by module path.** `bridge/context.py` and
`bridge/router.py` import `UndoService`; `bridge/db_bridge.py` imports
`emit_db_change` and `restart_world`; `bridge/router.py` *also* imports the
private `_values_equal` and publishes it on the wire class as both
`_values_equal` and `_stacks_equal`. So `__init__.py` re-exports all ten names
the old module **defined** (8 functions + `log` + the class) plus the two
deliberate parity names (`LayoutService`, marked `API parity` in the old file,
and `MAX_STACK_HISTORY`). Promoting the module to a package changed **no import
line anywhere**.

**2. The `MAX_STACK_HISTORY` patch seam.** `tests/test_world_write_gate.py`
shrinks the timeline cap by rebinding the *module attribute*
(`undo_service.MAX_STACK_HISTORY = 2`) in the two I-19 tests that prove an
evicted step gives up its tombstone. A leaf that did
`from backend.config_manager import MAX_STACK_HISTORY` would snapshot the value
at import time and those patches would land on nothing — the tests would then
fail loudly rather than silently, but they would fail. So
`recording._history_cap()` reads the attribute **through the package namespace,
at call time** (the technique step 3 used for the `asyncio` seam), and the
package re-exports the constant. Verified live, not assumed:

```
cap before patch: 100  →  cap after patch: 2
timeline with cap=2: ['layout-1', 'layout-2'] index 1   (3 pushes)
timeline restored cap: 3 entries
```

**3. The host contract.** The three collaborators are constructed with the
service as their `host` and call back into it. The complete set they use —
`_archive`, `_people`, `_config`, `_bus`, `_log`, `_timeline`, `_h_index`,
`_seq_next`, `_next_seq`, `_history_entry`, `_undo_pendings`, `_world_store`,
`history()` and `rewind_after_failure()` — is still one object after the split
(the mixins resolve each other through the MRO), so that contract is untouched.
The four class constants stay on the facade because
`tests/test_bridge_router.py` asserts `Bridge.COMMAND_KINDS ==
UndoService.COMMAND_KINDS`.

### The proof, not the promise

`tools/metrics/module_surface_diff.py` (new in this step — the plain-module
sibling of step 6's `qt_surface_diff.py`) loads the pre-split file from git and
the package as importable today, then diffs every name the old file *defined*:
kind, `inspect.signature` for functions, value for constants, and — for each
shared class — every non-dunder attribute reachable on it **including inherited
ones**, which is what makes a mixin split measurable rather than arguable.

```
module surface: 10 defined name(s), 10 reachable — IDENTICAL (2 ALLOWED)
  allowed: UndoService._migrated_entry MISSING (method)
  allowed: UndoService._schedule_world_undo_save MISSING (method)
```

The two ALLOWED rows are the dead-code removal below, named explicitly with
`--allow-missing` so the verdict states what changed instead of hiding it.
Negative controls (the tool must be able to fail): dropping the flags reports
**2 DIFFERENCE(S)**, exit 1; pointing it at one leaf
(`services.undo_service.walking`) reports **9 DIFFERENCE(S)**, exit 1.
Incidental imports the old file merely re-exposed (`Ok`, `EventBus`, `copy`, …)
are reported as information, not failures — nothing imported them from here
(every importer in the tree was grepped), and `--strict-imports` turns them
into failures if that ever stops being true.

Behaviour is locked first by
`tests/integration/services/test_undo_world_commands.py` (35 tests, step 7a,
`e11128a`), which took this file's coverage from the undo suites **73% → 94%**
(199 passed).

## The split

`services/undo_service/` — 12 files, 970 LOC:

| Module | Owns | LOC | Class | LOC / methods | MI |
|---|---|---:|---|---|---:|
| `entries.py` | `_values_equal`, `_same_entry`, `_position_of` | 53 | — | — | 82.1 |
| `timeline.py` | `TimelineMixin`: cleaning, entry shape, seq, `history`/`set_history`, migration | 82 | `TimelineMixin` | 53 / 7 | 79.2 |
| `worldsync.py` | `WorldSyncMixin`: config half + world table, merged by seq | 56 | `WorldSyncMixin` | 30 / 1 | 81.4 |
| `recording.py` | `RecordingMixin`: `push` (+ `_history_cap`, the patch seam) | 83 | `RecordingMixin` | 45 / 1 | 72.2 |
| `projections.py` | `ProjectionMixin`: the four stack-era compat names | 48 | `ProjectionMixin` | 24 / 4 | 91.2 |
| `commands.py` | `_apply_people_command`, `_apply_labels_command`, `_log_command`, `CommandsMixin`: `apply_command`, `_apply_archive_command`, `rewind_after_failure` | 127 | `CommandsMixin` | 55 / 3 | 68.1 |
| `dbconn.py` | `DbConnMixin`: `_apply_db_command`, `_db_delete_op`, `_db_switch_op` | 104 | `DbConnMixin` | **64 / 4** | 70.4 |
| `world_change.py` | `emit_db_change`, `restart_world`, `log` | 85 | — | — | 76.5 |
| `snapshots.py` | `SnapshotMixin`: `_apply_entry` | 59 | `SnapshotMixin` | 29 / 1 | 82.2 |
| `walking.py` | `UndoRedoMixin`: `undo`, `redo` | 96 | `UndoRedoMixin` | 57 / 2 | 69.6 |
| `service.py` | `UndoService(…8 mixins)`: the four constants, `__init__`, `attach`, `_log` | 113 | `UndoService` | **57 / 3** | 74.5 |
| `__init__.py` | frozen seam re-exports | 64 | — | — | 100.0 |

Import order is a DAG: `entries → commands → walking`, `world_change → dbconn`,
and the facade imports the eight mixins. **No mixin imports another mixin and
none imports the facade**; they reach each other through `self`, so the only
cross-leaf imports are the three module-level helpers (`_position_of`,
`_log_command`, `emit_db_change`/`restart_world`).

The target class goes from **409 LOC / 28 methods** to a **57 LOC / 3-method**
facade that resolves **28 attributes** through the MRO — the same surface, one
ninth of the body. The largest leaf class is `DbConnMixin` at **64 LOC /
4 methods** and the widest is `TimelineMixin` at **7 methods** (gate: ≤150 /
≤15). File MI goes **23.3 → 68.1–100** across the leaves; the worst function CC
is unchanged at **B (10)** (`_db_switch_op`, which is the same code it was).

The package is 426 LOC *larger* than the file it replaces. That is the eleven
module docstrings: each leaf now says what it owns and which bug class it
exists to prevent, which is the part a 564-LOC file could not afford. Steps 1–6
made the same trade (`bridge/history_bridge/` + `bridge/stack_bridge/`: 867 →
1215 LOC).

## Dead code removed (behaviour-preserving)

Two merge artifacts from the AREA C extraction, both with **zero callers**
anywhere in the tree (grepped across `.py`, `.js` and `.md`), and both visible
as coverage misses that no test could ever hit:

* `_migrated_entry` (14 LOC, coverage miss 238–242) — a seq-preserving entry
  rebuild. The archived test design of 2026-09-09 credits it with the B6 fix
  ("migrated entries must keep their seq"), and that fix is real and still
  runs — from `UndoProjection._migrated` in `services/undo_support.py`, which
  is what `from_raw_history` actually calls. This copy is the duplicate left
  behind when the projection moved out. The *behaviour* is pinned by
  `test_a_stored_entry_keeps_the_seq_it_was_migrated_with`.
* `_schedule_world_undo_save` (4 LOC, coverage miss 281) — a one-line forwarder
  to `self._world_store.schedule_save(entries)`. `TimelineCommit._store_timeline`
  calls the world store directly, so nothing ever went through this.

Both are declared to the surface diff with `--allow-missing`, so the tool's
verdict names them instead of silently passing.

## Observed, not changed

Three places where the code and its documentation disagreed. Step 7 moves
behaviour; it does not change it — so each is now pinned by a test and the
prose tells the truth:

* **`push`'s same-value branch never commits.** The docstring promised
  "including the same-value case, so a stale tail cannot survive a
  re-commit". It cannot happen: reaching the same-entry case means
  `index == len(history) - 1` already (the truncation above either did not fire
  or set it), so the `set_history` + `UndoHistoryChanged` inside that branch
  are **unreachable** (coverage miss 329–330, before and after). A no-op push
  therefore answers with a truncated list but writes nothing: the stored
  timeline keeps its redo tail and the bus stays quiet. Pinned by
  `test_a_repush_of_the_value_at_the_pointer_is_a_no_op`; the docstring now
  says so under "OBSERVED, NOT CHANGED".
* **`push_stack` answers from the store, not from the push.** It discards
  `push`'s result and returns `stack_projection()`, which re-reads the
  timeline — so after a no-op re-push it still shows the tail `push` truncated
  locally. Pinned by `test_push_stack_answers_from_the_store_not_from_the_push`.
* **`set_stack_projection(save=True)` ignores `save`.** The commit always
  persists. No caller in the tree passes it (`bridge/router.py` ×2,
  `bridge/undo_bridge.py`, one test — all positional without `save`), and
  dropping the parameter would change a published signature, so it stays:
  RULE 16 §16.4's dead-code row allows exactly this ("unused args on
  protocol/callback signatures may stay"). Vulture reports it at 100%
  confidence when the package is scanned alone; the gate scans all three
  `SMELL_FILES` together and vulture aggregates used names across them, so the
  gate is quiet. Recorded here rather than fixed.
* **`push` does not normalize; `push_stack` does.** Re-pushing a raw
  `[{"block_id": "PAUSE"}]` after an undo is *not* a no-op, because `history()`
  returns cleaned values (`enabled: True`) and `_same_entry` compares JSON. The
  dedupe only fires for callers that normalize first — which the bridge does.
  Pinned by the two re-push tests, which both go through `push_stack`.

## Rejected dishonest reductions

* **Deleting `_migrated_entry`'s docstring but keeping the method "for
  safety"** was rejected: a method with zero callers is not safety, it is a
  second definition that can drift from the one that runs — which is exactly
  how the B6 fix ended up with two copies.
* **"Fixing" `push` so the same-value case commits the truncation** was
  rejected for this step: it changes what the timeline stores after a no-op
  autosave (the redo tail would disappear), which is a behaviour change on a
  RULE 12 landmine and belongs in its own change with its own tests, not inside
  a size extraction. It is documented and pinned instead.
* **One `mixins.py` holding all eight mixins** was rejected: it recreates the
  ~400-LOC mixed-responsibility body being removed and would still trip the
  class-size gate.
* **Moving the four class constants onto the mixins that read them** was
  rejected: `tests/test_bridge_router.py` reads `UndoService.COMMAND_KINDS` and
  the router copies it onto the wire class, so the constants are part of the
  published vocabulary, not an implementation detail of one leaf.
* **Re-exporting the 26 incidental imports** (`Ok`, `Err`, `EventBus`, `copy`,
  …) to make the surface diff trivially identical was rejected: it would invent
  API nobody asked for and hide the one import that *is* a seam
  (`MAX_STACK_HISTORY`). The tool reports them as information instead, and
  `--strict-imports` exists if that judgement ever needs revisiting.
* **Making the mixins read the cap from `backend.config_manager` directly** was
  rejected: it is tidier and would break the two I-19 tests' patch target — a
  green-looking refactor that silently moves where a safety test bites.

## Gate bookkeeping

`tools/metrics/rule16_gate.py`:

* `SMELL_FILES` gained `services/undo_service/` (vulture walks the package
  recursively; pointing at the old module path would make it "could not be
  found" and pass on nothing). Worth scanning: it is the kind of whole-module
  pass that surfaces a dead forwarder.
* `CLONE_BASELINE` **shrank**: `('services/history/query.py',
  'services/undo_service.py')` — the plain `from __future__ / copy / json /
  logging / os` header — is gone, because no leaf of the package shares that
  five-import header with `history/query.py`. `--with-clones` reports **0 new
  groups, 0 stale entries**.
* `OWNED`, `RATCHET` (still empty) and `OVERRIDES` (still empty) needed no
  change: no owned function lived in this file and the class was never
  ratcheted — it was the enforcement test's anchor, and step 6 already
  re-anchored that to `bridge/history_bridge/userdb.py::UserDbMixin`.

`docs/current/SYSTEM_OF_RECORD.md` follows the split: the undo/redo row now
names the leaves that own each half (`walking.py` for `Ctrl+Z`, `commands.py` +
`dbconn.py` for the command kinds, `worldsync.py` for the two-store merge) and
gains the step-7a suite in its "pinned by" column; I-10 points at the package;
I-18 points at `commands.py`.

## Gates

* `tools/metrics/module_surface_diff.py /tmp/old_undo_service.py
  services.undo_service --allow-missing …` — **IDENTICAL (2 ALLOWED)**, exit 0;
  both negative controls exit 1.
* `radon cc -s services/undo_service` — worst **B (10)**, unchanged.
* `radon mi -s services/undo_service` — every leaf **A** (68.1–100.0).
* `tools/metrics/rule16_gate.py --with-clones` — exit 0, 0 new clone groups,
  0 stale entries, no smell findings.
* `tests/test_rule16_new_code.py` — **24 passed**.
* The nine undo/bridge suites (`test_services_undo`, `test_undo_support_contract`,
  `test_undo_world_commands`, `test_people_undo`, `test_archive_delete_undo`,
  `test_world_write_gate`, `test_undo_wire`, `test_world_events`,
  `test_bridge_router`) — **208 passed**, before and after the split.
* `tools/metrics/current_audit.py`: files > 500 LOC **3 → 2** (only
  `backend/config_manager.py` 502 and `backend/dom_highlight.py` 523 remain —
  step 8's targets), mean MI **70.17 → 70.85**, classes > 150 LOC **32 → 31**,
  classes > 15 methods **23 → 22**.
