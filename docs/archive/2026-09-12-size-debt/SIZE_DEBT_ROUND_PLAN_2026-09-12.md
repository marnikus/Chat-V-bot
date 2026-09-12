# Size-debt round — plan + step 1 (chat_sync split)

Round 4 of the code-quality rounds. Date 2026-09-12, base commit a882f73
(port of the DB-undo-restore feature). This doc records the measured problem,
the full prioritized step queue (~8–16 h per step), the design, and the
implementation log for **step 1 only** (the agreed scope for this round).

## 1. Measured problem (a882f73, audited 2026-09-12)

Fresh audit (`tools/metrics/current_audit.py` → `audit_round2.json`), against
the six-part framework: complexity (CC≤10 / cognitive≤15 / nesting≤3–4),
size (fn≤20–30 / class≤200–300 / params≤3–4 / methods≤10–15), coupling,
coverage (≥80% line / ≥75% branch), smells, maintainability.

| Part | Measured | Verdict |
|---|---|---|
| CC | mean 3.11, max 10, zero >10 | fits |
| cognitive | mean 2.16, max 17 (2 fns >15) | 2 soft targets left |
| nesting | max 4, 15 fns >3 | fits (soft band 3–4) |
| **fn LOC** | mean 9.60, max **122** (`build_probe`), **42 fns >30**, 192 >20 | **debt** |
| **class LOC** | **11 classes >300** (Collector 518, ScrollParser 507, HistoryBridge 474, SchemaMigrator 386, PersonLifecycle 369, MediaFetcher 342, AppendPlanner 338, HistoryQuery 312, StackBridge 308, ScrollParse 306, …) | **debt** |
| **file LOC** | **10 files >500** (below), 18 more in 301–500 | **debt** |
| methods/class >15 | 27 classes (HistoryRepo 44, Collector 39, LabelStore 38, ScrollParser 37, MediaStore 33, HistoryBridge 31, StackBridge 31, HistoryDB 30, SyncSession 24, …) | debt |
| params >4 | 70 fns (max 20) | debt |
| coverage | **line 94.88%, branch 82.55%** (measured this round, full suite + branch) | fits both thresholds |
| duplicates | 4 clone groups / 66 lines, all ratcheted (0 new) | fits |
| dead code | vulture: 1 unused import (actions/registry.py `Iterator`), 2 unused vars, `_MAX_QUIET_RETRIES` (removed in step 1) | trivial |
| maintainability | mean MI 64.45; prod 22 960 lines, tests 36 148 (test:code 1:1.57); churn hotspots bridge.py 38, action_engine 24, config_manager 20, collector 20, chat_parser 19 | acceptable |

The ten >500-LOC files (the bulk of the debt, ~5 600 lines):

| file | LOC | file | LOC |
|---|---|---|---|
| backend/chat_sync.py | 791 | services/undo_service.py | 564 |
| backend/scroll_parser.py | 674 | bridge/history_bridge.py | 537 |
| services/db_deletion.py | 665 | backend/dom_highlight.py | 523 |
| backend/history_query.py | 606 | services/db_deletion_flow.py | 509 |
| services/collector_service.py | 593 | backend/config_manager.py | 502 |

**Biggest problem: size debt** — 10 files >500 LOC + 42 fns >30 LOC + 11
classes >300 LOC, concentrated in the same hotspots the churn data flags.
Complexity and coverage are already inside the framework, so the round
targets size only.

## 2. Step queue (one file or tight pair per step, ~8–16 h each)

Order = file size × churn × class debt. Every step ends on the same gates
(§4). Steps 2–10 are planned but not implemented in this round.

- **S1 (this round) — `backend/chat_sync.py` (791).** Split by phase into the
  `backend/chat_sync/` package (7 files, façade re-exports the full old API).
  §3 is the design; §5 the implementation log.
- **S2 — `backend/scroll_parser.py` (674) + class ScrollParser (507 LOC / 37 methods).**
  Split the god class by method family (probe / parse / scroll / cache) into
  a `backend/scroll_parser/` package or sibling modules behind the same façade.
- **S3 — `services/db_deletion.py` (665) + `services/db_deletion_flow.py` (509).**
  One pipeline, two files: split by pipeline stage (request / apply /
  restore / purge) so each file owns one stage.
- **S4 — `backend/history_query.py` (606, 3 fns >30) + `backend/dom_highlight.py` (523).**
  Note: HistoryQuery is RULE-16-ratcheted (class 362 LOC / 14 methods) — the
  gate allows it to shrink, never grow; the split must keep the ratchet entry
  valid or update it by the documented procedure.
- **S5 — `services/collector_service.py` (593, Collector 518 / 39 m) + `services/collector_tick.py` (425).**
  The tick loop is the natural seam: state machine vs. one-tick executor.
- **S6 — `services/undo_service.py` (564) + `bridge/history_bridge.py` (537, 4 fns >30).**
  HistoryBridge is ratcheted (493 / 45) and QWebChannel-pinned — split
  internals only, never the slot surface.
- **S7 — `backend/config_manager.py` (502) + `backend/message_injector.py` (478, `_run_type_strategies` 70 LOC) + `backend/media_handler.py` (478).**
  Kills the second-worst function in the repo; config_manager is a churn
  hotspot (20) — split by config domain (agent / archive / run / UI).
- **S8 — `backend/dom_probe.py` (`build_probe` 122 LOC, the worst function) + `backend/chat_parser.py` (423, 2 fns >30) + remaining 301–500 files that fit (router 471, media_fetch 458, history_repo_lifecycle 432, history_schema_repair 420).**
- **S9 — class-size + params pass.** Remaining classes >300 LOC and >15
  methods not dissolved by S2–S8 (HistoryRepo 44 m, LabelStore 38 m,
  MediaStore 33 m, StackBridge 31 m, HistoryDB 30 m, SyncSession 24 m — seam
  already identified: extract opening/closing phases, §5.5), plus the 70
  fns with >4 params (introduce option objects, one file at a time).
- **S10 — long tail + close-out.** 150 fns in 21–30 LOC, 15 fns with
  nesting >3, the 2 cognitive >15 fns, vulture dead code, churn∩size
  hotspots, then full re-measure: audit + gate + coverage + report, and ratchet
  whatever improved.

Rejected: "split everything by LOC count" (ignores cohesion — a file is one
responsibility, RULE 18 §18.4), and "refactor the >500 files' logic while
moving it" (mixes two changes; moving code must stay byte-identical so the
suite proves equivalence — logic changes get their own step with its own
tests).

## 3. Step 1 design — `chat_sync.py` → package

The file's debt is **breadth, not depth**: 63 functions, max 28 LOC (none
>30), but 7 small-to-medium classes in one 791-LOC file. The module itself
documents the phase structure, so the split follows it:

```
backend/chat_sync.py (791)            backend/chat_sync/ (package)
  SyncOptions (73)                →   options.py    (89)
  MODE_*, ReadPlan, SyncPlanner   →   plan.py       (142)
  merge_live, SyncSession (248)   →   session.py    (286)
  SyncPersister (133)             →   persist.py    (146)
  SLICE_RETRIES, ChunkReader (72) →   reader.py     (88)
  DeltaAligner (31)               →   align.py      (44)
  run_sync (25)                   →   __init__.py   (78) — façade + run_sync
```

Rules followed:

1. **Façade, not rename.** `__init__.py` re-exports every old public name,
   so the three consumers (`backend/chat_parser.py`, the two chat_sync test
   files) need zero import changes — proven by the battery (§5.3).
2. **No runtime import cycles.** `session` → `{options, plan, persist}`;
   `persist`/`reader`/`align` reference `SyncSession` only under
   `TYPE_CHECKING` (annotations are lazy via `from __future__ import
   annotations`). `chat_parser` → `chat_sync` stays one-way.
3. **Byte-identical move.** No logic line changed; the only deletion is the
   dead constant `_MAX_QUIET_RETRIES` (defined at line 52, referenced
   nowhere in the repo — verified by grep before removal).
4. **Gate coverage kept honest.** `tools/metrics/dump_public_api.py`
   silently skipped subpackages (`module_names` did `if info.ispkg:
   continue`), so a package split would have *removed* the chat_sync public
   API from the AREA-D snapshot without failing anything. `module_names` now
   recurses into real subpackages (directories with `__init__.py`; data dirs
   like `backend/js` stay skipped) and the snapshot was refreshed by the
   documented procedure — all 7 public classes + `run_sync` + `merge_live`
   are pinned, now under their true modules.
5. **Deliberate residue (soft target only).** `SyncSession` keeps 248 LOC /
  24 methods. It fits every enforced RULE 16 threshold and the RULE 18 file
  band; 24 methods > the 10–15 soft band. Extracting its opening/closing
  phases into `SyncOpener`/`SyncFinalizer` would change the surface the
  phases tests drive directly — deferred to S9 with the seam identified
  here, so S9 doesn't re-research it.

## 4. Hard gates (every step, re-run at the end of this round)

- [x] full suite green: **2708 passed / 0 failed / 4 skipped / 1 xfailed / 777 subtests** (778.58 s)
- [x] `rule16_gate.py --with-clones` **exit 0** — owned functions fit, ratchet intact, 0 new clone groups, 0 stale
- [x] AREA-D snapshot test green after documented refresh; diff reviewed: only chat_sync entries moved, plus the pre-existing stale entries the refresh caught up (PersonPageRequest etc.)
- [x] stores import-count test: 40 → 41 with dated comment (the façade keeps one `from stores.history_models import SyncResult` for `run_sync`'s return annotation)
- [x] RULE 18 re-check on the new files: all 7 files 44–286 LOC (band 150–300, none over); max fn 28 LOC (threshold 30); 7-file module (sweet spot 5–15)
- [x] coverage (full suite, branch): line 94.88% / branch 82.55% — above both thresholds; chat_sync package files 87.9–100%

## 5. Step 1 implementation log (what actually changed)

1. Created `backend/chat_sync/` (7 files above); `git rm backend/chat_sync.py`.
   Total 876 LOC vs 791 — each module carries its own docstring/imports, the
   expected package tax.
2. `tools/metrics/dump_public_api.py` — `module_names` recurses into
   subpackages (the gate-coverage gap, §3.4).
3. `tests/unit/backend/backend_api_snapshot.json` — refreshed via
   `dump_public_api.py --write`; hand-reviewed: chat_sync classes now pinned
   under `backend.chat_sync.{align,options,persist,plan,reader,session}`,
   `run_sync` under the façade.
4. `tests/unit/stores/test_stores_public_api.py` — count 40 → 41, dated
   comment (the invariant is "stores refactor forces no import edits"; a
   package façade adding one annotation import is the legitimate bump the
   test's own comment describes).
5. Nothing else touched: no gate-table change (chat_sync is not an OWNED
   file), no consumer import change, no logic change.

## 6. Baseline → after (step 1)

| metric | before (a882f73) | after (step 1) |
|---|---|---|
| largest backend file | 791 (chat_sync) | 674 (scroll_parser — S2 target) |
| files >500 LOC | 10 | 9 |
| chat_sync package files | — | 7, all 44–286 LOC |
| suite | 2708/0 (baseline) | 2708/0 (identical) |
| gate | exit 0 | exit 0 (ratchet intact) |
| coverage line / branch | 94.88% / 82.55% (measured after) | same code, re-measured green |

Next: S2 (scroll_parser) on request — design first (the ScrollParser god
class needs a method-family survey before the cut lines are drawn).

## 7. Round status, 2026-09-12 (afternoon) — parallel session found

A second session (`arena/01a09227-chat-v-bot`, tip `82bfae8`, pushed
09:16 UTC) landed while this round was running. It did its own CC closure
(waves C/D/E1/E2 — same end state: 0 fns > CC 10), its own hand port of the
DB-undo-restore feature (`e4ef002`, "and fix the gate it left held" — differs
from this branch's port `a882f73` in exactly two files: `undo_archive.py`,
`undo_timeline.py`), and its own size round **Round F** whose step F1 split
`services/db_deletion.py` (665 → 6-file prefix family, shim 55 LOC).
Its design doc: `docs/archive/2026-09-12-round-f-size-tail/ROUND_F_DESIGN_2026-09-12.md`
on that branch.

Independently re-verified on `82bfae8` (worktree at `/home/user/measure01a09227`):

| check | this branch `7671f8b` | their branch `82bfae8` |
|---|---|---|
| suite | 2708/0 (777 subtests) | 2710/0 (777 subtests; WebEngine-GL test deselected — see below) |
| rule16 gate `--with-clones` | exit 0 | exit 0 |
| coverage line / branch | 94.88% / 82.55% | 94.89% / 82.54% |
| files >500 LOC | 9 (scroll_parser 674 largest) | 9 (chat_sync 800 largest) |
| fns >30 LOC / params >4 | 42 / 70 | 42 / 70 |
| mean MI | 64.82 | 65.27 |

The two size rounds are complementary, not duplicate: **their F1 = my S3**
(db_deletion), **my S1 = the file their doc §2 calls "structurally frozen"**
(chat_sync). Their §2 hit the exact same `dump_public_api.py` package-skip
limitation that §3.4 of this doc fixed — their option (a) was "refresh the
snapshot" (losing API pinning for those modules); the tool fix implemented
here achieves the split *while keeping* every chat_sync public class pinned
under its true submodule in the refreshed snapshot.

Divergences to decide before the rounds can converge (owner decision):

1. **Two ports of the same feature.** Theirs claims a gate fix in
   `undo_archive.py`/`undo_timeline.py` that mine lacks.
2. **WebEngine probe missing on their branch.** This branch's `59f45eb`
   (CC-tail restore) carries the `_qt_webengine_works()` subprocess probe in
   `tests/test_sash_webengine.py`; without it, their tree's full suite
   SIGABRTs in this sandbox (no GL) — that is why it was deselected above.
3. **Queue dedup.** Union view: S1/F1 done (both), S2 = scroll_parser
   (674/699) is the next shared step — on this branch it is unblocked by the
   snapshot tool fix; their branch's doc leaves it "frozen" pending decision.

