# Round H design — the ungated tail: make it visible, then burn it down

Date 2026-09-14 · branch `arena/01a09a119-chat-v-bot` · base `5197ce0` ("upd").
Required by RULE 16 §16.6 step 2 and RULE 17. Every number in §1–§2 was
re-measured from this tree, not quoted from a report; the commands are in
**Reproduction** at the end, and the full six-category audit is
`reports/CODE_QUALITY_METRICS_2026-09-14.md`.

**Status: design only. No step of this round has been started** — the
instruction for this session was to measure, research and plan. No production
file was modified; the tree is clean (`git status --short` empty apart from this
document's own folder).

## 1. What the tree looks like on the day this round is planned

Headline numbers (audit §Executive summary has the full table):

| Dimension | Your threshold | Measured 2026-09-14 | Verdict |
|---|---|---:|---|
| Cyclomatic complexity (max) | ≤ 10 | 10, **0 above** | ✅ |
| Cognitive complexity (max) | ≤ 15 | 15, **0 above** | ✅ |
| Nesting (max) | ≤ 3–4 | 4, **0 above** | ✅ |
| Function LOC (max) | ≤ 20–30 | 107 (JS-literal builder), 39 functions > 30 | ⚠️ |
| Class LOC (max) | ≤ 200–300 | 467, 36 classes > 150 | ❌ |
| Params (max) | ≤ 3–4 | 20 (RULE 3 wire), 11 functions > 4 | ⚠️ |
| Methods per class (max) | ≤ 10–15 | 44 (facade), 24 classes > 15 | ❌ |
| File LOC (max) | ≤ ~300 | 601, 23 files > 300 | ❌ |
| Line / branch coverage | ≥ 80% / ≥ 75% | 92.64% / 88.03% | ✅ |
| Mutation score | ≥ 70% | 99.37% (158/159) | ✅ |
| Test : production ratio | ~1 : 1 | 1 : 1.57 | ✅ |
| Maintainability index (min / mean) | higher is better | 24.9 / 68.05; 16 files < 40 | ⚠️ |
| JS coverage | (no floor exists) | 82.8%; 6 files never loaded | ⚠️ |
| **Gate blast radius** | every production change | **20 files = 9.6% of files, 11.9% of LOC** | ❌ |

### 1a. What changed since the last recorded snapshot

Round G closed at 2,828 tests / 91.38% line / 87.51% branch / 24 attributed JS
files at 80.18% (`docs/archive/2026-09-13-round-g-write-gate/G7_BACKLOG_DESIGN_2026-09-13.md` §6).
The AI Bot Chat surface has since landed with its tests — `services/bot_*.py`,
`bridge/bot_*.py`, `ui/js/bot-*.js`, `dark-select.js` — and the measured effect
is uniformly positive: **+344 tests, +1,786 JS lines attributed, +2.6 pp JS
coverage, +1.26 pp line, +0.52 pp branch**, with the complexity ceiling unmoved
at 10 / 15 / 4 and the parameter tail held at its documented 11-entry floor.
Nothing in §1b got worse; the mass simply moved from "unmeasured" to "measured".

### 1b. Why the tail is still where it was

Three rounds (F, G, and the AI-bot rounds) have attacked size by *target*: F1,
F2/F3, G2, G3, G7 each split one named file or class. The tail did not close,
because the gate they were measured against has almost no breadth (audit §1c):

| Enforcement | Scope | Share |
|---|---|---|
| Function limits | 164 named functions in 20 files (`OWNED`) | 7.2% of 2,268 functions |
| Class limits | classes in those 20 files, minus 3 `RATCHET`-exempt | 21 of 279 classes |
| File size | **nothing measures it** | 0% |
| Offenders outside enforcement | 39/39 long functions · 33/36 oversized classes · 21/23 oversized files · 11/11 wide signatures | ~90% |

And `RATCHET` is a ceiling, not a floor: `HistoryQuery` is measured at **310 LOC
against a frozen cap of 362**, so the worst class in the worst file may grow
**+17%** with the gate green. `HistoryBridge` (467) and `ScrollRunPart` (197) sit
exactly at their caps and cannot grow — the ratchet is two-sided for two of the
three and one-sided for the one that matters most.

This is the finding that decides Round H's first step, and it is a *process*
finding, not a size one: **the debt is now concentrated in exactly the places
the project has stopped looking.**

## 2. Prioritisation — why H1 is first, and what "biggest problem" means here

Ranked by severity class first (a broken guarantee beats structural mass), then
by what is spendable without an owner decision. Same logic as Round G §2.

1. **P1 — the gate cannot see 90% of the tree (§1b).** Every later step in this
   round is a size reduction, and a size reduction is only durable if the size
   cannot come back. Splitting `history_bridge.py` by hand while nothing measures
   its regrowth is the Round-F/G failure mode repeating a fourth time. H1 first,
   because it is also the cheapest step (~12 h) and it *protects every other one*.
2. **P2 — the size/cohesion mass itself.** 28.4% of production LOC in 23 files;
   36 classes over 150 LOC; worst MI 24.9. Ranked by (impact × feasibility)
   among the offenders, not by line count: H2 (`history_bridge.py`) is the only
   file that is simultaneously the worst MI, the biggest class, and the biggest
   coverage hole.
3. **P3 — coverage holes in 16 modules**, with the sharpest single fact in the
   audit: `backend/cdp_client` is the tree's **second most-depended-upon module**
   (Ca 21) and is covered at **63.14%**; `backend/message_injector_send` — the
   code that decides whether a message is sent — is at **21.13%**.
4. **P4/P5/P6 — the function-length tail, the JS half, the incoherent god
   classes.** Real, measured, but none of them is a guarantee that is currently
   broken. They fill the later steps.
5. **P7 — hygiene drift** (16 oversized files with no `ideal-size:` reason, one
   stale note, 34 untriaged unused imports). Cheap; folded into the steps that
   touch those files rather than given a step of its own, except where H1 can
   enforce it for free.

Deliberately **not** ranked high: module counts (§18.3 — `services/` 51 files,
`backend/` 44, `stores/` 38; the prefix-family convention holds and re-cutting
450 import paths is not this round's spendable work), the facade classes the
house shape keeps on purpose (`HistoryRepo` 44 methods, `LabelStore` 38,
`MediaStore` 33, `HistoryDB` 30), and churn / bug density / TDR, which are still
not honestly measurable from a one-commit checkout (audit §5).

## 3. Step plan — Round H (each step sized ≈ 8–16 h)

| # | Step | Target | Size driver |
|---|---|---|---|
| **H1** | **The gate sees the whole tree (tree baseline + two-sided ratchet)** | `tools/metrics/rule16_gate.py`, `reports/quality/tree_baseline_2026-09-14.json`, `tests/test_rule16_new_code.py` | §4 |
| **H2** | `bridge/history_bridge.py` — the worst file on three axes | 544 → facade + `history_*` parts; `HistoryBridge` 467/31 → ≤ 150/x; MI 24.9 ↑; coverage 62.25% → ≥ 90% | §5 |
| **H3** | `backend/history_query.py` — the worst file by size, and the one class with ratchet headroom | 601 → family; `HistoryQuery` 310/14 → ≤ 150/x; RATCHET lowered to the measured number; the `_my_nicks` survivor closed or proven | §6 |
| **H4** | `backend/dom_highlight.py` 514 + `backend/config_manager.py` 511 | both split under the AREA D golden; the stale `ideal-size:` note corrected; `config_manager` 82.09% ↑ | §7 |
| **H5** | `backend/cdp_client.py` 331 (Ca 21 @ 63.14%) + `backend/chat_parser.py` 426 + `backend/media_handler.py` 474 | split by protocol concern, payloads moved to `backend/js/` with harnesses; coverage ≥ 90% on `cdp_client` | §7 |
| **H6** | The `stores/` long-but-cohesive family | `SchemaMigrator` 407/25, `PersonLifecycle` 375/19, `AppendPlanner` 325/18, `MediaFetcher` 306/15 + the five 360–464-line store modules → helper-module extraction (§19.5) | §8 |
| **H7** | The `services/` incoherent god classes | `RunCoordinator` .97, `Collector` .95, `UndoService` .95, `RunQueueMixin` .94, `DbLifecycle` .88 → decompose by responsibility; `db_registry`'s private-name call made public-or-gone | §8 |
| **H8** | The function-length tail **outside** H2–H7 | 39 functions > 30 LOC → 0 above 30 except documented JS builders; aim ≤ 20 | §9 |
| **H9** | Coverage floors for the weak modules + the 12 embedded payloads | every production file ≥ 85% line / ≥ 80% branch or a named, dated exemption in `reports/`; payloads harnessed under `tests/js_harness.js` | §9 |
| **H10** | The JavaScript half gets a floor | 6 never-loaded files (1,239 lines) get harnesses; weakest loaded files → ≥ 85%; `js_coverage.py --check` + CI wiring | §10 |

Steps are independent enough to be executed out of order **except H1**, which
should land first because every other step's durability is measured by it.
Estimated total: **~140–155 h** of focused work.

## 4. H1 — the gate must see the whole tree

### 4.1 Problem, precisely

`rule16_gate.py` today has three scopes: `OWNED` (164 functions in 20 files,
hard gate), `RATCHET` (3 classes, ceiling-only) and `SMELL_FILES` (8 files). A
new production function *anywhere else* is not measured at all — RULE 16 §16.0's
"new production function → hard fail" is honoured by convention and review, not
by a runner. With one squashed commit in this checkout there is no base-SHA diff
to define "new" either, so the only workable definition is **a committed
baseline plus growth detection**.

### 4.2 The change

* `tools/metrics/rule16_gate.py` gains a tree mode that enumerates **every**
  production function, class and file under the eight roots and measures the same
  six axes it already measures (`loc, params, cc, cognitive, nesting`; class `loc`
  and `methods`; file `loc`).
* A committed baseline, `reports/quality/tree_baseline_2026-09-14.json`, records
  the measured number per symbol per axis. **Growth on any axis of any recorded
  symbol is a breach.** Shrinking is always allowed.
* A new symbol above a §16.1 hard limit is a breach (`> 30` LOC, `> 4` params,
  `> 150` class LOC, `> 15` methods, CC `> 10`, cognitive `> 15`, nesting `> 4`).
* A recorded symbol that no longer exists is **stale** and must be deleted from
  the baseline — the same discipline `CLONE_BASELINE`'s staleness check already
  uses, so the baseline cannot rot into a list of ghosts.
* A file over 300 lines with neither an `ideal-size:` note nor a baseline
  entry is a breach. This is how P7 stops being invisible, and it reuses the
  §18.5 mechanism the reader already knows.
* `RATCHET` becomes **two-sided**: exactly the recorded number or lower, for all
  three classes. That alone closes the `HistoryQuery` +52-line loophole.
* `--report` prints the burn-down table (symbols over each ideal, by area), so
  each later step in this round can show its own delta without re-deriving it.
* `--baseline` regenerates the file. Regeneration is an explicit, reviewed act
  whose diff names what grew — never a way to make a red gate green.

### 4.3 Tests (RULE 8 — each must fail with the feature removed)

1. A synthetic baseline in a temp tree where one recorded function is 2 LOC
   larger **fails**; the same tree at the recorded size **passes**.
2. A synthetic new function of 40 LOC in a file with no baseline entry **fails**.
3. A synthetic 320-line file with no `ideal-size:` note **fails**; adding the
   note **passes**.
4. A baseline entry whose symbol has been deleted is reported stale (**fails**)
   — proving the baseline cannot grow dead entries.
5. `RATCHET` growth of 1 LOC on `HistoryQuery` **fails** (the two-sided change),
   where today it would pass at anything up to 362.
6. The existing canary (`HistoryQuery.page` over the 30-LOC limit) still proves
   the measurement is not vacuous.

### 4.4 What H1 must not become

The failure mode is a gate that fails 200 items on day one and is bypassed with
`--no-verify` until someone deletes it. Therefore: **the baseline is allowed to
record today's debt; only growth, new offenders and stale entries fail.** The
burn-down is a report, not a fail line, until the steps below have paid it — at
which point the baseline is re-generated as a *smaller* file, and the diff of the
baseline is the round's progress statement.

Rejected dishonest simplification: deriving "new" from `git diff --name-only`.
It only works in a repository with usable history, it fails silently in a
squashed checkout, and it makes the gate's answer depend on what a developer
happened to commit together (a refactor that moves a function would read as
"new" and fail, while a new function added to an already-changed file would be
invisible). The baseline is boring and always correct.

## 5. H2 — `bridge/history_bridge.py`: the worst file on three axes

**Evidence.** 544 lines (SLOC 450) — 2nd largest file in the tree; **MI 24.9, the
worst maintainability score anywhere**; `HistoryBridge` 467 class LOC, 31 direct
methods (44 by the gate's nested-inclusive count), LCOM\* 0.86; **122 missing
statements and 49 missing branches — the largest coverage hole in the
repository** (62.25%); `RATCHET` frozen at exactly 467/44, i.e. at its cap with
no headroom, which is why nothing has moved here since F3d re-froze it.

**Method** (the G7 §4 `StackBridge` pattern, which is now the house recipe for a
QWebChannel bridge): keep a thin wire facade that owns the **7 Signals + 23
@Slots** byte-for-byte — that set is the JavaScript contract and cannot move —
plus a lazy `_parts` bundle holding cohesive parts in `bridge/` (`history_read`,
`history_write`, `history_media`, …). The slots delegate; nothing else changes.

**Verification battery.**
* Tests first (RULE 8): extend `tests/test_history_bridge.py` until it pins every
  behaviour that will move, then run it after each extraction. Target ≥ 90% line
  on the whole `history_*` bridge family and ≥ 80% branch.
* `tools/metrics/dump_public_api.py` against both goldens: the *blocks* twin must
  stay byte-identical; the `backend`/`actions` snapshot is not touched by a
  `bridge/` change, which is exactly why this file is the right first target.
* The JS side is the real contract test: the facade's slot names must not move,
  so the Node suites that drive `__cvbPush`/history rendering (`test_history_*`)
  are the equivalence gate — 29/29 green before and after.
* `RATCHET[("bridge/history_bridge.py","HistoryBridge")]` is **lowered** to the
  post-split numbers in the same commit; after H1 it is two-sided, so it can only
  ratchet down.

**Size:** ~16 h (the slot-preserving split is one pass; the coverage work is the
larger half).

## 6. H3 — `backend/history_query.py`: the worst file by size

**Evidence.** 601 lines — the largest file in the tree; MI 35.3; `HistoryQuery`
310 LOC / 14 methods at LCOM\* 0.74; two functions in the > 30 LOC tail
(`page` 53, `_search` 49); 20 missing statements; the configured mutmut job
leaves **982 mutants unreachable** in this module with `person_stats` accounting
for the bulk; the single surviving mutant (`_my_nicks` 7) lives here; and the
`RATCHET` cap (362) permits the class to grow 52 lines — the loophole H1 closes.

**Method.** Split by concept, in RULE 19 order: the functions are *long and flat*
(§19.5), so step 4 applies — extract per phase (`filters`, `item shaping`,
`paging`, `stats`) behind the existing public names. The AREA D golden records
the public surface of `backend/`, so the split is facade + module-level helpers,
and the golden is refreshed in-step under the F0 ruling with **conservation
accounting** (removed ∅, changed list enumerated, added list enumerated).

**Verification battery.**
* The four suites that already pin this path (`test_history_query.py`,
  `_edges`, `_gaps`, `test_person_page_request.py`) are the equivalence gate, plus
  the mutmut job: reachable mutants 159 → must not drop, killed must not drop.
* `person_stats`' unreachable cluster: either a new test reaches it, or the
  reason is recorded in `setup.cfg`'s job notes (the file already documents why
  narrow selection is not inflation).
* The survivor is closed one of two ways, both acceptable: a test that pins an
  observable difference, or an explicit "provably equivalent" entry in the
  baseline with the F6 §9 proof quoted. What is **not** acceptable is deleting
  the test-selection note that explains it.
* `RATCHET` lowered to the measured post-split numbers; `HistoryQuery` must come
  out ≤ 150 LOC or carry a recorded reason it cannot (the golden is the only
  plausible reason, and it is not binding after F0).

**Size:** ~16 h.

## 7. H4 / H5 — the rest of the `backend/` tail

| Step | Files | Evidence | Target |
|---|---|---|---|
| **H4** | `backend/dom_highlight.py` 514 (MI 54.9, 5 embedded payloads = 198 of the 420 payload lines, 4 unused-import re-exports), `backend/config_manager.py` 511 (82.09%, 38 missing statements, 22 missing branches, stale `ideal-size:` note says 507) | both pinned by AREA D; both carry a `NOTE` because a previous round deferred them | payload builders split into `backend/js/` + harness; config split by section (the sections are already named in `config/*.json`); note corrected; each file ≤ 300 lines |
| **H5** | `backend/cdp_client.py` 331 (**Ca 21 — 2nd most depended-upon module — at 63.14%**), `backend/chat_parser.py` 426 (20 missing statements, 3 unused imports), `backend/media_handler.py` 474 (53-line payload, 17 missing statements) | `cdp_client` is the single highest-leverage untested module in the tree by fan-in | `cdp_client` split by protocol concern (connect / evaluate / events) behind its existing class API — Ca 21 means the *names* are the contract; WebSocket error/retry paths tested (the 80 missing statements are mostly there); payloads moved to `backend/js/` and driven through the Node harness (RULE 8) |

`dom_highlight.py::interpret_click` sits at **exactly CC 10** — no headroom. This
step must not touch its decisions; it may only move code around them (§16.5: do
not worsen a legacy metric; you cannot improve CC without deleting a real
decision, and §16.2 forbids that).

**Size:** ~16 h each.

## 8. H6 / H7 — the two shapes of oversized class

The audit separates them, so the round does too.

**H6 — long but cohesive** (`LCOM*` 0.06–0.21): `SchemaMigrator` 407/25,
`PersonLifecycle` 375/19, `AppendPlanner` 325/18, `MediaFetcher` 306/15, plus the
five 360–464-line store modules around them (`history_schema_repair` 441,
`history_repo_lifecycle` 441, `media_fetch` 464, `history_repo_append` 366,
`history_repo_identity` 365). These are single-responsibility units
that happen to be long, so §19.5's remedy applies: **extract by phase**, not
decompose by responsibility. The store API is golden-pinned (`stores_api.py`
baseline, `test_stores_public_api.py`), so the step refreshes that baseline
in-step with conservation accounting, exactly as G7 §2 did for the wide-parameter
seven.

**H7 — large and incoherent** (`LCOM*` 0.74–0.97): `RunCoordinator` .97,
`Collector` .95, `UndoService` .95, `RunQueueMixin` .94, `DbLifecycle` .88 (and
`CDPClient` .91, whose file split is H5's — its cohesion pass rides along there). For these, RULE 19 steps 1–3 come first: an
incoherent class usually holds a flattened-but-real decision that belongs in a
named collaborator, and splitting before flattening just distributes the same
confusion (RULE 19's opening caveat). Extract into the existing conventions
(`services/run/*`, `services/collector_*`, `services/undo_*`).
Also in this step: `services/db_registry.py:289` calls
`db_deletion._append_db_files(...)` — a private name across a module boundary,
currently *documented* by a re-export shim. Make it public-and-named or remove
the need; do not leave a third state.

**Verification battery (both).** Tests first for every moved behaviour; the
structure tests that pin these families (`tests/unit/stores/test_stores_structure.py`,
`test_collector_structure.py`) stay green; class limits are re-checked by hand
before the gate sees them; every new class ≤ 150 LOC / ≤ 15 methods (§16.1).

**Size:** ~16 h each.

## 9. H8 / H9 — the two residues

**H8 — the function-length tail outside H2–H7.** 39 functions > 30 LOC today.
Two are closed as exemptions rather than splits: `backend/dom_probe.py::build_probe`
107 (one JS string literal, §16.1.5) and `actions/scroll_parse.py::config_schema`
44 (a schema table — data, not decision logic); both keep their recorded
`ideal-size:` reason. Twenty-eight move inside H2–H7 (H2 4, H3 2, H5 2, H6 13,
H7 7). **The residue this step owns is exactly 9:**

| LOC | Function | Shape (RULE 19 §19.5) |
|---:|---|---|
| 41 | `backend/message_injector.py::type_search` | sequential attempts → extract per rung |
| 40 | `bridge/layout_bridge.py::get_app_state` | payload assembly → extract per section |
| 39 | `actions/cancellation.py::_as_predicate` | nested predicate → name the compound (§19 step 3) |
| 39 | `actions/click_user.py::execute` | phase ladder → extract per phase |
| 34 | `backend/message_injector_type.py::_try_set_value` | flat fallback ladder |
| 34 | `actions/cancellation.py::sleep_with_stop` | at CC 10 — flatten first (§19 step 2) |
| 31 | `actions/mark_messaged.py::execute` | phase ladder |
| 31 | `actions/scroll_parse_run.py::to_scroll_options` | field mapping → table |
| 31 | `backend/scroll_parser_dom.py::settle` | polling loop → named predicate |

**Anti-gaming (§16.2):** no `foo_part1`, no one-line re-host helpers, no
flag-inferred control flow. Success is "no function above 30 except the two
documented exemptions", not "a smaller number". The residue is re-measured at the
start of the step, because H2–H7 will have moved some of these lines.

**H9 — coverage floors for the weak modules.** Worst-first, to
**≥ 85% line / ≥ 80% branch per production file**, or a dated, named exemption in
`reports/` for the ones that are structurally unreachable (the WebEngine-only
paths). The list is the audit's §3 table: `message_injector_send` 21.13%,
`app/lifecycle` 59.74%, `layout_bridge` 67.29%, `chat_text` 70.13%,
`db_deletion_flow_remove` 70.14%, `db_registry` 70.48%, `collector_bridge` 72.11%,
`db_deletion_scan` 73.47%, `cancellation` 73.55%, `people_bridge` 76.15%,
`label_bridge` 77.97%, `media_fetch` 78.65%, `db_lifecycle` 80.95%,
`db_deletion_flow` 81.03%, `config_manager` 82.09%.
Then: harness the **12 embedded JS payloads / 420 lines** through
`tests/js_harness.js` so they stop being inventory (§16.3 "JS probes go through
the harness", RULE 8 "tests execute the real thing"), and only after two
consecutive full runs hold the new numbers, raise the stored floors in
RULE 16 §16.3 (today's 92.64 / 88.03 are above the recorded 91.31 / 87.43 of the
G7 battery).

**Size:** ~12 h / ~16 h.

## 10. H10 — the JavaScript half gets a floor

**Evidence.** 30 attributed files, 11,895 lines, **82.8%** covered; **6 files
never loaded by any Node test** (`app.js` 510, `stack-drag.js` 356,
`url-toolbar.js` 168, `criteria-editor.js` 85, `composer.js` 81, `log-console.js`
39 = 1,239 lines); weakest loaded `presets-ui.js` 47.3%, `sash-grid.js` 64.2%,
`user-table.js` 66.1%, `stack-dnd.js` 67.8%, `history-store.js` 70.7%,
`window-presets.js` 73.1%; and **no floor exists** — the baseline is a
measurement, so nothing fails if `presets-ui.js` drops 10 points.

**Method.** Harnesses for the six never-loaded files (the file boundary is the
test boundary, as it is for Python); the six weakest loaded files to ≥ 85%;
`tools/metrics/js_coverage.py` gains `--check` with the floor as a ratchet
(`CLONE_BASELINE` discipline: may rise, may not fall) and is wired into
`tools/ci/quality-gate.yml`.

**Blocked-on-owner note (unchanged from G7):** that CI file still is not active —
a GitHub App token may not author `.github/workflows/*`, so someone with
`workflows` permission has to copy it into place. Until then the JS floor runs
from the pre-commit hook and by hand. This step must not delete
`tools/ci/quality-gate.yml` while it waits.

**Size:** ~16 h.

## 11. Anti-gaming rules every step in this round inherits (§16.2, §18.5)

* No `foo_part1` / `foo_part2`; extractions are allowed only when the new name
  states a real responsibility.
* No re-baselining to make growth legal: a baseline refresh is a reviewed commit
  whose diff names what grew.
* No deleting a real decision to move a complexity number (the four-binary-outcome
  floor of CC 5 stands).
* No splitting a JS/HTML literal to shrink a file (§16.1.5).
* Every new function has a test that fails if it is deleted (§16.3); every new
  class is ≤ 150 LOC and ≤ 15 methods (§16.1); new code aims at RULE 18's ideals
  (function 4–20, file 150–300), and every deviation carries an `ideal-size:`
  reason naming a constraint.
* `quality-override:` only with a real constraint, one per metric per symbol, and
  deleted the moment it goes stale (§16.4).
* Steps that move complexity across files write their own archived design doc
  (§16.6 step 2) before the first edit — H2–H7 each owe one, in this same folder.

## 12. Deliberately not in this round

* **§18.3 module counts.** `services/` 51 files, `backend/` 44, `stores/` 38,
  `actions/` 26 — the prefix-family convention (`collector_*`, `history_repo_*`,
  `db_deletion_*`, `undo_*`) is doing its job and is ratcheted by
  `tools/metrics/stores_modules.py`. Re-cutting them into sub-packages rewrites
  hundreds of import paths for a cohesion gain the tests do not currently show.
* **The facades that are correct by design.** `HistoryRepo` 44 methods,
  `LabelStore` 38, `MediaStore` 33, `HistoryDB` 30 — one-line delegations over a
  family, the shape RULE 19 §19.4 itself recommends for wide surfaces.
* **TDR, churn and bug density.** They need a full-history clone and a bug-fix
  convention; a tooling task, not an analysis one (audit §5 says so and refuses
  to invent numbers).
* **LCOM\* as a gate.** It stays a triage signal: it punishes parameter objects
  for being what they are.
* **Adding analysis packages to `requirements.txt`** — §16.8 keeps them in
  `requirements-dev.txt`.

## 13. RULE 16 / RULE 18 recheck of this plan (§16.7, self-review)

```text
[x] no production code changed by this round yet — measured, not assumed:
    rule16_gate.py PASS (owned functions fit, ratchet intact, no stale overrides)
    rule16_gate.py --with-clones PASS (0 new clone groups, 0 stale baseline entries)
[ ] tree-wide limits enforced ............ H1 (this is the gap H1 closes)
[ ] no oversized files > 300 without a reason ... H1 enforces; H4 fixes the one stale note
[ ] coverage floors ..................... held: 92.64% line / 88.03% branch
    (recorded baseline 91.31 / 87.43 at G7; §16.3 floors 80 / 75) ✅
[ ] mutation score ...................... 99.37% (158/159 reachable), one proven-equivalent survivor ✅
[ ] JS measured, no floor ............... 82.8%; floor is H10
[ ] every step's size target aims at RULE 18 and states its deviation reason
[ ] every step above that moves complexity across files owes its own design doc (§16.6 step 2)
[x] this document is an archive doc, not a context file — RULE 18 §18.4's 60–200 line
    budget does not apply to docs/archive/
[x] docs/current/ unchanged in line count: AGENT_RULES.md 730 (at its ~730 budget),
    SYSTEM_OF_RECORD.md 343, DOM_SELECTORS.md 338 — the metrics row in
    SYSTEM_OF_RECORD §8 was re-stated in place, not extended
[x] docs/README.md + docs/archive/README.md index the new folder and the true counts (RULE 17)
```

## 14. Reproduction

Every number in §1–§2 and every "Evidence" line in §5–§10 comes from the
commands in `reports/CODE_QUALITY_METRICS_2026-09-14.md` §Reproduction,
executed on this tree in this session (Python 3.11.2, Node v22.22.3,
PySide6 6.11.2):

```bash
.venv/bin/python tools/metrics/current_audit.py > /tmp/audit_h.json
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs COVERAGE_FILE=/tmp/.coverage_h \
  .venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q -p no:cacheprovider \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
COVERAGE_FILE=/tmp/.coverage_h .venv/bin/python -m coverage json -o /tmp/coverage_h.json
.venv/bin/python tools/metrics/js_coverage.py --json /tmp/js_cov_h.json
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/mutmut run --max-children 2
```

Suite: 3,172 passed, 2 skipped, 1 deselected, 1 xfailed, 902 subtests — 471 s.
Raw artifacts stayed outside the checkout (`/tmp/audit_h.json`,
`/tmp/coverage_h.json`, `/tmp/js_cov_h.json`, `/tmp/mutmut_results.txt`);
`mutants/` was deleted after the mutation run so the tree is clean.
