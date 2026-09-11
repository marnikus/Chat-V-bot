# Chat-V-bot — System of Record

**This is the one current doc.** Everything on this page describes the code as
it is *today*. It points outward — deep-dives, tests and history live elsewhere
and are linked from here.

| | |
|---|---|
| Last verified against code | 2026-09-10 (this checkout) |
| Test suite | `2545 passed, 3 skipped, 1 deselected, 1 xfailed, 771 subtests passed` + 22 green Node harness files |
| Coverage (measured, `--branch`, 8 production packages) | line **90.44%** · branch **84.38%** (floors: 80% / 75%) |
| Rules every code change must obey | [`docs/current/AGENT_RULES.md`](AGENT_RULES.md) |
| Map of current vs. historical docs | [`docs/README.md`](../README.md) |
| User-facing manual (install, Chrome, UI tour) | [`README.md`](../../README.md) |

> **Conflict rule.** If a statement here disagrees with an archived design doc,
> **this file wins.** Archived docs are true *as of the date in their name* —
> they are the reasoning, not the spec.
>
> **Living-doc rule.** A change that alters behaviour, an invariant or a flow
> updates this file in the *same* change. Do not add a new top-level doc for a
> feature: write the design into `docs/archive/<date>-<topic>/` and update the
> affected rows here.

---

## 1. What this is

A **PySide6 (Qt6) desktop app** that automates the Virt-Chat web platform
(`ru.virt-chat.com/chat`) inside an already-running Google Chrome, over the
Chrome DevTools Protocol. The UI is HTML/JS (`ui/`) rendered in a
`QWebEngineView`, talking to Python over a `QWebChannel`.

Start it with Chrome on `--remote-debugging-port=9222`, then `python main.py`.
The step-by-step is in the [root README](../../README.md); nothing below
repeats it.

**One run does:** connect to the Chrome tab → harvest the user list by
scrolling → filter it → for each person: open the private chat, act (type /
attach / send), mark them messaged, go back → repeat. In parallel, a **passive
collector** archives whatever private conversation is on screen.

---

## 2. Current behaviour (spec, by surface)

| Surface | What it does today | Implementation | Pinned by |
|---|---|---|---|
| **Action stack** | 16 ordered blocks, drag-and-drop, presets, per-block config panel. Blocks: `SCROLL_PARSE` `SEARCH_USERS` `CLICK_USER` `CLICK_MAIN_TAB` `CLICK_BACK` `CUSTOM_FIND` `WAIT_PAGE_LOAD` `TYPE_MESSAGE` `CLICK_SEND` `ATTACH_IMAGE` `COLLECT_HISTORY` `TAKE_PERSON` `MARK_MESSAGED` `CONDITIONAL_SKIP` `REPEAT_LOOP` `PAUSE` | `actions/*` (registry auto-scans the package), `services/run/` | `tests/test_action_registry.py`, `tests/unit/actions/`, `tests/integration/run_safety/` |
| **Find & click** | Every locating click goes through one two-phase, visually confirmed runner (RED outline on FIND, ORANGE on CLICK) | `backend/visual_click.py`, `backend/dom_highlight.py`, `actions/find_click_runner.py` | `tests/test_visual_click_contract.py`, `tests/test_find_click_visual.py` |
| **Scroll & Parse** | Harvests the CDK virtual-scroll list, reports each person as found, applies the block's own filter selects, purges rejects from the queue | `backend/scroll_parser.py`, `actions/scroll_parse.py` | `tests/test_scroll_parse_pipeline.py`, `tests/test_scroll_only_seek.py`, `tests/test_filter_purge.py` |
| **Run engine** | Plan-then-execute cycle loop, stop/pause gates, repeat cycles, empty-vs-broken reporting, JSONL trace | `services/run/` (see §3) | `tests/integration/run_safety/`, `tests/unit/services/test_cycle_plan.py` |
| **Passive collector** | Heartbeat probe per tick; archives only when the conversation changed; never blocks the UI; throttled (not paused) during a run | `services/collector_service.py`, `services/collector_tick.py` | `tests/test_collector_state.py`, `tests/integration/services/test_collector_tick_phases.py` |
| **Message archive** | Append-only per-person history, FTS5 search (LIKE fallback), paging that stays stable while collection appends, media downloaded and filed per person | `stores/history_*`, `services/history/`, `backend/history_query.py` | `tests/test_history_*`, `tests/unit/stores/`, `tests/integration/services/test_history_service_contract.py` |
| **People queue** | "Who should I message under the current filter" — `users` table of the active world; shrinks when filters tighten | `stores/user_memory.py`, `stores/user_query.py`, `services/people_service.py` | `tests/test_user_memory_*.py`, `tests/integration/services/test_services_people.py` |
| **Labels** | Coloured person tags + include/exclude filter rule, per world | `stores/label_*`, `ui/js/labels.js` | `tests/test_person_labels.py`, `tests/test_label_store_orphans.py`, `tests/unit/backend/test_label_store_dbmode.py` |
| **Undo / redo** | ONE global timeline across every editable surface, one `Ctrl+Z` | `services/undo_service.py`, `services/undo_support.py`, `stores/undo_store.py` | `tests/test_people_undo.py`, `tests/test_archive_delete_undo.py`, `tests/integration/services/test_undo_support_contract.py` |
| **Grid layout** | Any window in any cell; sashes draggable; layout validated before it is stored | `services/layout_service.py`, `bridge/layout_bridge.py`, `ui/js/sash-*.js` | `tests/test_grid_persistence.py`, `tests/integration/services/test_services_layout.py`, `tests/test_sash_webengine.py` |
| **Database worlds** | One `.db` file = one complete world; create / load / switch / clean / **permanent delete** | `services/db_service.py`, `services/db_lifecycle.py`, `services/db_deletion*.py` | `tests/test_db_manager*.py`, `tests/test_db_unified_world.py`, `tests/integration/safety_deletion/` |
| **Logging** | UI log console + file log + JSONL run trace | `backend/logger.py`, `ui/js/log-console.js`, `services/service_log.py` | `tests/unit/backend/test_logger_setup.py` |

---

## 3. Current flow

### 3.1 A run: plan → execute

`RunCoordinator.execute()` (`services/run/coordinator.py`, aliased
`ActionEngine`) — the outer loop owns only begin/teardown and the cycle count:

```
execute()
 ├─ _begin_run()                     cycles, state machine → RUNNING, tracer
 ├─ hooks.pre_run(engine)            (awaitable hook; may be sync or async)
 └─ for cycle in 1..cycles:
      ├─ _gate_before_cycle()        stop? → "stopped"  ·  pause → wait · stop?
      ├─ _execute_cycle()
      │    ├─ _try_prepare_cycle_queue()      ← PLAN
      │    │     collect (Scroll & Parse, if enabled) → check_stopped
      │    │     → label filter → check_stopped → order by column
      │    │     → TAKE_PERSON → check_stopped
      │    ├─ inspect_stack(stack)  → StackFacts  (one scan, pure data)
      │    ├─ choose_cycle_mode(facts, has_queue, take_matched, stopped)
      │    │        stopped → single_target → take-miss empty → queued
      │    │        → empty_stack → user-empty → standalone
      │    └─ dispatch                                          ← EXECUTE
      │          single_target → _run_single_target_cycle()
      │          queued/standalone → _run_user_queue()
      │          empty/empty_stack → _announce_empty_mode()
      └─ _cycle_transition(outcome, …)   repeat-loop stop conditions
 finally: post hook → _finish_signals() → cleanup-failure resolution
```

Planning is **pure**: `services/run/cycle_plan.py` holds the stack scan and the
mode table with no Qt, DB or CDP imports, so precedence is testable in
isolation (`tests/unit/services/test_cycle_plan.py`). Outcomes are
`worked | stopped | empty | empty_stack`, and "empty" is never reported as
success (invariant **I-3**).

Stop and cancel are honoured at every boundary: `RunStopped` → `"stopped"`;
`asyncio.CancelledError` always propagates untouched (see
`tests/integration/run_safety/test_stop_contract.py`).

### 3.2 Archiving a message (the only write path)

```
in-page agent (backend/js/chat_agent.js)
   │  binding: __cvbPush
   ▼
services/history/runtime.on_binding → Collector.handle_push
   ▼
backend/chat_parser.verify_private(state, nick, my_nick)   ← the two-step gate
   │  refuse → nothing is written, push channel disarmed until a tick re-verifies
   ▼
backend/chat_sync (delta/align) → stores/history_repo* (append, dedup, media)
```

The collector heartbeat (`services/collector_tick.py`) runs the same gate as
five explicit phases: `PROBE → GATE → NICK → VERIFY → ARCHIVE`, and its status
vocabulary is fixed: `Collecting … / Collected N … / No new messages /
Not in private tab now`.

### 3.3 Deleting a world (the only irreversible path)

`services/db_deletion_flow.delete_world()` — a fail-closed pipeline; a phase
that cannot verify stops the run and reports instead of guessing:

```
validate → scan → switch → detach → database → media → finalize
```

* **scan** (`services/db_deletion_scan.py`) builds the inventory: victim
  directory, remembered in-root `.db` paths, active folder. Anything outside
  that boundary is *not scanned and not protected* (`SUPPORTED_BOUNDARY`).
* **database** removes the SQLite file group main-first and stops at the first
  group failure; **media** unlinks file-by-file (never `rmtree`) and keeps any
  file another world still references; symlinks are retained.
* Result shape and phase/error strings are frozen: produced only by
  `services.db_deletion.DeletionOutcome.as_dict()` and pinned bit-for-bit by
  `tests/integration/safety_deletion/` (18 test files).
* **Clean DB** is *not* deletion: it backs the file up to `db_trash/` and is
  undoable.

---

## 4. Current invariants (safety guarantees)

Each one is enforced in code and pinned by a test. Rule numbers refer to
[`AGENT_RULES.md`](AGENT_RULES.md).

| # | Invariant | Enforced in |
|---|---|---|
| **I-1** | A click never lands on a node the user did not see highlighted; overlays can never intercept it (`pointer-events:none`) | `backend/visual_click.py` (RULE 1) |
| **I-2** | Every step is reported; a block that fails silently is a bug | `engine.report()` (RULE 2) |
| **I-3** | "Empty" is never reported as success, and empty is never confused with broken | run engine + blocks (RULE 4) |
| **I-4** | Long loops report incrementally, and a UI callback can never kill the pipeline | `on_collect` wiring (RULE 5) |
| **I-5** | Only entities that pass the *current* filter are persisted; a stricter re-run shrinks the list | `on_reject` + purge (RULE 6) |
| **I-6** | A stop request is honoured inside inner waits, not just the outer loop; "stopped" ≠ "failed" | `actions/cancellation.py` (RULE 7) |
| **I-7** | A guard that skips its own work never stalls the phases after it, and counting failures fail **open** | `_run_collect_phase` (RULE 9) |
| **I-8** | One decision, one control — no hidden second filter | block config (RULE 10) |
| **I-9** | A seek writes nothing: scroll-only mode neither collects, rejects nor purges | `backend/scroll_parser.py` (RULE 11) |
| **I-10** | One chronological undo timeline for every editable surface; automatic side-effects are never recorded | `services/undo_service.py` (RULE 12) |
| **I-11** | State that cannot be read back is never persisted (grid layout is validated and rejected, not repaired) | `services/layout_service.py` (RULE 13) |
| **I-12** | The archive is not the queue: filters, purges, undo and People-list edits never delete archived messages; collectors never add to the queue | `stores/history_repo*`, `stores/user_memory.py` (RULE 14) |
| **I-13** | Nothing is archived without the two-step private gate, re-applied on every write path; the gate fails **closed** | `backend/chat_parser.verify_private()` (RULE 15) |
| **I-14** | Media bytes are filed under the conversation they belong to, never in a global pile | `stores/media_layout.py` (RULE 15) |
| **I-15** | Deleting a world is permanent and leaves no orphans; the last world cannot be deleted; a failed switch leaves the app connected to the previous world | `services/db_deletion_flow.py`, `services/db_lifecycle.py` |
| **I-16** | No `os.unlink` happens before scan + plan + switch + detach + revalidate | `services/db_deletion_flow.py` |

---

## 5. Storage map (current)

**One `.db` file = one world** (schema v6, `stores/history_schema.py`).
Everything world-bound lives inside it:

| Table | Holds |
|---|---|
| `schema_meta` | version stamp + validation parity |
| `persons`, `messages`, `messages_fts` | the archive (append-only; `deleted_at` tombstones) |
| `media` | downloaded image/GIF rows (sha256, path, state) |
| `cursors`, `gaps` | per-person collection progress, backfill planning |
| `users` | the People queue ("who to message under this filter") |
| `labels`, `label_assigns` | label definitions and per-person tags |
| `undo_history` | the world-bound half of the undo timeline |
| `gaze_data` | radar / observation session state |
| `app_settings` | per-world settings (my nick, media caps, …) |

**App-level (not world-bound)** — `config/*.json`, one store per concern,
written atomically: `blocks.json` `bookmarks.json` `labels.json` `presets.json`
`session.json` `settings.json` `undo.json` (`stores/json_store.py`,
`stores/atomic.py`, `stores/migration.py`).

**Media bytes** — `saved_media/<Latin nick>/images|gifs/YYYY-MM-DD_NNN.ext`,
one stable folder per person via a `_nick.txt` marker.

Legacy paths still work: a pre-unified `chatbot.db` queue is re-homed into the
active world once at startup (`HistoryService.migrate_install()`, idempotent and
non-destructive).

---

## 6. Key modules

| Layer | Package | Responsibility |
|---|---|---|
| Contracts | `core/` (5 files) | DI container, EventBus, interfaces, `Result` — no Qt, no I/O |
| Blocks | `actions/` (23) | The 16 action blocks + `BaseAction`, registry, cancellation |
| Page-facing | `backend/` (30) | CDP client, DOM probes, chat parser + private gate, chat sync, scroll parser, visual click, media handler; **compatibility shims** for the pre-split names |
| Wire | `bridge/` (12) | `bridge/router.py` — ONE QObject on the QWebChannel, assembled from nine domain bridges: cdp · stack · people · history · label · db · collector · undo · layout |
| Orchestration | `services/` (31) | `run/` (engine), `history/`, collector, db lifecycle + deletion, layout, people, undo |
| Persistence | `stores/` (35) | SQLite world store + schema/repair, JSON stores, labels, media, presets, undo |
| Shell | `app/` (4) + `main.py` | Bootstrap/DI, window, lifecycle |
| UI | `ui/` (22 JS) | Grid, stack DnD, archive windows, collector panel, labels, db panel, composer, log |
| Tooling | `tools/` | `tools/metrics/*` audits, `tools/build_stubs.py` (headless Qt stubs) |

Bootstrap wiring is one function: `app/bootstrap.create_container()` registers
`config, bus, cdp, memory, criteria, engine, history, bridge`; `main.py`
connects them to the window and starts the qasync loop.

---

## 7. Tests

```bash
# Python (2545 tests + 771 subtests)
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine

# Front-end (22 Node harness files)
for f in tests/test_*.js; do node "$f"; done

# Quality gate that is executable (RULE 16)
.venv/bin/python tests/test_rule16_new_code.py
```

On a machine without GL/X11/NSS (apt blocked), build the stub libraries the
repo already ships a builder for, and put them on `LD_LIBRARY_PATH`:

```bash
.venv/bin/python tools/build_stubs.py .venv /tmp/stublibs
export LD_LIBRARY_PATH=/tmp/stublibs
```

| Directory | What it pins |
|---|---|
| `tests/test_*.py` | Feature-level and end-to-end contracts (db manager, history, grid, undo, media, private gate, blocks) |
| `tests/unit/` | Per-module contracts: `actions/`, `app/`, `backend/`, `bridge_safety/`, `core/`, `services/`, `stores/` |
| `tests/integration/safety_deletion/` | The 18 deletion regressions — result shape, fail-closed ordering, cancellation, shared media, symlinks |
| `tests/integration/run_safety/` | Stop/pause contracts, cycle event order, cleanup |
| `tests/integration/services/` | Service-layer contracts (run engine, history, db, collector, undo, layout, people) |
| `tests/js_harness.js` + `tests/dom_stub.js` | Runs real probe/UI JS against a DOM stub (RULE 8) |

**Frozen contracts** you must not break casually: the AREA D public-API
snapshot (`tests/unit/backend/test_backend_api_snapshot.py`), the QWebChannel
wire (`tests/unit/bridge_safety/test_router_contract.py`), the deletion result
dict, and the collector status strings.

---

## 8. Quality gates (summary — full text in the rules)

| Metric | Fail line | Measured now |
|---|---|---|
| Function LOC / params / methods | ≤ 30 / ≤ 4 / ≤ 15 | mean 9.98 LOC; legacy offenders tracked, not worsened |
| Radon CC / cognitive / nesting (new code) | ≤ 10 / ≤ 15 / ≤ 4 | project max CC 31 (legacy), mean 3.25 |
| Line / branch coverage | ≥ 80% / ≥ 75%, never lower than baseline | **90.44% / 84.38%** |
| Baseline snapshot | — | [`reports/CODE_QUALITY_METRICS_2026-09-10.md`](../../reports/CODE_QUALITY_METRICS_2026-09-10.md) |
| Ideal sizes (**preferences**, not gates) | function 4–20 lines · file 150–300 · module 5–15 files · context file 60–200 | median function 6 lines (57.7% in band) · median file 130 lines — RULE 18 |

---

## 9. Latest designs (newest first)

| Date | Design | Why you'd open it |
|---|---|---|
| 2026-09-10 | [Safety refactor — Area A design](../archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_A_DESIGN_2026-09-10.md) · [Area C design](../archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_C_DESIGN_2026-09-10.md) · [master plan](../archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_2026-09-10_PLAN.md) | The fail-closed deletion pipeline and its frozen contract |
| 2026-09-10 | [`_delete_unlocked` decomposition](../archive/2026-09-10-safety-refactor/DELETE_FLOW_EXTRACTION_DESIGN_2026-09-10.md) · [CC tail extraction](../archive/2026-09-10-safety-refactor/CC_TAIL_EXTRACTION_DESIGN_2026-09-10.md) · [remaining tail](../archive/2026-09-10-safety-refactor/CC_REMAINING_TAIL_DESIGN_2026-09-10.md) | How the worst hotspots were split without changing behaviour |
| 2026-09-10 | [History push lifecycle](../archive/2026-09-10-history-push-and-sort/HISTORY_PUSH_LIFECYCLE_DESIGN_2026-09-10.md) · [Sortable DB columns](../archive/2026-09-10-history-push-and-sort/SORTABLE_DATABASE_COLUMNS_DESIGN_2026-09-10.md) | The `__cvbPush` channel and the sort/query path |
| 2026-09-10 | [Code quality gates](../archive/2026-09-10-quality-gates/CODE_QUALITY_GATES_DESIGN_2026-09-10.md) · [RULE 16 fit](../archive/2026-09-10-quality-gates/RULE16_SIZE_COMPLEXITY_FIT_2026-09-10.md) | Where the thresholds came from and how they are measured |
| 2026-09-09 | [Four-area refactor plan](../archive/2026-09-09-four-area-refactor/REFACTOR_2026-09-09_FOUR_AREA_PLAN.md) (+ areas [A](../archive/2026-09-09-four-area-refactor/REFACTOR_2026-09-09_AREA_A_IMPLEMENTATION_DESIGN.md) [B](../archive/2026-09-09-four-area-refactor/REFACTOR_2026-09-09_AREA_B_DESIGN.md) [C](../archive/2026-09-09-four-area-refactor/REFACTOR_2026-09-09_AREA_C_DESIGN.md) [D](../archive/2026-09-09-four-area-refactor/REFACTOR_2026-09-09_AREA_D_DESIGN.md)) | Why the code is split into `core/actions/backend/bridge/services/stores` |
| 2026-09-09 | [Test-suite designs](../archive/2026-09-09-test-suite/) · [module matrix](../archive/2026-09-09-test-suite/TEST_COVERAGE_MODULE_MATRIX.md) | Which suite pins which module, and why |
| 2026-09-08 | [One DB = One World](../archive/2026-09-08-one-db-one-world/DB_CREATION_DELETION_REDESIGN_DESIGN_2026-09-08.md) | The storage model in §5 |

---

## 10. If you need the history of X, read Y

| Question | Read |
|---|---|
| Why is deletion permanent and fail-closed? | [Safety Area A design](../archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_A_DESIGN_2026-09-10.md), then [delete-flow extraction](../archive/2026-09-10-safety-refactor/DELETE_FLOW_EXTRACTION_DESIGN_2026-09-10.md) |
| Why one file per world, and what was wrong before? | [One DB = One World](../archive/2026-09-08-one-db-one-world/DB_CREATION_DELETION_REDESIGN_DESIGN_2026-09-08.md) |
| Why is the archive separate from the People queue? | [Message-history architecture](../archive/2026-09-06-collector-and-history/MESSAGE_HISTORY_ARCHITECTURE_DESIGN_2026-09-06.md) + [filter purge](../archive/2026-09-05-grid-scroll-undo/FILTER_PURGE_DESIGN_2026-09-05.md) |
| Why the two-step private gate? | [Private gate & media tree](../archive/2026-09-07-labels-and-collector/PRIVATE_GATE_AND_MEDIA_TREE_2026-09-07.md) |
| Why is find-and-click centralised (RED/ORANGE)? | [Visual confirmation](../archive/2026-09-05-grid-scroll-undo/FIND_CLICK_VISUAL_CONFIRMATION_DESIGN_2026-09-05.md) |
| Why does the collector look like a heartbeat? | [Passive collector](../archive/2026-09-06-collector-and-history/PASSIVE_CHAT_COLLECTOR_DESIGN_2026-09-06.md) + [history bugs it fixed](../archive/2026-09-07-labels-and-collector/MESSAGE_HISTORY_BUGS_DESIGN_2026-09-07.md) |
| Why does Scroll & Parse work this way (seek mode, backlog guard)? | [Scroll & Parse redesign](../archive/2026-09-05-grid-scroll-undo/SCROLL_PARSE_REDESIGN_2026-09-05.md) + [scroll-only seek](../archive/2026-09-05-grid-scroll-undo/SCROLL_ONLY_SEEK_DESIGN_2026-09-05.md) |
| Why one undo timeline instead of per-panel? | [People-list undo history](../archive/2026-09-05-grid-scroll-undo/PEOPLE_LIST_UNDO_HISTORY_DESIGN_2026-09-05.md) + [undo/redo toggle](../archive/2026-09-05-grid-scroll-undo/FEATURE_UNDO_REDO_ENABLE_TOGGLE_DESIGN_2026-09-05.md) |
| Why the grid behaves like this (autosave, controls, reset)? | [Sash layout](../archive/2026-09-05-grid-scroll-undo/SASH_LAYOUT_DESIGN_2026-09-05.md) + [grid window controls](../archive/2026-09-07-labels-and-collector/GRID_WINDOW_CONTROLS_DESIGN_2026-09-07.md) |
| Why did media recovery need a root-cause fix? | [Backfill media recovery](../archive/2026-09-07-labels-and-collector/BACKFILL_MEDIA_RECOVERY_ROOT_CAUSE_2026-09-07.md) |
| Why do labels live in the world? | [Person labels & DB management](../archive/2026-09-07-labels-and-collector/PERSON_LABELS_AND_DB_MANAGEMENT_DESIGN_2026-09-07.md) |
| What did the original architecture propose? | [Architecture v1.0.0 (design phase)](../archive/2026-09-04-foundation/ARCHITECTURE.md) — *superseded by this file* |
| Which DOM selectors are real? | [DOM selectors](DOM_SELECTORS.md) — still current, verified against the saved HTML |
