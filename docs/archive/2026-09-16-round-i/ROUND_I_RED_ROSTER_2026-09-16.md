# Round I — RED roster (post-R0 merged tree, measured 2026-09-16)

Measured on `arena/01a0a4de-chat-v-bot` after the R0 merge (36b8062).
Commands: the three tier slices from `reports/CODE_QUALITY_METRICS_2026-09-16.md`
Reproduction + `pytest tests/test_node_harness_suites.py -q`.

Total: **89 RED** (green: 3289 passed + 973 subtests). Each item carries a
decision below (`fix` = real regression, code changes; `drift` = legitimate
re-baseline, named in commit).

## A — Node harness suites (14) — R1.7, via our wrapper
`test_bot_chat_js.js`, `test_db_panel_js.js`, `test_grid_close_autosave.js`,
`test_grid_persistence.js`, `test_history_panels_boot.js`, `test_labels_ui_js.js`,
`test_preset_io_ui.js`, `test_sash_grid_window_controls.js`, `test_sash_resize.js`,
`test_user_memory_sort.js`, `test_userdb_refresh.js`, `test_userdb_sort.js`,
`test_window_preset_ui.js`, `test_window_presets.js`
Cluster hypothesis: split modules renamed exports/ids the suites drive
(fix production split congruence or suite explicitly to the new module map).

## B — UI-wiring DOM contracts (5) — R1.2
`test_people_undo` confirm-dialogs 1 · `test_live_status_and_order` user-table 1
· `test_person_labels` TestUiWiring 2 · `test_db_manager` TestUiWiring 4
(qt slice: destructive confirmed, four actions, three sizes, last-world delete disabled)

## C — Legacy router compat surface (2) — R1.3
`test_router_contract::TestLegacyCompatSurface` (stack-history helpers,
kind-projection helpers) — helpers removed while frozen contracts pin them.

## D — File bridge bulk failure (41) — R1.3, single-root-cause hunt
`tests/unit/bridge/test_file_bridge.py::FileBridgeCase`: 41 of 45 items red
(import preview/apply/export/revalidate/merge). A whole class failing ⇒
one broken seam (constructor/kwargs/dependency), almost certainly NOT 41 bugs.

## E — Undo projections & seams (2) — R1.4
`test_services_undo::TestProjections::test_set_stack_projection_normalizes_and_clamps`,
`test_undo_support_contract::TestTimelineCommitSeams::test_a_failed_command_stays_where_ctrl_z_finds_it`.

## F — Stores surface & counts (5) — R1.5 (declare-or-fold modules)
`test_stores_public_api` 2 (surface frozen, external imports),
`test_stores_structure::TestFileSize` 1, `test_stores_module_families` 2.

## G — Media network-watch (3) — R1.4
`test_media_network_watch::TestDownloadChain` ×3 (noise reporting, tier skip,
noise-drop-vs-reason).

## H — Gate self-tests (5) — R1.5/R4
`test_rule16_new_code::TestRequestObjectIsSmall` + `TestClassLimitsAreEnforced`
(request object over own size gate — fix the code, not the gate),
`test_js_gate::TestGateEndToEnd` (baseline drift — re-baseline after R2),
`test_smell_inventory::TestCloneBaseline` (clone drift — review & re-baseline).

## I — Metrics lane, merge-introduced (2) — R2-owned, expected red until then
`test_wait_budget` (main-side over-50 ms sleeps not in the pins — review list),
`test_js_coverage` floor ratchet (floor 82.7 vs actual 69.49 — the R2 problem
statement, intentionally red; DO NOT lower the floor before R2.3).

## J — Environment-bound (1) — R1.6
`test_sash_webengine::test_grid_in_real_webengine` — needs real GPU/GL.
Policy adopt: `webengine` mark + default-off (session-stream pattern),
opt-in run on a GPU machine.

## Watchlist (state-dependent)
Pre-merge (raw main) measurements had these RED; post-merge they PASS:
`test_archive_delete_undo::TestUiWiring` (4), `test_history_query_gaps` (2).
The suite's own `test_sleep_and_hope_ratchet.py` documents exactly this
flake class — re-run slices at the end of R1 before claiming them fixed.
Also: mixed-qt tier SIGABRT (−6) seen 2026-09-16; not reproduced in the
post-merge qt-only slice — R1.6 keeps a 3-run stability check open.

## Family decisions ledger
| Family | Decision | Notes |
|---|---|---|
| D file-bridge 41 | drift (test-side) | dialog seams moved to file_bridge_dialogs; patch at the consuming modules' namespaces |
| C router compat 2 | fix (production) | UndoService facade half-renamed save→world_idx; projection + all callers ke pt save; facade signature reverted |
| E undo projections 2 + undo_wire 2 | fix (production) | same facade fix |
| B UI-wiring 8 | drift (test-side) | JS split moved wiring into <name>-*.js parts; contracts now read the module bundle |
| G media watch 3 | drift (test-side) | two fetch tiers moved onto fetcher._http in the media-store split; seams re-pointed |
| F stores surface/counts 5 | fix 1 + drift 4 | PALETTE frozen shim restored in label_assignments.py; outside-import 46→47 (main's authored state, ledgered); file count 44→57 + history_* band 21 (§18.3 remedies both blocked, per-family ceiling); upward edge moved media_fetch→media_fetch_http (still exactly one, ledgered) |
| A Node suites 14 | drift (harness) + 2 real fixes | shared tests/_ui_loader.js per-file loader (coverage attribution kept); js_family lists updated to the drag/stack splits. REAL FIXES: UIHelpers.mergeParts froze getter members at bind time → Labels.filterActive never updated, label filter inert; window-presets export gated behind a local document → backend-outline presets un-exportable |
| H gate self-tests 5 | drift 4 + measure 1 | rule16 pins PersonPageRequest path → history_query_request.py; clone pins 13→12 (final H wave re-grouped, net −1); js_gate baselines refreshed (size: authored final-wave JS + mergeParts legit growth; coverage: max(old,current), labels.js structural re-pin, 43 new files pinned at first measurement) |
| I machinery 2 | drift | js_coverage ratchet: now green (85.31% after suite repairs; floor 82.7 kept). wait_budget: 17 load-bearing waits annotated # wait-budget: <reason>, 12 stale pins regen'd to 13 current |
| J webengine 1 | pending (R1.6) | env-bound: decide mark + default-off |
| watchlist archive_delete_undo 4 + history_query_gaps 2 | fix (drift) | were truncated out of the first roster, still red: _my_nicks classmethod→module-function re-point; archive UI bundle reads |
| residual (open) | 2 | test_window_presets::test_export_... (_safe_filename attr gone) + undo_support_contract timeline (rewind_after_failure(forward=...) signature) — under repair |

Post-wave verification: three tier slices 3419 passed / 9 failed→(watchlist pair fixed in wave) — see commit.
JS gate: 86 → 0 violations (PASS). Node suites: 14 red → 35/35 green.
JS coverage: 69.49% → 85.31% (floor 82.7 cleared without touching it).
