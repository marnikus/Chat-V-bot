# Code quality audit — Round I baseline (2026-09-14)

**Date:** 2026-09-14 · **Branch:** `arena/01a09e20-chat-v-bot` · **Commit:** `c0e18a2`
("Merge the pushed G/H1-H2 history with the locally-rebuilt H3-H7 work")
**Scope:** `core/ actions/ backend/ bridge/ services/ stores/ app/ main.py`
(206 production files, 30,947 physical lines / SLOC 20,065, 2,113 functions,
239 classes)

Every number below was re-measured from this tree for this report — static
metrics with `tools/metrics/current_audit.py`, tests with a full
`coverage run --branch` suite (460s), mutation with the configured
`[mutmut]` job, smells with vulture 2.16 + pylint 4.0.8 + `clone_scan.py`,
and the gate with `rule16_gate.py --with-clones` **with the tools present**
(see F7). Reproduction commands at the end.

---

## 0. Headline

**Complexity still closed. Tests still strong (suite identical to Round H,
mutation reproduces G5's 90.0% exactly). The remaining debt is one band
down from Round H: eighteen files at 300–399 lines, nineteen files under
MI 45 — of which eight are *in-band* files whose MI is density, not
length — plus three actionable classes over 300 lines, two real logic
duplications the gate does not scope, and a hygiene tail (one duplicate
class definition, one dead import, stale exemption headers).**

The audit's first job, as always, was re-testing the inherited claims
rather than quoting them. Round H's closing aggregates reproduce (§1);
its per-step exit table does not (F1). The current sizes are ground
truth; the plan in `docs/archive/2026-09-14-round-i/` is built on them.

---

## 1. The six metric families, measured

### 1.1 Complexity — closed (unchanged)

| Metric | Threshold | Measured | |
|---|---|---:|---|
| Cyclomatic complexity | ≤ 10 | max **10**, mean **2.97**, median 2, p95 7, **0** above | ✅ |
| Functions at the CC ceiling | — | **5** | ✅ |
| Cognitive complexity | ≤ 15 | max **15**, mean 2.01, **0** above | ✅ |
| Nesting depth | ≤ 3–4 | max **4**, **0** above | ✅ |

The five at CC 10 (the watch list — a single new `if` pushes one over):

| CC | Cog | LOC | Function |
|---:|---:|---:|---|
| 10 | 9 | 16 | `services/undo_support.py::_migrate_entry` |
| 10 | 7 | 31 | `services/run/cycle_plan.py::choose_cycle_mode` |
| 10 | 5 | 21 | `backend/config_manager.py::set_state` |
| 10 | 4 | 15 | `backend/private_gate.py::_foreign_authors` |
| 10 | 2 | 9 | `stores/label_filter.py::set_filter` (zero-`if` coalescing, G6) |

### 1.2 Size and volume — the debt, one band down

| Metric | Threshold | Measured | |
|---|---|---:|---|
| Function LOC | ≤ 20–30 | mean 9.46, median 7, p90 20, p99 35 | ✅ |
| Functions > 30 LOC | few | **36** (1.7%; H baseline: 38) | ⚠️ tail |
| Longest function | — | 122 (`dom_probe.build_probe`, §16.1.5 JS literal) | ✅ exempt |
| RULE 18.1 band (4–20 LOC) | aim | **62.7%** (H: 62.6%) | ⚠️ |
| **Files ≥ 400 LOC** | RULE 18 | **2** (`router` 527, `schema_repair` 460, both argued) | ✅ |
| **Files 300–399 LOC** | RULE 18 | **18** | ❌ **the target** |
| Class LOC | ≤ 200–300 | **4** over 300 (same 4 as H) | ⚠️ |
| Classes > 150 LOC | — | **39** | ⚠️ inventory |
| Methods declared > 15 | ≤ 10–15 | **25** (facades — see §3) | ⚠️ |
| Methods reachable > 15 (H6) | — | **46**, max **73** (`RunCoordinator`) | ⚠️ see §3 |
| Parameters declared > 4 | ≤ 3–4 | **52** (max 20; G4 artefact reading stands) | ⚠️ |
| Parameters effective > 8 (H6) | — | **57** (max 24) | ⚠️ see §3 |

The 18 files at 300–399 (the Round I size backlog):

| LOC | MI | File | Shape (see plan) |
|---:|---:|---|---|
| 380 | 49.1 | `backend/message_injector.py` | (a) message- vs search-typing, 1 caller each |
| 379 | 43.3 | `stores/history_repo_append.py` | (c) `AppendPlanner` LCOM\* 0.17 — argue |
| 373 | 44.8 | `stores/history_repo_identity.py` | (a) row-shaping fns vs identity class |
| 360 | 56.4 | `backend/dom_highlight.py` | dup delete (−52) then (a) builders vs interpreters |
| 359 | 53.9 | `actions/base.py` | in-band-adjacent, MI fine — no step |
| 359 | 45.2 | `backend/history_query/query.py` | MI fine, ratcheted — no step |
| 349 | 41.8 | `services/db_lifecycle.py` | (b)-lite or (c): `DbLifecycle` 1 component |
| 342 | 38.3 | `services/window_preset_service.py` | (c) G8 artefact — re-verify, skip |
| 340 | 55.0 | `actions/scroll_parse.py` | (c): block+schema are one concept — argue |
| 332 | 37.5 | `bridge/file_bridge.py` | (a) preset-apply collaborator (feature envy) |
| 331 | 36.7 | `backend/cdp_client.py` | (a) `CdpLease` → own module |
| 330 | 39.4 | `bridge/stack_bridge.py` | (b) preset-family mixins, H1-shape + wire guard |
| 312 | 41.1 | `services/preset_io.py` | research, lean (c): pure format library |
| 310 | 44.5 | `services/db_registry.py` | (a)-lite: deletion-inventory cluster |
| 308 | 36.2 | `services/history/mutate.py` | (b) legacy-import + world-undo mixins |
| 305 | 100.0 | `backend/dom_highlight_js.py` | JS payload — no step |
| 302 | 55.3 | `stores/history_repo_media.py` | MI fine — no step |
| 300 | 56.7 | `stores/history_db.py` | MI fine — no step |

### 1.3 Coupling and cohesion — healthy, god classes re-disproved

| Module (largest) | Ca | Ce | I |
|---|---:|---:|---:|
| `core.events` | 27 | 0 | 0.00 (stable foundation) |
| `bridge.router` | 1 | 17 | 0.94 (composition root — correct) |
| `services.run.coordinator` | 1 | 16 | 0.94 (composition root — correct) |
| `backend.cdp_client` | 18 | 0 | 0.00 |

No module is both heavily depended upon and heavily dependent. **No change.**

LCOM components were re-derived per class (§3): every large class is one
giant component plus disconnected *static utility* singletons
(`config_schema`, `normalise_nick`, `from_options`, `new_op_token`) — the
classic LCOM false positive, not a split signal. The single-component
large classes (`StackBridge` 31, `DbLifecycle` 24, `AppendPlanner` 19,
`SyncSession` 23, `CDPClient` 21, `HistoryMutateService` 15,
`LabelAssignments` 18) are cohesive: **LCOM wins, do not scatter**
(§18.2). There are still **no god classes** — reconfirmed with data,
not quoted.

Two honest micro-signals: `UndoService._clean_blocks/_clean_history` and
`UndoProjection.clean/stack_projection/kind_projection` are static-behaviour
pairs/singletons that belong at module scope (step I13).

### 1.4 Tests — strong, H-products have gaps

| Metric | Target | Measured | |
|---|---|---:|---|
| Suite | green | **2,869 passed**, 3 skipped, 1 xfailed, 903 subtests | ✅ identical to H |
| Line coverage | ≥ 80% | **91.15%** (H: 91.17) | ✅ |
| Branch coverage | ≥ 75% | **87.12%** (H: 87.15) | ✅ |
| Mutation score | ≥ 70% | **90.0%** (360/400 reached; G5 reproduced exactly) | ✅ |
| Test : code | ~1:1 | **1.55 : 1** (38,830 : 25,076) | ✅ |
| JS suites | green | **26 / 26** | ✅ |
| RULE 16 gate (tools present) | clean | owned fit, ratchet intact, 0 new clones, 0 stale | ✅ |

Coverage gaps that are Round-H products (step I11): `send_button.py`
**21.1%**, `history_media.py` **37.6%**, `history_bridge.py` 76.8%,
`media_download.py` 72.2%, `history_delete.py` 72.6%, `cdp_client.py`
63.1% (pre-existing). RULE 16.3 requires every new function to have a
test that fails if deleted — the H splits met the suite-green bar but
two of their new files are barely executed.

### 1.5 Code smells — two real duplications, one dead import

| Smell | Measured | |
|---|---|---|
| Exact-AST clones (audit) | **2** groups, 26 lines | ✅ |
| `clone_scan` header groups | **11**, all baselined, gate green | ✅ |
| pylint R0801 logic clones | **2** pairs (F4 — ungated inventory) | ❌ step I2 |
| Same-file duplicate definitions | **2** (`dom_highlight.py`, F2) | ❌ step I1 |
| Vulture ≥ 90 tree-wide | **7**: 1 dead import + 6 protocol-allowed | ⚠️ step I1 |
| Scanner-dodging import (F3) | **1** (`export.py` local `import os`) | ❌ step I1 |
| Long methods / god classes | 36 fns > 30 (1.7%) / **0** genuine | ✅/✅ |

### 1.6 Maintainability

| Metric | Measured | |
|---|---|---:|
| Mean MI | **69.30** (H: 69.32) | ✅ |
| Files below MI 45 | **19** (H: 19) | ⚠️ |
| Files below MI 40 | **7** | ⚠️ |
| corr(LOC, MI) | **−0.804** (H: −0.819) | length still dominates… |
| …but MI<45 *in-band* files | **8 of 19** (density, not length) | ❌ new: argue, don't split |
| Technical-debt ratio | not computed (no tracker baseline) | — |
| Code churn / bug density | **unmeasurable** — git history is 1 commit | — |

The eight density-MI files (all < 300 LOC — splitting any of them to
raise MI would be metric-gaming): `label_assignments` 37.7@242,
`layout_service` 38.9@234, `coordinator` 40.7@216 (`;`-chained
one-liners), `chat_sync/session` 40.8@279, `window_preset_bridge`
40.9@193, `history/runtime` 43.0@262, `window_preset_store` 43.6@87,
`undo_support` 44.4@292. Step I13 writes the per-file argument from
measurement, H-(c)-style.

---

## 2. Before → now (H closing → this audit)

| Metric | H closing | **Now** | Δ |
|---|---:|---:|---|
| Suite | 2,869 / 0 failed | **2,869 / 0 failed** | = |
| Subtests | 903 | **903** | = |
| Line coverage | 91.17% | **91.15%** | −0.02 pp (noise) |
| Branch coverage | 87.12→87.15% | **87.12%** | −0.03 pp (noise) |
| Mutation (scoped) | 90.0% (G5) | **90.0% re-run** | = reproduced |
| JS entrypoints | 26 / 26 | **26 / 26** | = |
| Production files | 206 | **206** | = |
| Total physical lines | 30,895 | **30,947** | +52 (merge) |
| SLOC | 20,037 | **20,065** | +28 (merge) |
| Functions | 2,107 | **2,113** | +6 (merge) |
| CC max / over | 10 / 0 | **10 / 0** | = |
| Cognitive max / over | 15 / 0 | **15 / 0** | = |
| Nesting max / over | 4 / 0 | **4 / 0** | = |
| Functions > 30 LOC | 38 (H baseline) | **36** | −2 |
| Files ≥ 400 | 2 | **2** | = |
| Files MI < 45 | 19 | **19** | = |
| Mean MI | 69.32 | **69.30** | −0.02 |
| Classes > 300 | 4 (same 4) | **4 (same 4)** | = |
| Gate | green | **green (tools present)** | = (scopes verified) |

Read together: the merge preserved Round H's aggregates almost exactly.
The debt moved nowhere because Round H finished what it aimed at
(files ≥ 400) — what remains is the next band down plus the inventory
Round H correctly left behind.

---

## 3. Correcting and extending the record

**F1 — Round H closing §2's per-step exits do not reproduce.**
Seven of the ten H3–H7 "after" sizes are 34–185 lines smaller than the
current tree, while §1's aggregates and the tree total (+52) reproduce:

| File | H §2 claimed | Current | Δ |
|---|---:|---:|---:|
| `services/collector_tick.py` | 35 | 69 | +34 |
| `stores/media_fetch.py` | 150 | 233 | +83 |
| `backend/config_manager.py` | 181 | 285 | +104 |
| `backend/media_handler.py` | ~190 | 231 | +41 |
| `stores/history_repo_lifecycle.py` | 182 | 264 | +82 |
| `backend/chat_parser.py` | 151 | 263 | +112 |
| `backend/message_injector.py` | 260 | 380 | +120 |
| `backend/dom_highlight.py` | 175 | 360 | +185 |

The splits themselves all exist in the tree (owners, gate, mixins,
payload module — verified file by file); only the claimed final sizes
are wrong. This audit treats current sizes as ground truth. Two of the
eight (`message_injector`, `dom_highlight`) are back over the 300-band
and re-enter the backlog on their merits (§1.2), not as "regressions".

**F2 — `backend/dom_highlight.py` defines `ElementMatch` and `Overlay`
twice** (lines 58/110, 86/138 — byte-identical, ~52 lines). The second
copies silently shadow the first; behaviour-neutral, which is why the
suite is green. A tree-wide AST scan for duplicate top-level
definitions finds these two and nothing else. Almost certainly a
rebuild/merge artefact. Neither clone detector sees same-file
duplication (both require ≥ 2 files) — step I1 deletes the copies and
adds the duplicate-definition guard the gate never had (proved
non-vacuous by reintroducing one).

**F3 — `services/history/export.py::_ensure_media_dir` keeps `import os`
function-local for the stated reason that hoisting it "would break that
baseline entry".** Shaping code to fit the scanner is exactly what §16.2
/ §18.5 forbid. Step I1 hoists it; if a new header group appears it is
argued in the baseline like the other eleven, not dodged.

**F4 — two real logic duplications pylint sees and the gate does not.**
The gate scopes pylint to blocks mentioning owned files, so these are
inventory, not breaches — but unlike the 11 baselined header groups,
these copy *logic*: (a) the 6-line JS candidate-label idiom in
`dom_highlight_js.py` (`_LABEL_JS`) vs inline in `dom_probe.py`;
(b) the ~10-line fail-open-predicate + wrapped-callback guard in
`backend/chat_sync/options.py` vs `backend/scroll_parser/parser.py`.
Step I2 single-sources both (JS fragment; `actions/cancellation.py`
owns the stop protocol) with byte-identical behaviour pinned by the JS
harness and the pipeline tests.

**F5 — the two `# ideal-size` headers cite stale numbers.**
`router.py` says 508 lines / MI 44.9, actual 527 / 46.8;
`history_schema_repair.py` says 440, actual 460. The arguments still
hold; the numbers drifted during H itself. Step I1 re-derives them
(and the growth during an exemption is itself a warning: exempt files
need a freeze-or-re-argue rule — step I14).

**F6 — H-product coverage gaps** (§1.4). New files `send_button.py`
(21.1%) and `history_media.py` (37.6%) are barely executed. Step I11
takes the five worst H-touched files to ≥ 80% with tests that fail if
deleted (RULE 8), not line-covering filler.

**F7 — the gate was verified with tools present, and its scopes with
it.** This sandbox previously had no `.venv`, so vulture/pylint
reported "NOT CHECKED — not a pass" in every round. With tools
installed the gate is **green**, and the two scoping decisions check
out as designed, not vacuous: vulture runs on the two owned files
(`SMELL_FILES`), pylint findings filter to owned-file blocks. The
tree-wide vulture 7 and pylint 2 are therefore correctly *inventory*.
The gap is that "zero new smells on the diff" (§16.4) has no tree-wide
enforcement — step I1 documents the inventory and step I14 records the
widen-or-allowlist decision rather than silently widening (widening
today would breach on six rule-allowed protocol signatures).

**F8 — small doc drift:** `docs/README.md` says "165 Python test files"
(actual 186); `AGENT_RULES.md` is 781 lines against its ~730 budget
(recorded 772 — over by 51, and §18.4 requires extract-before-add on
the next edit); `tests/` gained the H guard files the map does not
name. Step I1 fixes the counts; step I14 does the budgeted rules edit.

---

## 4. Prioritised backlog (hands over to Round I)

1. **Size band 300–399 with real seams** (§1.2 table): `file_bridge`,
   `stack_bridge`, `mutate`, `cdp_client`, `message_injector`,
   `dom_highlight`, `history_repo_identity`, `db_registry`
   (+ `db_lifecycle`/`preset_io` research-gated). Steps I3–I10.
2. **Duplication + hygiene inventory** (F2/F3/F4/F5/F8 + dead import):
   steps I1–I2. Small, first — it removes known-bad lines before any
   split measures against them.
3. **H-product coverage gaps** (F6): step I11.
4. **Verdict spikes with data, not splits**: `RunCoordinator` 73
   reachable (landmine — measure mixin coupling, then verdict +
   guard), `_DeleteState` 21 fields (per-phase usage clusters),
   `ScrollParse`/`AppendPlanner`/`SyncSession`/`preset_io` artefacts:
   step I12.
5. **Density-MI artefact record** (§1.6): step I13. Explicitly *not*
   splits — the anti-gaming case, argued per file.
6. **Rules + closing**: SLOC-budget edit with §18.2 extraction,
   exemption freeze-or-re-argue rule, full re-measurement, Round I
   closing: step I14. Round H backlog items #1 (WebEngine skip marker)
   and #2 (SLOC budget) close in I1/I14; #3–#4 into I12/I3–I10;
   #5 (mutation re-run) closes **with this audit**.

---

## Reproduction

```bash
# static audit (this report's §§1.1–1.3, 1.5–1.6)
python3 tools/metrics/current_audit.py > /tmp/audit_now.json

# full suite + branch coverage (~460s; webengine deselected, pre-existing abort)
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
python3 -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
COVERAGE_FILE=.coverage python3 -m coverage json -o /tmp/coverage_now.json

# mutation (scoped job, ~60s at ~23 mut/s)
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs python3 -m mutmut run
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs python3 -m mutmut results

# gate with tools present (symlink .venv/bin/{vulture,pylint,radon} first —
# _tool() only looks there; without them the smell checks report NOT CHECKED)
python3 tools/metrics/rule16_gate.py --with-clones
python3 tools/metrics/stores_modules.py
python3 -m vulture --min-confidence 90 core actions backend bridge services stores app
python3 -m pylint --disable=all --enable=R0801 backend/ bridge/

# JS suites
for f in tests/test_*.js; do node "$f" | tail -1; done
```

Measured on Python 3.11, Radon 6.0.1, cognitive-complexity 1.3.0,
vulture 2.16, pylint 4.0.8, mutmut 3.7.0, pytest 9.1.1, PySide6 6.11
(headless via `tools/build_stubs.py` against system site-packages).
