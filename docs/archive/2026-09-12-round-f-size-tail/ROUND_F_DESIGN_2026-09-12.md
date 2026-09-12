# Round F design — the 500-line file tail (RULE 18.2)

Date 2026-09-12 · branch `arena/01a09227-chat-v-bot` · base `e4ef002`
Measurement source: `reports/CODE_QUALITY_METRICS_2026-09-12.md`

Required by RULE 16 §16.6 step 2: *"Research and design the structure in a doc
first when the change moves complexity across files."* Round F moves code between
files, so this doc precedes the edit.

## 1. The problem Round F addresses

Complexity is closed: 0 / 1,997 functions above CC 10, 0 above nesting 4, 2
above cognitive 15 (both frozen JS-literal builders). RULE 19's remediation order
is nesting → cyclomatic → cognitive → **size last**. The first three are done, so
size is now legitimately the next thing to work on, and it is the only category
still failing:

| Size axis | Threshold | Measured |
|---|---|---:|
| Files > 500 lines | 0 | **10** |
| Classes > 150 LOC (the gate line) | 0 | **38 (18.3%)** |
| Classes > 300 LOC | 0 | **11** |
| Functions > 4 params | few | **70 (3.5%)** |
| Classes > 15 methods | 0 | **25** |
| Maintainability index floor | — | **11.1** |

This is mass, not tangles. The distinction drives the whole round: a size fix
must not be sold as a complexity fix, and none of the targets below has a CC
problem to fix.

## 2. Why the biggest file is *not* step 1

`backend/chat_sync.py` (800 lines, MI 11.1 — half the next-worst score) is the
obvious target and cannot be split by the recipe this repo normally uses.

`tools/metrics/dump_public_api.py` builds the frozen AREA D snapshot enforced by
`tests/unit/backend/test_backend_api_snapshot.py`. Two properties block the split:

1. `module_names()` → `if info.ispkg: continue`. **Packages are skipped.** Turning
   `backend/chat_sync.py` into `backend/chat_sync/` deletes the qualname
   `backend.chat_sync` from the snapshot and fails
   `test_no_module_disappeared_or_failed_to_import`.
2. `dump_module()` keeps a symbol only when `obj.__module__ == qualname`.
   **Re-exports are not owned.** Moving `SyncSession` to a sibling and
   re-exporting it reads as *removed*, failing
   `test_public_classes_keep_their_surface`.

The snapshot covers exactly `backend` and `actions` (`dump_public_api.py:204`); no
golden file exists over `services/`, `stores/` or `bridge/`. That is why every
family already split in this repo lives in `services/` or `stores/`
(`services/run/`, `services/history/`, `stores/history_repo*`, `label_*`,
`media_*`, `services/db_deletion*`) — not by taste, but because it was possible
there.

**Consequence:** 5 of the 10 oversized files are structurally frozen —
`chat_sync.py` 800, `scroll_parser.py` 699, `history_query.py` 596,
`dom_highlight.py` 527, `config_manager.py` 502. Round F therefore works the
unfrozen half, and the frozen half is handled in §7 rather than bypassed.

## 3. Step F1 — `services/db_deletion.py`

Chosen over the other unfrozen candidates on four grounds: largest unfrozen file
(665), worst unfrozen MI (20.54), **pure functions with no Qt** (so the
equivalence gate is trustworthy and there are no signals/slots to break), and it
*continues an existing prefix family* — RULE 18.2 names `services/db_deletion*`
as the worked pattern, so this is the documented remedy applied to the one member
of the family that was never split.

### 3.1 Current measurements

```
radon raw  LOC 665 · LLOC 495 · SLOC 479 · comments 52 (8% of LOC) · blank 102
radon mi   20.54
radon cc   worst block B (9) — no C or worse anywhere in the file
```

> Reading note: `radon mi -s` prints rank **A** for 20.54, because radon's rank
> bands (A ≥ 20) are far looser than the classic 0–100 MI scale the audit uses
> (≥ 85 good, 65–85 moderate, < 65 high risk). On the classic scale this file is
> deep in high-risk territory. Trust the raw number, not the letter.

There is **no complexity to fix here** — worst block CC 9, under the CC 10
ceiling. F1 is a pure size/cohesion move.

### 3.2 The file already declares its own seams

Six banner comments partition it, and AST analysis of cross-region name usage
confirms they are real boundaries, not decoration:

| Banner | Lines | Entities |
|---|---|---|
| `canonical paths / containment` | 28–63 | `canonical`, `is_within`, `is_same_file` |
| `inventory` | 64–255 | `DeletionInventory`, `_dedup`, `_registry_active_dir`, `_registry_root`, `_append_db_files`, `_known_db_in_root`, `_InventoryCollector`, `build_deletion_inventory` |
| `plan` | 256–326 | `DeletionPlan`, `_prune_symlink_dirs`, `_add_regular_files`, `collect_discovered_files` |
| `candidate policy` | 327–516 | 7 `_*_reason` predicates, `classify_candidate`, `_PathPolicy`, `_PolicyBuckets`, `_frozen_abspaths`, `_classify_file_group`, `plan_deletion` |
| `bounded filesystem helpers` | 517–615 | `unlink_one`, `_prune_roots`, `_prune_blocked`, `_prune_one_start`, `prune_empty_dirs`, `_as_list` |
| `outcome` | 616–665 | `DeletionOutcome` |

Measured cross-region dependencies (module-level names only):

* `canonical` — used by **all five** regions (21 sites). It is the shared
  foundation.
* `is_within` — used by plan, policy, exec.
* `DeletionInventory` — plan needs it (type of the thing being planned).
* `DeletionPlan` — policy needs it (type of the thing being decided).
* `is_same_file`, `collect_discovered_files`, `unlink_one`, `prune_empty_dirs`,
  `DeletionOutcome`, `build_deletion_inventory`, `plan_deletion` — referenced
  **only at their own definition** inside the file; every caller is external.
* `DB_GROUP_SUFFIXES` and `SUPPORTED_BOUNDARY` — **defined but never used inside
  the file at all.** `DB_GROUP_SUFFIXES` is imported by `db_deletion_flow.py`;
  `SUPPORTED_BOUNDARY` appears only in a docstring elsewhere.

That yields a strict linear DAG with no cycles:

```
paths ──> inventory ──> plan ──> policy
  └────────────────────────────> exec
```

### 3.3 Target structure

Six files replacing one. `outcome` folds into `exec` because `DeletionOutcome` is
the result type of the bounded filesystem helpers — same responsibility, and it
keeps the family at 8 members instead of 9.

| New file | Content (source lines) | ≈LOC | Imports from |
|---|---|---:|---|
| `services/db_deletion_paths.py` | 28–63 | 50 | stdlib only |
| `services/db_deletion_inventory.py` | 64–255 | 215 | `_paths` |
| `services/db_deletion_plan.py` | 256–326 | 95 | `_paths`, `_inventory` |
| `services/db_deletion_policy.py` | 327–516 | 215 | `_paths`, `_plan` |
| `services/db_deletion_exec.py` | 517–665 | 175 | `_paths` |
| `services/db_deletion.py` (shim) | constants + re-exports | 55 | all five |

Every file lands inside RULE 18.2's 150–300 band (or just under, for `paths` —
§18.2 says *"under 150 is normal and good for leaves and pure-data modules"*).

**Import direction rule** (goes in each module docstring, per §18.2 — "that
sentence is what keeps a module split from rotting back into a monolith"):
`paths` is the leaf and imports nothing from the family; arrows only ever point
down the DAG above; the shim imports everything and nothing imports the shim.

### 3.4 Preserving the public surface

Required surface, established by grep over all callers and tests:

| Name | Required by |
|---|---|
| `canonical`, `is_within`, `is_same_file` | tests; namespace use |
| `build_deletion_inventory`, `collect_discovered_files` | tests; namespace use |
| `classify_candidate`, `plan_deletion`, `prune_empty_dirs`, `unlink_one` | tests |
| `DeletionInventory`, `DeletionPlan`, `DeletionOutcome` | tests; `db_deletion_flow.py` |
| `DB_GROUP_SUFFIXES` | `db_deletion_flow.py` (`from … import`) |
| `SUPPORTED_BOUNDARY` | docstring reference only |
| `_append_db_files` | ⚠️ `db_registry.py:289`, **private, cross-module** |

`services/db_deletion_scan.py` and `services/db_registry.py` do
`from services import db_deletion` and then use it as an **attribute namespace**
(`db_deletion.plan_deletion(...)`), so the shim must bind these as real module
attributes, not merely list them in `__all__`.

Two hazards were checked before designing. **One of those checks was wrong, and
the equivalence gate caught it.** The correction is recorded here rather than
quietly rewritten, because it is the most reusable lesson in this round — see
§8.1.

* **Monkeypatch semantics — initially mis-analysed.** The pre-design check asked
  "is `_append_db_files` patched?" (no) and "do the deletion tests patch module
  attributes or stdlib?" — and concluded stdlib only, because the visible
  `mock.patch("os.unlink", …)` calls dominate the file. That conclusion was
  **false**: the tests also patch the family's own primitive in 12 places,
  `mock.patch.object(D, "canonical", …)` and
  `mock.patch("services.db_deletion.canonical", …)`. Pre-split, `canonical` and
  all its callers shared one module namespace, so patching it governed every
  call site. Post-split, each leaf held its own `from … import canonical`
  binding and the patch reached nothing.
* **Circular imports.** Averted by keeping both constants in the shim: they are
  used by nobody inside the family, so no leaf needs to import them, and the
  shim-only dependency cannot close a cycle. This one held.

### 3.5 Dishonest reductions rejected (§16.6 requires recording these)

* **Two files of ~330 lines.** Splits the number, not the responsibility — both
  halves stay over the 300 ideal and the 665-line mass merely moves.
* **`db_deletion_part1.py` / `_part2.py`.** Explicitly forbidden by §18.5 ("no
  `foo_part1`/`foo_part2`"). Names must be responsibilities, and the six banners
  supply them.
* **Padding comments to lift MI.** MI weights comment ratio; the file is at 8%
  comments. Adding prose to move a metric is gaming (§16.2). Comments will be
  written only where the moved code genuinely needs orientation in its new home —
  the module docstrings §18.2 mandates, nothing more.
* **Splitting one function's body across files** to shrink a region. No function
  here is over 30 LOC except none — worst is CC 9 at ~20 lines. There is nothing
  to carve.
* **Promoting to a `services/db_deletion/` package.** Legal here (no snapshot
  over `services/`), but it would break the family's established shape and the
  two `from services import db_deletion` namespace uses would keep working only
  by accident of `__init__` re-exports. Prefix family is the documented pattern
  and the smaller change.
* **Fixing the `_append_db_files` boundary smell in the same commit.** Tempting —
  renaming it public and updating `db_registry.py` is a 2-line change. Rejected
  as scope creep inside a behaviour-preserving refactor: it would mix a pure move
  with an API change and muddy the equivalence gate. Recorded as F1b (§6).

### 3.6 Targets to verify after the split

| Measure | Before | Target |
|---|---:|---|
| Largest file in family | 665 | **≤ 230** |
| Files over 500 lines (project) | 10 | **9** |
| Worst MI among the new six | 20.54 | **≥ 50** |
| radon CC worst block | B (9) | **unchanged B (9)** — must not regress |
| Full suite | 2,710 passed / 0 failed | **identical** |
| Line / branch coverage | 90.41% / 86.30% | **≥ baseline** |
| Clone groups | 11 (= baseline) | **11, none new** |
| vulture ≥90% | 7 | **7, none new** |

MI is expected to rise steeply because it penalises volume logarithmically: the
same code at ~200 SLOC per file instead of 479 scores far better with identical
complexity. If MI does **not** reach 50 the split did not actually reduce
per-file mass and should be re-examined rather than accepted.

## 4. Verification plan

A refactor claiming behaviour-preservation runs the existing suite as the
equivalence gate (§16.6 step 3). Order matters — cheap gates first:

1. `radon cc -s` on each new file — no block may reach C.
2. `tools/metrics/rule16_gate.py` — limits, ratchets, smells.
3. `tools/metrics/clone_scan.py .` — must still equal the 11-group baseline.
   **Known trap:** five new files whose first ≥6 lines are an identical import
   header form a *new* clone group and fail the gate. Headers will be
   differentiated by their genuinely different import sets; if a group still
   appears, break it with a real module constant, never by cosmetic reordering.
4. `tools/metrics/current_audit.py` — confirm the file/MI/size deltas above.
5. Full pytest suite with coverage, headless Qt.
6. `mutants/` deleted before commit (mutmut leaves it untracked and it is **not**
   gitignored).

## 5. Execution steps

| Step | Action |
|---|---|
| 1 | Extract `db_deletion_paths.py` (lines 28–63) + docstring/import header |
| 2 | Extract `db_deletion_inventory.py` (64–255), importing `canonical` |
| 3 | Extract `db_deletion_plan.py` (256–326), importing `is_within`, `DeletionInventory` |
| 4 | Extract `db_deletion_policy.py` (327–516), importing `canonical`, `DeletionPlan` |
| 5 | Extract `db_deletion_exec.py` (517–665), importing `canonical`, `is_within` |
| 6 | Rewrite `db_deletion.py` as the shim: docstring, `DB_GROUP_SUFFIXES`, `SUPPORTED_BOUNDARY`, re-exports |
| 7 | Run gates 1–4; fix import/header fallout |
| 8 | Run full suite + coverage; confirm identical pass count |
| 9 | Update `docs/current/AGENT_RULES.md` §18.2/§18.3 measured lines (RULE 17) |
| 10 | Commit with `git commit -F` (backticks in `-m` get shell-substituted) |

## 6. Remaining Round F steps

| # | Target | Numbers | Note |
|---|---|---|---|
| **F1** | `services/db_deletion.py` | 665 · MI 20.54 | this doc |
| F1b | `_append_db_files` boundary | 1 call site | make public or move the call; deferred from F1 to keep the move pure |
| F2 | `services/collector_service.py::Collector` | 526 LOC · 40 methods · LCOM 0.93 | §16.5 landmine; QObject + signals ⇒ **own design doc required** |
| F3 | `services/undo_service.py::UndoService` | 418 · 28 · LCOM 0.92 | partially split already (`undo_timeline.py`) |
| F4 | `bridge/history_bridge.py` | 542 · MI 24.2 | gate-ratcheted at 493/45: may shrink, may not grow; QWebChannel pins slots |
| F5 | wide-parameter tail | 70 functions > 4 params; worst 20 | §19.4 parameter object, as `PersonPageRequest` does |
| F6 | 9 mutation survivors | all in `history_query.py` | `list_persons` cluster first; cheapest test win available |
| F7 | dense small files | `window_preset_service.py` 287 · MI 16.1; `run/progress.py` 248 · MI 27.8 | low MI **without** size — invisible to a line-count sort; needs decomposition and explanation, not splitting |
| F8 | `stores/` module count | 37 files vs RULE 18.3's ~15 | promote a family to a sub-package; lowest urgency |

## 7. The frozen five — decision required, with a compliant interim

The AREA D snapshot test says: *"Refresh the snapshot only when a change is
intentional and coordinated."* So splitting `chat_sync.py` is **permitted** by the
contract's own terms — but it spends a golden file whose stated purpose is proving
no public API moved, and it should be an explicit decision rather than a
side-effect of a size cleanup.

Two options, not mutually exclusive:

* **(a) Refresh the snapshot** (`python tools/metrics/dump_public_api.py --write`)
  as a coordinated commit, then split `chat_sync.py` (800 · MI 11.1) and
  `scroll_parser.py` (699) into packages. Unblocks the two worst files in the
  project. Cost: the golden file no longer proves ownership for those modules,
  and any real future API drift in them becomes harder to catch.
* **(b) Record the constraint instead.** RULE 18.5 already accepts *"a frozen
  contract that forbids the split"* as a legitimate `ideal-size:` reason. Each of
  the five files can carry a comment naming the AREA D snapshot, so the next
  reader learns the size is a known, justified constraint rather than neglect.
  Zero risk, zero unblocking — it documents the debt instead of paying it.

Recommendation: apply **(b) now** in every case (it is free and honest), and take
**(a)** only as its own reviewed change if the MI 11.1 file is judged worth the
guarantee. This is a scope decision for the repository owner, so Round F proceeds
on the unfrozen half and does not assume it.

## 8. Outcome (recorded after execution)

F1 is implemented. All six files exist, the equivalence gate passes, and the
project's 500-line count drops from 10 to 9.

### 8.1 The lesson worth keeping: a re-export shim is not patch-transparent

The split was mechanically correct and **behaviourally wrong** on first run:
4 tests failed. Not one of them failed because logic moved; all four failed
because a test's `mock.patch` stopped reaching the code it was written to break.

Pre-split, `canonical()` and every one of its callers shared a single module
namespace, so `mock.patch.object(D, "canonical", …)` governed all of them.
Post-split, each leaf held its own `from … import canonical` binding, and the
patch on the shim reached nothing at all.

**The dangerous part was not the 4 failures — it was the 5 tests that still
passed.** They patched `canonical` with a `side_effect` that raises once and then
succeeds; with the patch inert, the code simply ran normally and the "it recovers"
assertion passed anyway. Those tests went from exercising a fallback to asserting
nothing, silently. A split that only checks "does the suite still pass" can ship
that.

Fix, in two parts:

1. **Leaves call the primitive through one shared namespace** —
   `from services import db_deletion_paths as _paths` and `_paths.canonical(…)`.
   This restores the pre-split property exactly: one place to patch governs every
   caller. Verified by probe, not by assumption: with `PATHS.canonical` patched,
   the spy fires in `inventory` (2×), `exec` (2×) and `policy` (4× `canonical`,
   1× `is_within`); with the *shim* patched, it fires 0× — which is the trap, now
   documented at the test's import site so nobody tidies it back.
2. **Test patch targets repointed** — 9 × `patch.object(D, "canonical")` →
   `patch.object(PATHS, "canonical")`, 2 × the string form
   `"services.db_deletion.canonical"` → `"services.db_deletion_paths.canonical"`,
   and 1 × `D._dedup(...)` → `INV._dedup(...)`, the module that owns it.
   **No assertion was altered**: `git diff tests/` contains zero changed
   `assert*` / `self.assert*` lines.

Note what did *not* break: `test_cancel_concurrency.py` patches
`delmod.build_deletion_inventory` on the shim and still works, because its
production caller (`db_deletion_scan`) reaches it as `db_deletion.<name>` —
late attribute lookup on the shim. **Namespace access through a shim stays
patchable; `from … import name` inside a leaf does not.** That single
distinction is the whole lesson, and it applies to every future split in this
repo, including the `stores/history_repo*` family already in the tree.

### 8.2 Targets vs achieved

| Measure | Before | Target | Achieved | |
|---|---:|---|---|---|
| Largest file in family | 665 | ≤ 230 | **205** (`_inventory`) | ✅ |
| Project files over 500 lines | 10 | 9 | **9** | ✅ |
| Worst MI among the new six | 20.54 | ≥ 50 | **49.59** (`_policy`) | ⚠️ missed by 0.41 |
| radon CC worst block | B (9) | unchanged | **B (9)** | ✅ |
| Full suite | 2,710 / 0 failed | identical | **2,710 / 0 failed** | ✅ |
| Line coverage | 90.41% | ≥ baseline | **90.42%** | ✅ |
| Branch coverage | 86.30% | ≥ baseline | **86.30%** | ✅ |
| Clone groups | 11 | 11, none new | **12 → baselined with reason** | ⚠️ see §8.3 |
| vulture ≥ 90% | 7 | 7, none new | **7, none new** | ✅ |
| pylint (the six files) | — | clean | **10.00/10** | ✅ |

New per-file MI: `_paths` 82.12, shim 100.00, `_plan` 74.57, `_exec` 54.90,
`_inventory` 50.59, `_policy` 49.59.

Two honest notes on that table:

* **`_policy` at 49.59 missed the ≥ 50 target.** It is a 2.4× improvement on
  20.54 and the module keeps the family's densest genuine decision logic (seven
  retain predicates plus the bucketing policy), so its complexity-per-line stays
  high by nature. The gap is 0.41 index points; closing it by adding prose would
  be gaming MI (§16.2), so it is recorded as missed rather than cosmetically
  fixed. The design target was slightly optimistic, not the outcome deficient.
* **Coverage of the six new files is 99–100%** (`_inventory` 99%, the rest 100%),
  against 77% for `db_deletion_flow.py` and 73% for `db_deletion_scan.py`, which
  F1 did not touch. The split moved no code out from under its tests.

### 8.3 One new clone group, baselined rather than dodged

`clone_scan` reported a 12th group: `_inventory` and `_policy` share the 6-line
header `from __future__ / os / dataclasses(dataclass, field) / from services
import db_deletion_paths as _paths`. Both modules genuinely need exactly those
four imports, and the shared `_paths` alias is load-bearing — it is §8.1's fix.

Two dodges were considered and rejected on the record:

* **A module constant after the imports does not dissolve the group.** The
  scanner hashes *every* consecutive statement window, so the four imports
  remain a window of their own regardless of what follows them. This was the
  mitigation §4 anticipated, and it does not work — worth knowing for the next
  split.
* **Deleting the blank line between import groups** would shrink the span to 5
  and hide the group below `MIN_SPAN = 6`. That is gaming the scanner (§18.5),
  so it was not done.

The group was therefore added to `CLONE_BASELINE` with a recorded reason, which
is the mechanism the file itself documents and has used before (the 2026-09-11
maintenance note). `rule16_gate.py --with-clones` now reports **0 new, 0 stale**.

### 8.4 Final RULE 16 / RULE 18 recheck, including what F1 did not fix

Re-measured on the committed tree (`tools/metrics/current_audit.py`):

| Check (§16.7) | Result |
|---|---|
| No new function > 30 LOC | ✅ none in the family; longest is 25 (`plan_deletion`) |
| No new class > 150 LOC / > 15 methods | ✅ largest is `_InventoryCollector` at 84 LOC / 8 methods |
| No new function > 4 params | ⚠️ two pre-existing, see below |
| CC ≤ 10, cognitive ≤ 15, nesting ≤ 4 | ✅ worst in family: CC 9, cognitive 11, nesting 4 |
| Line coverage ≥ 80% and ≥ baseline | ✅ 90.42% (baseline 90.41%) |
| Branch coverage ≥ 75% | ✅ 86.30% (baseline 86.30%) |
| Every new function has a test | ✅ n/a — F1 adds no functions, only moves them |
| No new vulture findings | ✅ 7, unchanged, none in the family |
| No new duplication groups | ⚠️ one, baselined with reason (§8.3) |
| Override comments used only with a real constraint | ✅ none used |
| Metrics not gamed | ✅ two dodges rejected on the record (§8.3) |
| RULE 18 ideals | ✅ six files at 45–205 lines; the three under 150 are a leaf, a shim and a pure-data module, which §18.2 explicitly allows |
| RULE 19 order respected | ✅ nesting → CC → cognitive were already clean; size taken last |
| Current docs updated (RULE 17) | ✅ AGENT_RULES §18.2/§18.3, archive index |

**Two wide-parameter functions now live in the family, and F1 deliberately left
them alone:** `db_deletion_policy.py::classify_candidate` (7 params) and
`::plan_deletion` (9). Both are keyword-only (`def f(*, …)`), which prevents
call-site ordering bugs but does not satisfy the ≤ 4 limit.

They are **not new violations**. Measured at `e4ef002` before the split, they
were already 7 and 9 params at 23 and 25 LOC, and after the move they are still
7 and 9 params at 23 and 25 LOC — byte-identical, so §16.5's "never grow a
legacy offender" holds. Project-wide the count is unchanged at **70 of 1,997**
functions over 4 params.

Fixing them here would have mixed a parameter-object redesign into a
behaviour-preservation refactor and invalidated the equivalence gate that caught
§8.1 — the exact scope discipline §3.5 applied to `_append_db_files`. They are
therefore handed to **F5**, which is the parameter-object step, with these two as
its first named targets; `PersonPageRequest` is the in-repo pattern to follow.
