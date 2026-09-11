# CC Tail — the whole inventory, prioritised, and the refactoring design

Date: 2026-09-11 (round 4). Branch: `arena/01a08dc3-chat-v-bot`.
Scope: **every** function in the production tree with cyclomatic complexity over
the gate — not the slice a previous round happened to reach.

Rules this document is written under: `docs/AGENT_RULES_CODE_QUALITY.md`
(RULE 16 gates, RULE 18 sizes and the reader's context budget) and the counting
conventions already fixed in `reports/CODE_QUALITY_METRICS_2026-09-11_round3.md`
(radon CC, `cognitive-complexity`, AST-span LOC, nesting by ancestry). Numbers
here are only comparable to that report, which used the same scanner and the
same definitions.

---

## 1. The inventory and how it was ordered

One command regenerates it:

```
.venv/bin/python tools/metrics/cc_inventory.py --coverage /home/user/analysis/coverage.json
```

The round-3 baseline had **63 functions over CC 10** in 1,668 (mean 3.30, max
28). Priority is not CC alone — it is *how far past the gate*, weighted by the
other gates the same function breaks and discounted by how well it is covered:

```
priority = CC - 10
         + 2 if cognitive > 15        (the report has to explain itself)
         + 2 if nesting > 3           (a reader cannot hold the frames)
         + 1 if LOC > 30              (RULE 18: one screen)
         + 1 if params > 4
         + 2 if line coverage < 80%   (the change is harder to prove)
```

Tier **A** — CC ≥ 16 or three gates at once: the functions whose every caller
inherits the whole branch tree.
Tier **B** — CC 14–15 with a cognitive or size breach: reachable by an ordinary
change, and the ones a reviewer will otherwise re-break.
Tier **C** — CC 11–13 in a file already flagged for another reason: fixed while
the file is open, not on their own.
Tier **D** — CC 11–13 elsewhere: listed, scheduled, not touched this round.

Frozen by `tests/unit/stores/test_stores_public_api.py`
(`FROZEN = ("stores.history_models", "stores.jsonio", "stores.migration")`, byte
comparison): `stores/migration.py::migrate_legacy_config` (CC 19). It stays
CC 19 **by design** — the test that pins it as the untouched legacy importer is
worth more than one gate number. Recorded as accepted legacy; see §5.

## 2. The five patterns that were used

Every fix below is one of these. They were chosen so the complexity goes into a
name, not into a `continue` or a helper that only re-raises.

1. **Table-driven dispatch** (`HistoryQuery._item`, `mutate._legacy_row`,
   `mutate._gaze_values`, `label_state._normalized`). A long `if`/`elif` chain or
   a chain of `x or default` coercions is a lookup table plus one loop: the
   branches stop existing, and adding a column becomes a table edit that cannot
   disagree with the SQL next to it.
2. **Score ladder** (`backend/tab_matcher.py`). Ordered rules that each answer
   *"match here?"* returning `None` for *no opinion*, chained with `or`. The
   `None` is load-bearing: a `(0, "")` answer is truthy and silently ends the
   ladder. `output.url` deliberately keeps the tab's *declared* url — the
   `ws_url` fallback is a scoring detail, not a value to hand back.
3. **Boundary extraction** (`actions/cancellation.py`, `actions/wait_page.py`,
   `services/run/error_recovery.py`, `services/history/runtime.py`). A
   `try/except/finally` that repeats at four call sites becomes one named
   boundary. The name says what the code was doing there (a stop boundary, a
   mark boundary), and the caller keeps the policy.
4. **Guard / verdict split** (`error_recovery._run_stack_entry`,
   `progress._single_target_guard`, `runtime._reopen_previous`). A helper returns
   the verdict, or `None` to keep going. The caller's `if verdict is not None:
   return verdict` is the whole policy; the helper owns the reporting that used
   to be duplicated at every exit.
5. **Phase split by collaborator** (`layout_service.normalize_grid_tree`,
   `label_world.load_from_db`, `history/mutate`). Each read, write or clean step
   becomes a module-level function taking exactly what it touches, so the class
   it came from does not grow methods to hold it. Where a mixin was already over
   the size ideal, the split produced two mixins composed under the old name
   (`RunExecutionMixin(CollectPhaseMixin, StepExecutionMixin)`) so every import
   and the MRO stayed as they were.

Anti-patterns deliberately **not** used: swallowing a branch in a
`contextlib.suppress`, moving a branch into a boolean-returning predicate whose
only caller is `if not pred()`, and adding a parameter to a function that already
has more than four (RULE 16 §6.2).

## 3. Verification, per file

For every touched file, in this order — the same protocol as
`CC_TAIL_EXTRACTION_DESIGN_2026-09-10.md` §6.3:

1. `tools/metrics/gate_check.py <path> --classes` — the gate table for the file,
   so a fix cannot trade CC for LOC, params, nesting or class size.
2. A differential harness against `git show HEAD:<path>` in `/tmp/diffh/`:
   both implementations loaded by `importlib`, the same inputs fed to both, and
   the *whole observable result* compared (value, key order, exception type and
   message, and for the async ones the ordered event log: engine reports, query
   counts, task states, orphans). A refactor that changes no behaviour must
   produce no divergence; where a scenario is wall-clock dependent it is dropped
   rather than tolerated.
3. Targeted tests for the touched area, then the full suite under coverage.
4. `vulture --min-confidence 80` (no dead code left behind by extraction) and
   `pylint --enable=R0801` (no new duplicate group) on the touched files.

Harness sizes this round: `history_query` 38,403 cases; `tab_matcher` 5,350;
`layout_service` 12,056; `cancellation` 21 scenarios; `wait_page` 16 scenarios;
`history/mutate` 40 scenarios against real SQLite files; `label_world` 3,513;
`progress` 580; `runtime.switch_db` 19 scenarios with a recorded call log.

Three defects were caught by that protocol, not by reading:
`wait_page._probe_once` had to keep `json.loads` inside the guarded region (a
malformed payload is a *probe failure*, reported and survived, not a crash);
`mutate.save_gaze` had to keep its value coercion **outside** the DB
`try/except` (a broken collector attribute must not be swallowed as a store
error); and `vulture` found an unreachable duplicate `return` a scripted edit
left behind.

## 4. What was done, file by file

The numbers for every row live in the generated table in §7, from one scanner on
two trees, so nothing here can disagree with them. This section is the *why*.

**`stores/label_state.py` — `_normalized`, CC 28.** The function cleaned four
payload keys with one branch pile. It is now five named cleaners
(`_label_identity`, `_clean_defs`, `_kept_ids`, `_clean_assign`, `_clean_filter`),
each owning one key's shape. The class `LabelState` shrank from 106 to 70 lines, and `_normalized` itself from 50 lines to 14; a label with
a non-string id still becomes the string the store keys on, which is the
behaviour `test_label_state_*` pins.

**`backend/history_query.py` — `_item`, CC 22.** Twenty-two ways to answer
"what is this column" is a table: `_ITEM_FIELDS` maps a column to its reader,
`_item_media` and `_item_value` hold the two shapes that need logic, and a
`_MEDIA` sentinel keeps the media branch from leaking into the scalar path.
Proved on 38,403 row shapes including `None`, empty strings and non-str ids.

**`backend/tab_matcher.py` — `score_tab` CC 20, `best_matches` CC 11.** The
scoring rules are an ordered ladder (`_tab_host_path` → `_score_same_site` →
`_score_within` → `_score_keyword`), where *no opinion* is `None`, so `or`
advances to the next rule. A helper returning `(0, "")` would be truthy and stop
the ladder silently — the reason `None` is the contract. `best_matches` scored
each tab twice (once to filter, once to sort); it builds `_match_row` once.
`output.url` keeps the tab's declared url: the `ws_url` fallback is for scoring.

**`services/layout_service.py` — `normalize_grid_tree` CC 19, `parse_grid_payload` CC 13.**
One recursive function that cleaned, validated, split errors and re-shaped sizes
became `_clean_leaf`, `_split_shape_error`, `_clean_sizes` and
`_clean_children(kids, depth, normalize)`; `normalize` is passed in so a
subclass override still reaches the leaves. The grid payload parser's older
layout-version upgrade now has its own name, `_match_window_set` — the behaviour
that must not regress (a v1 layout is migrated, not rejected) is a sentence
rather than a clause inside a 27-line function.

**`stores/media_layout.py` — `slugify_nick` CC 16** and
**`stores/history_repo_identity.py` — `_same_conversation` CC 18.** Transliteration
returns `(piece, lossy)` so the caller can decide whether the result is usable
(`_usable_slug`, `_dedupe_underscores`); identity compares signature lists in
one module function, `_signatures_agree`, after the stored-head guard was shown
to be redundant by exhaustion (12,762 combinations, plus 1,233 nicks including
Cyrillic, emoji, `a__b` and reserved device names).

**`actions/cancellation.py` — `await_with_stop` CC 19, cognitive 35, nesting 5.**
The supervised wait is now `_poll_supervised`, with `_step_seconds`,
`_as_supervised_task`, `_discard_result` and `_cancel_and_drain` around it; the
wrapper keeps only the entry stop-check and the `CancelledError` drain, because
that is the part a caller could otherwise not see. 21 scenarios compare outcome,
factory call counts, task states, orphaned tasks and stop-query counts.

**`actions/wait_page.py` — `execute` CC 25, cognitive 40 (the project's
maximum), 92 lines.** One block with four identical `try: check_stopped except
RunStopped: report; raise` sites and a probe inside a loop inside a try. It is
now a loop that reads as the policy — `_check_stop`, `_sleep_with_stop`,
`_probe_once`, then four named reports — over three landmines: an
already-stopped engine must not delay or probe at all (C1a), `timeout_ms=0` must
still probe exactly once so the timeout line can name the node count, and the
`attempt % 5 == 1` / `attempt % 7 == 1` report cadences are what make a long wait
readable. A failing probe must leave "last seen" untouched, which is why
`_probe_once` answers `(payload, timed_out, error)` and not a bare payload, and
why the malformed-JSON path stays inside the guarded region.

**`services/run/error_recovery.py` — `_execute_for_user` CC 18, `_run_collect_phase` CC 17.**
Two phases of a run were living in one function each. The collect half became
`CollectPhaseMixin`, the per-user half `StepExecutionMixin`, composed under the
name `RunCoordinator` already imports; the stop boundary in the stack is
`_stop_verdict`, the entry's decisions are `_run_stack_entry` (None to continue,
a verdict to end), and the phase trace dict is `_collect_stats` at module level
so the class did not gain a method for it. The B5 all-disabled guard and the
"pipeline-reported stop returns [] but does not raise" contract are preserved
verbatim — both are pinned by tests that check what the *engine* says, not what
it does.

**`services/history/mutate.py` — `_merge_legacy_queue` CC 18, `_rehome_undo_entries` CC 17,
`save_gaze` CC 11, `_import_config_labels` CC 11.**
Four importers that read a legacy database or app.json. Each is now a reader
table plus a short loop: `LEGACY_COLUMNS` decides both the SELECT list and the
INSERT binding (so a new column cannot be added to one and forgotten in the
other), `GAZE_FIELDS` says how each collector attribute is read, and
`UNDO_INSERT` is one statement shared by the import and by every save, which
also removed a duplicate-literal pair from the clone scan. `save_gaze` keeps its
value coercion *outside* the database `try`, deliberately: a broken attribute is
a bug, a broken store is a warning. Proved against real SQLite files: 40
scenarios, comparing table contents, config writes, renamed files and raised
values.

**`services/history/runtime.py` — `switch_db` CC 16, nesting 4.**
The fail-closed choreography was the risk, not the branching: which database was
opened with which FTS flag, what was closed, flushed, rebound, restarted,
written to app.json, and what the caller gets raised. `_reopen_previous` owns
the recovery; the queue rebind is one helper used on both paths (the forward path
must propagate a failure, the recovery path must only log it — that asymmetry is
the reason there are two, not one). Compared event-by-event on 19 scenarios with
a fake host, including "both files fail" and "the queue fails on the way back".

**`stores/label_world.py` — `load_from_db` CC 16, `flush_to_db` 31 lines.**
Four readers (`_label_defs`, `_assignments`, `_filter_state`, `_next_id`), each
answering "empty" for every shape of bad data instead of raising, and two write
helpers for the tables. 3,513 combinations of rows, orphan assignments, torn
filter JSON and corrupt counters, compared including the exception each side
raises.

**`services/run/progress.py` — `filter_by_labels` CC 14/cognitive 24, `_order_queue_by_column` CC 12, `_run_single_target_cycle` 46 lines.**
The label announcement (reason lookup, five-name cap, the "+N more" tail) is four
module functions; the Order-column scan is `_respects_order_column`; the
single-target cycle's three exits are `_single_target_guard`,
`_announce_single_target` and `_stop_before_mark`, kept as module functions in the
`cycle_plan.py` style so `RunQueueMixin` lost 30 lines instead of gaining four
methods. The `label_filter` that raises keeps the person — that is the contract
`label_allows` documents, and the harness sweeps callables that raise.

## 5. Sizes, not just complexity

Each extraction had to leave the *class* no worse than it was found
(RULE 16 §6.2 "warn on legacy growth"; the gate is > 150 LOC or > 15 methods):

| class | LOC before → after | methods before → after |
|---|---|---|
| `HistoryQuery` | 340 → 315 | 14 → 14 |
| `ConversationIdentity` | 238 → 232 | 12 → 12 |
| `LayoutService` | 184 → 183 | 13 → 14 |
| `HistoryMutateService` | 163 → 162 | 12 → 13 |
| `RunExecutionMixin` → `CollectPhaseMixin` + `StepExecutionMixin` | 178 → 91 + 148 | 7 → 6 + 10 |
| `RunHooksMixin` | 69 → 91 | 8 → 9 |
| `RunQueueMixin` | 149 → 119 | 8 → 8 |
| `WaitPageLoad` | 111 → 121 | 4 → 9 |
| `WorldSwitcher` | 100 → 138 | 6 → 12 |
| `LabelWorldSync` | (untouched size) 76 → 76 | 6 → 6 |

Two notes a reviewer should not have to rediscover. `mark_person_messaged` moved
from the execution mixin to `RunHooksMixin`, next to `person_collected` and
`unmessaged_nicks` — it is a per-person memory write, not step execution; the
coordinator's MRO and every call site (including the
`getattr(engine, "mark_person_messaged", None)` in `actions/mark_messaged.py`)
resolve exactly as before, and `backend_api_snapshot` covers only
`backend/**`+`actions/**`, which did not change. And `WaitPageLoad` grew by ten
lines because CC 25 cannot be split into eight helpers that each need the block's
own state; the three that did not (`_stopped_report`, `_report_probe_error`,
`_report_absent`) are module functions.

## 6. Follow-ups, in the order they should be taken

1. The CC 11–15 band left in the table below: `person_stats` (15, 31 LOC),
   `history_repo_identity._ui_record` (15, 5 params), `_ui_media` (11),
   `dom_probe.interpret` (14), `chat_parser.verify_private` (14),
   `message_injector.click_send` (14), `schema_repair` (13), `_order_queue_by_column`
   (9 now, still 18 LOC of dense reporting), and `services/run/cycle_plan.py`.
   Same protocol, one file per change.
2. `services/history/mutate.py`'s legacy importers (`_merge_legacy_queue`,
   `_import_config_labels`, `_rehome_undo_entries`) are one concern — "fold
   app.json and a pre-world database into a world" — that wants its own module
   with `db`, `config`, `memory`, `labels` as constructor arguments. It would
   take `HistoryMutateService` from 162 to about 110 LOC and remove the reason
   `runtime.py` reaches into `host._merge_legacy_queue`.
3. The two files whose *whole* problem is size, not branch count:
   `bridge/history_bridge.py` (493 LOC / 45 methods, ratcheted) and
   `services/db_deletion.py`. Neither is a CC task; both are decompositions, and
   each needs its own design document before a line moves.
4. Ten import cycles through `backend` (round-3 §3). Retiring the two
   back-assignment shims — `backend/bridge.py:9-10`, `backend/action_engine.py:3`
   — removes four of them and is a two-file change.
5. `stores/migration.py` conflict: either the freeze test gains an explicit
   "accepted legacy complexity" entry in `gate_check`'s exemption list, or the
   freeze is lifted with a note about what the file must never regain. That is
   the user's call, not a refactor.

## 7. The tail, in full

The generated inventory below is the authority: every function that was over
CC 10 when the pass started, its state now, and the line coverage of its file
before → after (a low number is a warning that the proof is thin, not a
licence to skip the function).

```
python3 tools/metrics/cc_tail_table.py \
    /home/user/analysis/audit_base.json /home/user/analysis/audit_round4.json \
    /home/user/analysis/coverage_base.json /home/user/analysis/coverage_round4.json \
    --frozen stores/migration.py
```

| # | function | CC | CC now | cog | cog now | LOC now | line cov | status |
|---|---|---|---|---|---|---|---|---|
| 1 | `stores/label_state.py::_normalized` | 28 | 2 | 25 | 1 | 14 | 95% → 93% | done |
| 2 | `actions/wait_page.py::execute` | 25 | 7 | 40 | 10 | 29 | 94% → 99% | done |
| 3 | `backend/history_query.py::_item` | 22 | 2 | 22 | 0 | 9 | 96% → 97% | done |
| 4 | `backend/tab_matcher.py::score_tab` | 20 | 10 | 26 | 8 | 19 | 91% → 93% | done |
| 5 | `actions/cancellation.py::await_with_stop` | 19 | 4 | 35 | 4 | 29 | 76% → 83% | done |
| 6 | `services/layout_service.py::normalize_grid_tree` | 19 | 9 | 20 | 8 | 29 | 98% → 99% | done |
| 7 | `stores/migration.py::migrate_legacy_config` | 19 | 19 | 14 | 14 | 79 | 96% → 96% | frozen |
| 8 | `services/history/mutate.py::_merge_legacy_queue` | 18 | 6 | 17 | 4 | 22 | 95% → 94% | done |
| 9 | `services/run/error_recovery.py::_execute_for_user` | 18 | 6 | 26 | 6 | 19 | 96% → 96% | done |
| 10 | `stores/history_repo_identity.py::_same_conversation` | 18 | 6 | 12 | 5 | 17 | 97% → 97% | done |
| 11 | `services/history/mutate.py::_rehome_undo_entries` | 17 | 7 | 12 | 7 | 21 | 95% → 94% | done |
| 12 | `services/run/error_recovery.py::_run_collect_phase` | 17 | 4 | 15 | 3 | 26 | 96% → 96% | done |
| 13 | `services/history/runtime.py::switch_db` | 16 | 6 | 18 | 5 | 29 | 89% → 89% | done |
| 14 | `stores/label_world.py::load_from_db` | 16 | 2 | 14 | 0 | 20 | 88% → 88% | done |
| 15 | `stores/media_layout.py::slugify_nick` | 16 | 6 | 20 | 5 | 20 | 96% → 97% | done |
| 16 | `backend/chat_sync.py::_settle_at_top` | 15 | 15 | 15 | 15 | 30 | 96% → 96% | open |
| 17 | `backend/chat_sync.py::plan` | 15 | 15 | 14 | 14 | 26 | 96% → 96% | open |
| 18 | `backend/history_query.py::person_stats` | 15 | 15 | 11 | 11 | 31 | 96% → 97% | open |
| 19 | `services/collector_service.py::handle_push` | 15 | 15 | 13 | 13 | 39 | 89% → 89% | open |
| 20 | `stores/history_models.py::from_dict` | 15 | 15 | 9 | 9 | 20 | 100% → 100% | open |
| 21 | `stores/history_repo_identity.py::_ui_record` | 15 | 15 | 14 | 14 | 26 | 97% → 97% | open |
| 22 | `backend/chat_parser.py::verify_private` | 14 | 14 | 11 | 11 | 40 | 90% → 90% | open |
| 23 | `backend/dom_probe.py::interpret` | 14 | 14 | 22 | 22 | 38 | 98% → 98% | open |
| 24 | `backend/message_injector.py::click_send` | 14 | 14 | 14 | 14 | 46 | 70% → 70% | open |
| 25 | `services/run/progress.py::filter_by_labels` | 14 | 8 | 24 | 9 | 13 | 90% → 91% | done |
| 26 | `services/undo_service.py::work` | 14 | 14 | 19 | 19 | 41 | 83% → 83% | open |
| 27 | `stores/user_memory.py::replace_all` | 14 | 14 | 18 | 18 | 39 | 99% → 99% | open |
| 28 | `actions/click_user.py::_verify_new_tab` | 13 | 13 | 10 | 10 | 29 | 97% → 97% | open |
| 29 | `backend/cdp_client.py::get_cookies` | 13 | 13 | 16 | 16 | 27 | 64% → 64% | open |
| 30 | `bridge/layout_bridge.py::save_window_states` | 13 | 13 | 7 | 7 | 21 | 66% → 66% | open |
| 31 | `services/db_lifecycle.py::_restore_unlocked` | 13 | 13 | 14 | 14 | 28 | 84% → 84% | open |
| 32 | `services/layout_service.py::parse_grid_payload` | 13 | 6 | 8 | 5 | 15 | 98% → 99% | done |
| 33 | `stores/history_repo_lifecycle.py::_restore_rows` | 13 | 13 | 12 | 12 | 35 | 95% → 95% | open |
| 34 | `stores/label_assignments.py::delete` | 13 | 13 | 6 | 6 | 20 | 93% → 93% | open |
| 35 | `stores/media_fetch.py::_download` | 13 | 13 | 12 | 12 | 21 | 80% → 80% | open |
| 36 | `actions/take_person.py::choose` | 12 | 12 | 12 | 12 | 23 | 100% → 100% | open |
| 37 | `backend/chat_parser.py::settle_after_top` | 12 | 12 | 16 | 16 | 41 | 90% → 90% | open |
| 38 | `backend/dom_highlight.py::interpret_find` | 12 | 12 | 11 | 11 | 29 | 97% → 97% | open |
| 39 | `services/db_registry.py::info` | 12 | 12 | 11 | 11 | 43 | 70% → 70% | open |
| 40 | `services/run/cycle_plan.py::inspect_stack` | 12 | 12 | 18 | 18 | 48 | 100% → 100% | open |
| 41 | `services/run/progress.py::_order_queue_by_column` | 12 | 9 | 7 | 6 | 18 | 90% → 91% | done |
| 42 | `services/undo_service.py::apply_command` | 12 | 12 | 15 | 15 | 28 | 83% → 83% | open |
| 43 | `stores/history_repo_lifecycle.py::_after_write` | 12 | 12 | 7 | 7 | 41 | 95% → 95% | open |
| 44 | `stores/history_schema_repair.py::_repair_tables` | 12 | 12 | 15 | 15 | 40 | 87% → 87% | open |
| 45 | `backend/media_handler.py::_inject_file` | 11 | 11 | 10 | 10 | 34 | 91% → 91% | open |
| 46 | `backend/media_handler.py::parse_patterns` | 11 | 11 | 9 | 9 | 21 | 91% → 91% | open |
| 47 | `backend/scroll_parser.py::_settle` | 11 | 11 | 19 | 19 | 39 | 94% → 94% | open |
| 48 | `backend/tab_matcher.py::best_matches` | 11 | 8 | 9 | 6 | 12 | 91% → 93% | done |
| 49 | `bridge/collector_bridge.py::set_my_nick` | 11 | 11 | 7 | 7 | 20 | 77% → 77% | open |
| 50 | `bridge/db_bridge.py::work` | 11 | 11 | 16 | 16 | 44 | 87% → 87% | open |
| 51 | `bridge/history_bridge.py::_to_clipboard` | 11 | 11 | 13 | 13 | 32 | 65% → 65% | open |
| 52 | `bridge/undo_bridge.py::push_global_history` | 11 | 11 | 12 | 12 | 29 | 100% → 100% | open |
| 53 | `services/history/export.py::init` | 11 | 11 | 11 | 11 | 39 | 86% → 86% | open |
| 54 | `services/history/mutate.py::_import_config_labels` | 11 | 5 | 8 | 4 | 14 | 95% → 94% | done |
| 55 | `services/history/mutate.py::save_gaze` | 11 | 6 | 10 | 5 | 12 | 95% → 94% | done |
| 56 | `services/history/query.py::load_app_settings` | 11 | 11 | 11 | 11 | 23 | 93% → 93% | open |
| 57 | `services/run/progress.py::_run_single_target_cycle` | 11 | 6 | 9 | 5 | 26 | 90% → 91% | done |
| 58 | `stores/history_repo_append.py::append` | 11 | 11 | 8 | 8 | 54 | 98% → 98% | open |
| 59 | `stores/history_repo_identity.py::_ui_media` | 11 | 11 | 10 | 10 | 22 | 97% → 97% | open |
| 60 | `stores/history_schema_repair.py::_copy_legacy_rows` | 11 | 11 | 9 | 9 | 32 | 87% → 87% | open |
| 61 | `stores/media_cache.py::migrate_layout` | 11 | 11 | 13 | 13 | 28 | 90% → 90% | open |
| 62 | `stores/media_fetch.py::_fetch_via_python` | 11 | 11 | 10 | 10 | 43 | 80% → 80% | open |
| 63 | `stores/media_fetch.py::on_response` | 11 | 11 | 10 | 10 | 13 | 80% → 80% | open |

Numbers come from `tools/metrics/cc_tail_table.py` run on the two `current_audit.py` dumps; the frozen row is §1's `stores/migration.py`, and `open` rows are §6's schedule, not oversights.
