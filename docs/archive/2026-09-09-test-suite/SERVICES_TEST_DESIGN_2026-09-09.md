# 🧪 Test Design — `services/` Orchestration Layer (Section E)

> **Date:** 2026-09-09
> **Branch:** `arena/01a0869c-chat-v-bot`
> **Method (per instruction):** design the test paths first, *then* look at
> implementation. No "coverage theatre" — every test asserts real behaviour,
> and the suite is used to hunt real bugs in the layer.

---

## 1. Scope & Rules

Target modules (8, from the Section E matrix):

| Module | LOC | Status | Existing tests (indirect) | New direct suite |
|---|---|---|---|---|
| `services/run_service.py` | 924 | 🔴 | `test_engine_standalone_run.py` | `test_services_run.py` |
| `services/collector_service.py` | 776 | 🟡 | `test_collector_state.py`, `test_collector_panel_js.js` | `test_services_collector_gaps.py` |
| `services/db_service.py` | 612 | 🟡 | `test_db_manager.py`, `test_db_switch_e2e.py` | `test_services_db_gaps.py` |
| `services/history_service.py` | 867 | 🔴 | *none direct* | `test_services_history.py` |
| `services/layout_service.py` | 203 | 🔴 | *none direct* | `test_services_layout.py` |
| `services/people_service.py` | 215 | 🔴 | `test_people_undo.py`, `test_search_users.py` | `test_services_people.py` |
| `services/cdp_service.py` | 119 | 🔴 | `test_cdp_events.py` (client events, not the service) | `test_services_cdp.py` |
| `services/undo_service.py` | 624 | 🔴 | `test_merge_undo_enabled.py` | `test_services_undo.py` |

Test-design rules:

1. **Behaviour over internals.** A test asserts the *contract* (Result shape,
   event emitted, DB rows, timeline state), never a private helper unless the
   helper **is** the contract (e.g. `LayoutService.normalize_grid_tree`).
2. **Result seam.** Every method that declares `Result[T]` must be proven on
   both paths: `Ok` and `Err(code)`. No bare exception may cross the seam —
   this is where bugs hide.
3. **Real stores where cheap.** `UserMemory`, `HistoryDB`, `ConfigManager`
   run against real SQLite / JSON in a temp dir (AGENT_RULES RULE 8). Only
   CDP/UI objects are faked (`FakePage` from `tests/test_chat_parser_delta.py`,
   `types.SimpleNamespace` for bridges).
4. **Events are assertions.** The services announce via `EventBus`; the
   bridge forwards them. Tests subscribe to the bus and assert the payload —
   the wire contract.
5. **Idempotency.** Push/append/save paths must be provably replay-safe
   (duplicate pushes, double ticks, repeated saves).
6. **Files go to `tests/integration/services/`** (already exists, matches the
   design doc §4.3 layout) and are also collectable by `pytest`. Each file is
   directly runnable: `python3 tests/integration/services/test_<x>.py`.

---

## 2. Module-by-module test plan

### 2.1 `undo_service.py` — `test_services_undo.py` (P1)

The ONE global timeline. Test paths:

| # | Path | Setup | Assert |
|---|---|---|---|
| U1 | `push` appends + returns `(history, index)` | fresh `UndoService(config)` | `Ok`, 1 entry, index 0, entry has `seq=1` |
| U2 | `push` unknown kind | `push("nope", {})` | `Err("unknown_kind")`, no entry |
| U3 | `push` identical tip value twice | push same grid payload twice | **1 entry** (dedupe), index unchanged |
| U4 | `push` after undo truncates redo tail | push A, B → undo → push A | **1 entry** (A), index 0, no stale B |
| U5 | `push` after undo *different* value | push A, B → undo → push C | [A, C], index 1 |
| U6 | cap at `MAX_STACK_HISTORY` (100) | push 105 entries | len == 100, index 99, oldest dropped |
| U7 | `push` same value after undo → no duplicate + no growth | U3+U4 combo | entries = 1 |
| U8 | `undo` on empty timeline | fresh | `Err("nothing_to_undo")` |
| U9 | `undo` first stack entry | one entry | `Err` ("nothing before the first entry") |
| U10 | `undo` stack walks to previous + applies state | fake engine captures `load_stack` | pointer −1, engine loaded previous blocks, `StackLoaded` emitted, config `last_stack` updated |
| U11 | `redo` at tip | after undo | `Err("nothing_to_redo")` |
| U12 | `redo` stack re-applies | after undo | pointer +1, engine loaded the redo blocks |
| U13 | `undo/redo` people command applies restore | `PeopleService` + `UserMemory` + loop | before/after rows restored, `Ok({kind, value, index})` |
| U14 | `undo` people command with **no** `_people` wired | `UndoService(config)` only | `Err("nothing_to_undo")` (cannot reverse) — never a fake success |
| U15 | `apply_command` unknown kind / malformed value | `apply_command({}, True)` | `False` |
| U16 | `push_stack` compat projection preserves order + index | stack, grid, stack | stacks list [s1, s2], index mapping correct |
| U17 | `kind_projection` | mixed kinds | only that kind, correct local index |
| U18 | `set_stack_projection` normalizes + clamps index | history with retired keys | cleaned blocks, index clamped |
| U19 | `push` emits `UndoHistoryChanged` | bus subscribed | 1 event |
| U20 | `sync_world_state` merges app + world entries by `seq` | config app entries {seq 1,3} + fake archive `load_world_undo` {seq 2} | merged order 1,2,3; index at tip; `Ok(None)` |
| U21 | `sync_world_state` with archive closed | `archive=None` / `db.is_open=False` | config-only timeline, no crash |
| U22 | world save scheduled only when archive open | fake archive open | `_undo_pendings` drained; `save_world_undo` called with world entries only |
| U23 | `migrate_global_history` legacy `stack_history` + `grid_layout_history` | config seeded with legacy keys | canonical grid entries, `undo_history` written, index = top (grid) |
| U24 | `migrate_global_history` raw `undo_history` list reused | config with `undo_history` | entries preserved, index clamped |
| U25 | `commit_timeline` assigns seq to entries missing it | `set_history([...no seq...])` | seqs assigned, `_seq_next` advances |

**Bug hypotheses checked here (see §3):** U3/U4 proved broken — the dedupe
compares *with* `seq` against *without*, and the redo tail is not truncated
on the same-value re-push.

### 2.2 `layout_service.py` — `test_services_layout.py` (P2)

Pure grid-tree logic (no I/O). Test paths:

| # | Path | Input | Assert |
|---|---|---|---|
| L1 | `default_tree` / `default_payload` | — | every `WINDOW_IDS` once, canonical JSON, `v=3`, parses clean |
| L2 | `node_type` spellings | `{"t":"leaf"}` / `{"type":"split"}` / non-dict | `"leaf"` / `"split"` / `None` |
| L3 | `normalize_grid_tree` valid leaf/split | canonical tree | canonical `t` tree, no `type`, sizes preserved |
| L4 | leaf without id / non-dict / unknown type | variants | `(None, "leaf without id")` etc. |
| L5 | split: bad dir, <2 children, sizes mismatch | variants | specific errors |
| L6 | size validation: below min, bool, non-number | sizes `[4, 96]` ok; `[0,100]`, `[True,100]` bad | errors mention size |
| L7 | sizes sum outside 99.5..100.5 | `[1,1]` | error |
| L8 | depth guard | 13 nested splits | `"tree too deep"` |
| L9 | `leaf_ids` dedupes nothing but lists all; duplicates | tree with duplicate id | both occurrences listed |
| L10 | `parse_grid_payload` corrupt JSON / non-dict / bad version | `"{", "[]", {"v":4}` | `(None, error)` |
| L11 | v1/v2 legacy payload upgraded, never rejected | v1 payload with `type` spelling + only V1 windows | canonical tree, `v` not required in output, all `WINDOW_IDS` present |
| L12 | v3 payload with missing/extra window | 11 of 12 windows | `window set mismatch` |
| L13 | `migrate_grid_tree` one missing window | tree without `labels` | leaf appended, sums 100 |
| L14 | `migrate_grid_tree` several missing | tree without `labels`, `dbconn` | split appended, sizes sum ≈100, min size ok |
| L15 | `migrate_grid_tree` no missing | full tree | returns the SAME tree object (no-op) |
| L16 | `canonical_grid_payload` valid/invalid | valid & garbage | compact JSON vs `(None, err)` |
| L17 | `legacy_grid_payload` v1 → `type` spelling, v3 passthrough | v1 payload / v3 payload / non-JSON | converted / raw preserved |
| L18 | roundtrip: `default_payload` → `parse` → `canonical` | — | idempotent |

### 2.3 `cdp_service.py` — `test_services_cdp.py` (P2)

Result seam + event fan-out. Test paths:

| # | Path | Setup | Assert |
|---|---|---|---|
| C1 | `fetch_tabs` success | fake cdp with 2 `TabInfo`-like objects | `Ok`, `TabsReceived` payload has id/title/url/ws_url |
| C2 | `fetch_tabs` failure | fake cdp raises | `Err("tab_fetch_failed")`, `LogMessage(error)` |
| C3 | `fetch_tabs` malformed tab entry | one tab without `ws_url` attr | **`Err` (no AttributeError escapes)** — bug hypothesis B2 |
| C4 | `connect` success | cdp returns True | `Ok(True)`, `LogMessage("Connected")` |
| C5 | `connect` failure | cdp raises | `Err("connect_failed")` (no raise) |
| C6 | `connect` returns False | cdp returns False | `Ok(False)`, no "connected" log |
| C7 | `find_tab_by_url` empty query | `""`, `"  "` | `Err("empty_query")`, `TabMatchResult("[]")` |
| C8 | `find_tab_by_url` fetch failure propagates | fake cdp raises on fetch | `Err("tab_fetch_failed")`, `TabMatchResult("[]")` |
| C9 | `find_tab_by_url` no tabs | fake cdp returns [] | `Ok([])`, warning log |
| C10 | `find_tab_by_url` match found | tabs + query "virt-chat.com/chat" | `Ok(matches)`, non-empty `matches_json`, success log kind names |
| C11 | `find_tab_by_url` no match | tabs don't match | `Ok([])`, error log listing available tabs |
| C12 | `install_status_forwarding` | fake cdp with connect/disconnect/error callables | bus receives `ConnectionChanged` connected/disconnected/error |
| C13 | `install_status_forwarding` no cdp / broken signals | cdp=None / connect raises | no crash, `None` |
| C14 | `attach` replaces cdp/bus | attach(new) | new injected, old unsubscribed behavior via new bus |

### 2.4 `people_service.py` — `test_services_people.py` (P1)

Snapshot → mutate → undo entry → announce. Test paths:

| # | Path | Setup | Assert |
|---|---|---|---|
| P1 | `rows` full snapshot columns | `UserMemory` with 2 users | dict shape of `people_row` (nick…notes), all columns |
| P2 | `payload` Ok + `#` order via engine | fake engine `queue_order` returns [b, a] | `order` 1/2 matched; `stats` from memory |
| P3 | `payload` engine raises → queue fallback | engine raises | `Ok`, order from `get_queue`, no Err |
| P4 | `payload` labels joined | fake labels `labels_map` | `labels` arrays per nick; no labels → `{}` |
| P5 | `labels_for_nicks` no label store / label store raises | `None` / raising fake | `{}` (fails open, no exception) |
| P6 | `delete_one` empty nick | `""`, `"  "` | `Err("empty_nick")`, `LogMessage(warn)` |
| P7 | `delete_one` unknown nick | memory without nick | `Ok(0)`, `PeopleChanged("noop")`, no undo entry |
| P8 | `delete_one` success | seeded | `Ok(1)`, `UsersDeleted` + `PeopleChanged("deleted")`, undo entry pushed |
| P9 | `delete_many` empty selection | `[]` | `Err("empty_selection")` |
| P10 | `delete_many` partial/unknown nicks | [existing, missing] | `Ok(count)` actual deleted count; entry only when count>0 |
| P11 | `set_messaged` True/False round trip | seeded | `Ok(True)`, flag flipped, entry; `Ok(False)` no event for unknown |
| P12 | `reset_messaged` | 1 marked 1 new | `Ok(1)`, both unmarked, entry pushed |
| P13 | `clear_all` | seeded | `Ok(n)`, `UsersDeleted("[]")` + `PeopleChanged("cleared")` |
| P14 | `apply` restores snapshot (undo/redo path) | rows snapshot | `Ok(len)`, memory equals rows, `PeopleChanged("restored")` |
| P15 | `apply` memory raises | raising memory | `Err("restore_failed")` |
| P16 | mutation failure path | memory delete raises | `Err("delete_failed")`, `PeopleChanged("error")` |
| P17 | `attach` rewires dependencies | attach(new) | new injected |
| P18 | no-op mutation pushes nothing | delete unknown → undo disabled | timeline empty |

### 2.5 `history_service.py` — `test_services_history.py` (P0)

The world owner: settings, per-world state, migration, gaze, world-undo,
fail-closed switch. Real `HistoryDB` + `FakePage`.

| # | Path | Setup | Assert |
|---|---|---|---|
| H1 | defaults + config merge | config with partial `history` | merged dict; `enabled`, media, preview defaults |
| H2 | 2 MB era cap migrated up | stored `max_file_mb: 2` (or ≤2) | bumped to 25; larger kept |
| H3 | `settings()` shape | after init | includes collector, fts, db_path |
| H4 | `apply_settings` applies live | patch media/preview/collector | media flags/bytes updated; collector configured; config.json written; world `app_settings` rows written |
| H5 | `apply_settings` collector patch | `{"collector": {"heartbeat_ms": 999}}` | collector heartbeat applied |
| H6 | `set_my_nick` trims and persists | `"  A B  "` | `"A B"`, collector nick, world row |
| H7 | `seed_app_settings` fills only missing keys | world partially seeded | missing rows added, existing kept |
| H8 | `load_app_settings` world wins over template | world has my_nick/media | collector nick + media bytes from world; malformed values ignored |
| H9 | `media_base_dir`/`world_media_dir` | config cache_dir | `<root>/<stem>` and world stem naming |
| H10 | `save_gaze`/`load_gaze` round trip | collector nick + counters | rows written; fresh service restores partner/counters; **verified gate not restored** |
| H11 | `save_gaze` with no nick | no partner | no rows (no-op) |
| H12 | `load_gaze` empty table | fresh db | no crash, state untouched |
| H13 | `migrate_install` idempotent | clean install | report all False on second run; no crash |
| H14 | `migrate_install` prunes ghost `db_recent` | config with missing path | `recent_pruned: True`, list cleaned |
| H15 | `migrate_install` rehomes world undo | config `undo_history` with people entry | moved to `undo_history` table, config keeps app half, flag set, second run no-op |
| H16 | `migrate_install` legacy queue merge | separate `chatbot.db` with users | rows merged (world wins), legacy renamed `.migrated-*`, queue switched |
| H17 | `save_world_undo` rewrites + seq order | entries [seq 2, seq 1] | table holds exactly entries ordered by seq |
| H18 | `save_world_undo` db closed / bad entries | closed db | no-op, no crash |
| H19 | `load_world_undo` + corrupt row | row with bad JSON | skipped, others loaded |
| H20 | `page()` convenience | person with messages | items + stats + my_nick; unknown nick → missing |
| H21 | `switch_db` success moves world state | world A seeded → create B | B's settings empty (fresh), A's data intact, collector state reset |
| H22 | `switch_db` fail-closed (rollback) | target path that cannot open | old world re-opened + state reloaded, exception raised, archive usable, collector restarted |
| H23 | `switch_db` empty path | `""` | `ValueError` (programmer error, not Result) |
| H24 | `close()` stops collector + task + persists gaze | started | task done, db closed, gaze row written |
| H25 | `start()` idempotent / disabled | already running / `enabled=False` | no second task / no task |
| H26 | `_on_binding` non-`__cvbPush` ignored | params name other | `None`, collector untouched |
| H27 | `init()` push binding + reconnect hook | fake cdp with add_binding/on_event | binding installed; reconnect triggers rebind (binding flag reset) |

### 2.6 `db_service.py` — `test_services_db_gaps.py` (P0)

Do **not** duplicate `test_db_manager.py` (42 tests already cover lists,
create/load/delete, last-world rule, media sharing, clean backup). Cover the
untested seams:

| # | Path | Assert |
|---|---|---|
| D1 | `safe_db_name` hostile chars / length cap | no path separators; ≤80 chars; suffix once |
| D2 | `db_stem` | `work.db→work`, nested→safe stem, empty→`world` |
| D3 | `file_group_size` with WAL/SHM | sum of existing siblings |
| D4 | `folder_size` missing dir | `(0,0)` |
| D5 | `active_path` service vs config fallback | service wins; config value; `"history.db"` default |
| D6 | `resolve` absolute / relative / empty | abs kept; relative → `<dir/safe_db_name>`; empty → `""` |
| D7 | `trash_dir`, `media_base_dir`, `media_dir` fallbacks | service path preferred, config fallback, `<root>/<stem>` |
| D8 | `known_paths` + `_remember` cap 12 | 15 paths → 12 newest, deduped |
| D9 | `list_dbs` sorts active-first + `can_delete` for 1 vs 2 worlds | active first; hint text |
| D10 | `info` offline (no service) | counts zero, `connected False`, sizes from disk |
| D11 | `info` online stats fields | db_bytes/text/persons/messages/media/fts |
| D12 | `load` offline (`service=None`) persists + remembers | `Ok` with `offline: True` |
| D13 | `restore_backup` restores file + reconnects (undo of clean) | file content back, active path, message count restored |
| D14 | `restore_backup` backup missing | `Err`-style `{ok: False, error: "the backup is gone"}` |
| D15 | `restore_backup` to a non-active target | file copied, config db_path NOT changed when different |
| D16 | `clean` failure path keeps backup | fake service whose db raises → `{ok: False, error, backup}` |
| D17 | `_media_references` unreadable world → keeps file (never deletes unknown) | corrupt db file among worlds | delete still worked; references conservative |

### 2.7 `run_service.py` — `test_services_run.py` (P0)

Extends `test_engine_standalone_run.py` (standalone/empty-queue regressions)
into the loop/state/error-recovery contract. Same approach: real
`ActionEngine` (QObject works headless), recording fake blocks, fake memory.

| # | Path | Assert |
|---|---|---|
| R1 | pause stops between users, resume continues | block runs user1; paused → user2 waits until resume; then runs |
| R2 | stop mid-run ends cleanly | `is_running` False after, `stack_complete` emitted, remaining users skipped |
| R3 | stop while paused exits the pause wait | `_wait_if_paused` returns, run ends |
| R4 | block raises → user fails → NEXT user still runs (error recovery) | per-user `user_complete(nick, False)`, then True for next, run completes |
| R5 | `repeat` cycles run N times + Stop breaks | N=3 → 3 cycles; stop during cycle 2 → 2 (or as allowed) and tracer reason "stopped" |
| R6 | repeat with empty queue stops after one cycle | 1 cycle, log "No users found" |
| R7 | `mark_person_messaged` 4 statuses | ok/already/missing/error |
| R8 | `queue_order` no scroll block = get_queue order (newest first, tie A–Z) | deterministic order; messaged excluded |
| R9 | `queue_order` with enabled SCROLL_PARSE = `sort_people` path | block presence flips order |
| R10 | `filter_by_labels` announce + reasons | skipped list logged once; kept order stable |
| R11 | `label_allows` fail-open: missing/raising guard | True |
| R12 | `person_collected` upserts + emits + tracer note | person_found JSON, memory row |
| R13 | `unmessaged_nicks` fails open on memory error | set() |
| R14 | `person_rejected` deletes + emits; failure → False | person_removed JSON, memory row gone |
| R15 | `_expand_nick_on_block` substitution + restore | string attrs replaced for one step, restored after; `_`-prefixed untouched |
| R16 | `_run_take_phase` no match keeps previous selection | warning logged + `selected_nick` preserved |
| R17 | `note_selected` empty ignored | unchanged |
| R18 | `load_stack` normalizes, drops unknown block ids, disabled kept but skipped | stack size; disabled block never executes |
| R19 | already-running guard | second `execute()` returns immediately, no double-run |
| R20 | `user_complete(Nick, False)` on SKIP/fail | signals per user |
| R21 | `person_collected`/`person_rejected` with failing memory never raise | graceful |

### 2.8 `collector_service.py` — `test_services_collector_gaps.py` (P0)

`test_collector_state.py` already pins detection, statuses, push, throttling,
self-heal, probe-failure (31 tests). Cover the untested paths:

| # | Path | Assert |
|---|---|---|
| K1 | `tick` probe `TimeoutError` becomes ERROR then recovers | status ERROR with timeout text, next tick COLLECTED |
| K2 | `reset_state` clears volatile state | nick/verified/totals/last_probe... all reset; `_probe_penalty` is CDP-reliability state and is deliberately KEPT (7.0) — a DB swap must not forget how flaky the connection is |
| K3 | `person_cleared` matching nick zeroes totals + status | Radar counters reset, `history_cleared` reason |
| K4 | `person_cleared` wrong/empty nick no-op | totals untouched |
| K5 | `backfill_older` without partner | warn log, state unchanged |
| K6 | `backfill_older` with partner resets cursor + force backfill | cursor reset, `_force_backfill`, re-tick collected |
| K7 | `_remember_partner` archive-only (no memory) | person exists in archive, `"archive_only"` |
| K8 | `_remember_partner` known vs new vs memory error | result strings; PeopleChanged only for new |
| K9 | `configure` unknown keys ignored, `settings()` round trip | no crash, only known keys |
| K10 | `state` property + `state_payload` keys | payload key set |

---

## 3. Bug hypotheses to verify during implementation

These were spotted from the *contracts* (docstrings / design docs), before
reading the implementations in detail. Each is written as a failing test
first; a green test after a minimal fix documents the bug.

| # | Hypothesis | Evidence path | Verdict (to fill) |
|---|---|---|---|
| B1 | `UndoService.push` cannot dedupe an identical tip entry (fresh entry has no `seq`, stored one does) — duplicate timeline entries when the grid/stack pushes the same payload twice. | `push("grid", X)` × 2 → 2 entries | **CONFIRMED** (probe: 2 entries) |
| B2 | `push` of the same value **after undo** does not truncate the redo tail (and adds a duplicate instead of staying put). | push A,B → undo → push A → [A,B,A] | **CONFIRMED** |
| B3 | `CdpService.fetch_tabs` builds the `TabsReceived` payload *outside* the try — a malformed tab lets an `AttributeError` cross the Result seam (violates "no bare exception crosses a layer boundary"). | tab without `ws_url` | **CONFIRMED by code inspection** |
| B4 | Undo pointer is not restored across restart with a live archive: `sync_world_state()` always sets the pointer to the tip, so an undo performed before quitting is silently lost (UI shows the last entry as applied). | split persistence + startup sync | **CONFIRMED by code inspection — architecture limitation, documented; fix deferred** |
| B5 | `run_service._execute_for_user` returns `True` when every block is disabled, so the cycle marks each queued person "messaged" — the New queue is consumed without anything running (the UI even says "nothing to run"). | all-disabled stack + 1 user → `memory.marked == []` expected | **CONFIRMED — fixed** |
| B6 | `undo_service.migrate_global_history` rebuilds every entry via `_history_entry` and **drops `seq`** — after a restart the app-half entries have no seq, so `sync_world_state` sorts them all BEFORE the world entries and `_commit_timeline` re-numbers them, colliding with the world table's seqs: the app/world interleaving is corrupted and seq identities are no longer unique. | stack,people,grid in config + world row → merged [stack,people,grid] by seq | **CONFIRMED — fixed** (`_migrated_entry` preserves the original `seq`) |

Fix policy: B1/B2 (one small change in `UndoService.push`), B3 (wrap the
conversion in the try), B5 (`_execute_for_user` returns `False` on
all-disabled) and B6 (`migrate_global_history` preserves `seq` via
`_migrated_entry`) are fixed **with the failing test kept**. B4 is left
as an explicit limitation (fixing pointer persistence across the split
config/world stores would need a world-id marker — out of scope for a
test-coverage pass, and behavior is data-safe: the restored state is correct,
only the redo pointer is lost).

---

## 4. Execution log

| Step | Command | Result |
|---|---|---|
| Baseline (existing service tests) | `pytest tests/test_engine_standalone_run.py tests/test_collector_state.py tests/test_db_manager.py tests/test_history_query.py` | ✅ green (process hangs on aiosqlite worker thread — pre-existing, unrelated) |
| New suites | `pytest tests/integration/services/<file>` — one file per invocation (a combined run with real SQLite loops times out at 600s) | layout 33 ✅ · cdp 15 ✅ · undo 35 ✅ · people 23 ✅ · run 33 ✅ · history 32 ✅ · db_gaps 17 ✅ · collector_gaps 15 ✅ (203 total) |
| Fixes kept as regressions | B1/B2, B3, B5, B6 | `_same_entry` + truncate-before-dedupe in `push`; `fetch_tabs` conversion inside try; all-disabled → `False`; `_migrated_entry` preserves `seq` |
| Existing suites re-checked after service edits | `tests/test_people_undo.py`, `tests/test_merge_undo_enabled.py`, `tests/test_cdp_events.py` | (logged at run time) |

*Document completed: 2026-09-09 — design first; implementation follows in the
same change set.*
