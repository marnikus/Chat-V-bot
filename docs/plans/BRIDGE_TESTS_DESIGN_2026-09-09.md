# 🧪 Bridge Layer Test Design — Section D (Wire / Boundary)

> **Version:** 2026-09-09 · **Base:** `2f019ba` (branch `arena/01a08695-chat-v-bot`)
> **Scope:** all 10 modules of `bridge/` (Section D of `TEST_COVERAGE_REF_DESIGN_2026-09-09.md`)
> **Rule:** tests are designed from the *contract* (architecture doc §5, slot/signal
> signatures, JS callers in `ui/js/`, existing pinned expectations) — **before**
> reading implementation bodies. Every test asserts observable wire behaviour
> (return JSON, emitted signals, store state). No execution-only "cofy" tests.

---

## 0. Contract-invariants (hold for every module)

| # | Invariant | Catches |
|---|---|---|
| C-1 | A `@Slot` never raises across the wire: invalid / corrupt / empty JSON arguments produce a **safe response** (error JSON, `False`, `[]`) + a log, never an exception | crash-on-bad-input |
| C-2 | Request/response slots answer on a signal carrying the **same `req_id`**; concurrent requests never cross | crossed responses |
| C-3 | Every mutation emits the domain `*_changed/updated` signal **with the full fresh state** (JS re-renders from payload, never deltas) | stale UI |
| C-4 | Every user-visible mutation pushes an **undo entry** (kind `"people"`/`"grid"`/… ) and Ctrl+Z via `undo()` reverses it | lost undo |
| C-5 | Router re-exports every domain slot and signal under the **historical name** with the same signature | dead JS feature |
| C-6 | A store write must be **persisted** (constructor reload sees it) | lost-on-restart |

## 1. Fixture strategy (one harness, shared)

`tests/bridge_harness.py` — no Qt app required (existing suite convention):

* `FullBridge` — real `Router` built via the real constructor: real `ConfigManager`
  (temp dir), real `UserMemory` (temp sqlite), fake engine (`SimpleNamespace`).
* `make_bare(**attrs)` — `Bridge.__new__(Bridge)` + `QObject.__init__` +
  attribute injection (the `test_people_undo.py` convention) for module-scoped tests.
* `Recorder` — records signal emissions `(args…)` for ordered assertions.
* `run(coro)` — `asyncio.run`.
* `event_loop_pair()` — `qasync`-free loop stub: bridges schedule coroutines with
  `asyncio.ensure_future`; tests drive the loop with `loop.run_until_complete`
  on a private loop (no Qt event loop needed headless).

---

## 2. Behavior matrix per module

### D1. `bridge/router.py` — P0 (rules, fallback, forwarding cycle)

| ID | Behaviour | Arrange → Act → Assert | Bug it catches |
|----|-----------|------------------------|----------------|
| R-1 | Every domain signal is published on Router **as a signal** | build `Bridge.__new__` → scan metaobject → name present, `Signal` type | slot/signal became a plain method → JS connect() dead |
| R-2 | Every domain slot published **as a slot** with correct arity | metaobject scan → parameter count ≥ declared | signature drift breaks QWebChannel |
| R-3 | Slot forwards args verbatim and returns value | fake domain bridge records `(args)` → `br.get_stack_json()` returns its value; multi-arg slot `label_create("a","#111111")` receives both in order | arg swap / dropped arg in forwarder |
| R-4 | Signal re-emission: domain signal → Router signal, payload intact | connect Router signal → poke domain bridge signal → same payload received once | fan-out wiring |
| R-5 | Fallback: unknown domain bridge class in `BRIDGE_SPECS` build fails **loudly** (no silent skip) | build with a broken spec → raises / asserts, never builds a half router | silent missing features |
| R-6 | Lazy bridge instantiation: domain bridge built **once**, on first use; second access returns same object | count instantiations via instrumented subclass → 1 after two calls | re-built bridges drop subscriptions |
| R-7 | Write-through: `br._config = cfg2` **after** construction is seen by lazily-built bridges (legacy compat §5.3-2) | construct bare, set `_config`, call slot touching config → cfg2 used | stale service construction |
| R-8 | Class-attr re-export: `GRID_VERSION`, `WINDOW_IDS`, `V1_WINDOW_IDS`, `COMMAND_KINDS`, `_default_grid_tree`, `_parse_grid_payload`, `COMMAND_KINDS` exist on Router and match domain classes | `getattr(Bridge, name)` == `getattr(LayoutBridge/UndoBridge, name)` | legacy test/JS constant lookup breaks |
| R-9 | Subclassing works (`class FakeBridge(Bridge)`) and instantiates | §5.3-4 | Shiboken ObjectType surprises |
| R-10 | Cycle: each router slot routes to exactly one domain bridge; domain bridge never routes back into a router slot for the same call (no recursion) | instrumented forwarder → call each slot once → forward count == 1 | routing cycle / double execution |
| R-11 | `log_message` re-exported + emitted by `_log` helper | call `br._log("x","warn")` → `log_message("x","warn")` | log window blind |
| R-12 | Wire parity: the set of published names ⊇ every `bridge.*` name called from `ui/js/*.js` | grep JS calls → assert each exists as callable attr | typo'd slot name ships |

### D2. `bridge/stack_bridge.py` — P1 (push/pop/undo/state sync)

| ID | Behaviour | Assert | Bug it catches |
|----|-----------|--------|----------------|
| S-1 | `run_stack(valid json)` → `engine.load_stack(blocks)` + engine run scheduled | fake engine got the exact block list | broken run button |
| S-2 | `run_stack(corrupt json)` → no engine call, no raise (C-1) | engine untouched, no exception | crash on bad payload |
| S-3 | `stop/pause/resume` → engine.stop/pause/resume called | recorded calls | dead controls |
| S-4 | `save_message`→`get_message` roundtrip persisted in config (C-6) | reload ConfigManager from disk → same text | composer text lost |
| S-5 | `save_criteria`→`get_criteria` roundtrip | same | criteria lost |
| S-6 | `save_stack_preset(name, json)` → stored, cleaned; `preset_list_updated` emitted with JSON containing the name; re-save same name **overwrites** (1 entry, not 2) | store + signal payload | duplicate presets |
| S-7 | `load_stack_preset(missing)` → `{"ok": false, "error": …}` JSON (C-1) | parse and check | crash |
| S-8 | `load_stack_preset(existing)` → `{"ok": true, blocks…}` + `stack_loaded(name, json)` emitted | ok + signal | load flow dead |
| S-9 | `delete_stack_preset(missing)` → error JSON; `delete_stack_preset(existing)` → gone from list + signal | list state | phantom entries |
| S-10 | `snapshot_stack` returns canonical JSON of current engine stack | parse == blocks | snapshot drift |
| S-11 | Template preset CRUD mirrors stack preset CRUD (S-6..S-9 for templates, incl. `template_loaded`) | | |
| S-12 | Custom block CRUD: `save_custom_block(name, json)` → stored + `custom_blocks_updated`; `delete_custom_block(missing)` → error JSON | | |
| S-13 | Engine signals forwarded: `step_started(i, id, nick)`, `step_complete`, `stack_complete` reach StackBridge signals | | progress bar dead |
| S-14 | Stack history: `push_stack_history(blocks)` grows global timeline entry `kind:"stack"`; `get_stack_history` returns projection; `save_stack_history(json, idx)` sets it (C-4) | undo service history | stack undo blind |
| S-15 | Preset save emits AFTER store write (signal payload includes the new entry) | ordering | UI one-behind |

### D3. `bridge/undo_bridge.py` — P1 (Unit: command, redo, empty)

| ID | Behaviour | Assert | Bug it catches |
|----|-----------|--------|----------------|
| U-1 | `get_undo_history` → JSON `{undo_history|history, index}` usable by `app.js` (`Array.isArray(state.undo_history)`) | parse, keys, array | undo panel dead |
| U-2 | `push_global_history(kind, value_json)` → True + timeline grew by 1 entry `{kind, value}`; **invalid JSON → False**, timeline unchanged (C-1) | bool + length | corrupt undo entry |
| U-3 | `undo()` on **empty** timeline → safe JSON `{ok:false}` (C-1) | no raise | crash on Ctrl+Z at start |
| U-4 | `redo()` on nothing-to-redo → safe JSON (C-1) | | crash |
| U-5 | push → undo → entry applied **backwards**: value.before restored to store, index moved back; `history_changed` emitted | store state + signal | wrong-direction apply |
| U-6 | push → undo → redo → forward half re-applied | store state | redo broken |
| U-7 | interleave kinds: people push, stack push, people push → undo twice pops **last two** regardless of kind (shared timeline) | timeline index | per-kind index bug |
| U-8 | `undo_stack/redo_stack` operate on `kind:"stack"` projection only; global index untouched by stack-only undo when the tip entry is another kind → safe no-op | | projection cross-talk |
| U-9 | `undo_grid_layout/redo_grid_layout` projection likewise | | |
| U-10 | `push_stack_history` via UndoBridge and `push_global_history("stack"…)` land in the same timeline (one source of truth) | | forked histories |
| U-11 | `save_stack_history(json, idx)` restores BOTH list and index (JS sends full projection back) | | index lost |
| U-12 | undo disabled (config `ui.undo_enabled=false` or equivalent flag) → `undo()` is a no-op returning safe JSON, pushes are ignored/allowed per contract — pin actual | | toggle dead |
| U-13 | `history_changed` emitted on push, undo, redo — not on empty undo/redo | signal log | UI refresh storm / missing refresh |

### D4. `bridge/history_bridge.py` — P1 (sync, lazy, refresh)

| ID | Behaviour | Assert | Bug it catches |
|----|-----------|--------|----------------|
| H-1 | `history_page(req_id, nick, opts)` answers `history_page_ready(req_id, page-json)` with **same id**; page contains that nick's rows (real sqlite archive) | req_id echo + rows | crossed/empty pages |
| H-2 | Two interleaved requests (A then B) answer B-first — ids never swap (C-2) | order of emissions | id swap |
| H-3 | `history_page` for unknown nick → `history_page_ready` with empty items (not error, C-1) | | missing-nick crash |
| H-4 | Lazy anchor: `anchor_json` with `{before_id/after_id…}` returns older/newer page only (lazy paging contract) | row ids relative to anchor | eager full load |
| H-5 | `history_search(req_id, q)` answers `history_search_ready` with matches only | filter correctness | search dead |
| H-6 | `history_stats` / `userdb_stats` answer with same req_id | | |
| H-7 | `userdb_page(req_id, query)` returns persons + stats payload | | userdb panel dead |
| H-8 | `history_delete_person(nick, hard)` → True; subsequent `userdb_page` lacks the nick; `userdb_changed` emitted `{action, nick}` (C-3) | | delete ghost |
| H-9 | `history_clear_person(nick)` → messages cleared, person kept | | nuke instead of clear |
| H-10 | history ops without an archive attached → `history_error(scope, msg)` signal, all return `False`, no raise (C-1) | | crash in fresh profile |
| H-11 | `history_delete_message(nick, ts…)` removes one message only | sibling rows intact | over-delete |
| H-12 | `history_merge_person(from, into)` → rows moved; source gone | | merge loses rows |
| H-13 | `media_path/media_restore/open_media_folder` respond without archive per contract (error-signal, False) | | |
| H-14 | corrupt `options_json` → error signal + safe, no raise | | |

### D5. `bridge/label_bridge.py` — P2 (assign/edit/delete contract)

| ID | Behaviour | Assert | Bug it catches |
|----|-----------|--------|----------------|
| L-1 | `get_labels()` → JSON with labels list + per-nick assignments | parse shape | |
| L-2 | `label_create(name, color)` → new id JSON; duplicate name rejected; **empty name rejected** (C-1) | ok flag | dup/empty labels |
| L-3 | `label_update(id, name, color)` → True; store updated; unknown id → False | | silent rename miss |
| L-4 | `label_delete(id)` → True; assignments to that label removed from all nicks (no orphans); unknown id → False | assignments map | orphan assignments |
| L-5 | `label_assign(nick, id)` → True; unknown label id → False; second assign idempotent (one entry) | | dup badges |
| L-6 | `label_unassign(nick, id)` → True; when absent → False (or idempotent — pin actual) | | |
| L-7 | `label_set_for(nick, ids_json)` **replaces** the whole set; corrupt JSON → False (C-1) | | merge instead of replace |
| L-8 | `label_set_filter(rule_json)` / `label_clear_filter()` roundtrip; corrupt → False | | filter stuck |
| L-9 | EVERY mutation (C-3): `labels_changed(full-json)` emitted exactly once per mutation, payload reflects post-state | signal log | stale badges |
| L-10 | Mutation persistence (C-6): reload store from disk → assignment still there | | lost on restart |
| L-11 | create → assign → delete-label chain: nick ends with **empty** assignment list, not dangling id | | dangling id in JS |

### D6. `bridge/layout_bridge.py` — P2 (layout sync, resize)

| ID | Behaviour | Assert | Bug it catches |
|----|-----------|--------|----------------|
| Y-1 | `get_grid_layout()` on fresh config → default payload (parses, version == GRID_VERSION, contains all WINDOW_IDS) | | fresh-profile crash |
| Y-2 | `save_grid_layout(valid)` → True; `get_grid_layout` returns it; persisted (C-6) | | lost layout |
| Y-3 | `save_grid_layout` with **wrong version** → REJECTED (False), stored layout unchanged (RULE 13) | | silent destruction |
| Y-4 | `save_grid_layout` with unknown window id → rejected | | unmigrated set |
| Y-5 | legacy v1 payload (7 windows) → `get_grid_layout` upgrades to current set (migration kept) | | user arrangement destroyed |
| Y-6 | `reset_grid_layout()` → default payload + `grid_layout_changed` emitted | | |
| Y-7 | `save_window_states(states)` → `get_window_states` roundtrip; unknown keys dropped/rejected per contract | | |
| Y-8 | resize-consistency: leaf sizes in saved payload sum to parent's size (validation) — invalid sizes rejected | | broken sash |
| Y-9 | `set_block_config_pinned(True/False)` → persisted; `get_app_state` reflects it | | pin lost |
| Y-10 | `grid_layout_persisted(ok)` emitted on close-time save | | |

### D7. `bridge/people_bridge.py` — P2 (people sync, undo)

| ID | Behaviour | Assert | Bug it catches |
|----|-----------|--------|----------------|
| P-1 | `refresh_users()` → `users_updated(rows-json)` + `stats_updated(stats-json)`; rows match sqlite content | | |
| P-2 | `delete_user(nick)` → user gone, `users_deleted(json, count)` with correct count, **undo entry `{before, after}` pushed** (C-4), undo restores row | store + signals + undo | delete w/o undo |
| P-3 | `delete_users(corrupt json)` → safe, no raise, nothing deleted (C-1) | | |
| P-4 | `delete_users(json)` multi → single undo entry with both rows in before/after (one Ctrl+Z) | | N undos for one action |
| P-5 | `set_user_messaged(nick, True)` → flag set in store + undo entry; undo reverts flag | | |
| P-6 | `reset_messaged()` → all flags cleared, undo entry reverses (C-4) | | |
| P-7 | `clear_memory()` → table empty + undo entry restores all | | destructive w/o undo |
| P-8 | engine `person_found`/`person_removed`/`person_marked` forwarded to signals (C-3) + list refresh | | live row missing |
| P-9 | `users_updated` payload rows carry label ids (labels cross-wire) | | badges lost |

### D8. `bridge/cdp_bridge.py` — P2 (Unit: event, disconnect)

| ID | Behaviour | Assert | Bug it catches |
|----|-----------|--------|----------------|
| C-1b | `get_tabs()` → JSON array string (empty when no tabs) | | |
| C-2b | `connect_tab(ws)` → schedules service connect; status signal on success/fail path via service events | | connect button dead |
| C-3b | `find_tab_by_url(query)` emits `tab_match_result(found-json, query)` on hit; safe no-match payload on miss | | |
| C-4b | `add_url_preset(url)` → stored + `url_presets_updated`; duplicate add does not duplicate; `remove_url_preset(missing)` safe | | |
| C-5b | `set_last_url_preset(url)` persisted (C-6) | | |
| C-6b | disconnect path: service disconnect event → `connection_status` forwarded | | status stuck green |

### D9. `bridge/db_bridge.py` — P2 (DB sync, transaction)

| ID | Behaviour | Assert | Bug it catches |
|----|-----------|--------|----------------|
| B-1 | `db_list()` → JSON list of worlds (real temp dir with *.db files) | | |
| B-2 | `db_info(req_id)` → `db_info_ready(req_id, json)` same id (C-2) | | |
| B-3 | `db_create(name)` → True; file exists; `db_changed({action:"create", ok:true…})` emitted (C-3) | | |
| B-4 | `db_create(dup)` → False + db_changed ok:false (or per contract) — no overwrite | | silent overwrite |
| B-5 | `db_load(path)` → True + db_changed action:"load"; `db_load(missing)` → False, **state unchanged** (transaction: no half-switch) | | half-switched world |
| B-6 | `db_delete(path)` → trash/removed + db_changed; deleting **active** db handled per contract (pin) | | active-deleted corruption |
| B-7 | `db_clean()` → closes/creates clean world + db_changed | | |
| B-8 | `db_changed` payload always `{action, path, ok…}` JSON-parseable | | |

### D10. `bridge/collector_bridge.py` — P2 (collector state)

| ID | Behaviour | Assert | Bug it catches |
|----|-----------|--------|----------------|
| K-1 | `collector_state()` → JSON snapshot parseable with state fields (status/running/enabled) | | |
| K-2 | `collector_set(settings-json)` merges (not replaces) — unspecified keys keep values; emits `collector_status` (C-3) | | settings wipe |
| K-3 | `collector_set(corrupt)` → safe no-op (C-1) | | |
| K-4 | `collector_command("start"/"stop")` → collector.running flips + `collector_status` emitted; unknown command safe | | |
| K-5 | `get_my_nick`/`set_my_nick` roundtrip + `my_nick_changed` emitted | | |
| K-6 | archive `history_appended` payload `{nick, items, added}` forwarded when archive attached | | |
| K-7 | `collector_log` forwarding from collector service log lines | | log window blind |

---

## 3. Execution protocol (Red → triage → Green)

1. Implement tests from this matrix (each cites its ID in the docstring).
2. Run the whole suite. For each red test triage:
   * **mis-designed test** (contract misread) → fix test, note it in §4;
   * **real bug** → minimal fix in the bridge, keep the test as regression.
3. Final: full bridge suite + all previously-existing tests green (no regressions).

## 4. Triage log (filled during implementation)

### 4.1 Real bugs found (red test → minimal bridge fix → green)

| # | Module | Bug (found by) | Fix |
|---|--------|----------------|-----|
| 1 | `stack_bridge.py` | **`run_stack` accepted valid-JSON-but-not-a-list payloads** (e.g. `{...}`): `normalize_blocks` silently coerced them to `[]` and **wiped the engine's stack**, then started an empty run. `save_stack_preset` had the `isinstance` guard, `run_stack` did not. (S-2) | same non-list guard + error log as the preset path |
| 2 | `stack_bridge.py` | **Every preset/template/custom-block action announced its list TWICE** on the wire: `_emit_*` emitted the domain signal AND published `PresetsChanged`, which the bridge's own bus subscription re-emitted (self-echo). JS re-rendered twice per action. (S-6/S-9) | `_publish_presets` re-entrancy guard; external events (undo restores, imports) still re-emitted |
| 3 | `cdp_bridge.py` | **Same self-echo for URL bookmarks** — `url_presets_updated` fired twice per add/remove. (C-4b) | same guard in `_emit_bookmarks`/`_on_presets` |
| 4 | `collector_bridge.py` | **`set_my_nick` announced `my_nick_changed` TWICE** — a direct emit plus the bus `MyNickChanged` event its own subscription re-emits. (K-4) | bus event is the one wire path; direct emit removed |
| 5 | `collector_bridge.py` | **Every `collector_set`/`collector_command` announced the collector state twice** — the collector's synchronous `status_changed` (forwarded via `attach_archive`) plus the bridge's own manual emit. (K-2/K-3) | announce window: `status_changed` forwarder suppresses echoes inside a command's synchronous window; async ticks pass through |

### 4.2 Test-design corrections (mis-designed tests, contract re-pinned)

* S-7: `load_stack_preset(missing)` returns the JSON sentinel `"null"` (what
  `presets-ui.js` checks), not an `{ok:false}` object.
* S-4: composer text is an in-memory slot + engine handoff — NOT
  config-persisted (the snapshot for restart is `last_stack`, covered by S-1).
* U-2: `push_global_history` accepts ONLY frontend-owned kinds (`stack`,
  `grid`); server-owned kinds (`people`, `labels`, `archive`, `dbconn`) must
  return `False` so edits are never double-recorded (the server pushes them).
  `""` coerces to `"[]"` — pushing an emptied stack is a legal edit.
* U-7/U-8: undo/redo return the entry at the NEW pointer (the state being
  restored) — JS applies `raw.value`; the per-surface slots are projections
  that run the one global op and return `null` on a kind mismatch.
* U-12: dropped — there is no global undo-disable flag (the FEATURE doc's
  `enabled` toggle is the per-block run flag); the empty-timeline paths
  (U-3/U-4) pin the toggle-adjacent behaviour.
* H-10: the `history_error` signal IS the no-archive answer (report, don't
  raise); `get_history_settings` merges the patch over full defaults.
* Y-1/Y-6/Y-7: fresh profile `get_grid_layout` → `""` (JS builds its own
  default); `reset_grid_layout` returns its payload via the slot return
  (`sash-grid.js` applies it — no changed-signal); fresh config ships sane
  default `window_states`.
* P-1/P-5: every people mutation produces the awaited refresh PLUS the
  bus-driven `PeopleChanged` refresh (the cross-domain seam) — pinned as
  "≥ 1, last payload is the post-state" instead of exactly one.
* P-9/H-15: rows carry full label objects (`labels_map`), not bare ids.
* B-3/B-6: DB lifecycle slots run against an attached archive service
  (production order, per `main.py`); offline (service-less) creates only
  switch the stored path and skip the undo entry by design.
* K-3: a command may add ONE genuine async state broadcast from the
  collector loop on top of its own announcement.
* C-3b: `tab_match_result` echoes the CLEANED query; bookmarks are
  deduped by exact string with factory defaults pre-seeded.

### 4.3 Result

* New files: `tests/bridge_harness.py` + 9 test files, **116 tests**,
  every design ID from §2 covered (except U-12, dropped above).
* Full repo per-file runs (the repo's convention; multi-file pytest
  collection trips over import-time Qt probe construction — pre-existing):
  **57/57 Python files green, 18/18 JS files green.**
  Known pre-existing quirk (verified at base): `test_db_manager.py` passes
  in ~15 s but its process lingers at exit (non-daemon resource), so a
  shell timeout kills an already-finished run.
* Mutation spot-checks: re-injecting bugs #1, #3 and #4 turns the
  corresponding tests red — the suite fails on semantic change, not just
  on crashes.
