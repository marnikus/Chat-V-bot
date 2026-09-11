# Archived docs — historical, not current

Every design, plan and root-cause doc this repository has produced, grouped by
the date and topic they were written for. **Nothing here is the spec.** The
current spec, invariants and flows live in
[`docs/current/SYSTEM_OF_RECORD.md`](../current/SYSTEM_OF_RECORD.md); the rules
live in [`docs/current/AGENT_RULES.md`](../current/AGENT_RULES.md).

An archived doc is true *as of the date in its folder name*. Do not edit one to
catch up with the code — write a new dated doc instead (RULE 17).

**79 documents in 12 groups.**

| Group | Docs | What it covers |
|---|---:|---|
| [`2026-09-04-foundation/`](#2026-09-04-foundation) | 5 | The original architecture proposal (written before any code existed — **superseded by `docs/current/SYSTEM_OF_RECORD.md`**) plus the first three rounds of bug fixes and the configurable Find & Click block. |
| [`2026-09-05-grid-scroll-undo/`](#2026-09-05-grid-scroll-undo) | 15 | The window grid ("sash layout"), the Scroll & Parse pipeline, visual click confirmation, filter purging and the first global undo timeline. |
| [`2026-09-06-collector-and-history/`](#2026-09-06-collector-and-history) | 15 | The message-history archive, its three windows, the passive collector, and the person-targeting blocks (`{{nick}}`, Pick Person, Mark Messaged, attach/composer behaviour). |
| [`2026-09-07-labels-and-collector/`](#2026-09-07-labels-and-collector) | 7 | Person labels and DB management, the private-chat gate and media tree, collector UX, and the root-cause analysis of the media-backfill bug. |
| [`2026-09-08-one-db-one-world/`](#2026-09-08-one-db-one-world) | 4 | "One DB = One World": the unified single-file world, its schema / re-collection / radar fixes, label badge interaction, and the minimize-to-dock window fix. |
| [`2026-09-09-four-area-refactor/`](#2026-09-09-four-area-refactor) | 6 | The four-area split into `core/ actions/ backend/ bridge/ services/ stores/` — the reason the tree looks the way it does today. |
| [`2026-09-09-test-suite/`](#2026-09-09-test-suite) | 9 | Test designs per layer (backend, stores, services, core, main/JS), the coverage master plan and the module matrix. Use these to find out *which* suite pins *which* module. |
| [`2026-09-10-safety-refactor/`](#2026-09-10-safety-refactor) | 10 | The safety-first round: fail-closed permanent deletion (Area A), bridge behaviour protection (B), stop correctness and cycle orchestration (C), then the complexity extractions that followed. |
| [`2026-09-10-quality-gates/`](#2026-09-10-quality-gates) | 2 | Where the RULE 16 thresholds came from, and how one feature was measured against them. |
| [`2026-09-10-history-push-and-sort/`](#2026-09-10-history-push-and-sort) | 3 | The `__cvbPush` lifecycle hardening and sortable columns in the Full User Database. |
| [`2026-09-10-agent-rules-v1/`](#2026-09-10-agent-rules-v1) | 2 | The two rules files that [`docs/current/AGENT_RULES.md`](../current/AGENT_RULES.md) replaced. Kept for history — **do not follow these; follow the current file.** |
| [`2026-09-11-db-undo-restore/`](#2026-09-11-db-undo-restore) | 1 | The two bugs that ate a person: the world-file write gate (`stores/world_lock.py`), the archive command that verifies itself, the DB window’s refresh wiring and the instant, session-sized trash. |

---

## 2026-09-04-foundation

The original architecture proposal (written before any code existed — **superseded by `docs/current/SYSTEM_OF_RECORD.md`**) plus the first three rounds of bug fixes and the configurable Find & Click block.

*5 docs.*

- [`ARCHITECTURE.md`](2026-09-04-foundation/ARCHITECTURE.md) — ChatBot Automator — Detailed Architecture Document
- [`CONFIGURABLE_BLOCK_DESIGN_2026-09-04.md`](2026-09-04-foundation/CONFIGURABLE_BLOCK_DESIGN_2026-09-04.md) — Design — Configurable Action Block Constructor ("Find & Click")
- [`FIXES2_DESIGN_2026-09-04.md`](2026-09-04-foundation/FIXES2_DESIGN_2026-09-04.md) — Fix Design v2 — Clean Exit, Session Restore, Single Preset Store, Custom Find/Click Blocks
- [`FIXES_DESIGN_2026-09-04.md`](2026-09-04-foundation/FIXES_DESIGN_2026-09-04.md) — Fix Design — Preset Save/Load, URL Parse Preset, Step Debugger
- [`FIXES_DESIGN_2026-09-04c.md`](2026-09-04-foundation/FIXES_DESIGN_2026-09-04c.md) — Fix Design — People-List Deletion + Drag-and-Drop Stack Reordering

---

## 2026-09-05-grid-scroll-undo

The window grid ("sash layout"), the Scroll & Parse pipeline, visual click confirmation, filter purging and the first global undo timeline.

*15 docs.*

- [`CONFIG_PANEL_ROWS_AND_TOGGLE_FIX_DESIGN_2026-09-05.md`](2026-09-05-grid-scroll-undo/CONFIG_PANEL_ROWS_AND_TOGGLE_FIX_DESIGN_2026-09-05.md) — Block Config panel: toggle-bar fix + two-column row layout — design
- [`FEATURE_UNDO_REDO_ENABLE_TOGGLE_DESIGN_2026-09-05.md`](2026-09-05-grid-scroll-undo/FEATURE_UNDO_REDO_ENABLE_TOGGLE_DESIGN_2026-09-05.md) — Feature Design: Undo/Redo History + Enable/Disable Toggle for Action Blocks
- [`FILTER_PURGE_DESIGN_2026-09-05.md`](2026-09-05-grid-scroll-undo/FILTER_PURGE_DESIGN_2026-09-05.md) — Design — Rejected people must never enter the list (and must be purged)
- [`FIND_CLICK_VISUAL_CONFIRMATION_DESIGN_2026-09-05.md`](2026-09-05-grid-scroll-undo/FIND_CLICK_VISUAL_CONFIRMATION_DESIGN_2026-09-05.md) — Design — Visual Confirmation for “Find & Click” blocks + “Tab Main” does-nothing bug
- [`GRID_CLOSE_AUTOSAVE_DESIGN_2026-09-05.md`](2026-09-05-grid-scroll-undo/GRID_CLOSE_AUTOSAVE_DESIGN_2026-09-05.md) — Grid layout close-time autosave design
- [`GRID_PERSIST_UNDO_RESET_DESIGN_2026-09-05.md`](2026-09-05-grid-scroll-undo/GRID_PERSIST_UNDO_RESET_DESIGN_2026-09-05.md) — Flexible grid — backend persistence, undo/redo, and Reset to default
- [`GRID_ROW_RESIZE_MINIMUM_DESIGN_2026-09-05.md`](2026-09-05-grid-scroll-undo/GRID_ROW_RESIZE_MINIMUM_DESIGN_2026-09-05.md) — Grid row-resize stability and edge-control design
- [`GRID_WINDOW_MEMORY_SORT_DESIGN_2026-09-05.md`](2026-09-05-grid-scroll-undo/GRID_WINDOW_MEMORY_SORT_DESIGN_2026-09-05.md) — Grid persistence, global undo, window restore, and sortable people table
- [`LIVE_STATUS_AND_ORDER_COLUMN_DESIGN_2026-09-05.md`](2026-09-05-grid-scroll-undo/LIVE_STATUS_AND_ORDER_COLUMN_DESIGN_2026-09-05.md) — Live People status refresh + undo timestamp erase + Order (#) column
- [`PEOPLE_LIST_UNDO_HISTORY_DESIGN_2026-09-05.md`](2026-09-05-grid-scroll-undo/PEOPLE_LIST_UNDO_HISTORY_DESIGN_2026-09-05.md) — People-list actions join the global undo history — design
- [`REPEAT_LOOP_BLOCK_DESIGN_2026-09-05.md`](2026-09-05-grid-scroll-undo/REPEAT_LOOP_BLOCK_DESIGN_2026-09-05.md) — Repeat Loop action block — design
- [`SASH_LAYOUT_DESIGN_2026-09-05.md`](2026-09-05-grid-scroll-undo/SASH_LAYOUT_DESIGN_2026-09-05.md) — Flexible Grid Window System ("Sash Layout") — Design
- [`SCROLL_ONLY_MODE_AND_FILTER_CHECKBOX_REMOVAL_2026-09-05.md`](2026-09-05-grid-scroll-undo/SCROLL_ONLY_MODE_AND_FILTER_CHECKBOX_REMOVAL_2026-09-05.md) — Scroll & Parse: remove the duplicate "use_panel_filters" checkbox + add
- [`SCROLL_ONLY_SEEK_DESIGN_2026-09-05.md`](2026-09-05-grid-scroll-undo/SCROLL_ONLY_SEEK_DESIGN_2026-09-05.md) — Scroll & Parse — remove duplicate filter control, add "Only scroll, no people adding"
- [`SCROLL_PARSE_REDESIGN_2026-09-05.md`](2026-09-05-grid-scroll-undo/SCROLL_PARSE_REDESIGN_2026-09-05.md) — Design — "Scroll & Parse" as an integrated pipeline + shared visual confirmation

---

## 2026-09-06-collector-and-history

The message-history archive, its three windows, the passive collector, and the person-targeting blocks (`{{nick}}`, Pick Person, Mark Messaged, attach/composer behaviour).

*15 docs.*

- [`ATTACH_IMAGE_DIALOG_FORMATS_DESIGN_2026-09-06.md`](2026-09-06-collector-and-history/ATTACH_IMAGE_DIALOG_FORMATS_DESIGN_2026-09-06.md) — Attach Image: open upload dialog, select & send — with jpg/gif/png support
- [`CLICK_USER_RESPECT_ORDER_DESIGN_2026-09-06.md`](2026-09-06-collector-and-history/CLICK_USER_RESPECT_ORDER_DESIGN_2026-09-06.md) — Click User: “Respect the Order (#) column” checkbox
- [`CLICK_USER_USE_PERSON_FROM_MEMORY_DESIGN_2026-09-06.md`](2026-09-06-collector-and-history/CLICK_USER_USE_PERSON_FROM_MEMORY_DESIGN_2026-09-06.md) — Click User "Use Person from Memory" — click the {{nick}} person, not the queue
- [`CONFIG_PANEL_PIN_DESIGN_2026-09-06.md`](2026-09-06-collector-and-history/CONFIG_PANEL_PIN_DESIGN_2026-09-06.md) — Block Config pin (keep-open) — design
- [`EXTRA_PAUSE_STATUS_AND_ATTACH_TARGETING_DESIGN_2026-09-06.md`](2026-09-06-collector-and-history/EXTRA_PAUSE_STATUS_AND_ATTACH_TARGETING_DESIGN_2026-09-06.md) — Extra Pause status + Attach Image: active-chat targeting & visual confirmation
- [`HISTORY_UI_WINDOWS_DESIGN_2026-09-06.md`](2026-09-06-collector-and-history/HISTORY_UI_WINDOWS_DESIGN_2026-09-06.md) — History UI — three new windows, lazy loading, copy & search
- [`MARK_PERSON_MESSAGED_BLOCK_DESIGN_2026-09-06.md`](2026-09-06-collector-and-history/MARK_PERSON_MESSAGED_BLOCK_DESIGN_2026-09-06.md) — "Mark Person as Messaged" block — mark the {{nick}} person Done
- [`MESSAGE_COMPOSER_AND_PASTE_FALLBACK_DESIGN_2026-09-06.md`](2026-09-06-collector-and-history/MESSAGE_COMPOSER_AND_PASTE_FALLBACK_DESIGN_2026-09-06.md) — Message block: “use composer text” checkbox + paste/Ctrl+V typing fallback
- [`MESSAGE_HISTORY_ARCHITECTURE_DESIGN_2026-09-06.md`](2026-09-06-collector-and-history/MESSAGE_HISTORY_ARCHITECTURE_DESIGN_2026-09-06.md) — Message History Archive — Master Architecture
- [`MESSAGE_HISTORY_IMPLEMENTATION_PLAN_2026-09-06.md`](2026-09-06-collector-and-history/MESSAGE_HISTORY_IMPLEMENTATION_PLAN_2026-09-06.md) — Message History + Collector — Implementation Plan
- [`NICK_PLACEHOLDER_SELECTED_USER_DESIGN_2026-09-06.md`](2026-09-06-collector-and-history/NICK_PLACEHOLDER_SELECTED_USER_DESIGN_2026-09-06.md) — {{nick}} in any field: the remembered selected-user nickname
- [`PASSIVE_CHAT_COLLECTOR_DESIGN_2026-09-06.md`](2026-09-06-collector-and-history/PASSIVE_CHAT_COLLECTOR_DESIGN_2026-09-06.md) — Passive Private-Chat Message Collector — Background Architecture
- [`PICK_PERSON_MEMORY_BLOCK_DESIGN_2026-09-06.md`](2026-09-06-collector-and-history/PICK_PERSON_MEMORY_BLOCK_DESIGN_2026-09-06.md) — New "Pick Person" action block — pick a saved person and remember the nick
- [`SEARCH_BOX_TYPING_DESIGN_2026-09-06.md`](2026-09-06-collector-and-history/SEARCH_BOX_TYPING_DESIGN_2026-09-06.md) — Type into the users-list search (Поиск) box — verified focus + text
- [`SMART_LOCATE_DESIGN_2026-09-06.md`](2026-09-06-collector-and-history/SMART_LOCATE_DESIGN_2026-09-06.md) — Smart Locate — finding any user in the virtualized list without blind scrolling

---

## 2026-09-07-labels-and-collector

Person labels and DB management, the private-chat gate and media tree, collector UX, and the root-cause analysis of the media-backfill bug.

*7 docs.*

- [`BACKFILL_MEDIA_RECOVERY_ROOT_CAUSE_2026-09-07.md`](2026-09-07-labels-and-collector/BACKFILL_MEDIA_RECOVERY_ROOT_CAUSE_2026-09-07.md) — Bug #2 — failed media cannot be recovered via backfill: ROOT CAUSE — 2026-09-07
- [`COLLECTOR_LOG_WINDOW_DESIGN_2026-09-07.md`](2026-09-07-labels-and-collector/COLLECTOR_LOG_WINDOW_DESIGN_2026-09-07.md) — Collector-local History Log window
- [`COLLECTOR_NICK_HISTORY_JUMP_DESIGN_2026-09-07.md`](2026-09-07-labels-and-collector/COLLECTOR_NICK_HISTORY_JUMP_DESIGN_2026-09-07.md) — Clickable partner in the Collector → Person History + DB highlight
- [`GRID_WINDOW_CONTROLS_DESIGN_2026-09-07.md`](2026-09-07-labels-and-collector/GRID_WINDOW_CONTROLS_DESIGN_2026-09-07.md) — Grid Window Management Controls — Design
- [`MESSAGE_HISTORY_BUGS_DESIGN_2026-09-07.md`](2026-09-07-labels-and-collector/MESSAGE_HISTORY_BUGS_DESIGN_2026-09-07.md) — Message History — remaining bugs design — 2026-09-07
- [`PERSON_LABELS_AND_DB_MANAGEMENT_DESIGN_2026-09-07.md`](2026-09-07-labels-and-collector/PERSON_LABELS_AND_DB_MANAGEMENT_DESIGN_2026-09-07.md) — Person History Management, Labels, Color Picker, Label Manager & DB Connection — Design
- [`PRIVATE_GATE_AND_MEDIA_TREE_2026-09-07.md`](2026-09-07-labels-and-collector/PRIVATE_GATE_AND_MEDIA_TREE_2026-09-07.md) — Private-chat gate & the readable media tree — 2026-09-07

---

## 2026-09-08-one-db-one-world

"One DB = One World": the unified single-file world, its schema / re-collection / radar fixes, label badge interaction, and the minimize-to-dock window fix.

*4 docs.*

- [`DB_CREATION_DELETION_REDESIGN_DESIGN_2026-09-08.md`](2026-09-08-one-db-one-world/DB_CREATION_DELETION_REDESIGN_DESIGN_2026-09-08.md) — DB Creation & Deletion Redesign — Unified Single-DB ("One DB = One World")
- [`DB_SCHEMA_RECOLLECT_RADAR_FIXES_DESIGN_2026-09-08.md`](2026-09-08-one-db-one-world/DB_SCHEMA_RECOLLECT_RADAR_FIXES_DESIGN_2026-09-08.md) — DB Schema Errors, History Display, Re-Collection & Radar Count — Design
- [`LABEL_BADGE_ASSIGN_EDIT_DELETE_DESIGN_2026-09-08.md`](2026-09-08-one-db-one-world/LABEL_BADGE_ASSIGN_EDIT_DELETE_DESIGN_2026-09-08.md) — Label Badge Interaction — Assign / Edit / Delete + Quick Assign on Person Click — Design
- [`WINDOW_CONTROLS_MINIMIZE_DOCK_FIX_DESIGN_2026-09-08.md`](2026-09-08-one-db-one-world/WINDOW_CONTROLS_MINIMIZE_DOCK_FIX_DESIGN_2026-09-08.md) — Window Controls — Minimize-to-Bottom-Strip Redesign (bugfix)

---

## 2026-09-09-four-area-refactor

The four-area split into `core/ actions/ backend/ bridge/ services/ stores/` — the reason the tree looks the way it does today.

*6 docs.*

- [`REFACTOR_2026-09-09_AREA_A_IMPLEMENTATION_DESIGN.md`](2026-09-09-four-area-refactor/REFACTOR_2026-09-09_AREA_A_IMPLEMENTATION_DESIGN.md) — AREA A — Startup & Test Harness Implementation Design
- [`REFACTOR_2026-09-09_AREA_B_DESIGN.md`](2026-09-09-four-area-refactor/REFACTOR_2026-09-09_AREA_B_DESIGN.md) — AREA B — `stores/` — design for the implementation
- [`REFACTOR_2026-09-09_AREA_C_DESIGN.md`](2026-09-09-four-area-refactor/REFACTOR_2026-09-09_AREA_C_DESIGN.md) — AREA C — Services Refactor Design (Structure)
- [`REFACTOR_2026-09-09_AREA_D_DESIGN.md`](2026-09-09-four-area-refactor/REFACTOR_2026-09-09_AREA_D_DESIGN.md) — AREA D — `backend/` + `actions/` Refactor Design
- [`REFACTOR_2026-09-09_DESIGN.md`](2026-09-09-four-area-refactor/REFACTOR_2026-09-09_DESIGN.md) — ChatBot Automator — Architecture Refactor 2026-09-09
- [`REFACTOR_2026-09-09_FOUR_AREA_PLAN.md`](2026-09-09-four-area-refactor/REFACTOR_2026-09-09_FOUR_AREA_PLAN.md) — Refactor Plan — 4 Independent Parallel Areas

---

## 2026-09-09-test-suite

Test designs per layer (backend, stores, services, core, main/JS), the coverage master plan and the module matrix. Use these to find out *which* suite pins *which* module.

*9 docs.*

- [`BACKEND_TESTS_DESIGN_2026-09-09.md`](2026-09-09-test-suite/BACKEND_TESTS_DESIGN_2026-09-09.md) — Backend (Section C) Test Design — Bug-Finding Pass
- [`CORE_LAYER_UNCOVERED_DESIGN.md`](2026-09-09-test-suite/CORE_LAYER_UNCOVERED_DESIGN.md) — Core Layer Uncovered Design — Real Path Tests (No Fakes)
- [`SERVICES_TEST_DESIGN_2026-09-09.md`](2026-09-09-test-suite/SERVICES_TEST_DESIGN_2026-09-09.md) — Test Design — `services/` Orchestration Layer (Section E)
- [`STORES_TEST_DESIGN_2026-09-09.md`](2026-09-09-test-suite/STORES_TEST_DESIGN_2026-09-09.md) — `stores/` — Persistence Layer: test design (spec-first)
- [`TEST_COVERAGE_MODULE_MATRIX.md`](2026-09-09-test-suite/TEST_COVERAGE_MODULE_MATRIX.md) — Test Coverage Module Matrix — Full Inventory & Design Mapping
- [`TEST_COVERAGE_REF_DESIGN_2026-09-09.md`](2026-09-09-test-suite/TEST_COVERAGE_REF_DESIGN_2026-09-09.md) — Master Design: Test Coverage Refactor Plan — Cover All Logic
- [`UNCOVERED_LOGIC_DESIGN_2026-09-09.md`](2026-09-09-test-suite/UNCOVERED_LOGIC_DESIGN_2026-09-09.md) — Uncovered Logic Design — Phase 3 Extension (Real Tests, Real Paths)
- [`UNDO_STORE_REPAIR_2026-09-09.md`](2026-09-09-test-suite/UNDO_STORE_REPAIR_2026-09-09.md) — Undo timeline persistence repair — stores/undo_store.py (+ siblings)
- [`design_main_and_js_tests.md`](2026-09-09-test-suite/design_main_and_js_tests.md) — Design: `main.py` smoke + JS wire contracts

---

## 2026-09-10-safety-refactor

The safety-first round: fail-closed permanent deletion (Area A), bridge behaviour protection (B), stop correctness and cycle orchestration (C), then the complexity extractions that followed.

*10 docs.*

- [`CC_REMAINING_TAIL_DESIGN_2026-09-10.md`](2026-09-10-safety-refactor/CC_REMAINING_TAIL_DESIGN_2026-09-10.md) — Remaining max-CC / nesting tail — extraction design (round 3 proposal)
- [`CC_TAIL_EXTRACTION_DESIGN_2026-09-10.md`](2026-09-10-safety-refactor/CC_TAIL_EXTRACTION_DESIGN_2026-09-10.md) — Remaining max-CC tail — extraction design (post `_delete_unlocked` fix)
- [`DELETE_FLOW_EXTRACTION_DESIGN_2026-09-10.md`](2026-09-10-safety-refactor/DELETE_FLOW_EXTRACTION_DESIGN_2026-09-10.md) — `_delete_unlocked` decomposition — design (max-CC regression fix)
- [`SAFETY_REFACTOR_2026-09-10_PLAN.md`](2026-09-10-safety-refactor/SAFETY_REFACTOR_2026-09-10_PLAN.md) — Safety-first improvement design: three independently implementable areas
- [`SAFETY_REFACTOR_AREA_A_2026-09-10.md`](2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_A_2026-09-10.md) — Area A — permanent deletion safety
- [`SAFETY_REFACTOR_AREA_A_DESIGN_2026-09-10.md`](2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_A_DESIGN_2026-09-10.md) — AREA A — Deletion Safety: New-Structure Design (implementation blueprint)
- [`SAFETY_REFACTOR_AREA_B_2026-09-10.md`](2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_B_2026-09-10.md) — Area B — bridge behavior protection
- [`SAFETY_REFACTOR_AREA_C_2026-09-10.md`](2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_C_2026-09-10.md) — Area C — stop correctness, then cycle orchestration
- [`SAFETY_REFACTOR_AREA_C_CC_DESIGN_2026-09-10.md`](2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_C_CC_DESIGN_2026-09-10.md) — AREA C follow-up — design for the remaining CC 9 in `_execute_cycle`
- [`SAFETY_REFACTOR_AREA_C_DESIGN_2026-09-10.md`](2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_C_DESIGN_2026-09-10.md) — AREA C — Stop Correctness + Cycle Orchestration: New-Structure Design (implementation blueprint)

---

## 2026-09-10-quality-gates

Where the RULE 16 thresholds came from, and how one feature was measured against them.

*2 docs.*

- [`CODE_QUALITY_GATES_DESIGN_2026-09-10.md`](2026-09-10-quality-gates/CODE_QUALITY_GATES_DESIGN_2026-09-10.md) — Design: Code quality rules and auto-enforcement
- [`RULE16_SIZE_COMPLEXITY_FIT_2026-09-10.md`](2026-09-10-quality-gates/RULE16_SIZE_COMPLEXITY_FIT_2026-09-10.md) — RULE 16 conformance of the sortable-columns feature

---

## 2026-09-10-history-push-and-sort

The `__cvbPush` lifecycle hardening and sortable columns in the Full User Database.

*3 docs.*

- [`HISTORY_PUSH_LIFECYCLE_DESIGN_2026-09-10.md`](2026-09-10-history-push-and-sort/HISTORY_PUSH_LIFECYCLE_DESIGN_2026-09-10.md) — History push lifecycle safety — design
- [`HISTORY_PUSH_LIFECYCLE_PLAN_2026-09-10.md`](2026-09-10-history-push-and-sort/HISTORY_PUSH_LIFECYCLE_PLAN_2026-09-10.md) — History push lifecycle safety — split plan (H1/H2/H3)
- [`SORTABLE_DATABASE_COLUMNS_DESIGN_2026-09-10.md`](2026-09-10-history-push-and-sort/SORTABLE_DATABASE_COLUMNS_DESIGN_2026-09-10.md) — Sortable columns in the Full User Database (BD)

---

## 2026-09-10-agent-rules-v1

The two rules files that [`docs/current/AGENT_RULES.md`](../current/AGENT_RULES.md) replaced. Kept for history — **do not follow these; follow the current file.**

*2 docs.*

- [`AGENT_RULES.md`](2026-09-10-agent-rules-v1/AGENT_RULES.md) — Code generation rules for this repository
- [`AGENT_RULES_CODE_QUALITY.md`](2026-09-10-agent-rules-v1/AGENT_RULES_CODE_QUALITY.md) — RULE 16 — Code quality gates (mandatory for every agent change)

---

## 2026-09-11-db-undo-restore

Ctrl+Z in the Full User Database window reported success while the person stayed deleted
(`database is locked` inside a scheduled task), and the DB list never refreshed on its own.
This folder holds the design for both fixes.

*1 doc.*

- [`DB_UNDO_RESTORE_DESIGN_2026-09-11.md`](2026-09-11-db-undo-restore/DB_UNDO_RESTORE_DESIGN_2026-09-11.md) — One write gate per world file, an archive command that proves itself, DB-window auto-refresh, instant deletes and the session-sized trash
