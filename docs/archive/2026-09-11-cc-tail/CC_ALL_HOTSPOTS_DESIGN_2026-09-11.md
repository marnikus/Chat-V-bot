# Every cyclomatic-complexity hotspot — inventory, prioritisation, extraction design

Date: 2026-09-11. Status: **inventory + design complete; implementation in
progress.** Measured on branch `arena/01a08fd1-chat-v-bot` (parent `3fc511b`)
with `tools/metrics/current_audit.py` (radon 6.0.1, cognitive-complexity
1.3.0). Precursor design (round-3 proposal, unimplemented):
`docs/archive/2026-09-10-safety-refactor/CC_REMAINING_TAIL_DESIGN_2026-09-10.md`.

## 1. Measured problem

Scope: 1,668 production functions in `core/ actions/ backend/ bridge/
services/ stores/ app/` + `main.py`.

| Metric | Measured | RULE 16 fail line | Verdict |
|---|---:|---:|---|
| Functions CC > 10 | **63** (mean 3.30, max 28) | CC ≤ 10 | 96.2 % inside |
| Cognitive > 15 | 21 (max 40) | ≤ 15 | 98.7 % inside |
| Nesting > 4 | 3 (max 6) | ≤ 4 | flat |
| Functions > 30 LOC | 74 | > 30 | flat |
| Functions > 4 params | 70 | > 4 | flat |

Baseline suite (this snapshot): **2,558 passed, 4 skipped, 1 deselected,
1 xfailed**, 273 s, `QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs`.

## 2. Prioritisation rule

Priority = **CC × blast radius**, not CC alone. Three tiers:

* **P1 (CC ≥ 16, 14 functions)** — the structural tail. Every one is a ladder
  of independent decisions that can be split into named predicates/phase
  functions. Fixing these moves the project maximum from 28 to 15.
* **P2 (CC 13–15, 15 functions)** — same shape, smaller ladders.
* **P3 (CC 11–12, 34 functions)** — one or two decisions over the line;
  usually a single extract or an early-return predicate each.

Cross-cutting tiebreak: a hotspot that is **pure** (no I/O, no Qt, no
concurrency) is done first — it is provable by a table check. Concurrency and
destructive paths (`cancellation`, `wait_page`, `error_recovery`,
`runtime.switch_db`) are done after the pure tier, each with a differential
harness.

## 3. The full inventory (all 63, in priority order)

| # | Tier | Location | CC | cog | nest | LOC | par | Shape / planned extraction |
|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | P1 | `stores/label_state.py:74 _normalized` | 28 | 25 | 3 | 50 | 0 | three independent cleaners: `_def_entry`/`_clean_defs`, `_clean_assign`, `_clean_filter` (+`_dedup`, `_keep_known`) |
| 2 | P1 | `actions/wait_page.py:40 execute` | 25 | 40 | 3 | 92 | 3 | `_stopped_report` boundary helper, `_probe_once`, `_report_not_found`/`_report_timeout`, `_wait_loop` |
| 3 | P1 | `backend/history_query.py:236 _item` | 22 | 22 | 2 | 34 | 1 | `_item_media` + alias locals (`direction`/`from_nick`/`stamp`); keeps key order |
| 4 | P1 | `backend/tab_matcher.py:70 score_tab` | 20 | 26 | 3 | 36 | 3 | `_score_url_like`, `_score_keyword`; `best_matches` (11) via `_tab_result` |
| 5 | P1 | `actions/cancellation.py:119 await_with_stop` | 19 | 35 | 5 | 75 | 4 | `_step_seconds`, `_as_supervised_task`, `_cancel_and_drain`, `_poll_supervised` |
| 6 | P1 | `services/layout_service.py:42 normalize_grid_tree` | 19 | 20 | 2 | 36 | 2 | `_clean_leaf`, `_clean_sizes`, `_clean_children`; then `parse_grid_payload` (13) |
| 7 | P1 | `stores/migration.py:39 migrate_legacy_config` | 19 | 14 | 2 | 79 | 2 | `_read_legacy_dict`, `_split_store_files` (table-driven), `_write_split`, `_archive_legacy` |
| 8 | P1 | `services/run/error_recovery.py:127 _execute_for_user` | 18 | 26 | 3 | 67 | 2 | `_block_run_decision`, `_run_one_block` |
| 9 | P1 | `services/history/mutate.py:102 _merge_legacy_queue` | 18 | 17 | 2 | 22 | 1 | `_legacy_user_rows`, `_insert_legacy_user`, `_archive_legacy_trio` |
| 10 | P1 | `stores/history_repo_identity.py:262 _same_conversation` | 18 | 12 | 1 | 23 | 6 | per-comparison-kind early-return predicates; 6-param signature frozen |
| 11 | P1 | `services/run/error_recovery.py:66 _run_collect_phase` | 17 | 15 | 3 | 54 | 1 | `_known_messaged_set`, `_persist_collected` + one summary formatter |
| 12 | P1 | `services/history/mutate.py:142 _rehome_undo_entries` | 17 | 12 | 2 | 23 | 0 | entry filter + seq backfill + insert loop helpers |
| 13 | P1 | `stores/media_layout.py:47 slugify_nick` | 16 | 20 | 4 | 35 | 1 | translit table + `_fold_one` predicate |
| 14 | P1 | `services/history/runtime.py:141 switch_db` | 16 | 18 | 4 | 60 | 1 | `_park_and_flush`, `_reopen_previous`, `_commit_switch` |
| 15 | P1 | `stores/label_world.py:37 load_from_db` | 16 | 14 | 3 | 38 | 1 | row reader + section cleaners |
| 16 | P2 | `backend/chat_sync.py:633 _settle_at_top` | 15 | 15 | 2 | 30 | 0 | settle-state predicates |
| 17 | P2 | `backend/chat_sync.py:216 plan` | 15 | 14 | 1 | 26 | 4 | per-transition helper |
| 18 | P2 | `stores/history_repo_identity.py:145 _ui_record` | 15 | 14 | 0 | 26 | 5 | field-group builders |
| 19 | P2 | `services/collector_service.py:434 handle_push` | 15 | 13 | 1 | 39 | 1 | payload validation + dispatch helper |
| 20 | P2 | `backend/history_query.py:524 person_stats` | 15 | 11 | 1 | 31 | 1 | counter helpers |
| 21 | P2 | `stores/history_models.py:109 from_dict` | 15 | 9 | 1 | 20 | 1 | per-field coercion table |
| 22 | P2 | `services/run/progress.py:82 filter_by_labels` | 14 | 24 | 4 | 23 | 2 | one predicate per label rule |
| 23 | P2 | `backend/dom_probe.py:163 interpret` | 14 | 22 | 3 | 38 | 2 | pure probe-result parsing ladder (`build_probe` untouched, §1.5) |
| 24 | P2 | `services/undo_service.py:436 work` | 14 | 19 | 3 | 41 | 0 | per-kind applier |
| 25 | P2 | `stores/user_memory.py:210 replace_all` | 14 | 18 | 3 | 39 | 1 | row normaliser + insert loop |
| 26 | P2 | `backend/message_injector.py:409 click_send` | 14 | 14 | 1 | 46 | 2 | send-button resolution + verification steps |
| 27 | P2 | `backend/chat_parser.py:196 verify_private` | 14 | 11 | 1 | 40 | 5 | RULE 15 gate: `_authors_of`, `_tab_named` |
| 28 | P2 | `backend/cdp_client.py:245 get_cookies` | 13 | 16 | 3 | 27 | 1 | `_tab_list_response`-style response walker |
| 29 | P2 | `services/db_lifecycle.py:239 _restore_unlocked` | 13 | 14 | 3 | 28 | 2 | restore-step helpers (destructive path: differential) |
| 30 | P2 | `stores/history_repo_lifecycle.py:153 _restore_rows` | 13 | 12 | 2 | 35 | 2 | row-set selection + write loop |
| 31 | P3 | `stores/media_fetch.py:194 _download` | 13 | 12 | 2 | 21 | 1 | transport + storage split |
| 32 | P3 | `actions/click_user.py:175 _verify_new_tab` | 13 | 10 | 1 | 29 | 5 | tab-title predicates |
| 33 | P3 | `services/layout_service.py:99 parse_grid_payload` | 13 | 8 | 1 | 27 | 1 | version guard + window-set check |
| 34 | P3 | `bridge/layout_bridge.py:119 save_window_states` | 13 | 7 | 1 | 21 | 1 | state normaliser |
| 35 | P3 | `stores/label_assignments.py:119 delete` | 13 | 6 | 2 | 20 | 1 | membership rebuild |
| 36 | P3 | `services/run/cycle_plan.py:31 inspect_stack` | 12 | 18 | 2 | 48 | 1 | per-stack-fact predicate |
| 37 | P3 | `backend/chat_parser.py:312 settle_after_top` | 12 | 16 | 2 | 41 | 5 | settle predicate ladder |
| 38 | P3 | `services/undo_service.py:352 apply_command` | 12 | 15 | 2 | 28 | 2 | per-kind branch methods |
| 39 | P3 | `stores/history_schema_repair.py:55 _repair_tables` | 12 | 15 | 3 | 40 | 0 | per-table repair step |
| 40 | P3 | `actions/take_person.py:53 choose` | 12 | 12 | 4 | 23 | 2 | candidate-selection predicates |
| 41 | P3 | `backend/dom_highlight.py:449 interpret_find` | 12 | 11 | 2 | 29 | 2 | field coercion helpers |
| 42 | P3 | `services/db_registry.py:204 info` | 12 | 11 | 1 | 43 | 0 | facet builders |
| 43 | P3 | `services/run/progress.py:123 _order_queue_by_column` | 12 | 7 | 2 | 18 | 1 | sort-key per column |
| 44 | P3 | `stores/history_repo_lifecycle.py:311 _after_write` | 12 | 7 | 0 | 41 | 8 | side-effect fan-out helpers; 8-param signature frozen |
| 45 | P3 | `backend/scroll_parser.py:330 _settle` | 11 | 19 | 3 | 39 | 2 | settle-condition predicates |
| 46 | P3 | `bridge/db_bridge.py:71 work` | 11 | 16 | 3 | 44 | 0 | command router methods |
| 47 | P3 | `bridge/history_bridge.py:462 _to_clipboard` | 11 | 13 | 4 | 32 | 1 | format selection |
| 48 | P3 | `stores/media_cache.py:37 migrate_layout` | 11 | 13 | 2 | 28 | 0 | per-layout-kind move |
| 49 | P3 | `bridge/undo_bridge.py:43 push_global_history` | 11 | 12 | 3 | 29 | 2 | kind validation + dispatch |
| 50 | P3 | `services/history/export.py:57 init` | 11 | 11 | 2 | 39 | 0 | binding/table bootstrap steps |
| 51 | P3 | `services/history/query.py:79 load_app_settings` | 11 | 11 | 3 | 23 | 0 | per-key coercion |
| 52 | P3 | `backend/media_handler.py:356 _inject_file` | 11 | 10 | 1 | 34 | 2 | input-resolution + verify |
| 53 | P3 | `services/history/mutate.py:76 save_gaze` | 11 | 10 | 2 | 18 | 0 | gaze-row upsert split |
| 54 | P3 | `stores/history_repo_identity.py:172 _ui_media` | 11 | 10 | 1 | 22 | 2 | media-field builder |
| 55 | P3 | `stores/media_fetch.py:84 on_response` | 11 | 10 | 1 | 13 | 1 | decode/dispatch |
| 56 | P3 | `stores/media_fetch.py:260 _fetch_via_python` | 11 | 10 | 4 | 43 | 1 | transport + retry |
| 57 | P3 | `backend/media_handler.py:127 parse_patterns` | 11 | 9 | 4 | 21 | 1 | pattern-kind parser |
| 58 | P3 | `backend/tab_matcher.py:108 best_matches` | 11 | 9 | 2 | 23 | 3 | `_tab_result` |
| 59 | P3 | `services/run/progress.py:146 _run_single_target_cycle` | 11 | 9 | 1 | 46 | 2 | cycle-step helpers |
| 60 | P3 | `stores/history_schema_repair.py:146 _copy_legacy_rows` | 11 | 9 | 2 | 32 | 3 | column projection |
| 61 | P3 | `services/history/mutate.py:125 _import_config_labels` | 11 | 8 | 1 | 16 | 0 | label-row coercion |
| 62 | P3 | `stores/history_repo_append.py:33 append` | 11 | 8 | 1 | 54 | 13 | 13-param legacy signature frozen; inner helpers only |
| 63 | P3 | `bridge/collector_bridge.py:128 set_my_nick` | 11 | 7 | 1 | 20 | 1 | validation + apply |

## 4. Rules of engagement (inherited from rounds 1–3, unchanged)

1. **Design first, implement per phase, measure, report.** Every phase is its
   own commit with before/after audit numbers.
2. **Behaviour-preserving**: no message, key, reason code, exception type,
   ordering or signal changes. `asyncio.CancelledError` always propagates
   after the same cleanup; `RunStopped` still beats a concurrently landed
   result; `timeout_ms = 0` still performs exactly one probe.
3. **Zero edits to existing tests.** New tests may be added; they must fail if
   the extracted unit were deleted (RULE 16 §16.3).
4. Every new/extracted unit: CC ≤ 10, cognitive ≤ 15, nesting ≤ 4, LOC ≤ 30,
   params ≤ 4. Legacy functions may only shrink.
5. **Anti-gaming (§16.2)**: no `foo_part1`/`foo_part2`, no lambda dispatch
   tables that only hide branch count, no deleted decisions. Every new name
   states a responsibility already visible in the domain.
6. Frozen surfaces stay: public names/signatures, Qt `@Slot` boundaries,
   `ActionResult` values, store/bridge API snapshots. The RULE 16 gate's
   `RATCHET` caps are hard: `HistoryQuery` 362 LOC / **14 methods**,
   `HistoryBridge` 493 / 45 — **extract module-level functions, not methods,
   inside those two classes** (measured today 340 / 14 and 486 / 31).
7. Coverage never below 90.44 % line / 84.38 % branch; Vulture set (7)
   unchanged; `tools/metrics/clone_scan.py` reports no new group.
8. `backend/dom_probe.py build_probe` (122 LOC embedded JS) stays untouched
   per §1.5; only its pure `interpret` parser is in scope (#23).

## 5. Phase plan

| Phase | Contents | Target after |
|---|---|---:|
| A | Pure ladders #1,#3,#4,#6,#7,#10,#13,#20,#21,#33 | max CC ≤ 19 |
| B | Concurrency #5 `await_with_stop`, #2 `wait_page.execute` | max cognitive ≤ 20 |
| C | Run engine #8,#11,#22,#36,#43,#59 (`services/run` all ≤ 10) | max CC ≤ 18 |
| D | History/stores tail #9,#12,#14,#15,#18,#19,#24,#25 | max CC ≤ 16 |
| E | Backend/bridge tail + nesting sites #2…#63 remainder | max CC ≤ 10 |

Exit criteria per phase: full suite green with unchanged counts; no legacy
metric worsened; `radon cc -s` on touched files shows every new unit ≤ 10;
`tools/metrics/current_audit.py` diff attached to the phase note.
