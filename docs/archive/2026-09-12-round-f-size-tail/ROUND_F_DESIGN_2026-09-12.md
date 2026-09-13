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

**(b) has been applied.** Each of the five frozen files now carries an
`ideal-size:` note directly under its module docstring, naming the AREA D
snapshot as the constraint and pointing here — so a reader who opens
`backend/chat_sync.py` and sees 800 lines learns at line 24 that this is a
documented contract limitation rather than neglect. The frozen snapshot test
still passes 9/9 and the gate still reports ratchet intact with 0 new clone
groups (comments are not statements, so the AST-window scanner cannot see them);
no signature or class span moved. Option **(a)** remains open and unassumed.

Two measured side-effects, stated rather than glossed, because one of them cuts
against a rule:

* **Each file grew by 7 lines** (chat_sync 800 → 807, scroll_parser 699 → 706,
  history_query 596 → 603, dom_highlight 527 → 534, config_manager 502 → 509).
  §16.5 says never grow a legacy offender, and these are the five worst
  offenders in the tree. The growth is nevertheless the prescribed remedy: §18.5
  requires a deviation from an ideal to carry a visible reason, and a reason has
  to occupy lines. The gate's `RATCHET` measures *class* spans, not file length,
  so it is unaffected and still reports intact — but the tension is real and is
  recorded here instead of being left implicit.
* **MI rose slightly on all five** (11.10 → 11.35, 28.30 → 28.58, 35.00 → 35.41,
  55.30 → 55.91, 40.50 → 40.96), because MI rewards comment ratio. This was not
  the purpose and must not be read as progress: §16.2 treats lifting a metric
  with prose as gaming. The notes were added to satisfy §18.5, the movement is
  +0.25 to +0.61 index points against a floor of 11.1, and every file remains far
  outside the 150–300 ideal. If anything the notes make the debt more visible,
  which is the opposite of what gaming tries to do.

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

## 9. Step F6 — the nine mutation survivors (executed 2026-09-13)

F6 is the Round F step that changes no code: it adds tests. That is why §6
called it the cheapest win and why it is the safest candidate to run in parallel
with anything — no production line moves, so no size metric, no ratchet and no
clone group can be touched by it. It landed as one new test file
(`tests/test_history_query_gaps.py`, 12 tests, 306 lines), the `[mutmut]`
section of `setup.cfg`, and one entry in `.gitignore`.

**Measured outcome: 158 of 159 reachable mutants killed (99.37%), one survivor
left, and that survivor is provably equivalent.** The audit's 94.34% (150/159,
reports/CODE_QUALITY_METRICS_2026-09-12.md §3) is superseded. Eight of the nine
named survivors are closed. The step also found a defect in the measurement
itself (§9.3), which is worth more than any of the mutants.

### 9.1 What the nine survivors actually were

`mutmut show` on each, classified by *why* nothing killed it — the reason
dictates the remedy, and the three reasons below are not the same problem:

| Mutant (mutmut 3.7.0 name) | The change | Why it survived | Now |
|---|---|---|---|
| `_like_escape` 13 | `replace("\\", …)` → `replace("XX\\XX", …)` | no *selected* suite sends a backslash | killed |
| `_like_escape` 14 | replacement `"\\\\"` → `"XX\\\\XX"` | same | killed |
| `HistoryQuery._clamp` 4 | the `except` branch assigns `None` | same | killed |
| `HistoryQuery._clamp` 9 | `max(1, …)` → `max(2, …)` | same | killed |
| `HistoryQuery._my_nicks` 7 | `or "[]"` → `or "XX[]XX"` | **equivalent** (§9.4) | recorded |
| `list_persons` 18 | COUNT fallback `0` → `None` | unreachable through a real engine | killed |
| `list_persons` 21 | the COUNT fallback argument dropped | **equivalent** against the real engine (§9.4) | killed by a convention pin |
| `list_persons` 22 | COUNT fallback `0` → `1` | unreachable through a real engine | killed |
| `list_persons` 29 | `LIMIT ? OFFSET ?` lower-cased | SQLite folds keyword case: **equivalent** | killed by a statement pin |

Two of the nine are real bugs waiting for an input, and it is worth saying what
they do rather than only that they survived:

* `_like_escape` 13 leaves a user's backslash un-doubled. With `ESCAPE '\'` the
  pattern `%a\b%` then means *a, followed by a literal b*, so searching for the
  person named `a\b` returns the person named `ab` — and reports a confident
  `total` for them. Verified against a real database in
  `TestABackslashInANickFilter`.
* `_clamp` 4 turns a recoverable page into a crash: `limit` arrives from a JSON
  blob the UI built, so a hand-edited payload can put `"garbage"` in it, the
  `except` handler assigns `None`, and `min(MAX_LIMIT, None)` raises
  `TypeError` inside a bridge slot. The user sees a list that stops paging.

The other six sit on defensive code, which is why coverage never complained:
`_clamp`'s floor, `_my_nicks`'s fallback and the COUNT's `default` argument are
all *executed* by the existing suites, and executing a line is not asserting its
value — the same distinction `tests/test_person_item.py` was written for.

### 9.2 Four of the nine were a property of the job, not of the tests

`setup.cfg` selects three suites (the sort path). `tests/test_history_query_edges.py`
— the module's adversarial suite, written for the 2026-09-09 test round — is not
one of them, and it already kills four of the nine. Measured, not assumed: each
mutant was run against each file separately
(`MUTANT_UNDER_TEST=<name> pytest -q --noconftest <file>` inside `mutants/`).

| Mutant | `test_history_query_edges.py` | `test_history_query.py` | the three selected suites |
|---|---|---|---|
| `_like_escape` 13 | **1 failed** — `TestLikeEscape::test_wildcards_and_backslash_are_escaped` | 28 passed | survived |
| `_like_escape` 14 | **1 failed** — same test | 28 passed | survived |
| `_clamp` 4 | **1 failed** — `TestPaginationEdges::test_limit_is_clamped_both_ways` | 28 passed | survived |
| `_clamp` 9 | **1 failed** — same test | 28 passed | survived |
| `_my_nicks` 7 | 17 passed | 28 passed | survived |
| `list_persons` 18 / 21 / 22 / 29 | 17 passed | 28 passed | survived |

So the audit's "9 survivors" meant *9 mutants no selected suite kills*. Its
description of them as "a concrete, actionable test-gap list" was right for five
and wrong for four: those four were a scoping artifact of the job.

**Widening the selection was measured and rejected.** Adding that one file
executes all 29 functions of `backend/history_query.py`, which makes **910 of
1,141 mutants reachable instead of 159** — computed by mapping the file's
executed-line coverage under `test_history_query_edges.py` onto mutmut's
per-function mutant counts. The narrow job runs in 22–28 s across three clean runs on this
machine (the audit recorded ~2 min on its own); a 5.7× larger reachable set
whose tests each build a temporary SQLite database is a different kind of gate, and `setup.cfg`
says in terms that narrowness is the point ("~1 minute instead of hours"). The
widened job's runtime was **not** measured — that part is an estimate and is
labelled as one.

Instead `tests/test_history_query_gaps.py` pins the same four guarantees at the
level the job measures — through `list_persons`, over a real database, as a page
the UI asked for — rather than as helper-level unit assertions. The duplication
is named in the file's docstring *and* in the `setup.cfg` comment beside the
selection, with the reason, so the next reader neither rediscovers it nor
deletes one side thinking the other is redundant.

### 9.3 The trap found on the way: the job silently reports 100% when conftest cannot import

mutmut 3.7.0 runs pytest **in-process** and reads any non-zero exit as "killed".
`tests/conftest.py` imports PySide6 and then `services.run` / `app.bootstrap` /
`main`; on a machine without system OpenGL or libdbus that import fails, pytest
exits **4** (usage error), mutmut raises `BadTestExecutionCommandsException`
inside its forked child, the child dies with exit status **1** — and the parent
records a kill.

Measured on this sandbox before PySide6 was installed: **1141 mutants, 159
reachable, 159 killed, 0 survived.** A perfect mutation score produced by a test
runner that never ran. Every one of the nine survivors in the audit looked
closed, including `_my_nicks` 7, which cannot be killed by any test anywhere.

Two things follow, and both are committed:

* `setup.cfg` now sets `pytest_add_cli_args = --noconftest`, with the
  measurement in the comment above it. The flag is neutral where PySide6 exists:
  with it, the job reproduces the audit's numbers exactly — **150 killed / 9
  survived / 982 no tests**, the same three integers — and none of the selected
  suites uses a conftest fixture, which the file's existing comment already
  said. What the flag removes is an environment-dependent false green.
* `mutants/` is now in `.gitignore`. The audit had to remind itself to delete it
  before committing ("mutmut leaves it untracked and it is **not** gitignored");
  an ignored directory cannot be committed by `git add -A`, which is the failure
  mode the reminder was protecting against.

Note the direction of this error: it inflates the score. A mutation job that can
only fail by reporting *too many* kills is worse than no job, because the number
is quoted (§3 of the audit quotes it) and nobody re-checks a 100%.

### 9.4 Three equivalent mutants, with the proofs, and the two pins that are conventions rather than behaviour

`_my_nicks` 7 is **unkillable and is left alive**:

> `json.loads(v or "[]")` vs `json.loads(v or "XX[]XX")`. For a truthy `v` the
> `or` short-circuits in both and the mutant never executes. For a falsy `v` the
> original parses `"[]"` to `[]`, and the mutant raises inside the `try` and
> returns `[]` from the `except`. Same value, same type, for every possible
> input.

Killing it would require spying on the argument `json.loads` receives, i.e.
pinning a string literal instead of a behaviour — §16.2's "did not game metrics"
applies to a mutation score too, so it is reported as equivalent and excluded,
which is the reporting the audit's own convention asks for ("explicit
timeout/equivalent-mutant reporting"). `TestTheIdentityListFallback` pins the
behaviour both paths share instead, and records one schema fact found while
writing it: `my_nicks` is `TEXT NOT NULL DEFAULT '[]'`
(`stores/history_schema.py:55`), so the falsy branch is reachable only through a
hand-emptied string, a non-JSON string, or a row that omits the column — a
stored NULL is impossible.

Two more mutants are equivalent **against the real engine** and were closed by
pins that are honest about being pins:

* `list_persons` 21 drops the third argument of the COUNT call.
  `HistoryDB.scalar(self, sql, params=(), default=0)` already defaults to the
  same `0`, so no test through a real database can distinguish the two. The new
  `RecordingDB` stand-in declares `default` as a **required positional**, which
  pins the call convention instead: the count's fallback belongs to the caller,
  not to whichever default the engine happens to carry today. This is the
  weakest of the twelve tests — it is the one that could be deleted without
  losing a behaviour guarantee — and it is labelled as such in its docstring.
* `list_persons` 29 lower-cases `LIMIT ? OFFSET ?`. SQLite folds keyword case,
  so the behaviour is identical and only an assertion on the emitted SQL text
  can see it. `TestTheSqlItSends` keeps that assertion because the statement is
  the contract the module documents and the paging invariant depends on, but the
  test says plainly that it pins a statement rather than an outcome. Exact-case
  SQL assertions are not new to this repo:
  `tests/test_person_page_request.py` already asserts
  `"deleted_at IS NULL AND nick_lc LIKE ? ESCAPE '\\'"` and the full
  `columns()` body character for character.

Excluding the one unkillable mutant from the denominator, the job is
**158/158 = 100%**; including it, **158/159 = 99.37%**. Both are given so
neither can be quoted selectively — the same discipline §3 of the audit applied
to its two mutation numbers.

### 9.5 Targets vs achieved

| Measure | Before | Target | Achieved | |
|---|---:|---|---|---|
| Mutants killed (reachable) | 150 / 159 = 94.34% | 9 survivors closed | **158 / 159 = 99.37%** | ✅ 8 closed, 1 equivalent |
| Survivors | 9 | 0 | **1** (`_my_nicks` 7, proved equivalent) | ✅ recorded, not chased |
| Reachable mutants (the denominator) | 159 | unchanged | **159** | ✅ not moved |
| "no tests" mutants | 982 | unchanged | **982** | ✅ |
| Job runtime | ~25 s | not hours | **~25 s** (22–28 over three clean runs) | ✅ selection stayed narrow |
| Production lines changed | — | 0 | **0** | ✅ |
| `production_nonblank_noncomment` | 23,620 | unchanged | **23,620** | ✅ |
| Mean MI (production) | 66.1135 | unchanged | **66.1135** | ✅ identical to 4 d.p. |
| Files over 500 lines | 7 | unchanged | **7** | ✅ (was 9 at F1; F2/F3 lowered it) |
| Clone groups (`clone_scan`) | 12 = baseline | 12, none new | **12, 0 new / 0 stale** | ✅ `tests/` is outside the scanner's packages |
| Exact-clone groups (`current_audit`) | 4 / 66 lines | unchanged | **4 / 66 lines** | ✅ |
| Ratchet (`HistoryQuery` 362 LOC / 14 methods) | intact | intact | **intact** | ✅ class untouched |
| vulture ≥ 90% | 7 | 7, none new | **7, none new** | ✅ |
| `rule16_gate.py --with-clones` | pass | pass | **pass** (all owned functions fit) | ✅ |
| `tests/test_rule16_new_code.py` | 23 passed | 23 passed | **23 passed** | ✅ |
| Suite (this sandbox, see caveat) | 2,323 passed | ≥ baseline | **2,338 passed** | ✅ +12 new, +3 unskipped |
| `history_query.py` coverage under the job's suites | 39% line (125/225 missed) | ≥ | **40% line (121/225 missed)** | ✅ |

**The suite caveat, stated rather than glossed.** The full 2,710-test suite could
not be run here: this sandbox has no system `libGL.so.1` and no `libdbus-1`, and
Debian's package mirrors are unreachable, so 21 test modules cannot import
PySide6's widget bindings at all (the same limitation `setup.cfg`'s existing
comment describes). What was run, with `--noconftest` and
`--continue-on-collection-errors`, is the 2,300-odd tests that do not need a
GUI toolkit:

* before the change: **2,323 passed, 6 failed, 36 errors, 7 skipped, 894
  subtests**;
* after: **2,338 passed, 6 failed, 36 errors, 4 skipped, 894 subtests**;
* the 42 `FAILED`/`ERROR` lines are **byte-identical** between the two runs
  (`diff` on the sorted lists), and every one is an `ImportError` on
  `libGL.so.1` / `libQt6DBus` or a downstream consequence of it — including
  `test_backend_api_snapshot.py::test_no_module_disappeared_or_failed_to_import`,
  which counts a module that fails to import as disappeared.

The +15 is 12 new tests plus 3 in `tests/test_rule16_new_code.py` that stopped
skipping: they `skipTest("radon not installed …")` when the tools are absent,
and this sandbox gained a `.venv` between the two runs. Repo-wide line/branch
coverage was therefore **not** re-measured, and no claim is made about it; it
cannot have fallen, since F6 adds tests and changes no production line.

### 9.6 What F6 deliberately did not do

* **No module-wide mutation run.** §9.2 measured that it would make 910 mutants
  reachable; running it is a half-hour-scale job that would very likely surface
  survivors in `page`, `around`, `db_stats` and `_search`, none of which F6 was
  scoped to fix. If the owner wants the module measured rather than the feature,
  that is its own step — call it F6b — and it should be scheduled as such, not
  smuggled into a test-only commit.
* **No change to `list_persons` itself.** Four mutants sat on
  `int(await self.db.scalar(…, 0))`, and a reader may reasonably ask whether the
  fallback should be reinforced at the call (`int(… or 0)`) instead of only
  pinned by a test. Not done: `list_persons` is an OWNED function in the RULE 16
  gate and `HistoryQuery` is under a ratchet, so touching it is a code change
  with its own equivalence gate, and F6's value is precisely that it has none.
* **No JavaScript suite run.** No JS changed; the 26 entrypoints are untouched.

---

### 9.7 Reapplied to `arena/01a09227-chat-v-bot` (2026-09-13): the same three integers, and two corrections

§§9.1–9.6 were written and measured on `arena/01a09a4e-chat-v-bot`, in a sandbox
with no PySide6 at all. This branch has a working Qt (`QT_QPA_PLATFORM=offscreen`
plus a stub `libGL` on `LD_LIBRARY_PATH`), so the step was **re-measured here
rather than trusted**. The two branches share the merge-base `6fca06d` (step
F3e), which makes F6 a single commit on a common ancestor — cherry-picked
(`4f009b1`) rather than merged, so this branch keeps its own boot-fix and F3f
history.

**How it landed.** Four of the five files applied byte-identically: `diff`
against `git show 4f009b1:<path>` is empty for `setup.cfg`, `.gitignore`, this
document and `tests/test_history_query_gaps.py`. The single conflict was
`docs/archive/README.md`, where both branches had extended a *different* bullet
inside the same two-line block. Resolved by keeping both records — §9's sentence
on the `ROUND_F_DESIGN` bullet, this branch's §8.14–§8.16 sentence on the
`ROUND_F2_F3_GOD_CLASS_DESIGN` bullet. Nothing paraphrased, nothing dropped.

**The mutation job reproduces exactly.** Measured as a 2×2 over the two things
that decide the outcome — the flag, and whether the Qt libraries are reachable:

| `pytest_add_cli_args = --noconftest` | Qt reachable | Result |
|---|---|---|
| present | yes | **158 killed / 1 survived / 982 no tests**, rc=0 |
| present | no | **158 / 1 / 982**, rc=0, 22.9 s |
| absent | yes | **158 / 1 / 982**, rc=0 — the flag is neutral here |
| absent | no | **abort: `BadTestExecutionCommandsException`, rc=1** |

All three completing runs agree on §9.5's three integers (158/159 = 99.37%,
denominator 159 reachable + 982 "no tests", 1,141 generated), and the single
survivor is `backend.history_query.xǁHistoryQueryǁ_my_nicks__mutmut_7` — the
mutant §9.4 proves equivalent. Runtime 22.9–25.7 s across the runs, inside
§9.5's 22–28 s band.

**Correction 1 — §9.3's mechanism does not reproduce under pytest 9.1.1.** §9.3
has the conftest failure exit 4 *inside the forked child*, the child die with 1
and the parent record a kill, giving a silent 159/159. Measured here, mutmut
3.7.0's `PytestRunner.execute_pytest` raises on exactly that code:

```python
if exit_code == 4:
    raise BadTestExecutionCommandsException(params)
return exit_code
```

and a conftest import failure reaches it in the **parent's** `run_stats` phase,
before a single mutant is scored — so the job aborts loudly (row 4 of the table)
instead of inflating. What the flag buys on this branch is therefore narrower and
more concrete than §9.3 states: **the job runs at all.** Row 4 *is* this sandbox
without the flag, and `mutmut run` is normally invoked without the Qt variables,
because those exist only to work around missing system libraries.

The silent path is still live, but through a different exit code — worth stating,
because it governs every future edit of `pytest_add_cli_args_test_selection`:

| pytest 9.1.1 situation | exit code | mutmut 3.7.0 reads it as |
|---|---|---|
| `tests/conftest.py` fails to import | **4** | raise → the job aborts |
| a selected **test module** fails to import | **2** | **a kill — silently** |
| everything imports, tests pass | 0 | pass |

So the invariant is: *every suite in the selection must import without Qt.* All
four currently do — each returns rc=0 with no environment variables set and
`--noconftest` — which is what makes the job environment-independent, and the new
file's only two mentions of PySide6 are docstring text, not imports. A future
suite added to that list without checking this would reintroduce exactly the
false green §9.3 was worried about, through exit 2 rather than exit 4.

**Correction 2 — §9.5's coverage percentages.** The row reads "39% → 40% line
(125 → 121 of 225 missed)". The missed counts reproduce here exactly (125 under
the three-suite selection, 121 under the four), but 100/225 and 104/225 are
**44% and 46%** as `coverage` reports them, not 39% and 40%. The counts are the
load-bearing half of that row and they are right; the percentages are not.

**Full-suite numbers, with no caveat of the kind §9.5 needed.** This sandbox
imports PySide6, so the whole suite runs:

* **2788 passed, 0 failed**, 3 skipped, 1 deselected, 1 xfailed, **894 subtests**,
  8 m 24 s — the 2776 of step F3f plus the 12 new tests, with no test changing
  status.
* Product-only coverage: line **91.76%** (14166/15438, was 91.75%), branch
  **86.96%** (3254/3742, unchanged). The statement count did not move at all —
  15438 before and after — which is §9.5's "production lines changed: 0" verified
  from the coverage data instead of asserted from the diff.
* `backend/history_query.py` under the **full** suite: 96.00% → **96.89%** line
  (216 → 218 of 225), branch 89.58% unchanged. A different measurement from
  §9.5's job-suite row, quoted separately for that reason.

**One failure appeared in the first post-cherry-pick run, and it was not F6's.**
`tests/integration/services/test_services_people.py::TestSnapshots::test_payload_falls_back_to_queue_when_engine_raises`
failed at the 15% mark with `'Bob' != 'Anna'`. It is recorded rather than dropped,
and the diagnosis is deliberately marked incomplete:

* The assertion is an ordering one. `stores/user_query.py` orders the queue with
  `ORDER BY first_seen DESC`, and SQLite ranks NULL and `''` below every text
  value, so under DESC they land **last**. Bob first therefore means Anna's row
  reached the query *without* the `first_seen` the test seeded — a lost or
  reordered write, not a wrong comparison.
* It cannot be the new file: the failure is at 15% of collection while
  `tests/test_history_query_gaps.py` is collected near the end, and every test in
  `PeopleCase` gets its own `tempfile.TemporaryDirectory()` with its own
  `users.db`, so no other process can pollute its data.
* It cannot be a code regression: `git diff 6fca06d..HEAD` touches no production
  file in that path — `backend/history_query.py`, `stores/user_query.py` and
  `stores/user_memory.py` are all byte-identical to the run that passed 2776 with
  zero failures forty minutes earlier.
* It passes 3/3 in isolation, the file passes 23/23, and the clean re-run quoted
  above passed it with no failure anywhere in 2788 tests.
* What differed about the failing run: five other pytest invocations were running
  concurrently with it (four coverage probes across two attempts, plus the
  43-second `tests/test_rule16_new_code.py` gate). This repo coalesces concurrent
  saves — the `WriteTurn` behaviour that
  `ROUND_F2_F3_GOD_CLASS_DESIGN_2026-09-12.md` §8.9–§8.10 settled and left as
  residual risk F3c. A dropped write under CPU contention is consistent with that
  and with nothing else observed. **Not proven**: seen once, under load, never
  reproduced. Named so the next reader does not rediscover it, and so the run
  that produced it is not quoted anywhere as a clean 2788.

**RULE 16 / RULE 18 recheck, in this sandbox.**

* `rule16_gate.py --with-clones` **rc=0** — all owned functions fit, ratchet
  intact (`HistoryQuery` 362/14 untouched, `HistoryBridge` 467/44 from §8.14),
  clone scan **0 new groups / 0 stale baseline entries**.
* `tests/test_rule16_new_code.py` **23 passed**, matching §9.5.
* `tests/test_history_query_gaps.py`: radon MI **A (67.84)** — §9.5 quotes 68.16,
  a radon-version difference, same grade; `radon cc -n C` reports **no block
  ranked C or worse**; **20 functions, longest 12 lines, none over §18.1's 20**;
  8 classes and one responsibility — the eight mutants its module docstring names.
* The file is **306 lines**, 6 over §18.2's 150–300 band, and it gets **no**
  `ideal-size:` note: §18.5 requires the reason to name a *constraint*, and "it
  is a test file" is not one. That is the treatment this branch already gives its
  728- and 826-line test files (F2/F3 document §8.15.4), and inventing a note
  here would be the gaming §18.5 forbids. The cherry-picked commit message says
  307 lines; `wc -l` says 306 in both trees.
* The `mutants/` ignore entry was verified working rather than assumed:
  `git check-ignore -v mutants/` → `.gitignore:18`, and `git status` stayed clean
  with 12 entries on disk. The directory was removed after the runs.

---

## 10. Steps F4, F5, F7 and F8 reapplied, and revalidated against §6's targets (2026-09-13)

### 10.1 How they arrived, and why revalidation was not optional

`arena/01a09a61-chat-v-bot` shares this branch's merge-base (`6fca06d`, step F3e)
and carries two commits: `4c21492` (F4, F7, F8 and the start of F5) and `5cdbd7f`
(the rest of F5). Both were cherry-picked — `79e407f` and `43f265c`. Only two
files were touched by both branches, and git auto-merged both correctly, which
was checked rather than assumed: `bridge/history_bridge.py` carries their
`ideal-size:` note *and* §8.14's `run_when_world_open` import and call site, and
`tests/test_world_write_gate.py` carries their import path *and* §8.15's two
`forward=False` doubles.

Revalidation was not optional here. `4c21492`'s message reports no suite run, no
gate run and no measurement of any target it claims; it lists what was written.
Every number in §§10.2–10.6 below was measured in this sandbox after the
cherry-pick, against §6's target table.

### 10.2 F4 — a legitimate note whose numbers were stale

§6's F4 target is `bridge/history_bridge.py` (542 · MI 24.2), "gate-ratcheted at
493/45: may shrink, may not grow; QWebChannel pins slots".

What arrived is a four-line `ideal-size:` note naming the QWebChannel wire
contract. That is a legitimate §18.5 reason — the rule lists "wire format" and "a
Qt slot signature" as constraints, and §7 already applied exactly this remedy to
the frozen five. The note's *numbers* were wrong for this branch:

| The note claimed | Measured here |
|---|---|
| 542 lines | **544** (539 before the note; the note is 5 lines) |
| ratcheted at 493 LOC / 45 methods | **467 / 44** — §8.14's boot-wait fix lowered it |

Both corrected, and the note now says where the lower ratchet came from. The net
change to the file against `0685d53` is **five comment lines and zero code
lines**, verified by diffing every changed line against `^+#`. MI is 24.95.

F4's size target therefore was not reduced *by F4*: the class shrank 493/45 →
467/44 through §8.14, and the note then grew the file by 5 lines — the same
tension §7 recorded for the frozen five, and recorded here for the same reason
rather than left implicit.

### 10.3 F7 — seven false claims, and prose that moved the metric it was meant to fix

§6's F7 target names two files with "low MI **without** size" and prescribes
"**decomposition and explanation, not splitting**". What arrived was explanation
only, and the explanation did not survive measurement:

| Claim in the reapplied comments | Measured |
|---|---|
| "~40 tiny functions" (`window_preset_service.py`) | **22** |
| "Every function is small (4–25 LOC)" | two are over §18.1's 20: `_grid` **24**, `validate_document` **22** |
| "worst CC is 4" | **9** (`_grid`), then 8, 8, 7, 6, 6 |
| "intentionally NOT split despite its 287 lines" | the prose made it **316** — outside §18.2's 150–300 band, carrying no note |
| "`RunProgress`: 65 LOC" | **40** |
| "`RunQueueMixin`: 183 LOC" / "a 180-line mixin" | **177** |
| "worst CC is 6" (`run/progress.py`) | **9** (`queue_order`, `_run_single_target_cycle`) |

Two structural problems sit behind the arithmetic. First, the prose **raised the
metric F7 exists to lower**: MI went 16.08 → **34.61** on `window_preset_service.py`
and 27.85 → **33.30** on `run/progress.py`, with no function decomposed. §7 said
this in terms when the frozen five gained +0.25 to +0.61 from their notes —
"§16.2 treats lifting a metric with prose as gaming" — and +18.53 is thirty times
that. Second, the `ideal-size:` annotation was on the wrong file in both
directions: `run/progress.py` carried one at 262 lines, *inside* §18.2's band,
where §18.5 has nothing to annotate, while `window_preset_service.py`, which the
prose pushed *out* of the band at 316, carried none.

Both notes were rewritten from measurement. `window_preset_service.py` is back
inside the band at **299** lines, `run/progress.py` at **258**, and every number
in both is one this section reproduces. Their MI is now 28.71 and 31.79 — still
above the pre-F7 values, and that residue is prose and must not be read as the
decomposition F7 owes. §6's decomposition half is **still open**: `_grid` (24
LOC, CC 9), `validate_document` (22), `queue_order` (CC 9) and
`_run_single_target_cycle` (31 LOC, CC 9 — over §16.1's fail line as legacy debt,
and `_run_take_phase` at 28 beside it).

### 10.4 F5 — 230 lines that nothing used, the pattern that produced them, and what got wired instead

§6's F5 target is the wide-parameter tail: "70 functions > 4 params; worst 20",
remedy "§19.4 parameter object, as `PersonPageRequest` does".

What arrived was `stores/history/history_requests.py` (230 lines, nine
dataclasses) plus `AppendPlanner.append_v2()`. Measured, not read:

* **eight of the nine dataclasses had exactly one reference in the tree — their
  own definition.** `AppendRequest` had four, all of them the unused `append_v2`.
* `append_v2` was **never called**: `git grep` finds it in its own definition, one
  docstring pointing at it, and two documents.
* the target metric did not move: **70 functions over 4 params, worst 20** — the
  same two integers §6 started from. `history_repo_append.py::append` still had
  its 13.
* the file carried an unused `field` import: pylint `W0611`, rating 9.28/10.

One precision, because it cuts against the obvious conclusion: the **tracked**
vulture metric did *not* regress (7 findings before and after). Vulture resolves
names across the whole scanned set, and `field` is imported and used by
`stores/history_models.py` (3×) and by four modules of `services/db_deletion_*`
(2–8× each), so a repo-wide scan does not report the symbol. Per-file, pylint
does. The dead code was real; the metric that would have caught it was not the
one this repo quotes.

The same blind spot is pre-existing rather than something F5 introduced:
`core/events.py` and `backend/criteria_engine.py` both import `field` and use it
zero times (the latter also imports an unused `Optional`), and neither file was
touched by this branch. Recorded as §18.3-class debt — three import lines to
delete, in two modules whose frozen status must be checked first — not paid here,
because it is outside the four steps being reapplied.

**The root cause is in the plan document that came with it.** Its "Pattern to
Follow" prescribed: add `operation_v2()` beside `operation()`, keep the old
method, "Update Call Sites (**Optional**)", "Remove Old Method (Future)". Followed
literally that yields a second API nobody calls and a metric that never moves —
the `foo_part1` / `foo_part2` shape §16.1.1 forbids. §19.4's own model does the
opposite: `HistoryQuery.list_persons(self, req: PersonPageRequest)` has no `_v2`
twin anywhere in `backend/history_query.py`.

So the eight unused dataclasses and `append_v2()` were dropped, the plan document
was rewritten around the in-place pattern, and **one object was wired for real**.
`WriteContext` was kept because its eight fields match `_after_write`'s eight
parameters exactly — same names, same order, same defaults — and because all five
of that function's call sites are inside `stores/`, so no frozen contract and no
other area had to move:

* `PersonLifecycle._after_write(ctx)` — the implementation, 41 → **40** LOC, so a
  legacy function improved rather than worsened (§16.0);
* `HistoryRepo._after_write(ctx)` — the facade, whose docstring also stopped
  naming `AppendPlanner` for a method that lives on `PersonLifecycle`;
* the two `AppendPlanner` call sites and `_touch_cursor`'s, which now omits
  `bootstrapped=None` because the field defaults to it.

Measured outcome: **70 → 68** wide functions, worst still 20. `history_repo.py`
lost two over-long lines (54 → 52 `line-too-long`), the family grew by the two
import lines (1089 → 1091), and the new `stores/history_requests.py` is 48 lines,
radon MI **A (100.00)**, no block ranked C or worse, and — the proof it is not
dead — **100% line and 100% branch coverage** from the suite.

`stores/` therefore goes 37 → **38** files. `test_stores_structure.py` pins that
count and documents every increment, so the ceiling was raised in its own idiom,
with the reason in the comment: a leaf module joining the `history_*` family,
which §18.3 counts as one module (9 → 10), holding only objects a live signature
consumes.

The metric walker, because the plan document points here:

```python
import ast, os
PKGS = ["core", "actions", "backend", "bridge", "services", "stores", "app"]
files = ["main.py"]
for p in PKGS:
    for dp, dn, fns in os.walk(p):
        dn[:] = [d for d in dn if d != "__pycache__"]
        files += [os.path.join(dp, f) for f in fns if f.endswith(".py")]

def nparams(fn):
    a = fn.args
    n = len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
    n += bool(a.vararg) + bool(a.kwarg)          # §16.1: one each
    first = (a.posonlyargs + a.args)[:1]
    return n - bool(first and first[0].arg in ("self", "cls"))

wide = [(nparams(f), p, f.name) for p in files
        for f in ast.walk(ast.parse(open(p, encoding="utf-8").read()))
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
over = sorted(w for w in wide if w[0] > 4)
print(f"wide={len(over)} worst={max(over)}")
```

Run from the repository root it prints `wide=68 worst=(20,
'actions/scroll_parse.py', '__init__')` on this branch, and printed `wide=70`
with the same worst offender before F5 was wired.

`AppendRequest` stays unbuildable for now, and the reason is a contract rather
than effort: `HistoryRepo.append` and `AppendPlanner.append` (13 params each)
have production callers in `backend/chat_sync.py`, one of the AREA D frozen five,
so migrating them is the §7 option (a) decision — the same reasoning §9.6 applied
to `list_persons`.

### 10.5 F8 — reverted by owner ruling: the move breaks AREA B's frozen surface

§6's F8 target is `stores/`'s module count, "37 files vs RULE 18.3's ~15 —
promote a family to a sub-package; **lowest urgency**".

What arrived did promote the family: nine `stores/history_*.py` files moved to
`stores/history/`, 36 files' imports updated, `stores/` down to 28. It also broke
the build, and the commit that did it reports no suite run. Five tests failed:

* `tests/unit/stores/test_stores_public_api.py` — four of them, including
  `test_the_three_frozen_modules_did_not_move_at_all`, reporting
  `stores.history_db disappeared`, `stores.history_models disappeared`,
  `stores.history_repo disappeared`;
* `tests/unit/stores/test_stores_structure.py::TestClassSize::test_public_method_counts`
  — `KeyError: 'stores.history.history_repo'`, because `MAX_PUBLIC`'s module keys
  were updated to the new paths while the *historical* `api_baseline_pre_b1.json`
  they are compared against still uses the old ones.

AREA B's contract is explicit: its test fails on "any change at all inside the
three frozen modules", and the plan it implements says at §7.3 rule 1 that "**No
area renames, moves, or changes the signature of any symbol that another area
imports**". A move is a rename of every import path.

**Owner ruling, 2026-09-13: revert.** §6 rates F8 the lowest-urgency step in the
round, and spending a frozen guarantee — the golden file whose whole purpose is
proving no public surface moved — is a poor trade for it. That is §7's reasoning
for AREA D applied to AREA B, and as there it is the owner's call, not the
implementer's. Refreshing the baseline remains available later as its own
reviewed change.

Reverted by restoring 33 paths to `0685d53` and deleting `stores/history/`; the
three F4/F7 files were deliberately excluded from the restore so their corrections
survived, and §8.15's work in `test_world_write_gate.py` came back with the old
import path intact. Verified after: no `stores.history.` or `stores/history/`
reference remains anywhere in the tree, the stores contract tests pass
(**39 passed, 606 subtests**), and the F6 and F3f suites still pass
(**83 passed**). `F8_IMPLEMENTATION_SUMMARY.md` was deleted, since the
implementation it summarises does not exist on this branch; this section is its
record instead. `stores/` keeps its 37 files, plus F5's one, and §18.3's debt
stands unpaid and documented.

### 10.6 Targets vs achieved

| Step | §6's target | Achieved on this branch | |
|---|---|---|---|
| **F4** | `bridge/history_bridge.py` 542 · MI 24.2; ratcheted 493/45, may shrink not grow; QWebChannel pins slots | §18.5 note kept — the QWebChannel slot contract is a constraint the rule accepts — with its numbers corrected to **544 lines** and the **467/44** ratchet §8.14 produced. Net **5 comment lines, 0 code lines**; MI 24.95 | ✅ documented · ⚠️ size not reduced by F4 |
| **F5** | wide-parameter tail: 70 functions > 4 params, worst 20 | **68**, worst 20. `WriteContext` wired into `_after_write`, its facade and all five call sites; eight unused dataclasses and `append_v2()` dropped; plan document rewritten around in-place migration | ⚠️ 2 of 70 — real, not claimed complete |
| **F7** | MI 16.1 / 27.8 *without* size; needs **decomposition and explanation**, not splitting | Explanation rewritten from measurement (seven of its claims were false); both files back inside §18.2's band at **299** / **258**. **Decomposition not done** — `_grid`, `validate_document`, `queue_order`, `_run_single_target_cycle` all still owe it | ❌ half of two halves |
| **F8** | `stores/` 37 files vs §18.3's ~15; promote a family; lowest urgency | **Reverted by owner ruling.** The move breaks AREA B's frozen surface (5 failing tests) and plan §7.3 rule 1. Debt stands, documented | ❌ not applied |

### 10.7 Verification

The cherry-picked state, before any correction, was **not** green: 5 failed /
2783 passed / 521 subtests. That run is recorded here and quoted nowhere else as
a result. After the corrections:

* Suite: **2788 passed, 0 failed**, 3 skipped, 1 deselected, 1 xfailed, **897
  subtests**, 8 m 36 s. Same test count as `0685d53` (2788) with no test changing
  status; the +3 subtests are `test_stores_public_api.py` iterating the new
  module's public names.
* Product-only coverage: line **91.77%** (14183/15455, was 91.76% at 14166/15438),
  branch **86.96%** (3254/3742, unchanged). The +17 statements are the new
  parameter-object module (13) and three import lines; all are covered.
* `stores/history_requests.py` **100% line and branch**; the three migrated files
  held or improved (`history_repo_lifecycle.py` 96.19 → 96.23%,
  `history_repo_append.py` 98.34 → 98.35%, `history_repo.py` 89.43 → 89.52%).
  `window_preset_service.py` stays **100%/100%** and `run/progress.py` 90.77%,
  neither having changed but prose.
* `rule16_gate.py --with-clones` **rc=0** — all owned functions fit, ratchet
  intact (`HistoryQuery` 362/14, `HistoryBridge` 467/44), clone scan **0 new
  groups / 0 stale baseline entries**.

### 10.8 RULE 16 / RULE 18 recheck

* **§16.0** — the one legacy function whose signature changed improved: 41 → 40
  LOC. Nothing in `OWNED` was touched; `OWNED` covers only `history_query.py` and
  `history_bridge.py`, so no ratcheted function moved.
* **§16.1 / §16.2** — the new file is one dataclass: radon MI **A (100.00)**, no
  block ranked C or worse, no function at all. The two rewritten docstrings and
  the corrected note are comment-only. No `_v2` twin, no dispatch table, no
  re-hosted body: the migration changed one signature and five call sites.
* **§16.2 anti-gaming, applied to this step itself** — the MI rise F7's prose
  produced was removed rather than kept, and the residue that remains is labelled
  as prose in §10.3 so no later reader books it as progress.
* **§18.1** — no function added. The two over-ideal functions F7's comment
  misdescribed (`_grid` 24, `validate_document` 22) are now named accurately and
  recorded as owed.
* **§18.2** — repo-wide re-measured: **171 files, median 132, 7 still over 500**
  (was 170 / 134 / 7). `window_preset_service.py` returned to the band at 299;
  `stores/history_requests.py` is 48 lines, which §18.2 calls normal and good for
  a leaf pure-data module. No `ideal-size:` note was invented: the only one added
  is F4's, on a 544-line file that genuinely exceeds the band, citing a Qt slot
  contract §18.5 lists.
* **§18.3** — `stores/` is 38 files, still past ~15, held by prefix families
  (`history_*` now 10, `label_*` 6, `media_*` 4). F8's attempt to fix this by
  sub-package is reverted and the debt is recorded rather than paid.
* **§18.5** — every number in every note added or rewritten here was measured in
  this sandbox before it was written, and each note's own line count agrees with
  the file it sits in (`bridge/history_bridge.py` says 544 and is 544;
  `run/progress.py` says 258 and is 258).
