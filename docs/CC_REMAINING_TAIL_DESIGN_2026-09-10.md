# Remaining max-CC / nesting tail — extraction design (round 3 proposal)

Date: 2026-09-10. Status: **design only — not implemented.** This document
is the required follow-up to round 2 (see
`reports/CODE_QUALITY_METRICS_2026-09-10_cc-tail.md`, §6 "Newly exposed
problems", and `docs/CC_TAIL_EXTRACTION_DESIGN_2026-09-10.md`). It fixes
**max cyclomatic CC only** (plus the nesting sites that CC extraction
touches), in behavior-preserving, independently verifiable phases. No
production code in this doc has been changed yet.

## 1. Problem (measured at the round-2 snapshot)

Project maxima after round 2: CC **28**, cognitive **40**, nesting **6**;
**64** functions CC > 10, **21** cognitive > 15, **3** nesting > 4,
**75** functions > 30 LOC. Every remaining hotspot is pre-existing
legacy; the round-2 targets are all ≤ 9.

### 1.1 The CC ≥ 16 binding tier (the queue, in priority order)

| # | Location | CC | cog | nest | LOC | Risk / test surface |
|---|---|---:|---:|---:|---:|---|
| 1 | `stores/label_state.py:74 _normalized` | 28 | 25 | 3 | 50 | Low — pure; `test_stores_*`, label suites |
| 2 | `actions/wait_page.py:40 execute` | 25 | **40** | 3 | 92 | High — cooperative cancel; `test_wait_page_cancellation.py` |
| 3 | `backend/history_query.py:80 _item` | 22 | 22 | 2 | 34 | Low — pure row mapping; `test_history_query*.py` |
| 4 | `backend/tab_matcher.py:70 score_tab` | 20 | 26 | 3 | 36 | Low — pure heuristic; `test_tab_matcher.py` |
| 5 | `actions/cancellation.py:119 await_with_stop` | 19 | 35 | **5** | 75 | **Highest** — shared supervision core; many suites |
| 6 | `services/layout_service.py:42 normalize_grid_tree` | 19 | 20 | 2 | 36 | Low — recursive validator; `test_services_layout.py` |
| 7 | `stores/migration.py:39 migrate_legacy_config` | 19 | 14 | 2 | 79 | Medium — one-shot file migration; `test_stores_migration_rollback.py` |
| 8 | `services/history/mutate.py:102 _merge_legacy_queue` | 18 | 17 | 2 | 22 | Medium — DB writes; history suites |
| 9 | `services/run/error_recovery.py:127 _execute_for_user` | 18 | 26 | 3 | 67 | High — run path; run-safety suites + pins |
| 10 | `stores/history_repo_identity.py:262 _same_conversation` | 18 | 12 | 1 | 23 | Low — pure (6-param legacy signature, keep) |
| 11 | `services/run/error_recovery.py:66 _run_collect_phase` | 17 | 15 | 3 | 54 | High — run path; run-safety suites |
| 12 | `services/history/runtime.py:141 switch_db` | 16 | 18 | **4** | 60 | High — world switch fallback; `test_switch_failure.py`, `test_services_history.py` |
| 13 | `stores/label_world.py:37 load_from_db` | 16 | 14 | 3 | 38 | Medium |
| 14 | `stores/media_layout.py:47 slugify_nick` | 16 | 20 | **4** | 35 | Low — pure transform |

### 1.2 Remaining nesting > 4 (hard-gate dimension)

- `bridge/collector_bridge.py:97 collector_command` — nesting **6**, CC 9:
  a seven-branch `elif` Qt command router.
- `actions/cancellation.py:119 await_with_stop` — nesting **5** (#5
  above).
- `backend/cdp_client.py:187 fetch_tabs` — nesting **5**, CC 5:
  `try → async with → async with → for → if` around the CDP tab list.

### 1.3 Structural problems the last round exposed

- `services/db_deletion.py` is now a **665-LOC / MI 20.54** module whose
  units are all small (worst CC 9) but which bundles four
  responsibilities: inventory collection, candidate classification,
  deletion planning/policy, pruning/unlinking.
- `RunCoordinator` still 181 LOC / 17 direct methods and
  `DbRegistry` 223 LOC / 14 (both legacy class-gate; method counts must
  not grow).
- Two frozen wide signatures (`classify_candidate` 7 kwargs,
  `plan_deletion` 9 kwargs) — needs an explicit facade-versioning
  decision, out of scope for a pure-CC round.
- Uncovered named branches from round 2 (between-cycle stop gate,
  cleanup-precedence warnings) and the uncalled raw facade
  `deletion_inventory_sources` — optional characterization tests.

## 2. Rules of engagement (same contract as rounds 1–2)

1. **Design first, implement per phase, measure, then report.** Every
   phase is its own commit with before/after audit numbers.
2. Behavior-preserving: no message, key, reason code, exception type,
   ordering, or signal changes. `asyncio.CancelledError` always
   propagates after the same cleanup; never weaken destructive-path
   protections; never rmtree; stale-plan revalidation stays before
   irreversible boundaries (round-1 pins).
3. **Zero edits to existing tests.** Each risky phase ships a differential
   harness comparing the `HEAD` implementation against the refactored one
   across scenarios (method used successfully twice: run engine
   13 scenarios, registry facade 7). Pure-logic phases rely on existing
   suites plus property/table checks recorded ad hoc.
4. RULE 16 hard gates for every new/extracted unit: CC ≤ 10, cognitive
   ≤ 15, nesting ≤ 4, LOC ≤ 30, params ≤ 4 (excl. self; kwargs count
   individually; **kwargs one). Legacy functions may only be *reduced*.
   Anti-gaming: no meaningless condition helpers or lambda dispatch
   whose only purpose is hiding branches (§2.1) — every new name must
   state a real responsibility already visible in the domain.
5. Frozen facades stay: public names/signatures, Qt `@Slot` boundaries,
   `ActionResult` values, store/bridge public API snapshots
   (`api_baseline.json`, `backend_api_snapshot.json`) must not change.
6. Coverage never below round-2 values (line 90.44 %, branch 84.38 %);
   Vulture set unchanged (7); no new clone groups; `import` stays light
   for `services.run` (function-local `actions.*` imports).
7. `dom_probe.build_probe` (122 LOC embedded JS) stays untouched per
   RULE 16 §1.5; only its pure `interpret` parser is a later target.

## 3. Phase A — pure-logic ladders (low risk, CC 28 → ~19)

One pull request, four/six files, no concurrency.

### A1. `label_state._normalized` → three pure phase functions

Extract from the 50-LOC body, on the same class (or module-private
pure functions taking `raw`, to keep the class small):

- `_clean_defs(raw) -> tuple[list[dict], set[str]]` — dict-only items,
  `normalize_name`/id dedup (by id then by casefolded name), normalized
  color/created_at fields.
- `_clean_assign(raw, seen_ids) -> dict[str, list[str]]` — nick
  normalization, list guard, membership filter, order-preserving dedup.
- `_clean_filter(raw, seen_ids) -> dict` — include/exclude membership,
  dedup, and the pinned "**exclusion wins**" filter rule kept verbatim
  with its comment.
- `_normalized` becomes: `raw = self._raw(); defs, ids = …; return
  {"defs": …, "assign": …, "filter": …, "next_id": …}` (CC 1–2).

Pin: exclusion-wins behavior and dedup ordering have existing label
tests; add no new behavior.

### A2. `history_query._item` → table-driven field mapping

The CC 22 is almost entirely `or`/`and` density in a dict literal.

- `_item_media(data) -> dict | None` — the media_id/missing-file branch
  (including the vanished-cache-file → `state="missing"`, `path=""`
  rule).
- Module constant `_FIELD_SPECS: tuple[tuple[str, str, object], …]`
  listing `(out_key, source_key, default)` covering the alias pairs
  (`dir`/`direction`, `from`/`from_nick`, `time`/`ts_display`) and the
  int casts (`id`, `ord`, `occ`); `_item` builds the dict by looping the
  table, then attaches `media`. Both legacy alias keys remain present in
  the exact output (UI contract). Verify with
  `test_history_query*.py` and the bridge API snapshot.

### A3. `tab_matcher.score_tab` / `best_matches`

- `_score_url_like(q_host, q_path, q_norm, tab_url) -> tuple[int,str]|None`
  — site-key/path ladder (500/300/200/60), including the
  `except Exception → ("","")` parse fallback verbatim.
- `_score_keyword(q_norm, url_norm, title) -> tuple[int,str]|None`
  (60/"keyword" else None).
- `score_tab` becomes: guards → exact check → `_score_url_like(...) or
  _score_keyword(...) or (0, "")`. `best_matches` keeps its two-pass
  shape; extract `_tab_url(tab)` / `_tab_result(...)` only if its CC
  (11) remains — otherwise leave.
- `_item`/score functions are pure: a quick cross-product differential
  (queries × tabs × titles incl. malformed URLs) against `HEAD`
  validates score/kind pairs.

### A4. `layout_service.normalize_grid_tree`

Split the recursive validator without changing error strings
(they are asserted by layout tests):

- `_clean_leaf(node) -> (dict|None, err|None)` (leaf without id rule).
- `_clean_sizes(sizes)` — bool/type/min-size checks and the
  99.5–100.5 sum rule.
- `_clean_children(kids, depth)` — recursive normalization with the
  depth-12 guard message ("tree too deep") reached via recursion.
- `normalize_grid_tree` keeps only the type/`dir`/children-shape head
  checks and assembles the split node. `parse_grid_payload` (CC 13) is
  in the same file — include only if time-boxed, otherwise phase D.

### A5. `migration.migrate_legacy_config` → read / split / archive

- `_read_legacy_dict(path) -> dict|None` — existence guard,
  `_store_files_present` guard, JSON/object validation with the exact
  warning strings, returning None on every "start fresh" path.
- `_split_store_files(data, state) -> dict[str, Any]` — pure:
  filename → payload for the seven stores, driven by an ordered
  constant list (settings via `CLAIMED_SECTIONS` complement, presets,
  bookmarks, blocks, labels, session, undo); identical coercion
  (`isinstance` guards, undo index fallback -1).
- `_write_split(config_dir, files)` — `makedirs` + `save_json` loop.
- `_archive_legacy(legacy_path) -> archived_name|None` — timestamped
  `os.replace` with the exact "could not be renamed" warning.
- Function becomes a linear driver (~CC 3). Files are read once and
  written in the same order; a migration differential over
  temp config dirs (valid/minimal/corrupt/already-migrated/non-dict)
  compares produced file trees byte-for-byte.

### A6. Identity/pure transformers while in the area (optional, same PR)

`history_repo_identity._same_conversation` (18) and
`media_layout.slugify_nick` (16, nest 4) are pure functions; reduce by
introducing early-return predicates per comparison kind. Keep the 6-param
`_same_conversation` signature (legacy).

**Exit A:** project max CC ≤ 19; cognitive max unchanged on wait_page
(40, phase B); full suite green; no snapshot drift.

## 4. Phase B — cancellation supervision and WaitPageLoad (highest care)

Concurrency-sensitive; must be done as its own PR with a differential
harness and explicit task-lifecycle checks.

### B1. `actions/cancellation.await_with_stop` (CC 19, cog 35, nest 5)

The same drain sequence repeats three times (stop, deadline, external
cancel):

```python
task.cancel()
try:
    await task
except (asyncio.CancelledError, Exception):
    pass
```

Extract (module-private, real names):

- `async def _cancel_and_drain(task) -> None` — cancel + swallow exactly
  `(CancelledError, Exception)` as today; never swallow
  `BaseException` (so external cancel semantics survive).
- `_as_supervised_task(coro)` — the future/Task vs coroutine
  normalization already in the prologue; plus the `slice_s` coercion
  helper `_step_seconds(slice_s) -> float`.
- `async def _poll_supervised(task, engine, step, deadline)` — the
  while loop: stop → drain + `RunStopped`; deadline → drain +
  `TimeoutError`; done → stop re-check (stop wins over a concurrently
  landed result) or `task.result()`; otherwise
  `wait_for(shield(task), step)` with `asyncio.TimeoutError: continue`.
- `await_with_stop` becomes: entry stop-check → task coercion →
  `try: return await _poll_supervised(...) except asyncio.CancelledError:
  drain-if-not-done; raise`.

Pin: ONE task is created from the factory; it is always awaited after
cancel; no orphan; `TimeoutError` vs `RunStopped` vs propagated
`CancelledError` precedence; result landing concurrently with stop is
rejected. Existing `test_cancel_concurrency.py` plus the cancellation
unit tests are the regression net; add a differential harness covering:
normal return, slow-complete vs deadline, stop before/while/done,
factory returning a finished future, zero/negative/garbage slice,
external cancel while pending and while draining.

### B2. `WaitPageLoad.execute` (CC 25, cog 40, 92 LOC)

Five identical `try: check_stopped/sleep_with_stop … except RunStopped:
_stopped_report(); raise` sites dominate the body.

- `async def _check_or_report_stop(self)` and/or
  `async def _sleep_or_stop(self, delay)`: run the stop boundary and on
  `RunStopped` emit the existing "⏹ Wait stopped on request…" report
  then re-raise (nested `_stopped_report` stays).
- `async def _probe_once(self, cdp, deadline) -> tuple[raw|None,
  timed_out:bool, exc|None]` — single bounded probe with the
  `max(deadline, now+0.05)` single-probe-at-timeout rule preserved;
  returns instead of breaking/raising so the loop decides.
- `_report_not_found(self, attempt, res)` /
  `_report_timeout(self, total)` carry the throttled
  (`attempt % 7 == 1`, `attempt % 5 == 1`) messages verbatim.
- `execute` keeps: entry stop → pre-delay → deadline → the while loop
  (check → probe → check → found return / deadline break / throttled
  progress / interval sleep) → terminal FAIL report. CC target ≤ 8,
  cog ≤ 12, LOC ≤ 30 (loop may live in a `_wait_loop` if needed, but
  note the run-engine structural-pin lesson: check whether any test
  source-inspects this method **before** moving the loop out —
  `test_wait_page_cancellation.py` is behavior-based; verify).

Pin: timeout_ms = 0 still performs exactly one probe; found-after-stop
loses to stop; probe exceptions are reported on attempts 1,6,11…;
`RunStopped` propagates without the timeout report.

**Exit B:** cognitive project max 40 → ≤ ~20; nesting 5 in this file → 0.

## 5. Phase C — run-engine remainder

Same differential harness style as round 2 (the run-safety harness is
already built at `tests/integration/run_safety/_helpers.py`; add a
matrix script like round 2's, do not modify tests).

- `error_recovery._execute_for_user` (18/26/67): extract
  `_block_run_decision(block, user) -> str|None` (disabled →
  `step_skip/run_skip` notes; `CONDITIONAL_SKIP`; the
  SCROLL_PARSE/REPEAT_LOOP/TAKE_PERSON continue set) and
  `_run_one_block(block, idx, user) -> status` (context, step events,
  retry-with-backoff with the exact `RunStopped` → step_end/
  step_complete/`run_end stopped` sequence and `Exception → "fail"`).
  The loop then contains: stop boundaries (two) → decision → runner →
  status early-return. Keep `finally` restore/ctx reset with the block.
- `_run_collect_phase` (17/15/54): extract
  `_known_messaged_set()`, `_persist_collected(result)` (upsert +
  summary log variants: seeking found / seeking none / seen-matched /
  purged — one formatter), and keep the tail stop predicate
  (`is_stop_requested` → RunStopped beats `result.stopped` legacy
  `[]` return — that compatibility comment must survive).
- `progress.filter_by_labels` (CC 14, cog 24, nest 4),
  `cycle_plan.inspect_stack` (CC 12, cog 18),
  `progress._run_single_target_cycle` (11, 46 LOC),
  `progress._order_queue_by_column` (12): predicate extraction per
  label rule / per stack fact; pure helpers preferred.
- Optional class-size follow-up: move the cycle/user runners into the
  existing `RunExecutionMixin` file grouping so `RunCoordinator` drops
  below 15 methods of *coordinator-owned* logic (the class stays the
  facade; method-count accounting excludes inherited mixins).

**Exit C:** no function in `services/run` above CC 10; rerun the
round-2 13-scenario matrix (extended for disabled/conditional blocks).

## 6. Phase D — history service tail + db_deletion module split

- `history/runtime.switch_db` (16, nest 4): extract
  `_park_and_flush(host) -> parked`,
  `_reopen_previous(host, previous, parked)` (the full fallback ladder
  incl. memory re-switch + world-state reload warnings, then collector
  restart + raise), and `_commit_switch(host, fresh, target, parked)`
  (rebind, settings persistence with the `collector` key excluded,
  collector reset guarded, world-state load, collector restart). The
  function becomes: validate → park → close/open attempt → commit or
  reopen. `test_switch_failure.py` already exercises the fallback.
- `history/mutate`: `_merge_legacy_queue` → `_legacy_user_rows(path)`
  (aiosqlite read with the RuntimeError wrapping),
  `_insert_legacy_user(row)` (SQL + 11 columns as module constants),
  `_archive_legacy_trio(path, stamp)` (`""`/`-wal`/`-shm`).
  `_rehome_undo_entries` (17) → entry filter + seq backfill + insert
  loop helpers. `_import_config_labels` (11) only if touched.
- Remaining stores/history CC 11–15 (`history_repo_lifecycle`,
  `history_repo_append.append` CC 11 with 13 params — treat as frozen
  legacy signature unless an internal kwargs fold is possible,
  `schema_repair`, `user_memory.replace_all`, `media_fetch`,
  `media_cache.migrate_layout`) follow the same predicate/helper
  pattern; bundle by file, one behavior area at a time.
- **db_deletion package split (structural, zero logic change):** convert
  `services/db_deletion.py` into `services/db_deletion/` with
  `canonical.py` (path predicates), `inventory.py`
  (`DeletionInventory`, `_InventoryCollector`,
  `build_deletion_inventory`, `collect_discovered_files`),
  `classify.py` (predicate ladder, `classify_candidate`),
  `plan.py` (`_PathPolicy`, `_PolicyBuckets`, `plan_deletion`,
  `DeletionPlan`), `prune.py` (`unlink_one`, `prune_empty_dirs`,
  `DeletionOutcome`), constants in `constants.py`, and an `__init__.py`
  re-exporting the **exact** frozen public surface
  (`DB_GROUP_SUFFIXES, SUPPORTED_BOUNDARY, canonical, is_within,
  is_same_file, DeletionInventory, build_deletion_inventory,
  collect_discovered_files, classify_candidate, plan_deletion,
  DeletionPlan, unlink_one, prune_empty_dirs, DeletionOutcome`).
  Verify with the full 129-test deletion suite (tests import
  `services.db_deletion.*`); the two callers' function-local imports
  must keep working. Only do this once phases A–C land, as a standalone
  PR.

## 7. Phase E — backend/bridge tail and the last nesting sites

- `collector_bridge.collector_command` (nest 6): the seven-way elif is a
  genuine **Qt command router** (not hidden condition logic). Give each
  command a named method (`_collector_start` does collector.start +
  archive.start; `_collector_tick`/`_collector_backfill` wrap
  `_run_async` with the exact task names; pause/resume/stop forward) and
  a frozen `dict[str, Callable]` mapping command → bound method; the
  unknown-command early return and the trailing status emit stay in the
  Slot. This matches §2.1's allowance for real routing tables (the
  methods carry the behavior, not lambdas). Bridge snapshot tests must
  stay green.
- `cdp_client.fetch_tabs` (nest 5): `_tab_list_response(session)` (the
  two nested async-context managers + GET) and
  `_page_tab(item) -> TabInfo | None` (type=="page" guard) reduce nesting
  to 2; failure logging/returns stay.
- `chat_sync.py` (MI 11.86, lowest in repo; `plan` 15,
  `_settle_at_top` 15): phase-sized on its own — map the sync
  state-machine decisions to named steps; behavior-differential via the
  collector/sync suites.
- `dom_probe.interpret` (14/22) is pure probe-result parsing (no JS
  payload) — ladder split is safe; never touch `build_probe`.
  `chat_parser` (`verify_private` 14, `settle_after_top` 12),
  `scroll_parser._settle` (11/19), `media_handler.parse_patterns`/
  `_inject_file`, `message_injector.click_send` (14), and the CC 11
  bridge methods (`db_bridge.work`, `history_bridge._to_clipboard`,
  `undo_bridge.push_global_history`, `collector_bridge.set_my_nick`,
  `layout_bridge.save_window_states`) complete the tail.

**Exit E:** project max nesting ≤ 4 (target 3); functions CC > 10
project-wide ≤ ~30 and none outside an explicit, commented legacy
waiver; no run/collector/CDP observable change.

## 8. Sequencing and exit criteria

| PR | Contents | Expected max CC after |
|---|---|---:|
| R3-A | §3 pure ladders (A1–A5, A6 optional) | ≤ 19 |
| R3-B | §4 cancellation core + wait page | ≤ 18, cog max ≤ ~20 |
| R3-C | §5 run-engine remainder | ≤ 18 (services/run all ≤ 10) |
| R3-D | §6 history tail + db_deletion package | ≤ 15 |
| R3-E | §7 backend/bridge tail + nesting sites | ≤ ~13; nesting ≤ 4 |

Hard exit criteria for every PR:

1. Full suite: same test counts green, zero test modifications; JS
   untouched (20/20 baseline).
2. All new units within RULE 16 gates; no legacy metric worsened;
   class method counts unchanged unless the class-size step itself is
   the PR.
3. Coverage ≥ round-2 baseline (90.44 % line / 84.38 % branch); Vulture
   findings set unchanged; clone scan (`tools/metrics/clone_scan.py`)
   reports no new group.
4. Risky phases (B, C, D-switch, E-bridge) include a recorded
   differential harness with scenario lists appended to each phase's
   design/PR note.
5. A new metrics report is produced after the final phase, and if new
   structural problems surface (the pattern of each round so far), a
   successor design doc is written before implementation.

## 9. Explicitly deferred (not CC work)

- God-class decomposition of `ScrollParser`, `Collector`,
  `HistoryBridge`, `UndoService`, `HistoryRepo` (>300 LOC / >30 methods):
  responsibility redesign, not CC extraction — separate design.
- Wide constructors / signatures (`scroll_parse.__init__` 20 params,
  `history_repo_append.append` 13, the two frozen deletion kwargs):
  require config-object or facade-versioning decisions.
- Bridge coverage pockets, stale JS registration test, the pre-existing
  unawaited-coroutine warning, real-WebEngine CI environment.
- The uncalled `deletion_inventory_sources` raw facade: add tests or
  remove in a dedicated facade-review change.
