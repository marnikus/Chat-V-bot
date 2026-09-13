# Step 6 — split the bridge facades (`HistoryBridge`, `StackBridge`)

Done 2026-09-13. Target: the round plan's step 6 — `bridge/history_bridge.py`
(**537 LOC**, `HistoryBridge` **474 LOC / 31 methods**, MI 23.5, LCOM\* 0.87)
and `bridge/stack_bridge.py` (**330 LOC**, `StackBridge` **31 methods**,
LCOM\* 0.89; the plan's table says 308 for this file, `wc -l` on the pre-split
blob says 330). The plan's success metric: *class 474/31 → ≤150/≤15*.

Both are §16.5 landmines: they are the whole JS ⇄ Python wire surface, so a
lost slot is a silently dead button in the UI rather than a failing import.

## Why it is one step

The two files are the same shape of debt and the same shape of fix, and they
fail the same gate for the same reason: one QObject per window family, with
every surface of that family stacked into one class body.

`HistoryBridge` mixes seven vocabularies — the async answering runner
(`_run_async` / `_schedule` / `_json_arg`), archive reads, the Full User
Database page, the three reversible deletions (RULE 12), person
purge/restore/merge, cached media and the clipboard, and the archive settings.
`StackBridge` mixes the run control, the composer/criteria pair, the two
preset stores, the custom blocks and the wiring. Neither class shares much
state (LCOM\* 0.87/0.89 — the methods mostly touch `self.ctx`, not each
other), which is exactly the "candidate for a responsibility split" signal the
plan ordered by.

Splitting them together is also what makes the *verification* honest: one
surface-diff tool, written once, proves both facades publish the identical wire
API.

## The seam to preserve (the one risk)

`bridge/router.py` builds the QWebChannel class from each bridge's **metaobject**,
walking members from `metaObject().methodOffset()` upward. That is the risk
with teeth:

* A `@Slot` or `Signal` declared on a **QObject base class** lands in the
  *base's* metaobject section, i.e. **below** the derived class's
  `methodOffset()` — so `_meta_members()` never sees it and the slot silently
  disappears from the JS wire API. No import error, no test failure unless a
  test publishes the surface.
* Therefore the mixins are **plain classes** (`object`-only). Their
  `@Slot`-decorated functions are inherited into the facade's own namespace and
  PySide registers them in the *facade's* metaobject section, which is what the
  router walks. This is the step-4 `Collector(QObject, LifecycleMixin, …)`
  precedent, applied to a Qt-published class where the offset actually bites.

Importers read the modules by name — `bridge/router.py` imports `HistoryBridge`
and `StackBridge`, the `bridge_safety` tests import `StackBridge`, and the
history tests reach for the three module-level helpers beside the class. So
both `__init__.py` files re-export the frozen seam (`HistoryBridge` +
`_file_mime` / `_person_request` / `_qt_clipboard`; `StackBridge`), and
promoting a module to a package changed **no import line anywhere**.

### The proof, not the promise

`tools/metrics/qt_surface_diff.py` (new in this step) instantiates the old file
and the new package side by side under `QT_QPA_PLATFORM=offscreen` and diffs the
two published surfaces — the metaobject members the router would walk, plus
every public attribute of a live instance:

```
HistoryBridge: 28 published metaobject members, 82 attributes — IDENTICAL
StackBridge:   29 published metaobject members, 83 attributes — IDENTICAL
```

Negative control (the tool must be able to fail): diffing the old
`HistoryBridge` against a QObject-mixin variant reports **2 MISSING** members
and exits 1 — i.e. the tool detects exactly the offset hazard above, so the two
IDENTICAL verdicts are evidence, not decoration.

`tests/unit/bridge/test_history_bridge_surfaces.py` (18 tests, step 6a) pins the behaviour the suite did not already cover: the guarded
async answering (`_run_async` success / exception / JSON-arg paths), the
`req_id` correlation on the ready signals, the deletion refusals, and the
settings-without-archive branch.

## The split

`bridge/history_bridge/` — 10 files, 728 LOC:

| Module | Owns | LOC | Class | LOC / methods |
|---|---|---:|---|---|
| `support.py` | `_file_mime`, `_person_request`, `_qt_clipboard` (module helpers) | 49 | — | — |
| `runner.py` | `RunnerMixin`: `_run_async`, `_schedule`, `_json_arg` | 54 | `RunnerMixin` | 37 / 5 |
| `reads.py` | `ReadsMixin`: person history, search, stats, my-nick detection | 106 | `ReadsMixin` | 89 / 9 |
| `userdb.py` | `UserDbMixin`: the Full User Database page + counters | 50 | `UserDbMixin` | 33 / 4 |
| `deletion.py` | `DeletionMixin`: the three reversible removals (RULE 12) | 141 | `DeletionMixin` | 120 / 6 |
| `person_ops.py` | `PersonOpsMixin`: purge / restore / merge, People-list helpers | 79 | `PersonOpsMixin` | 59 / 8 |
| `media.py` | `MediaMixin`: cached media, cache folder, clipboard | 125 | `MediaMixin` | 101 / 10 |
| `settings.py` | `SettingsMixin`: archive settings, with and without an archive | 38 | `SettingsMixin` | 21 / 2 |
| `bridge.py` | `HistoryBridge(QObject, …7 mixins)`: the 7 signals + `__init__` | 64 | `HistoryBridge` | **24 / 1** |
| `__init__.py` | frozen seam re-exports | 21 | — | — |

`bridge/stack_bridge/` — 9 files, 487 LOC:

| Module | Owns | LOC | Class | LOC / methods |
|---|---|---:|---|---|
| `wiring.py` | `WiringMixin`: context wiring and the shared emit helpers | 58 | `WiringMixin` | 37 / 5 |
| `run_control.py` | `RunControlMixin`: run / stop / pause / resume / snapshot | 72 | `RunControlMixin` | 56 / 6 |
| `composer.py` | `ComposerMixin`: `save_message`, `get_message` | 24 | `ComposerMixin` | 13 / 2 |
| `criteria.py` | `CriteriaMixin`: `save_criteria`, `get_criteria` | 21 | `CriteriaMixin` | 10 / 2 |
| `presets.py` | `StackPresetMixin`: the stack preset store | 101 | `StackPresetMixin` | 81 / 6 |
| `templates.py` | `TemplatePresetMixin`: the template preset store | 64 | `TemplatePresetMixin` | 45 / 5 |
| `blocks.py` | `CustomBlockMixin`: custom Find & Click blocks | 63 | `CustomBlockMixin` | 46 / 4 |
| `bridge.py` | `StackBridge(QObject, …7 mixins)`: signals + `__init__` | 68 | `StackBridge` | **24 / 1** |
| `__init__.py` | frozen seam re-exports | 16 | — | — |

Import order is a DAG in both packages: leaves (`support` / `wiring`) first,
then the mixins, then the facade, then `__init__`. **The mixins own no state
and never import the facade** — they resolve each other's helpers through the
MRO and everything they need through `self.ctx`, so the facade is the only
module that imports them (`backend/history_query/` precedent).

The two target classes go from **474 LOC / 31 methods** and **31 methods** to
**24 LOC / 1 own method** each; the largest leaf class in either package is
`DeletionMixin` at **120 LOC / 6 methods** and the widest is `MediaMixin` at
**10 methods** — inside the ≤150 / ≤15 gate with room to spare. 31 published
walk-methods per facade are unchanged (that is the point).

## Rejected dishonest reductions

* **QObject mixins** (`class ReadsMixin(QObject)`, then
  `HistoryBridge(ReadsMixin, …)`) were rejected: they *look* tidier and would
  have passed the suite, but the inherited slots fall below `methodOffset()`
  and vanish from the wire API — a dead button in the UI with a green test run.
  The negative control in `qt_surface_diff.py` exists to prove this is real and
  not a story.
* **One `mixins.py` per package** holding all seven mixins was rejected: it
  recreates the mixed-responsibility file being removed (a ~450 LOC module with
  seven vocabularies), and the class-size gate would still see one file over
  the line.
* **Deleting the module-level helpers into the class** (`_file_mime` as a
  static method, etc.) was rejected: `bridge/history_bridge.py`'s helpers are
  imported by name from tests, and moving them would change the frozen seam for
  no size win.
* **Splitting only `HistoryBridge`** (the bigger number) was rejected: the plan
  books step 6 as *the bridge facades*, and `StackBridge` is the same debt at
  31 methods — leaving it would leave the round's "no class over 150 LOC /
  15 methods" criterion unmet for `bridge/`.
* **Trimming the published surface** (dropping a slot nothing seems to call)
  was rejected: RULE 12/§16.4 — the wire API is a compat facade, JS is not
  statically checkable from here, and "seems unused" is how a button dies.

## Gate bookkeeping

`tools/metrics/rule16_gate.py` now *owns* both packages rather than ratcheting
them:

* `OWNED` gained the two package paths; **`RATCHET` is now empty** — the last
  two entries in it were these classes, so the ratchet has nothing left to
  carry. A test (`test_rule16_new_code.py`) asserts the ratchet *bites* by
  feeding it a synthetic over-limit entry, so an empty dict cannot silently
  mean "enforcement off".
* Class enforcement re-anchored from the deleted `bridge/history_bridge.py` to
  `bridge/history_bridge/userdb.py::UserDbMixin`; a test asserts no owned file
  is also baselined.
* `CLONE_BASELINE`: the stale `("bridge/db_bridge.py", "bridge/history_bridge.py")`
  header group is gone (one side no longer exists); three new *header* groups
  appeared and are baselined with justification — the mixin docstring/`from
  __future__` headers of `presets.py`/`templates.py`,
  `deletion.py`/`person_ops.py` and `runner.py`/`layout_service.py`. They are
  import+docstring preamble, not duplicated logic (0 new duplicate-line groups
  over the threshold; `--with-clones` reports 0 new / 0 stale).
* The pylint filter follows the file → package rename.

## Gates

* `radon cc -s bridge/history_bridge bridge/stack_bridge` — worst **B (8)**
  (`CustomBlockMixin.save_custom_block`); everything else A.
* `tools/metrics/rule16_gate.py --with-clones` — exit 0, 0 new clone groups,
  0 stale baseline entries.
* `tests/test_rule16_new_code.py` — **24 passed**.
* `tools/metrics/qt_surface_diff.py` on both facades — IDENTICAL (exit 0).
* Full suite: **2727 passed, 3 skipped, 1 deselected, 1 xfailed, 777 subtests**
  (9 m 41 s).
* `tools/metrics/current_audit.py`: files > 500 LOC **4 → 3**, mean MI
  **68.76 → 70.17**, classes > 150 LOC **34 → 32**, classes > 15 methods
  **25 → 23**; CC > 10 still 0, nesting > 4 still 0.
