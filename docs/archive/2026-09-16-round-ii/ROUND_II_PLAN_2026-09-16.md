# Round II plan — 2026-09-16 (PLAN ONLY — no implementation in this commit)

Input: [`reports/CODE_QUALITY_METRICS_2026-09-16_ROUND2.md`](../../../reports/CODE_QUALITY_METRICS_2026-09-16_ROUND2.md)
(measured on the working tree with the user's verification fixes: suite 3375 green, all gates exit 0,
37 JS functions >30 LOC remain, 9 files below the 80 % per-file coverage floor).
Round I (verification/verification-machinery) is closed; **Round II attacks the remaining structural
debt: the JS god-function cluster and the per-file coverage-floor debt.**

Standing rules for every area: `docs/current/AGENT_RULES.md` — especially RULE 16 (gates on every
production change, floors never decrease), RULE 18 §18.4 (SOR/AGENT_RULES at ceiling — replace lines,
never add net lines), RULE 8 (tests execute the real thing — no shallow mocks), RULE 17 (SOR §7 flows
stay true; docs move only if flows change), RULE 19 (fix complexity before size).

## 0. Where the biggest problem is (research summary)

Per-file over-30 distribution (§5 of the metrics report) shows the debt is **not flat**: the top 4
files hold **21 of 37** violating functions and **≈ 2.6 k of ≈ 3.1 k** over-30 LOC, and each of them
is one giant module-IIFE that survived the Round-H split wave (the *leaf* files got split; these
*cores* did not). Churn data (§6) says these exact surfaces are hot (`sash-grid` family, `stack-dnd`,
bot/*). So the round's split axis = one area per core file, prioritized by apex size × churn:
**chat_agent (782) > sash-core (661) > history-model+view (386/327/238) > long tail (12 fns) + coverage floor.**

Feasibility (checked during measurement): every apex has clean internal seams —
- `chat_agent.js`: constants → fingerprint (fnv1a/hex8/fingerprint) → DOM utils → pane model →
  parse/cache/walk → push buffer/observer → state()/API.
- `sash-core.js`: window registry → tree primitives → default layouts → tree ops →
  moveWindow → validate/prune → migrate.
- `history-model.js`: pure row/date helpers (39–160) + `create()` model object (162–238+).
- `history-view.js`: node builders (21–165) + render family (166+).

Test nets already exist per area (`tests/test_history_agent_js.js`, `test_private_scope_js.js`,
`test_sash_core*.js`, `test_sash_drag.js`, `test_history_lazy_paging.js`, `tests/js_family.js`) —
each loads the single file today and must move to the parts-loading harness (`tests/_ui_loader.js`
`loadModule/readUi`) when its area splits the file.

## 1. Areas, isolation, branches

Four areas on four sibling branches off the session integration branch. Ownership is **exclusive**:
an area may only touch its files; shared pins (`reports/js_size_baseline.json`,
`reports/js_coverage_baseline.json`, `tools/metrics/*` ratchets, smell tables) follow the doctrine
below (§3).

| Area | Branch (suggested) | Owns (exclusive) | Scope |
|---|---|---|---|
| **A — chat_agent core** | `round2/area-a-chat-agent` | `backend/js/chat_agent*`; `tests/test_history_agent_js.js`, `tests/test_private_scope_js.js` | 782 apex → facade ≤ 150 + 5 parts |
| **B — sash core** | `round2/area-b-sash-core` | `ui/js/sash-core*`; `tests/test_sash_core*.js`, `tests/test_sash_drag.js`, `tests/test_sash_grid_window_controls.js` | 661 apex + moveWindow(51) → facade + 4 parts |
| **C — history model/view** | `round2/area-c-history-mv` | `ui/js/history-model*`, `ui/js/history-view*`; `tests/test_history_lazy_paging.js` (+ its family entries) | 386/327/238 → 2 facades + 4 parts |
| **D — coverage floor + tail** | `round2/area-d-verification` | `tests/**` new files; ratchet/floor tables in `tools/metrics/file_coverage_floor.py`; JS tail: `ui/js/labels*`, `collector-panel*`, `color-picker*`, `composer*`, `core/bridge-ready*` | 9 files → ≥ 80 %; 12 tail fns → ≤ 30 |

Non-goals (explicitly out): `sash-grid-drag-core.js` / `bot-settings-core.js` watch objects (P3 —
measure again at round exit; split only if an area already owns the file), `dom_probe::build_probe`
(P4, pinned python apex), any UI/behaviour change, SOR §7 flow changes (none are planned — splits are
behavior-preserving, so RULE 17 docs move = metrics report + this plan only).

### 1.1 Area A — `backend/js/chat_agent.js` (803 lines, 6 over-30 fns, apex 782) — P1

Constraints: `fingerprint()` is **mirror-locked** with `backend/history_models.py` (parity suites
`tests/test_chat_parser_delta.py`, `tests/unit/backend/test_history_models.py`); `VERSION = 11`,
`SEP`, HEAD/TAIL fingerprint counts and the `__cvbPush` channel semantics must not change; the IIFE
singleton state (`lastPane`, `cache`, `buffer`, `observer`, `stats`) must stay one instance.

Steps (each lands separately, suite green after each):
1. Record the section map with exact line ranges + the external API object; freeze as a comment
   ledger in the part files (understand — done, see §0; verify remainder of the tail).
2. Extract `chat_agent_dom.js` — the pure DOM utils (`qs/qsa/clean/ownText/isAncestor/isHidden/
   visible/num/liveMediaUrl`). No state. Load order first.
3. Extract `chat_agent_fingerprint.js` — `fnv1a/hex8/fingerprint/SEP/strip` (+ constants
   HEAD/TAIL). Run the python parity suites after this step.
4. Extract `chat_agent_pane.js` — pane model (`paneOf/paneGroups/groupAuthors/selectPane/
   paneAmong/visiblePane/containers/messagesRoot/inDocument`, `lastPane/lastPartner`).
5. Extract `chat_agent_parse.js` — `parseNode/liveFields/fieldsStale/keyOf/walk/authorsOf`,
   moving `cache/stats`.
6. Extract `chat_agent_push.js` — `bufferRecord/schedulePush/sendPush`, `buffer/dropped/observer/
   observedRoot/pushTimer`, the MutationObserver wiring.
7. Thin facade `chat_agent.js` (≤ ~150): `state()` assembly + public API export; re-point the two
   node suites to `_ui_loader.loadModule('backend/js/chat_agent.js')` parts mode.
8. Re-pin `js_size`/`js_coverage` baselines per doctrine (§3), update `tests/js_family.js` list.

Design rule: parts hold **functions only**; shared mutable state lives in exactly one part
(pane-state in 4, parse-cache in 5, push-queue in 6) and is passed by closure from the facade —
no new globals beyond the existing export (RULE: one control per decision). If a cut cannot keep
behaviour byte-identical, redesign the cut (RULE 19): split along a narrower seam rather than
changing semantics.

### 1.2 Area B — `ui/js/sash-core.js` (684 lines, 3 over-30 fns, apex 661) — P1

Constraints: `VERSION = 4` layout format + the V1→V3 migration vectors are pinned by python-side
persistence tests (`tests/test_grid_persistence.py`, `test_grid_layout_v2_migration.py`) and
`test_sash_core_v2.js`; `WINDOWS` registry order is observable.

Steps:
1. Section map exact (registry 27–65 · primitives 66–85 · layouts 85–164 · tree ops 165–482 ·
   move 484–541 · validate/prune 583–620 · migrate 621+).
2. `sash-core-tree.js` — pure tree ops: `leaf/split/clone/normalizeSizes/isLeaf/isSplit/
   forEachLeaf/findNode/splitLeaf/insert*/remove*/leafPaths/parentPath/nodeAtPath/setSplitSizes*`.
3. `sash-core-layouts.js` — `defaultTree/layoutA/B/C/PRESETS` (+ `WINDOWS`, `V*_WINDOW_IDS`,
   `VERSION`, `WINDOW_TITLES` stay here as the single registry).
4. `sash-core-move.js` — `moveWindow` (51) decomposed: target-resolution helper + insert/remove
   plan + apply (each ≤ 30).
5. `sash-core-validate.js` — `validate/pruneTree/evenSizes/migrate`.
6. Facade `sash-core.js` re-exports the flat API the four suites import today; point the suites at
   parts via `_ui_loader`; keep `js_family.js` entry.
7. Baselines re-pin per doctrine; verify python grid-persistence suites untouched-green.

### 1.3 Area C — `ui/js/history-model.js` + `history-view.js` (~800 combined, 9 over-30) — P1

Constraints: `history-model` is the paging/search state machine consumed by `history-panel*` and the
python `__cvbPush` path; `create()`'s options surface (`initial`, `pageSize`, `search`, `labels`)
must not change; `history-view` node builders have DOM parity pinned by snapshot-style suites.

Steps:
1. Model map (helpers 39–160 · `create()` 162+ incl. `reset/request/requestInitial/requestOlder`).
2. `history-model-rows.js` — pure data layer: `fileUrl/previousDay/dayLabel/groupByDay/toRow/
   highlight/clipboardText`.
3. `history-model-request.js` — request builders + paging counters (the closure state moves here,
   created by the facade per `create()`).
4. Facade `history-model.js` — `create()` assembly ≤ 30/branch, re-export.
5. `history-view-nodes.js` — `el/appendHighlighted/mediaSrc/mediaRestoreNode/mediaNode/
   messageNode/gapNode/dayNode/nodeFor`.
6. `history-view-render.js` — `renderRows/renderGroups/renderHeader/renderSearchGroups`.
7. Facade `history-view.js`; point `test_history_lazy_paging.js` + family loader at parts.
8. Baselines re-pin per doctrine.

### 1.4 Area D — coverage floor + smell tail — P2

Constraints: **RULE 8 — real tests only** (the floor rose this far on real flows; shallow mocks are
rejected by review + the integration gate). D must not open any file owned by A/B/C.
D is the only area allowed to edit ratchet tables (`tools/metrics/file_coverage_floor.py` RATCHET,
`tests/wait_budget_baseline.txt` if a genuinely long wait is added — justify, don't accumulate).

Steps:
1. Hygiene: delete the stale ratchet entry (`stores/media_fetch_http.py`); re-assert gate exit 0.
   Then re-measure canonical coverage **per-tier** (fresh process per tier, never one traced flat
   run — traced flat runs deadlock in this sandbox, §4.1 of the metrics report) and record the new
   line/branch floors with a dated pin.
2. `bridge/layout_bridge.py` 67.3 → ≥ 80 (missing 29: `get_app_state` error paths).
3. `services/db_registry.py` 70.5 → ≥ 80 and 4. `services/db_deletion_scan.py` 73.5 → ≥ 80
   (registry/scan share fixtures — write once).
5. `services/db_deletion_flow_remove.py` 70.1 → ≥ 80; 6. `_flow_detach.py` 78.8 → ≥ 80;
   7. `services/db_deletion_flow.py` 81.0 → verify (already ≥ 80 on user json — re-pin).
8. `bridge/collector_bridge.py` 72.1, 9. `bridge/people_bridge.py` 76.1, 10. `bridge/label_bridge.py`
   78.0 → ≥ 80 (bridge family, one session).
11. `stores/media_fetch.py` 77.7 + `history_schema_legacy.py` 82.8 + `media_network.py` 83.1 → re-pin.
12. JS tail splits (each ≤ 30 after): `color-picker.js::open(73)`, `composer.js::init(60)`,
    `core/bridge-ready.js::(anon)(54)`, `collector-panel.js::init(59)+1`, labels family
    (`labels.js::init(55)`, `labels-edit::_editRow(54)`, `labels-assign::renderAssign(50)`,
    `labels-render::pill(47)`).
13. Final: bump ratchets upward (never down), assert `file_coverage_floor.py --gate` exit 0.

## 2. Per-area implementation process (mandatory)

1. **Understand** — run the area's existing suites; record which behaviours they pin (suite names +
   what each asserts); reproduce the apex's section map (done for A/B/C in §0).
2. **Research / design** — if current code doesn't fit the rules (it doesn't — that's why we're
   here), redesign *the cut lines only*: stateless-helper part first, state-owning part second,
   facade last. Rejected designs must be named in the area's commit message.
3. **Implement** — one step per commit; suite green after every step; no behaviour change (this is a
   behavior-preserving decomposition: same exports, same IIFE singletons, same wire formats).

## 3. Shared-pin doctrine & integration (prevents the four branches colliding)

- `reports/js_size_baseline.json` / `reports/js_coverage_baseline.json`: each area re-pins **only
  its own files' entries** in its final commit (old pins kept when higher, floors never decrease;
  new split parts pin at first measurement; dated ledger comment in the commit).
- `docs/current/AGENT_RULES.md` / `SYSTEM_OF_RECORD.md`: **no area edits them** (no rule-number or
  flow changes are planned; RULE 18 §18.4 ceiling is already consumed).
- Integration (the session branch, in order D → C → B → A): merge one area, re-run `js_coverage.py`
  + `js_gate.py` + `rule16_gate.py --with-clones`, resolve pin overlaps centrally, then next.
- If two areas must touch the same test file (shouldn't — ownership is exclusive), the one merged
  later rebases; no shared-file edits outside the table above.

## 4. Exit criteria for Round II (recheck RULE 16 + RULE 18)

- [ ] `run_tiers.py --with-qt` exit 0, 3 consecutive runs, no webengine runaway.
- [ ] `js_gate.py` PASS with **≤ 10 over-30 functions remaining** and **0 functions > 100 LOC**
      (from 37 / 5 today); each remaining pin named in the baseline ledger.
- [ ] All four apex files decomposed: `chat_agent.js`/`sash-core.js`/`history-model.js`/
      `history-view.js` facades ≤ ~150 LOC each.
- [ ] `file_coverage_floor.py --gate` exit 0 with **0 below-floor files outside the ratchet** and
      the ratchet strictly smaller than today.
- [ ] Python line coverage ≥ 93.16 (never-decrease) and branch ≥ today's §4.1 number; JS coverage
      ≥ 85.31 (re-pinned upward if the splits raise attribution).
- [ ] RULE 16 gates all exit 0 (`rule16_gate --with-clones`, smell inventory, wait budget).
- [ ] RULE 18: SOR/AGENT_RULES line counts unchanged (343/730) unless a flow genuinely changed;
      context files stay 60–200 lines; this plan + the metrics report are the only new docs.
- [ ] Every area's commit chain contains: per-step commits, named design decisions, baseline
      re-pin commit with dated ledger.

## 5. What Round II is NOT

Not a rewrite, not a re-architecture, not new features; no python production edits except (possibly)
D's test-adjacent shims; no SOR §7 flow changes; no relaxation of any floor. R3+ (watch objects,
`dom_probe` apex, global floor raises) is scoped only after these exit criteria measure green.
