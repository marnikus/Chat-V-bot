# CC tail fixes — design round 3 (find ALL, prioritize, fix)

Date: 2026-09-11. Status: **implementation in progress** (phases marked
below). This round follows the round-3 proposal
`docs/archive/2026-09-10-safety-refactor/CC_REMAINING_TAIL_DESIGN_2026-09-10.md`
and the rules in `docs/current/AGENT_RULES.md` (RULE 16 hard gates, RULE 18
ideals, §16.5 legacy landmines, §16.6 workflow). It re-measures the current
tree, re-prioritizes the **complete** CC > 10 inventory, and fixes the tail in
behavior-preserving phases.

## 1. Measured problem (this checkout, 2026-09-11)

Tool: `tools/metrics/current_audit.py` (frozen walkers; radon CC rules).

| Metric | round-2 report | now |
|---|---:|---:|
| Functions CC > 10 | 64 | **63** |
| Project max CC | 28 | **28** |
| Mean CC | 3.31 | 3.32 |
| Cognitive > 15 (max) | 21 (40) | 21 (40) |
| Nesting > 4 (max) | 3 (6) | 3 (6) |
| Functions > 30 LOC | 75 | 74 |

Full 63-function inventory (same walker dump as §3) is the work queue.
Grouping by file so fixes bundle into behavior areas (one suite run each):

| Area | file | CC>10 there | worst |
|---|---|---:|---|
| stores/labels | `stores/label_state.py`, `stores/label_world.py`, `stores/label_assignments.py` | 3 | **28** |
| backend/history read | `backend/history_query.py` (×2) | 2 | 22 |
| backend match/parse | `backend/tab_matcher.py` (×2), `backend/chat_parser.py` (×2), `backend/dom_probe.py`, `backend/dom_highlight.py` | 6 | 20 |
| layout | `services/layout_service.py` (×2) | 2 | 19 |
| stores/migration+identity | `stores/migration.py`, `stores/history_repo_identity.py` (×3) | 4 | 19 |
| actions stop core | `actions/cancellation.py`, `actions/wait_page.py`, `actions/click_user.py`, `actions/take_person.py` | 4 | 25, cog 40 |
| run engine | `services/run/error_recovery.py` (×2), `services/run/progress.py` (×3), `services/run/cycle_plan.py` | 6 | 18 |
| history service | `services/history/mutate.py` (×3), `services/history/runtime.py`, `services/history/export.py`, `services/history/query.py` | 6 | 18 |
| chat sync (MI floor) | `backend/chat_sync.py` (×2) | 2 | 15 |
| collector/undo | `services/collector_service.py`, `services/undo_service.py` (×2) | 3 | 15 |
| media | `backend/media_handler.py` (×2), `stores/media_fetch.py` (×3), `stores/media_cache.py`, `stores/media_layout.py` | 7 | 16 |
| stores/history repo | `stores/history_models.py`, `stores/history_repo_lifecycle.py` (×2), `stores/history_repo_append.py`, `stores/history_schema_repair.py` (×2) | 6 | 15 |
| stores/labels+users | `stores/user_memory.py`, `stores/label_assignments.py` | 2 | 14 |
| db lifecycle/registry | `services/db_lifecycle.py`, `services/db_registry.py` | 2 | 13 |
| bridge | `bridge/db_bridge.py`, `bridge/history_bridge.py`, `bridge/undo_bridge.py`, `bridge/collector_bridge.py`, `bridge/layout_bridge.py` | 5 | 11, nest 6 |
| backend cdp/media | `backend/cdp_client.py`, `backend/message_injector.py` | 2 | 13 |

## 2. Prioritization

Score = (CC weight × 2) + cognitive + (nesting > 4 ? 20 : 0) +
(shared-coupling bonus: cancellation core +20, run engine +10) −
(landmine-care penalty − partially offset by existing suites). Ties broken by
"pure logic first" (differential-proofable in bulk). Result:

**Priority 1 — pure-logic ladders, project maxima (phase A).**
`label_state._normalized` 28 · `history_query._item` 22 ·
`tab_matcher.score_tab` 20 (+`best_matches` 11, same file) ·
`layout_service.normalize_grid_tree` 19 (+`parse_grid_payload` 13) ·
`migration.migrate_legacy_config` 19 · `history_repo_identity.`
`_same_conversation` 18 + `_ui_record` 15 · `label_world.load_from_db` 16 ·
`media_layout.slugify_nick` 16.
Why first: 9 of the 14 functions ≥ CC 16, all side-effect-light, each pinned
by existing suites (labels, history query, tab matcher, grid persistence,
migration rollback, media layout). Differential harnesses are cheap tables.

**Priority 2 — shared stop core & its client (phase B).**
`cancellation.await_with_stop` 19/cog 35/nest 5 — the one hotspot every block
and the engine flows through; `wait_page.execute` 25/cog 40 — holds the
project cognitive maximum, and its fix *uses* the phase-B helpers.
Highest care: differential harness per §16.2; task-lifecycle pins (no orphaned
task; `RunStopped` vs `TimeoutError` vs propagated `CancelledError`).

**Priority 3 — run-engine remainder (phase C).**
`error_recovery._execute_for_user` 18 · `_run_collect_phase` 17 ·
`progress.filter_by_labels` 14/nest 4 · `cycle_plan.inspect_stack` 12 ·
`progress._order_queue_by_column` 12 · `progress._run_single_target_cycle` 11.
Net: `tests/integration/run_safety/` + round-2 pin strings.

**Priority 4 — history service/state tail (phase D).**
`mutate._merge_legacy_queue` 18 · `mutate._rehome_undo_entries` 17 ·
`runtime.switch_db` 16/nest 4 · `chat_sync.plan` 15 · `_settle_at_top` 15 ·
`undo_service.work` 14 · `apply_command` 12; then the `history_repo_*`,
`history_schema_repair`, `user_memory.replace_all` 14.

**Priority 5 — backend/bridge tail + the two other nesting sites (phase E).**
`chat_parser.verify_private` 14 · `settle_after_top` 12 ·
`dom_probe.interpret` 14 (never `build_probe`, §16.1.5) ·
`message_injector.click_send` 14 · `collector_service.handle_push` 15 ·
`cdp_client.get_cookies` 13 (+`fetch_tabs` nest 5) · `media_handler` ×2 ·
`scroll_parser._settle` 11/nest 3 · `collector_bridge.collector_command`
nest 6 (router → named methods + frozen dispatch dict) · bridge CC 11 set ·
`take_person.choose` 12, `click_user._verify_new_tab` 13, `db_lifecycle.`
`_restore_unlocked` 13, `db_registry.info` 12, media `stores` tail.

### Rejected dishonest reductions (must not appear in any phase)

* one-line helpers re-hosting the original body under a non-name (§16.2);
* lambda dispatch tables whose only job is hiding `if` count — the
  `collector_bridge` router gets *named bound methods*, the one allowed
  routing-table case;
* deleting real branches (floor: label normalization's dedup+filter decisions
  cost ≥ 5 CC by themselves);
* splitting `dom_probe.build_probe` / `build_highlight_probe` JS payloads
  (§16.1.5 exemption);
* changing the frozen 6-param `_same_conversation` / wide legacy signatures
  to dodge the param cap — CC work only; arity is frozen this round;
* `foo_part1/foo_part2` splits.

## 3. Complete prioritized work queue (63 functions)

| # | file:line function | CC | cog | nest | LOC | phase |
|---|---|---:|---:|---:|---:|---|
| 1 | `stores/label_state.py:74 _normalized` | 28 | 25 | 3 | 50 | A |
| 2 | `actions/wait_page.py:40 execute` | 25 | 40 | 3 | 92 | B |
| 3 | `backend/history_query.py:236 _item` | 22 | 22 | 2 | 34 | A |
| 4 | `backend/tab_matcher.py:70 score_tab` | 20 | 26 | 3 | 36 | A |
| 5 | `actions/cancellation.py:119 await_with_stop` | 19 | 35 | 5 | 75 | **B** |
| 6 | `services/layout_service.py:42 normalize_grid_tree` | 19 | 20 | 2 | 36 | A |
| 7 | `stores/migration.py:39 migrate_legacy_config` | 19 | 14 | 2 | 79 | A |
| 8 | `services/history/mutate.py:102 _merge_legacy_queue` | 18 | 17 | 2 | 22 | D |
| 9 | `services/run/error_recovery.py:127 _execute_for_user` | 18 | 26 | 3 | 67 | C |
| 10 | `stores/history_repo_identity.py:262 _same_conversation` | 18 | 12 | 1 | 23 | A |
| 11 | `services/history/mutate.py:142 _rehome_undo_entries` | 17 | 12 | 2 | 23 | D |
| 12 | `services/run/error_recovery.py:66 _run_collect_phase` | 17 | 15 | 3 | 54 | C |
| 13 | `services/history/runtime.py:141 switch_db` | 16 | 18 | 4 | 60 | D |
| 14 | `stores/label_world.py:37 load_from_db` | 16 | 14 | 3 | 38 | A |
| 15 | `stores/media_layout.py:47 slugify_nick` | 16 | 20 | 4 | 35 | A |
| 16 | `backend/chat_sync.py:216 plan` | 15 | 14 | 1 | 26 | D |
| 17 | `backend/chat_sync.py:633 _settle_at_top` | 15 | 15 | 2 | 30 | D |
| 18 | `backend/history_query.py:524 person_stats` | 15 | 11 | 1 | 31 | D |
| 19 | `services/collector_service.py:434 handle_push` | 15 | 13 | 1 | 39 | E |
| 20 | `stores/history_models.py:109 from_dict` | 15 | 9 | 1 | 20 | D |
| 21 | `stores/history_repo_identity.py:145 _ui_record` | 15 | 14 | 0 | 26 | A |
| 22 | `backend/chat_parser.py:196 verify_private` | 14 | 11 | 1 | 40 | E |
| 23 | `backend/dom_probe.py:163 interpret` | 14 | 22 | 3 | 38 | E |
| 24 | `backend/message_injector.py:409 click_send` | 14 | 14 | 1 | 46 | E |
| 25 | `services/run/progress.py:82 filter_by_labels` | 14 | 24 | 4 | 23 | C |
| 26 | `services/undo_service.py:436 work` | 14 | 19 | 3 | 41 | D |
| 27 | `stores/user_memory.py:210 replace_all` | 14 | 18 | 3 | 39 | D |
| 28 | `actions/click_user.py:175 _verify_new_tab` | 13 | 10 | 1 | 29 | E |
| 29 | `backend/cdp_client.py:245 get_cookies` | 13 | 16 | 3 | 27 | E |
| 30 | `bridge/layout_bridge.py:119 save_window_states` | 13 | 7 | 1 | 21 | E |
| 31 | `services/db_lifecycle.py:239 _restore_unlocked` | 13 | 14 | 3 | 28 | D |
| 32 | `services/layout_service.py:99 parse_grid_payload` | 13 | 8 | 1 | 27 | A |
| 33 | `stores/history_repo_lifecycle.py:153 _restore_rows` | 13 | 12 | 2 | 35 | D |
| 34 | `stores/label_assignments.py:119 delete` | 13 | 6 | 2 | 20 | A |
| 35 | `stores/media_fetch.py:194 _download` | 13 | 12 | 2 | 21 | E |
| 36 | `actions/take_person.py:53 choose` | 12 | 12 | 4 | 23 | E |
| 37 | `backend/chat_parser.py:312 settle_after_top` | 12 | 16 | 2 | 41 | E |
| 38 | `backend/dom_highlight.py:449 interpret_find` | 12 | 11 | 2 | 29 | E |
| 39 | `services/db_registry.py:204 info` | 12 | 11 | 1 | 43 | D |
| 40 | `services/run/cycle_plan.py:31 inspect_stack` | 12 | 18 | 2 | 48 | C |
| 41 | `services/run/progress.py:123 _order_queue_by_column` | 12 | 7 | 2 | 18 | C |
| 42 | `services/undo_service.py:352 apply_command` | 12 | 15 | 2 | 28 | D |
| 43 | `stores/history_repo_lifecycle.py:311 _after_write` | 12 | 7 | 0 | 41 | D |
| 44 | `stores/history_schema_repair.py:55 _repair_tables` | 12 | 15 | 3 | 40 | D |
| 45 | `backend/media_handler.py:127 parse_patterns` | 11 | 9 | 4 | 21 | E |
| 46 | `backend/media_handler.py:356 _inject_file` | 11 | 10 | 1 | 34 | E |
| 47 | `backend/scroll_parser.py:330 _settle` | 11 | 19 | 3 | 39 | E |
| 48 | `backend/tab_matcher.py:108 best_matches` | 11 | 9 | 2 | 23 | A |
| 49 | `bridge/collector_bridge.py:128 set_my_nick` | 11 | 7 | 1 | 20 | E |
| 50 | `bridge/db_bridge.py:71 work` | 11 | 16 | 3 | 44 | E |
| 51 | `bridge/history_bridge.py:462 _to_clipboard` | 11 | 13 | 4 | 32 | E |
| 52 | `bridge/undo_bridge.py:43 push_global_history` | 11 | 12 | 3 | 29 | E |
| 53 | `services/history/export.py:57 init` | 11 | 11 | 2 | 39 | D |
| 54 | `services/history/mutate.py:76 save_gaze` | 11 | 10 | 2 | 18 | D |
| 55 | `services/history/mutate.py:125 _import_config_labels` | 11 | 8 | 1 | 16 | D |
| 56 | `services/history/query.py:79 load_app_settings` | 11 | 11 | 3 | 23 | D |
| 57 | `services/run/progress.py:146 _run_single_target_cycle` | 11 | 9 | 1 | 46 | C |
| 58 | `stores/history_repo_append.py:33 append` | 11 | 8 | 1 | 54 | D |
| 59 | `stores/history_repo_identity.py:172 _ui_media` | 11 | 10 | 1 | 22 | A |
| 60 | `stores/history_schema_repair.py:146 _copy_legacy_rows` | 11 | 9 | 2 | 32 | D |
| 61 | `stores/media_cache.py:37 migrate_layout` | 11 | 13 | 2 | 28 | E |
| 62 | `stores/media_fetch.py:84 on_response` | 11 | 10 | 1 | 13 | E |
| 63 | `stores/media_fetch.py:260 _fetch_via_python` | 11 | 10 | 4 | 43 | E |

Nesting > 4 sites (hard gate) not already listed:
`bridge/collector_bridge.py:97 collector_command` (nest **6**, CC 9, phase E)
and `backend/cdp_client.py:187 fetch_tabs` (nest **5**, CC 5, phase E);
`actions/cancellation.py:119` (nest 5) is #5 above.

## 4. Phase designs

### Phase A — pure-logic ladders (this round's core)

A1 **`label_state._normalized`** → three module-level pure helpers named after
the payload keys they produce: `_clean_defs(raw) -> (defs, seen_ids)`,
`_clean_assign(raw, seen_ids)` (keeps `assign` only for known ids,
order-preserving dedup via `dict.fromkeys`), `_clean_filter(raw, seen_ids)`
(the pinned *exclusion wins* comment survives verbatim on its body).
`_normalized` keeps ordering: defs → assign → filter → `next_id`. Same dict
keys, same types, same dedup order. Pinned by label suites +
`test_label_store_orphans`.

A2 **`history_query._item`** → `_item_media(data)` handles the
media_id/missing-file branch (vanished cache file ⇒ `state="missing"`,
`path=""` comment preserved); a module constant `_FIELD_SPECS`
(`(out_keys, source_key, default)`) drives the two alias columns
(`dir`/`direction`, `from`/`from_nick`, `time`/`ts_display`) and the int
casts (`id`, `ord`, `occ`). The anti-gaming check: the table replaces
*data* repetition, not decisions; each branch (`or` defaults, the media
branch) stays visible in code. Exact key set and order preserved
(UI contract + `backend_api_snapshot.json`).

A3 **`tab_matcher.score_tab`** → `_host_path_of(tab_url) -> (host, path)`
(the `urlparse`/`unquote` try/except, `(\"\",\"\")` fallback verbatim),
`_score_url_like(q_host, q_path, q_norm, tab_host, tab_path) ->
(score, kind) | None` (500 already checked by caller; then 300/200/weak-60 /
full-keyword-60 ladder), `_score_keyword(q_norm, url_norm, title)`.
`score_tab`: entry guards → exact → url-like → keyword. `best_matches` (CC
11): extract `_tab_url(tab)` used in both loops.

A4 **`layout_service.normalize_grid_tree`** → `_clean_leaf(node)`,
`_clean_sizes(sizes) -> list|error` (bool/type/min + sum rule),
`normalize_grid_tree` keeps depth-12, node-type, dir, kids/sizes shape and
recursion. All `error` strings byte-identical (asserted by
`test_grid_persistence` / `test_services_layout`). `parse_grid_payload`:
extract `_window_set_error(tree, version)` (known-sets upgrade + final
"must appear once" check).

A5 **`migration.migrate_legacy_config`** → `_read_legacy_dict(legacy_path,
config_dir) -> data|None` (existence + `_store_files_present` + the two
exact warning strings), `_split_store_files(data) -> dict[filename,
payload]` — pure, driven by the seven named sections incl. the
`CLAIMED_SECTIONS` complement and the undo index fallback −1 —
`_write_store_files(config_dir, files)`, `_archive_legacy(legacy_path)`
(timestamped `os.replace` + rename-warning). The driver performs the same
write order 1–7 and the same single log line.

A6 **same-file pure companions**: `history_repo_identity._same_conversation`
→ `_exact_match(cursor, head_sig, tail_sig)` + `_any_match(cursor, head_any,
tail_any)` predicates (frozen 6-param signature kept); `_ui_record` folds the
`or`-default pairs through a module `_FIELD_SPECS` like A2 (media join stays
its own await). `label_world.load_from_db` → `_filter_from_raw(raw)` +
`_next_id_from_db(db)` async one-liners with real responsibilities.
`media_layout.slugify_nick` → `_transliterate(raw) -> (slug, lossy)`;
`_final_slug(slug, raw, lossy)` keeps the reserved-name/hash rules.
`label_assignments.delete` → early-return guards.

**Exit A target:** project max CC ≤ 16 (only `score_tab` ladder level ~7
worst in the cluster) — i.e. every remaining CC > 10 is ≤ 16; no label /
history / layout / migration behavior drift; full suite green.

### Phase B — stop core + wait page (highest care, differential harness)

B1 **`await_with_stop`** → `_cancel_and_drain(task)` (exact
`except (asyncio.CancelledError, Exception)` swallow; never BaseException),
`_supervised_task(factory)` (future/task vs coroutine coercion),
`_step_seconds(slice_s)` (float coercion, ≤0 ⇒ default), `_poll_supervised`
(while loop: stop-check → deadline-check → done-check with stop-wins
recheck → shielded slice wait; `TimeoutError: continue`).
`await_with_stop`: entry stop-check → coercion →
`try: return await _poll_supervised(...)` / `except CancelledError:
drain-if-not-done; raise`.

B2 **`wait_page.execute`** → `_report_stopped()` method replacing the nested
closure (engine captured on `self._engine`? No — engine is a parameter;
keep a small `_stop_boundary(engine)` helper that wraps
`check_stopped`/`sleep_with_stop` and on `RunStopped` emits the existing
report then re-raises), `_probe_once(cdp, probe_deadline)` (bounded single
probe incl. the `max(deadline, now+0.05)` timeout rule; returns
`(res, outcome)`), `_report_not_found(...)` / `_report_timeout(...)`
throttled message helpers (verbatim strings, same `%7`/`%5` cadence).
`execute` keeps: entry stop → pre-delay → header report → loop → terminal
FAIL report. Verified `tests/unit/actions/test_wait_page_cancellation.py` is
behavior-based (no `inspect.getsource`), so the loop may move into helpers.
Differential: normal found, timeout_ms=0 single probe, stop before/while/done,
probe exception cadence, found-after-stop loses.

**Exit B targets:** `execute` CC ≤ 8 / cog ≤ 12; `await_with_stop` CC ≤ 8 /
nest ≤ 3; project cognitive max 40 → ≤ 26; project nesting max 6 (the bridge
router, phase E).

### Phases C–E (this doc records the design; implementation rounds follow A/B)

C (run engine): `_block_run_decision(block) -> note|None`,
`_run_one_block(block, idx, user) -> status`, `_known_messaged_set()`,
`_persist_collected(result)` (summary-log formatter variants preserved),
label-filter predicate extraction (`_label_verdict(filter_state, label_ids)`).
Keep round-2 structural-pin lesson: no source-inspected method moves.

D (history/stores): `switch_db` → `_park_and_flush` / `_commit_switch` /
`_reopen_previous` (fallback ladder verbatim); `mutate` → `_legacy_user_rows`,
`_insert_legacy_user`, `_archive_legacy_trio`; `_rehome_undo_entries` → entry
filter + seq backfill; `from_dict` → `_media_from_dict`; `replace_all` →
row-validation helpers; `person_stats` counts dictionary-driven.

E (backend/bridge tail + last nesting): `collector_command` → frozen
`{}`-dispatch of *named bound methods* (allowed router case), unknown-command
early return and trailing status emit stay in the Slot; `cdp_client` →
`_tab_list_response(session)` + `_page_tab(item)`; `verify_private` →
`_authors_ok` + `_tab_ok` predicates (fail-closed comments survive);
`dom_probe.interpret` ladder split (never `build_probe`); media/scroll/bridge
CC 11 set by predicate extraction.

## 5. Hard gates for every phase (exit checklist)

1. Every new/extracted unit: CC ≤ 10, cognitive ≤ 15, nesting ≤ 4, LOC ≤ 30,
   params ≤ 4 (radon/frozen walker), no legacy metric worsened.
2. Zero edits to existing tests; full suite green (baseline this round:
   2,545 passed, recorded below); REQ ≥ baseline coverage (line 90.44 % /
   branch 84.38 %).
3. Vulture set unchanged (7); no new clone group
   (`tools/metrics/clone_scan.py`); frozen API snapshots unchanged
   (`api_baseline.json`, `backend_api_snapshot.json`).
4. `doc`s: this file updated (RULE 17); `SYSTEM_OF_RECORD.md` metrics row only
   if a metric actually moves.

## 6. Baseline recorded before any edit

Tree: branch `arena/01a09022-chat-v-bot`, commit `f82007c`. Audit snapshot:
`/home/user/analysis/audit_round3_start.json` (63 functions CC > 10,
logged in §3). Test baseline: **2,576 passed, 2 pre-existing failures**
(297 s). Both failures are drift introduced by the f82007c merge, not by
this round:

1. `test_rule16_new_code.py::TestCloneBaselineIsHonest` — a new exact-AST
   clone group `stores/preset_store.py | stores/window_preset_store.py`
   (the per-path singleton-cache `__new__` tail) landed without entering
   `CLONE_BASELINE`.
2. `test_stores_public_api.py::…untouched` — pinned count 37, actual 38:
   the merged `backend/preset_store.py` compatibility shim added one
   `from stores…` facade import.

### Phase 0 — baseline repair (before CC work)

* **Clone:** extract the named helper `JsonFileStore._instance_for(key)`
  (the owning layer — both stores share that base; its docstring owns
  the-per-path-identity concept). The cache attribute stays per-subclass
  (`cls._by_path`, `instance._cache_key`); tests only pop/clear those
  dicts and are unaffected. The clone group disappears honestly — it is
  **not** merely added to `CLONE_BASELINE` (that would ratchet a smell).
* **Import pin:** bump 37 → 38 per the test's own documented bump rule
  ("another area legitimately grows the surface"); the +1 is the RULE
  16 §0 compatibility facade `backend/preset_store.py`.

### Phase-outcome log (all gates re-run at every row)

* **Phase D** `ef6b8a9` — history service/stores CC remainder. Over-gate
  63 → 27, max CC 15. Full suite green at commit.
* **Wave E1** `1b47757` — backend/actions hot path
  (`cdp_client.get_cookies`, `dom_highlight.interpret_find`,
  `click_user._verify_new_tab`, `take_person.choose`,
  `scroll_parser._settle`, `tab_gate`). Over-gate 27 → 16, max CC 13.
  Collector/actions/backend/bridge-cluster suites green; radon `-n C`
  clean on all touched files.
* **Wave E2** — bridges (`collector_command`, `db_bridge` work closure,
  `history_bridge` clipboard trio — helpers lifted to module level so the
  frozen HistoryBridge class cap is NOT breached, `undo_bridge` decoders,
  `layout_bridge._state_ids`), the media trilogy
  (`media_fetch._download` → `_tier_results`, `on_response` → `_mime_of`,
  `_fetch_via_python` → `_session_headers`/`_python_session_get`), the
  history tail (`export.init` ladder, `query.load_app_settings` →
  `_decode_app_settings`, `mutate.save_gaze` → `_gaze_rows`,
  `_import_config_labels` → `_config_label_bundle`,
  `history_repo_append.append` → `_gap_detail`/`_fill_counts`,
  `media_cache.migrate_layout` → `_rehome_one`) and the last nesting
  site (`cdp_client.fetch_tabs` → `_list_targets`, nest 5 → 4).
  **Queue exhausted: 0 functions CC > 10 (max 10), 0 nesting > 4,**
  cognitive > 15 = 2 frozen legacy (`router._build_router_class` —
  §16 named-bound-method exception, `settings_store.get`).
  Full suite **2,578 passed, 4 skipped, 1 xfailed**.

  Wave-E2 incident honesty log: (a) dropped `return True` in
  `db_bridge._db_action` — slot bool contract — found via
  `test_db_manager::TestDbBridge`, restored; (b) Phase-D latent bug
  `services/run/collect_phase.py` used `log` without defining it
  (containment lost a NameError) — caught by
  `test_run_state_machine_contract`, fixed (`import logging` +
  narrowed `from asyncio import CancelledError`, which also keeps the
  module header out of a new 3-file clone group);
  (c) `tests/test_sash_webengine.py` crashed the whole suite with a
  SIGABRT on machines without GL — its own docstring promises it skips
  there, so the skip guard now probes a real QWebEngineView show/paint
  in a subprocess (pre-existing; unrelated to this round's logic).
