# Round H design — the frontend, the Python tail, and the verification that proves both

Date 2026-09-14 · branch `arena/01a0a11b-chat-v-bot` · base `5197ce0`
Owners' input: the code-quality metric list (complexity, size/volume,
coupling/cohesion, tests, smells, maintainability) and *"research where the
biggest problem is, split it into many steps … split to 3–4 areas isolated to
develop independently on different branches … plan all areas, no implementation
for now."*

**Status of this document: PLAN ONLY.** No production file was changed to write
it. Every number is measured on this tree — source of record
[`reports/CODE_QUALITY_METRICS_2026-09-14.md`](../../../reports/CODE_QUALITY_METRICS_2026-09-14.md),
raw evidence in `/tmp/audit_h.json`, `/tmp/coverage_h.json`,
`/tmp/js_cov_h.json`, `/tmp/mutmut_results.txt`. Required by RULE 16 §16.6 step 2
and RULE 17.

---

## 1. Where the biggest problem is — measured, not assumed

The metric categories in the owner's brief now stand like this at `5197ce0`:

| Category | State | Evidence |
|---|---|---|
| **Complexity** | **closed** | 0/2,268 functions over CC 10 (max 10); 0 over cognitive 15 (max 15); max nesting 4; mean CC 2.98 |
| **Size (Python)** | **tail, shrinking** | 39 functions > 30 LOC (1.7%); 36 classes > 150 LOC; 23 files > 300; 4 files > 500; max file 601 |
| **Size (JavaScript)** | **unbounded — the biggest gap** | no size gate exists; largest file 1,361 lines; largest object 1,331 LOC / 69 methods; largest function 205 LOC; 9.2% of JS functions > 30 LOC vs 1.7% in Python |
| **Coupling** | **healthy** | hubs `core.events` 27/0, `cdp_client` 21/0, `core.result` 17/0; every I ≥ 0.77 module is a composition root or router |
| **Cohesion** | **mixed, and readable** | 170 classes scored: mean LCOM\* 0.594; the ≥ 0.85 set splits into 7 delegation facades (57–86% one-liners) and 17 genuinely incoherent classes |
| **Tests** | **strong, with one blind spot** | 3,172 passed / 0 failed; line 92.64%; branch 88.03%; mutation 99.37%; ratio 1 : 1.57 · JS 29/29 green, 82.8% covered, **6 files never loaded (1,239 LOC)** |
| **Smells** | **small and stable** | 13 clone groups (all import headers, 0 new); 7 vulture findings; four inspected private-member boundary crossings |
| **Maintainability** | **improved, one outlier** | mean MI 68.05 (was 64.85); floor 24.9 (was 11.1); `bridge/history_bridge.py` is the worst file and is 66.4% covered |

### Ranking, by impact × feasibility

1. **The frontend is the largest un-gated mass in the repository, and nobody has
   ever measured its shape.** 30 files / 11,865 lines against RULE 16's Python
   scope. Its two biggest objects are bigger than any Python class in the
   project by LOC *and* by method count; its longest function (205 LOC) is 3.8×
   the longest real Python function; and because no gate looks at it, every
   future change compounds it. Nothing else in the tree is growing unchecked.
2. **The archive path's two worst files.** `bridge/history_bridge.py`
   (544 lines, **MI 24.9 — worst in the project**, 467-LOC / 31-method class,
   **66.4% covered**) and `backend/history_query.py` (601 lines, largest file,
   ratcheted class, and the seed of the mutation job). Both are §16.5 landmines;
   both are load-bearing for the feature the owner just shipped.
3. **Service/store cohesion and the dense outliers.** 17 genuinely incoherent
   classes (not the facades), the cohesive-but-407-LOC `SchemaMigrator`, and the
   files whose MI is low *because they are dense*, not because they are long:
   `window_preset_service.py` (326 lines, MI 30.6), `run/progress.py` (314,
   31.0), `history/mutate.py` (294, 34.9), `app/window.py` (128, 33.7).
4. **Verification debt.** One mutation job covering one module; a coverage hole
   that sits precisely on the risky files (`history_bridge` 66.4%, `cdp_client`
   65.2%, `message_injector_send` 26.3%); and the defect class the last round
   proved is real — a test double that invented an interface, which let a dead
   feature ship green (`BOT_CHAT_DEFECTS_2026-09-13.md` P1).

### Why these four become four *areas* and not one queue

Each area owns a **disjoint file set**, so it can be developed, reviewed and
verified on its own branch with no merge conflict against the others:

| Area | Owns (production files) | Owns (test/tool files it adds) |
|---|---|---|
| **A — Frontend JS** | `ui/**`, `backend/js/**` | `tests/test_*.js` (new + existing JS suites), `tests/js_harness.js`, `tools/metrics/js_*.py` |
| **B — Backend + bridge spine** | `backend/**/*.py` (except `backend/js/`), `bridge/**/*.py` | `tests/unit/backend/**`, `tests/unit/bridge/**`, `tests/test_*history*` as needed |
| **C — Services, stores, actions, app** | `services/**`, `stores/**`, `actions/**`, `app/**` | `tests/unit/services/**`, `tests/unit/stores/**`, `tests/integration/**` |
| **D — Verification & measurement** | none (tools/docs only) | `tools/metrics/*.py`, `tests/**` existing files, `docs/**`, `reports/**`, `setup.cfg` |

Two rules make the partition hold:

* **Interfaces between areas are frozen.** An area may rename, shrink or split
  *its own* internals; it may not change a signature that another area's file
  calls (e.g. C may not change `HistoryQuery.page`'s signature for B, B may not
  change `LabelStore.set_for` for C). Where a change genuinely requires a cross
  interface move, it is recorded as a **cross-area note** in this document and
  scheduled into the later of the two areas — never smuggled in.
* **`tools/metrics/rule16_gate.py` is shared.** `OWNED`, `RATCHET` and
  `SMELL_FILES` are edited by whichever area renames the function in question,
  in the same commit as the rename, and only in its own rows. D owns the file's
  structure. This is the one file all four areas touch; it is small, its edits
  are line-local, and the existing gate test fails loudly when it is wrong.

> **Branch note for this session.** The areas are designed for one branch each
> (`round-h/a-frontend`, `round-h/b-backend-bridge`, …) and independent
> verification. This session's branch is fixed to
> `arena/01a0a11b-chat-v-bot`, so execution here will be sequential on that one
> branch, one area per commit series — the isolation property is what keeps that
> safe, not the branch names.

---

## 2. Area A — the frontend: gate the shape, then fix what the gate reveals

**Priority: first.** It is the only subsystem with no size limit at all, it
holds the largest artefacts in the repo, and its verification floor is the
weakest (6 files at 0%, the two biggest files at 64%/68%).

Full detail: [`AREA_A_FRONTEND_JS_DESIGN_2026-09-14.md`](AREA_A_FRONTEND_JS_DESIGN_2026-09-14.md).

| Step | Content | Target |
|---|---|---|
| **H-A1** | `tools/metrics/js_size.py` — the JS analogue of the AST walker: per-file LOC, per-object method count, per-function LOC, JSON + table; baseline recorded in `reports/JS_SIZE_BASELINE_2026-09-14.md` | measurement exists |
| **H-A2** | `tools/metrics/js_gate.py` + `tests/test_js_gate.py` — RULE 16's fail lines applied to JS (function > 30 LOC, object > 15 methods or > 150 LOC, file > 500 with ratchet) and a per-file coverage floor that may not decrease | **owner decision D1** |
| **H-A3** | Split `ui/js/sash-grid.js` 1,361 → facade ≤ 300 + 4–5 parts (tree render, windows menu, dock/minimize, preset validation, drag/resize) — the `stores/history_repo.py` + parts pattern, in JS | `SashGrid` ≤ 15 methods |
| **H-A4** | Split `ui/js/stack-dnd.js` 1,341 → facade + parts; break `_showConfig` (180 LOC) into a **per-block row-builder table** + one generic renderer (RULE 19 §19.2: tables are data, not branches) | no function > 30 LOC |
| **H-A5** | Node harness for the six never-loaded files; then split `app.js::setupBridgeListeners` (205 LOC) into per-window registration functions | every shipped file loaded by ≥ 1 test |
| **H-A6** | Coverage lift: `presets-ui.js` 47.3 → ≥ 80%, `sash-grid` / `stack-dnd` / `user-table` / `history-store` / `window-presets` → ≥ 85% | total JS ≥ 90% |

**Area-closing gates:** 29 existing Node suites + new ones green;
`js_coverage.py` ≥ 90% total and no file at 0%; `js_gate.py` clean; the two big
files ≤ 500 lines or carrying an `ideal-size:`-style note with a constraint.

## 3. Area B — the backend/bridge spine

**Priority: second.** Worst MI in the project, the largest file, and the lowest
coverage among load-bearing modules — the three problems overlap on the same two
files.

Full detail: [`AREA_B_BACKEND_BRIDGE_DESIGN_2026-09-14.md`](AREA_B_BACKEND_BRIDGE_DESIGN_2026-09-14.md).

| Step | Content | Target |
|---|---|---|
| **H-B1** | `bridge/history_bridge.py` 544 / MI 24.9 / 66.4% → wire facade + parts (`_read`, `_delete`, `_media`, `_settings`); **tests first** for the delete/clear/purge slots the split touches | MI ≥ 45, coverage ≥ 90%, ratchet lowered |
| **H-B2** | `backend/history_query.py` 601 → search back-end module + row-projection module; close the last mutation survivor (`_my_nicks`) | ≤ 350 lines, class ≤ 15 methods |
| **H-B3** | `backend/config_manager.py` 511 / MI 40.9 → split defaults+merge / IO / migration / validation | ≤ 300 lines, `ConfigManager` ≤ 15 methods |
| **H-B4** | `backend/dom_highlight.py` 514 → the six embedded JS payloads (219 lines) to `dom_highlight_js.py`; §16.1.5's exception is kept only where the payload is a single literal | ≤ 300 lines |
| **H-B5** | `bridge/router.py` 486 → `Router.__init__` (8 params) to an options object; `backend/media_handler.py` 474 → dialog path vs payload; `backend/chat_parser.py` 426 / LCOM 0.94 → settle-timing policy separated from parsing | 0 files > 500 lines in `bridge/` |
| **H-B6** | `backend/cdp_client.py` 331 / MI 36.7 / **65.2% covered** / CDPClient 208/21/0.91 → transport vs event dispatch, starting from the coverage hole | coverage ≥ 85% |

## 4. Area C — services, stores, actions, app

**Priority: third.** The largest Python mass (139 files / 21,726 lines), and the
place where cohesion debt actually lives — as distinct from the facades, which
must be left alone.

Full detail: [`AREA_C_SERVICES_STORES_DESIGN_2026-09-14.md`](AREA_C_SERVICES_STORES_DESIGN_2026-09-14.md).

| Step | Content | Target |
|---|---|---|
| **H-C1** | The run family — `services/run/coordinator.py` (RunCoordinator 0.97), `run/progress.py` (RunQueueMixin 227/22/0.94, MI 31.0), `run/error_recovery.py`, `run/collect_phase.py`, `run/run_lifecycle.py` — decomposed by phase | no class > 15 methods, each file ≤ 300 |
| **H-C2** | The undo family — `services/undo_service.py` reduced to the facade it already is (28 methods, 86% delegations), raw handlers moved out; `services/history/mutate.py` (MI 34.9) split by operation | `UndoService` ≤ 15 methods |
| **H-C3** | The DB/world family — `services/db_lifecycle.py` (DbLifecycle 276/22/0.88), `services/db_registry.py` (302, MI 41.1, **70.7% covered**), `stores/history_db.py` (HistoryDB 232/30/0.86) | coverage ≥ 85% each |
| **H-C4** | The store planners — `SchemaMigrator` 407/25/0.12, `PersonLifecycle` 375/19/0.06, `AppendPlanner` 325/18/0.18, `MediaFetcher` 306/15/0.21 (MI 31.5) → cohesive helper modules (split by *naming the helper's responsibility*, §16.1.1) | ≤ 200 LOC each |
| **H-C5** | Dense-file pass — `window_preset_service.py` (MI 30.6 in 326 lines), `run/progress.py`, `stores/label_assignments.py` (MI 35.5), `app/window.py` (MI 33.7), `services/layout_service.py`, `actions/click_user.py` (ClickUser 0.93) | MI ≥ 50 on each |
| **H-C6** | Facade adjudication in writing — `HistoryRepo`, `LabelStore`, `MediaStore`, `Collector`, `UndoService`, `HistoryExportService` are 73–86% one-line delegations; either extract what remains or record each as an accepted shape with its evidence | decision recorded, no blind splits |

## 5. Area D — verification and measurement debt

**Priority: fourth, and independent** — it touches no production file, so it can
run first, last, or in parallel with all three others.

Full detail: [`AREA_D_VERIFICATION_DESIGN_2026-09-14.md`](AREA_D_VERIFICATION_DESIGN_2026-09-14.md).

| Step | Content | Target |
|---|---|---|
| **H-D1** | Mutation platform: widen the `history_query.py` job (159 → 910 reachable, measured in `setup.cfg`) and configure a **second** job over a pure module family | score recorded for ≥ 2 modules (**decision D2**) |
| **H-D2** | The RULE 8 double audit — enumerate every fake standing in for a production collaborator and assert interface parity (the mechanism that hid the dead label store) | a checker + an audited list, zero invented attributes |
| **H-D3** | Coverage-gap programme — the eight lowest-covered modules (`message_injector_send` 26.3%, `cdp_client` 65.2%, `history_bridge` 66.4%, `app/lifecycle` 66.7%, `db_deletion_flow_remove` 69.3%, `layout_bridge` 70.1%, `db_registry` 70.7%, `db_deletion_scan` 70.9%) | each ≥ 80% |
| **H-D4** | Baseline/doc currency — RULE 16 §16.3 still quotes the 2026-09-10 floors (90.44 / 84.38); RULE 18.2's measured bullet lists files that have since moved; the two doc maps need this round | numbers match the tree |
| **H-D5** | Smell ratchet — 7 vulture findings (six are callback/protocol args: document or delete), 13 clone groups (already baselined) | inventory shrinks or is documented |

---

## 6. Owner decisions this plan needs

| # | Decision | Recommendation | Consequence if deferred |
|---|---|---|---|
| **D1** | Adopt a **JavaScript** size + coverage gate (RULE 16 is Python-scoped) | Yes — mirror §16.1's fail lines and add a per-file coverage floor with a ratchet for the two big files | Area A's splits have nothing holding them in place; the frontend regrows |
| **D2** | Widen the mutation job for `history_query.py` (159 → 910 reachable mutants, longer runtime) and add a second job | Yes for the second job on a pure module family; widen `history_query` only if the runtime is acceptable | mutation stays a one-module measurement |
| **D3** | Are the dense-file passes allowed to change public shape, or internals only? | Internals only for `window_preset_service`, `run/progress`, `layout_service` (their public methods are consumed elsewhere) | each step would otherwise need a signature review |

## 7. Deliberately out of scope

* **Rewriting the frontend** (ES modules, a build step, a framework). RULE 18
  wants reads that fit in a context window; it does not ask for a bundler, and
  the app deliberately ships plain scripts loaded by `ui/index.html`.
* **Splitting the facades** (`HistoryRepo` 44 methods, `LabelStore`, `MediaStore`,
  `Collector`, `UndoService`). Measured: 73–86% of their methods are one-line
  delegations. Area C H-C6 makes that judgement explicit rather than assumed.
* **Touching `core/`.** 7 files / 544 lines, mean MI 85.0, worst 60.3 — the
  healthiest area in the tree; nothing there is over any threshold.
* **Reconstructing churn / bug density / technical-debt ratio.** The checkout
  history is two whole-repo commits; those numbers would be fiction.

## 8. Definition of done for the round

1. Area A: `js_gate.py` green; no JS file > 500 lines without a recorded
   constraint; total JS coverage ≥ 90%; every shipped file loaded by a test.
2. Areas B/C: no file > 500 lines in `bridge/`+`services/`+`stores/`; the four
   files over 300 lines carry either a split or a recorded reason; MI floor
   ≥ 45; every class named in §1 of the area docs ≤ 15 methods.
3. Area D: mutation measured for ≥ 2 modules; every module ≥ 30 statements
   ≥ 80% covered; the RULE 8 audit list exists and is clean.
4. Round-wide: Python suite green (≥ 3,172 passed, coverage ≥ 92.64 / 88.03),
   RULE 16 gate green with `--with-clones`, all 29+ Node suites green, and
   `docs/current/AGENT_RULES.md` §16.3/§18.2 measured bullets re-quoted from this
   tree.

## Reproduction (evidence for every number in this plan)

```bash
.venv/bin/python tools/metrics/current_audit.py > /tmp/audit_h.json
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/python -m coverage run \
  --branch --source=core,actions,backend,bridge,services,stores,app,main -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
COVERAGE_FILE=/tmp/.coverage_h .venv/bin/python -m coverage json -o /tmp/coverage_h.json
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
.venv/bin/python tools/metrics/js_coverage.py --json /tmp/js_cov_h.json
node /tmp/jsfn.js ui/js/*.js ui/js/core/*.js backend/js/*.js   # JS shape (no repo tool yet)
```
