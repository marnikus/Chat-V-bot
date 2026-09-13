# Code quality audit — 2026-09-13

Snapshot: `37d43b4` ("Round F F5 + F8"), branch `arena/01a09b51-chat-v-bot`.
**No production code was changed to produce this audit.** Every number was
re-measured from the tree with the commands in **Reproduction** at the end.

Organised against the six requested categories: complexity, size,
coupling/cohesion, tests, smells, maintainability. The prioritised remediation
plan this audit hands over to is **Round G**:
`docs/archive/2026-09-13-round-g/ROUND_G_PLAN_2026-09-13.md`.

## Executive summary

**Complexity stays closed. Size is still the debt — but the shape of it changed.**

Across **2,058** production functions there is still **not one** above Radon
cyclomatic complexity 10 and **not one** nested deeper than 4. Two functions sit
at cognitive 17, both recorded exemptions. *(Superseded by round G: see the
G6 closing note at the end of this section — max cognitive is now 15, and the
population sitting exactly at CC 10 fell from 16 to 5.)* Tests are the strongest they have
been: **2,800 passed / 3 skipped / 0 failed** plus **897 subtests**, line
coverage **90.87%**, branch **86.94%**, and all **26** JS entrypoints green.

What is left is mass and density, and the F5/F8 round moved exactly the metrics
it aimed at while leaving the top of the list untouched:

* wide-parameter functions **70 → 51** (F5 hit its recorded floor inside
  `stores/`, and stopped where frozen contracts start);
* `stores/` measured at **15 effective modules** (F8), in band for RULE 18.3;
* files over 500 lines **10 → 7**, but the **top two are unchanged**:
  `backend/chat_sync.py` 807 lines at **MI 11.4** and `backend/scroll_parser.py`
  706 at MI 28.6.

The single most important finding is unchanged from 2026-09-12 and is now
**blocking the whole remaining top of the list**: five of the seven oversized
files live in `backend/`, which the frozen AREA D public-API snapshot forbids
splitting into packages or sibling modules. Round G therefore opens with that
decision (**G0**) instead of pretending the ordinary recipe is available.

### Before → now

| Metric | 2026-09-12 (`e4ef002`) | **2026-09-13 (`37d43b4`)** | Direction |
|---|---:|---:|---|
| Python tests passed | 2,710 / 0 failed | **2,800 / 0 failed** | +90 |
| Python subtests | 777 | **897** | +120 |
| Line coverage | 90.41% | **90.87%** | +0.46 pp |
| Branch coverage | 86.30% | **86.94%** | +0.64 pp |
| Mutation score (scoped) | 94.34% | **99.37%** (158 killed / 1 survived of 159 reachable) | +5.03 pp |
| Production Python files | 154 | **171** | +17 |
| Production nonblank/noncomment | 23,136 | **23,823** | +687 |
| Test nonblank/noncomment | 36,178 | **37,914** | ratio 1 : 1.59 |
| Functions | 1,997 | **2,058** | +61 |
| Max Radon CC | 10 | **10** | held |
| Functions CC > 10 | 0 | **0** | held |
| Mean CC | 3.09 | **3.03** | −0.06 |
| Functions cognitive > 15 | 2 | **2** | held (both exempt) |
| Functions nesting > 4 | 0 | **0** | held |
| Functions > 30 LOC | 42 | **43** | +1 |
| Functions > 4 params | 70 | **51** | **−19 (F5)** |
| Classes > 150 LOC | 38 | **38** | flat |
| Classes > 300 LOC | 11 | **9** | −2 |
| Classes > 15 methods | 25 | **25** | flat |
| Files > 500 lines | 10 | **7** | −3 |
| Files > 300 lines | 29 | **26** | −3 |
| Mean maintainability index | 64.85 | **66.36** | +1.51 |
| Files below MI 40 | 22 | **19** | −3 |
| Exact clone groups | 11 | **12** (0 new vs baseline; gate green) | baselined |
| JS test entrypoints | 26 / 26 | **26 / 26** | held |

Read together: the round bought **breadth** (params, modules, mean MI) and did
not touch **depth** (the two worst files). That is the whole argument for Round G's
ordering.

---

## 1. Complexity metrics

Scope: all 171 production Python files under `core`, `actions`, `backend`,
`bridge`, `services`, `stores`, `app`, plus `main.py`. Excludes tests, `tools/`,
vendored assets, frontend JavaScript, generated caches.

| Metric | Your threshold | Measured | Verdict |
|---|---|---:|---|
| Cyclomatic complexity (max) | ≤ 10 per function | **10** | ✅ at the ceiling, none above |
| Functions with CC > 10 | 0 | **0 / 2,058** | ✅ closed |
| Mean / median / p95 CC | — | 3.03 / 2 / 8 | ✅ healthy distribution |
| Cognitive complexity (max) | ≤ 15 | **17** → **15** after G6 | ✅ closed |
| Functions cognitive > 15 | 0 | **2 (0.1%)** → **0** after G6 | ✅ closed |
| Mean cognitive | — | **2.09** | ✅ flat, not just capped |
| Nesting depth (max) | ≤ 3–4 | **4** | ✅ met at loose bound |
| Functions nesting > 4 | 0 | **0** | ✅ closed |

The ten functions sitting exactly at CC 10 — the ones a single new `if` would
push over the fail line:

| CC | Cog | Function |
|---:|---:|---|
| 10 | 11 | `actions/cancellation.py::sleep_with_stop` |
| 10 | 15 | `actions/type_message.py::execute` |
| 10 | 4 | `backend/chat_parser.py::_foreign_authors` |
| 10 | 10 | `backend/chat_text.py::authors_from_items` |
| 10 | 5 | `backend/config_manager.py::set_state` |
| 10 | 11 | `backend/dom_highlight.py::interpret_click` |
| 10 | 10 | `backend/history_query.py::page` |
| 10 | 14 | `backend/person_filter.py::check` |
| 10 | 15 | `backend/scroll_parser.py::_consume_batch` |
| 10 | 10 | `backend/visual_click.py::click_phase` |

Four of them (`type_message.execute`, `person_filter.check`,
`scroll_parser._consume_batch`, `cancellation.sleep_with_stop`) are *also* near
the cognitive ceiling. These are the repo's genuine complexity frontier and are
step **G6** — RULE 19's order (nesting → CC → cognitive → size) says they are
touched before any size work on the same functions.

**The two cognitive outliers changed identity since 2026-09-12** and this matters:

| Function | Cognitive | Status |
|---|---:|---|
| `bridge/router.py::_build_router_class` | 17 | class-factory over the QWebChannel slot table; 51 LOC |
| `stores/settings_store.py::get` | 17 | typed-getter dispatch |

The previously recorded pair (`backend/dom_probe.py::build_probe` and its twin)
now measure cognitive **8** — the embedded-JS builders are no longer the
outliers, they are only *long* (122 LOC, the §16.1.5 exemption). So the old
"both are frozen JS builders" line in the 2026-09-12 report is **no longer true
of this tree**; the two current outliers are ordinary Python and are in scope
for G6. That is a correction, not a regression: neither function got worse, the
JS builders got measured properly.

### 1.x G6 closing note — the ceiling was a cluster, not a peak

Re-measured after round G (2026-09-13, end of round):

| Metric | Before G6 | After G6 | Target |
|---|---:|---:|---|
| Max cognitive complexity | 17 | **15** | ≤ 15 ✅ |
| Functions cognitive > 15 | 2 | **0** | 0 ✅ |
| Functions at CC exactly 10 | 16 | **5** | ≤ 5 ✅ |
| Functions CC > 10 | 0 | **0** | 0 ✅ |

Two corrections to the record, both of the same kind — a number that was
believed rather than measured:

1. **`dom_probe.build_probe` is cognitive 8, not 17.** The §16.1.5 exemption
   covers its *length* (a 122-line JS literal) and never covered complexity.
   The earlier reports carried the 17 forward from a run that attributed the
   whole module to the function. AGENT_RULES §16.1.5 now says so explicitly.
2. **`bridge/history_bridge.py::history_delete_person` was the real cognitive
   outlier at 16**, and nothing in the reports named it. It is now 10, with
   the soft/hard deletion bookkeeping extracted to a module-level
   `_record_person_deletion` whose docstring states why a hard delete pushes
   no undo entry.

**What the CC-10 cluster turned out to be.** Sixteen functions sat exactly at
the ceiling and only *six* of them were complex in any sense a reader would
recognise. Radon charges +1 per `and`/`or`, so a function that is nothing but
defensive coalescing — `int(row["n"] or 0)` eight times over — scores the same
as one with eight real branches. `stores/label_filter.py::set_filter` is the
clearest case: **CC 10, cognitive 2, zero `if` statements**. Measuring both
metrics together is what separates them; measuring CC alone would have sent
this round refactoring straight-line code.

So the eleven that were changed were chosen by *cognitive* load, and each
extraction names a responsibility rather than splitting a body:
`_page_rows`/`_neighbour_flags` (paging cursors vs. edge detection),
`_truncate_all`/`_move_world_media_to_trash` (the containment guard that stops
a clean from taking every world's images), `_open_fallback` (normalising a
raised failure and an `ok: False` into one refusal path), `_no_match_line`,
`_rename_if_free`, `_reattributed_params`, `_cached_file_exists` and
`_downloads_unavailable`. The last two were each about to be written twice, in
`media_store` and `media_fetch`; they live in `media_layout`, the module both
already depend on, so the clone baseline stayed at 10 groups rather than 12.

**Two things the gates caught that review would not have.** Extracting helpers
as *methods* grew `HistoryQuery` and `HistoryBridge` past their frozen class
ceilings — the RULE 16 ratchet failed the commit, and the helpers moved to
module scope where they belonged. Separately, the `stores/` 400-SLOC test
failed because `media_fetch.py` was already at 398; the fix was not to raise
the ceiling but to put the shared helper in the module that shares it, leaving
both files *smaller* than before the round.

**The canary had to be replaced.** `tests/test_rule16_new_code.py` proves the
gate is not vacuous by asserting a known-oversized function is still reported.
That canary was `HistoryQuery.page` — 53 LOC — which this round reduced to 29,
so the test failed by succeeding. Its own message says to pick another rather
than soften the check; the canary is now `HistoryQuery._search` (49 LOC).

## 2. Size and volume metrics

| Metric | Your threshold | Measured | Verdict |
|---|---|---:|---|
| Function LOC (max) | ≤ 20–30 | **122** (`dom_probe.build_probe`, JS literal, §16.1.5) | ❌ documented exemption (LOC only — its cognitive complexity is 8) |
| Mean / median function LOC | — | 9.51 / 7 | ✅ well inside |
| Functions > 30 LOC | few | **43 (2.1%)** | ⚠️ tail |
| Functions in the RULE 18.1 band (4–20) | aim | **61.9%** (p90 = 20) | ⚠️ down from 63.6% |
| Class LOC (max) | ≤ 200–300 | **532** (`ScrollParser`) | ❌ 1.8× loose bound |
| Classes > 300 LOC | 0 | **9** | ❌ |
| Classes > 150 LOC (gate line) | 0 | **38 (16.8%)** | ❌ |
| Params (max) | ≤ 3–4 | **20** (`actions/scroll_parse.py::__init__`) | ❌ 5× |
| Functions > 4 params | few | **51 (2.5%)** | ⚠️ improved from 70 |
| Methods per class (max) | ≤ 10–15 | **44** (`stores/history_repo.py::HistoryRepo`) | ❌ |
| Classes > 15 methods | 0 | **25** | ❌ |
| File LOC (max) | ~150–300 ideal | **807** | ❌ 2.7× |
| Files > 500 lines | 0 | **7** | ❌ |
| Files > 300 lines | few | **26** | ⚠️ |
| File median | ~200 | **136** | ✅ the *body* of the tree is in band |

Median file 136 lines against a max of 807 is the real picture: this is not a
uniformly bloated codebase, it is a healthy one with **seven hotspots**.

### The seven files over 500 lines

| Lines | SLOC | MI | File | Splittable? |
|---:|---:|---:|---|---|
| 807 | 536 | **11.4** | `backend/chat_sync.py` | ❌ AREA D frozen |
| 706 | 492 | 28.6 | `backend/scroll_parser.py` | ❌ AREA D frozen |
| 603 | 417 | 35.4 | `backend/history_query.py` | ❌ AREA D frozen |
| 544 | 450 | 24.9 | `bridge/history_bridge.py` | ⚠️ QWebChannel slot set pinned; ratcheted |
| 534 | 388 | 55.9 | `backend/dom_highlight.py` | ❌ AREA D frozen |
| 509 | 315 | 41.0 | `backend/config_manager.py` | ❌ AREA D frozen |
| 509 | 382 | 31.5 | `services/db_deletion_flow.py` | ✅ **unfrozen, pure, F1 family** |

**Only one of the seven is freely splittable today.** That single fact sets
Round G's shape.

### Wide-parameter tail after F5 — where the remaining 51 live

| Package | Functions > 4 params |
|---|---:|
| `actions` | 15 |
| `backend` | 13 |
| `services` | 13 |
| `stores` | 7 |
| `bridge` | 2 |
| `app` | 1 |

Worst offenders: `actions/scroll_parse.py::__init__` (**20**),
`backend/scroll_parser.py::__init__` (19), `backend/chat_parser.py::sync_conversation`
(14), `actions/click_user.py::__init__` (13), `stores/history_repo.py::append` and
`stores/history_repo_append.py::append` (13 each),
`backend/visual_click.py::find_and_click` (12), `actions/custom_find.py::__init__` (11).

F5 cleared `stores/` from 24 to 7 and stopped: the rest sit on the AREA D
snapshot (`actions/*` block constructors are snapshotted *with their
`config_schema()` output*) or on RULE 3, which requires block settings to be
plain instance attributes and explicitly forbids hiding them behind `**kwargs`
to dodge the cap (§16.1.1 rule 2). **The remaining 51 are therefore not one
problem.** They are two: ~15 `actions/` constructors that need a snapshot
decision, and ~36 ordinary functions that need parameter objects. Round G splits
them accordingly (G4).

### Classes over the gate line — the god-class inventory

| LOC | Methods | LCOM* | Class |
|---:|---:|---:|---|
| 532 | 39 | 0.88 | `backend/scroll_parser.py::ScrollParser` |
| 467 | 31 | 0.86 | `bridge/history_bridge.py::HistoryBridge` |
| 406 | 25 | 0.12 | `stores/history_schema_repair.py::SchemaMigrator` |
| 375 | 19 | 0.06 | `stores/history_repo_lifecycle.py::PersonLifecycle` |
| 329 | 18 | 0.18 | `stores/history_repo_append.py::AppendPlanner` |
| 310 | 14 | 0.74 | `backend/history_query.py::HistoryQuery` |
| 308 | 31 | 0.89 | `bridge/stack_bridge.py::StackBridge` |
| 306 | 14 | 0.92 | `actions/scroll_parse.py::ScrollParse` |
| 306 | 15 | 0.21 | `stores/media_fetch.py::MediaFetcher` |
| 276 | 22 | 0.88 | `services/db_lifecycle.py::DbLifecycle` |
| 250 | 23 | 0.89 | `backend/chat_sync.py::SyncSession` |
| 239 | 40 | **0.97** | `services/collector_service.py::Collector` |
| 232 | 30 | 0.86 | `stores/history_db.py::HistoryDB` |
| 228 | 44 | 0.89 | `stores/history_repo.py::HistoryRepo` |

Note the LCOM column: `SchemaMigrator` (0.12), `PersonLifecycle` (0.06) and
`AppendPlanner` (0.18) are **big but genuinely cohesive** — every method touches
the same state. Splitting those by line count would make the codebase worse.
`Collector` (0.97 over 40 methods), `ScrollParse` (0.92) and `HistoryBridge`
(0.86 over 31 Qt slots) are big **and** incoherent. Size and cohesion must be
read together, which is why Round G targets by `LOC × LCOM`, not by LOC.

## 3. Coupling and cohesion metrics

Module granularity = one Python module. Ca = modules importing it, Ce = modules
it imports, I = Ce/(Ca+Ce).

**Highest efferent coupling (Ce) — the modules that know too much:**

| Ce | Ca | I | Module |
|---:|---:|---:|---|
| 17 | 1 | 0.94 | `bridge.router` |
| 15 | 1 | 0.94 | `services.run.coordinator` |
| 13 | 3 | 0.81 | `services.undo_service` |
| 12 | 3 | 0.80 | `services.collector_service` |
| 10 | 3 | 0.77 | `backend.config_manager` |
| 10 | 2 | 0.83 | `services.history` |
| 9 | 2 | 0.82 | `app.bootstrap` |

**Highest afferent coupling (Ca) — the load-bearing modules:**

| Ca | Ce | Module |
|---:|---:|---|
| 25 | 0 | `core.events` |
| 16 | 0 | `backend.cdp_client` |
| 14 | 0 | `core.result` |
| 13 | 2 | `actions.base_action` |
| 11 | 0 | `stores.history_models` |
| 9 | 5 | `services.run` |

This is a **healthy** coupling profile and deserves saying plainly: the four
most-depended-on modules have **Ce = 0** (instability 0, maximally stable), and
the high-Ce modules are composition roots (`bridge.router`, `app.bootstrap`,
`coordinator`) whose *job* is to know everyone. Nothing here needs a dependency
inversion; `core/` is a proper stable core and nothing in it depends outward.

The one genuine smell is `services.undo_service` and `services.collector_service`
at Ce 13/12 with Ca 3 — they are not composition roots, they are services, and
their instability near 0.8 says they will break whenever anything moves. Both are
also the worst LCOM classes. That coincidence is not noise: **a class that knows
12 modules and shares no state between its methods is a package wearing a class
costume.** G2 and G3.

**Worst cohesion (LCOM*, classes ≥ 5 methods):**

| LCOM* | Methods | Class |
|---:|---:|---|
| 0.97 | 40 | `services/collector_service.py::Collector` |
| 0.96 | 17 | `services/run/coordinator.py::RunCoordinator` |
| 0.95 | 28 | `services/undo_service.py::UndoService` |
| 0.94 | 13 | `backend/chat_parser.py::ChatParser` |
| 0.94 | 20 | `bridge/people_bridge.py::PeopleBridge` |
| 0.93 | 7 | `actions/base.py::BaseAction` |
| 0.92 | 14 | `actions/scroll_parse.py::ScrollParse` |

(Small holders like `core/result.py::Err` also read 1.0; LCOM* is meaningless on
a 3-field value object and those are excluded from any remediation.)

## 4. Test quality metrics

| Metric | Target | Measured | Verdict |
|---|---:|---:|---|
| Tests passing | — | **2,800 passed, 3 skipped, 1 deselected, 1 xfailed, 0 failed** (+897 subtests) | ✅ |
| Line coverage | ≥ 80% | **90.87%** | ✅ +0.46 pp vs baseline |
| Branch coverage | ≥ 75% | **86.94%** (3,255 / 3,744) | ✅ +0.64 pp |
| Mutation score | ≥ 70% | **99.37%** on the configured scope | ✅ |
| Test-to-code ratio | ~1:1 | **1 : 1.59** (23,823 prod / 37,914 test nbnc) | ✅ over-tested, fine |
| JS entrypoints | all green | **26 / 26** | ✅ |
| RULE 16 gate | pass | **pass** — all owned functions fit, ratchet intact, no stale overrides, 0 new clone groups | ✅ |

**Mutation detail.** 1,141 mutants generated over the configured scope
(`backend/history_query.py`), 982 unreachable by the selected suites and
excluded, **158 killed, 1 survived** → 99.37% of reachable. The single survivor
is `HistoryQuery._my_nicks` mutant 7 — the `or "[]"` → `or "XX[]XX"` mutation
already recorded as **semantically equivalent** in
`ROUND_F_DESIGN_2026-09-12.md` §9.4. So: **F6 is complete.** The nine survivors
that step was created to close are down to one, and that one cannot be killed
because killing it would require asserting a difference that does not exist.

The honest caveat, unchanged: mutation is measured on **one file**. 99.37% is a
statement about `history_query.py`'s tests, not the repo's. Widening the scope is
step **G5**, and it should be expected to *lower* the headline number — that is
the point of measuring it.

## 5. Code smell metrics

| Smell | Detector | Finding |
|---|---|---|
| Duplicated code | `clone_scan.py` | **12 groups, 89 unique physical lines, 0 new** vs the frozen baseline — gate green |
| Dead code | `vulture --min-confidence 90` | **7 findings** |
| Long methods | §16.1 | 43 functions > 30 LOC |
| God classes | §16.1 | 25 classes > 15 methods; worst 44 |
| Feature envy | review | no automated gate; `Collector`/`UndoService` are the manual candidates |

**All 7 vulture findings, with a verdict on each** (this is inventory, not a
work order — six are false positives and saying so prevents a future round
"fixing" them):

| Finding | Verdict |
|---|---|
| `actions/registry.py:18` unused import `Iterator` | **real** — one-line delete, only genuine finding |
| `backend/cdp_client.py:35` `exc_type`, `tb` | false positive — `__aexit__` protocol signature |
| `services/run/coordinator.py:61` `scroll_parser` | false positive — injected collaborator attribute |
| `services/run/hooks.py:68,71,74` `coordinator` | false positive — callback signatures (§16.4 permits) |

Of the 12 clone groups, 9 are 6–9-line **import headers** in sibling modules of
the same family (`bridge/*_bridge.py`, `stores/*_store.py`,
`services/db_deletion_*`) — an artefact of the very family-splitting RULE 18.2
asks for, correctly baselined rather than "fixed" by re-merging files. Two are
real and worth a look: `actions/click_back.py:20` vs
`actions/click_main_tab.py:19` (**span 15** — the largest clone in the tree, two
find-and-click blocks) and `backend/media_handler.py:118` vs
`backend/message_injector.py:98` (span 7). Those two go to **G7**.

## 6. Maintainability metrics

| Metric | Measured |
|---|---|
| Mean maintainability index | **66.36** (was 64.85) |
| Files below MI 40 | **19** (was 22) |
| Worst MI | **11.4** — `backend/chat_sync.py` |
| Technical debt ratio | not honestly measurable (see below) |
| Code churn | not measurable — **this checkout has 1 reachable commit** |
| Bug density | not measurable — no defect attribution in history |

**The 19 files below MI 40:**

| MI | Lines | File |
|---:|---:|---|
| 11.4 | 807 | `backend/chat_sync.py` |
| 24.9 | 544 | `bridge/history_bridge.py` |
| 28.6 | 706 | `backend/scroll_parser.py` |
| **28.7** | **299** | `services/window_preset_service.py` |
| 31.5 | 509 | `services/db_deletion_flow.py` |
| 31.5 | 464 | `stores/media_fetch.py` |
| **31.8** | **258** | `services/run/progress.py` |
| **32.2** | **151** | `services/run/hooks.py` |
| 32.9 | 425 | `services/collector_tick.py` |
| **33.7** | **128** | `app/window.py` |
| 34.9 | 294 | `services/history/mutate.py` |
| 35.4 | 603 | `backend/history_query.py` |
| 35.5 | 229 | `stores/label_assignments.py` |
| 36.7 | 331 | `backend/cdp_client.py` |
| 36.9 | 174 | `services/history/query.py` |
| 37.5 | 332 | `bridge/file_bridge.py` |
| 37.7 | 441 | `stores/history_repo_lifecycle.py` |
| 38.9 | 234 | `services/layout_service.py` |
| 39.4 | 330 | `bridge/stack_bridge.py` |

Bolded rows are the **density** cases — low MI in a file that is already inside
RULE 18.2's size band. `app/window.py` is the sharpest example in the tree: **MI
33.7 in 128 lines.** No size-driven refactor will ever find it, and splitting it
would be actively wrong. These five files need comments, naming and local
simplification, not surgery — step **G8**, and they are the reason this report
ranks by MI as well as by lines.

`chat_sync.py` at MI 11.4 is less than half the next-worst score and a sixth of
the project mean. One file carries most of the maintainability risk in the
repository, and it is the one the AREA D snapshot forbids splitting.

**On the three metrics not reported.** TDR needs a remediation-cost model no
tool here produces; MI is the proxy and is above. Churn needs history and this
checkout has **one** commit reachable from HEAD — a churn ranking from that
would be invented, not measured. Bug density needs bug-labelled commits, which
this project does not have a convention for. Reporting these three as numbers
would be false precision; getting them for real is a tooling task (full clone +
a `fix:` commit convention), noted in Round G's appendix and deliberately **not**
sold as an analysis step.

## 7. What to do next

Full plan, with steps sized at 8–16 hours each, RULE 16 §16.6's four-phase
process applied per step, and the rejected alternatives recorded:

**`docs/archive/2026-09-13-round-g/ROUND_G_PLAN_2026-09-13.md`**

Priority order, in one line each:

| # | Step | Why here |
|---|---|---|
| **G0** | Decide the AREA D snapshot question | Blocks 5 of 7 oversized files, including MI 11.4. Nothing above it can start. |
| **G1** | `backend/chat_sync.py` 807 / MI 11.4 (needs G0) | Worst file in the repo by a factor of two |
| **G2** | `Collector` 239 LOC / 40 methods / LCOM 0.97 / Ce 12 | Worst cohesion + worst coupling, unfrozen |
| **G3** | `UndoService` 179 / 28 / LCOM 0.95 / Ce 13 | Same shape, smaller, already part-split |
| **G4** | Wide-parameter tail 51 → ≤ 35 | Continues F5 where it is not frozen |
| **G5** | Widen mutation scope beyond one file | Turns a 1-file 99% into a real number |
| **G6** | The CC-10 frontier + 2 cognitive-17 functions | RULE 19 order: complexity before size |
| **G7** | The 2 real clone groups | Cheapest honest win in the report |
| **G8** | Density pass on the 5 small low-MI files | Invisible to every size-based sort |

## Reproduction

```bash
# environment (in-repo venv; gitignored)
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python tools/build_stubs.py          # headless Qt on a box without GL

# static audit (complexity, size, LCOM, coupling, MI, clones)
.venv/bin/python tools/metrics/current_audit.py > /tmp/audit.json

# full suite + coverage
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
.venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
.venv/bin/python -m coverage json -o coverage.json

# mutation score (scoped by setup.cfg; ~75s; delete mutants/ afterwards)
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/mutmut run
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/mutmut results

# gates and smells
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
.venv/bin/python tools/metrics/stores_modules.py
.venv/bin/vulture --min-confidence 90 core actions backend bridge services stores app

# JS suites
for f in tests/test_*.js; do node "$f" | tail -1; done
```

Measured on Python 3.11, Radon 6.0.1, cognitive-complexity 1.3.0, vulture 2.16,
mutmut 3.7.0, pytest 9.1.1. Suite wall time 501s.
