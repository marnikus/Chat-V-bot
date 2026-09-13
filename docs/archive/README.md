# Archived docs — historical, not current

Every design, plan and root-cause doc this repository has produced, grouped by
the date and topic they were written for. **Nothing here is the spec.** The
current spec, invariants and flows live in
[`docs/current/SYSTEM_OF_RECORD.md`](../current/SYSTEM_OF_RECORD.md); the rules
live in [`docs/current/AGENT_RULES.md`](../current/AGENT_RULES.md).

An archived doc is true *as of the date in its folder name*. Do not edit one to
catch up with the code — write a new dated doc instead (RULE 17).

**83 documents in 16 groups.**

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
| [`2026-09-11-cc-tail/`](#2026-09-11-cc-tail) | 1 | The complexity tail the quality gates left behind: every over-gate function in the tree decomposed to CC ≤ 10, measured phase by phase. |
| [`2026-09-11-db-undo-restore/`](#2026-09-11-db-undo-restore) | 1 | The two bugs that ate a person: the world-file write gate (`stores/world_lock.py`), the archive command that verifies itself, the DB window’s refresh wiring and the instant, session-sized trash. |
| [`2026-09-11-rules-appendices/`](#2026-09-11-rules-appendices) | 1 | Detail moved out of [`docs/current/AGENT_RULES.md`](../current/AGENT_RULES.md) to keep it inside its §18.4 reading budget — RULE 1's worked visual-click examples. |
| [`2026-09-12-db-undo-restore-port/`](#2026-09-12-db-undo-restore-port) | 1 | Porting that feature onto the CC-tail tree by hand (the branches have unrelated histories): the four merge conflicts, the write-gate bug the port exposed, and the re-measured RULE 16 / RULE 18 numbers. |
| [`2026-09-12-round-f-size-tail/`](#2026-09-12-round-f-size-tail) | 2 | Round F: the 500-line file tail. Why the frozen AREA D snapshot blocks splitting the two worst files, the `services/db_deletion.py` split that it does not block, and the decomposition of the two god classes the snapshot does not cover — `Collector` and `UndoService`. |

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

## 2026-09-11-cc-tail

The quality gates were green on *new* code while a tail of legacy functions stayed over them.
This folder holds the round that closed the tail: CC > 10 went from 63 functions to 0, phase by
phase, with the measured table at the end.

*1 doc.*

- [`CC_TAIL_FIXES_DESIGN_2026-09-11.md`](2026-09-11-cc-tail/CC_TAIL_FIXES_DESIGN_2026-09-11.md) — Every over-gate function decomposed (CC, cognitive, nesting, LOC), the frozen exemptions, and the measured end state

---

## 2026-09-11-rules-appendices

[`docs/current/AGENT_RULES.md`](../current/AGENT_RULES.md) has a reading budget (§18.4): an agent
must be able to load all the rules in one pass. When a rule's worked examples outgrew that budget
they moved here, and the rule keeps the norm plus a link.

*1 doc.*

- [`RULE1_VISUAL_CLICK_EXAMPLES.md`](2026-09-11-rules-appendices/RULE1_VISUAL_CLICK_EXAMPLES.md) — RULE 1's worked examples: what the shared visual runner does and why find-and-click goes through it

---

## 2026-09-11-db-undo-restore

Ctrl+Z in the Full User Database window reported success while the person stayed deleted
(`database is locked` inside a scheduled task), and the DB list never refreshed on its own.
This folder holds the design for both fixes.

*1 doc.*

- [`DB_UNDO_RESTORE_DESIGN_2026-09-11.md`](2026-09-11-db-undo-restore/DB_UNDO_RESTORE_DESIGN_2026-09-11.md) — One write gate per world file, an archive command that proves itself, DB-window auto-refresh, instant deletes and the session-sized trash

---

## 2026-09-12-db-undo-restore-port

The write gate and the verified undo above were built on a branch whose history this one does not
share, so the feature had to be ported by hand onto a tree that had independently been through the
CC-tail round. This folder records what that port needed — not the feature's reasoning, which is
the 2026-09-11 doc.

*1 doc.*

- [`PORT_NOTES_2026-09-12.md`](2026-09-12-db-undo-restore-port/PORT_NOTES_2026-09-12.md) — The hand port: four merge conflicts and how each was resolved, the `init()` bug that left a world holding its own write gate, and the re-measured RULE 16 / RULE 18 numbers

---

## 2026-09-12-round-f-size-tail

The 2026-09-12 audit closed out complexity (0 / 1,997 functions above CC 10) and left size as the
only failing category: 10 files over 500 lines, 38 classes over the 150-LOC gate line. This folder
holds the design for the round that works that tail, including the finding that five of those ten
files — the two worst among them — sit behind the frozen AREA D public-API snapshot, which skips
packages and counts only symbols a module owns.

*2 docs.*

- [`ROUND_F_DESIGN_2026-09-12.md`](2026-09-12-round-f-size-tail/ROUND_F_DESIGN_2026-09-12.md) — The 500-line tail, the snapshot that freezes half of it, and the six-file split of `services/db_deletion.py` with its measured dependency DAG and rejected dishonest reductions. §8 records F1's executed outcome, including the lesson that a re-export shim is not `mock.patch`-transparent. §9 records step F6 (2026-09-13), the test-only one: the audit's 9 mutation survivors in `backend/history_query.py` reduced to 1 at 158/159 = 99.37%, and the three reasons they survived were not the same problem — four were killed all along by `tests/test_history_query_edges.py`, which the `[mutmut]` job does not select (widening it was measured at 910 reachable mutants instead of 159 and rejected), four sat on a `db.scalar` fallback and an SQL keyword case that no real database can distinguish, and one (`_my_nicks` 7) is provably equivalent and left alive rather than killed by a spy on `json.loads`. §9.3 is the finding worth more than the mutants: mutmut reads any non-zero pytest exit as a kill, so on a machine where `tests/conftest.py` cannot import PySide6 the job reports **159/159 killed, 0 survivors** — a false 100% that `pytest_add_cli_args = --noconftest` now makes impossible, with `mutants/` gitignored so the sandbox cannot be committed either. §9.7 records the reapplication to `arena/01a09227-chat-v-bot`, where the whole step was re-measured in a sandbox that *does* import PySide6 rather than trusted: the job reproduces 158/159 = 99.37% with `_my_nicks` 7 as the sole survivor and the full suite reaches 2788 passed with no caveat needed, and two of §9's own claims needed correcting — under pytest 9.1.1 a conftest failure exits **4** and mutmut 3.7.0 *raises* on 4 instead of scoring a silent kill, so the flag's value here is that the job runs at all (the silent path survives through exit **2**, a selected test module that fails to import), and §9.5's "39% → 40%" is 44% → 46% for the 125 → 121 missed lines it reports correctly
- [`ROUND_F2_F3_GOD_CLASS_DESIGN_2026-09-12.md`](2026-09-12-round-f-size-tail/ROUND_F2_F3_GOD_CLASS_DESIGN_2026-09-12.md) — Steps F2 and F3: decomposing the two §16.5 landmine god classes the AREA D snapshot does *not* freeze, `Collector` (526 class LOC / 40 methods / LCOM 0.92) and `UndoService` (418 / 28 / 0.92), into collaborator families following the convention `tests/unit/stores/test_stores_structure.py` already pins. §8 records F2's executed outcome against every target, the three targets it missed and why, two frozen contracts it touched (the clone baseline and the `stores/` import pin), and the RULE 16 / RULE 18 recheck. §8.9–§8.10 settle the intermittent world-switch undo failure as a *product* bug rather than test timing — concurrent saves desynchronised `WriteTurn.held` from the gate depth, fixed by coalescing saves, with the residual `WriteTurn` risk recorded as F3c. §8.11 records F3's executed outcome: 573 → 241 lines, `UndoService` 418 → 179 class LOC with all 28 names still on the facade, the five frozen contracts it had to respect (`push` and its monkeypatched module global chief among them), the degenerate LCOM\* the `owner` convention produces in a part, and the DB-connection undo seams the split exposed as having no test at all. §8.12 records F3d closing that gap to 100% (repo line coverage 91.69%, branch 86.84%), correcting §8.11.8's framing of it — the delete branch is legacy-entry-only, since `db_bridge` guards its only `dbconn` push with `if op != "delete"` — and naming two product decisions it found and deliberately left open: the D4 tension over whether a persisted legacy delete entry may restore a deleted world, and `dbconn` still announcing "database restored" from the intent, the exact bug I-18 fixed for `archive`. §8.13 records F3e resolving the second of those: `_log_command` now skips `dbconn` as it skips `archive`, and `undo_db._announce` writes the line from the DbManager's own result instead of from the intent (SYSTEM_OF_RECORD I-21), while failures stay silent because `emit_db_change` already warns and every `{"ok": False}` carries an `error`. The timeline still moves from the intent and the rewind asymmetry against `archive` is named rather than copied, since rewinding a *legacy delete* entry is decision 1's question. Its negative check found that I-18's archive suppression had never been pinned by any test in the repo, so a new test class now holds both kinds: 8/8 mutations caught by the gaps file's 28 tests (repo line coverage 91.69%, branch 86.82%, `undo_db.py` still 100% line and branch). The D4 tension remained open at that point. §8.14 records the boot-wait fix cherry-picked from the unrelated branch `arena/01a099fd-chat-v-bot` — 254 commits and no merge base, so cherry-pick rather than merge: `wait_for_world_open` / `run_when_world_open` answer a request that races the world open instead of letting it die unheard, and the JS side re-asks once its listeners exist. Three conflicts were resolved by keeping both sides' truths, and `HistoryBridge`'s ratchet was re-frozen at the 467/44 the fix actually produced instead of being left at 493/45, which also lowers F4's starting point. §8.15 is F3f, the people double line: `_log_command` became a whitelist (`labels` is the only command kind that applies synchronously), `people_service.apply` learned the direction so its single surviving line says ↩ or ↪ truthfully, and two unreachable blocks in `_apply_entry` were deleted rather than pinned — along with the correction of a false claim made mid-step about the archive flow being untested, which the suite disproved by breaking two doubles in `test_world_write_gate.py`. §8.16 records the owner's ruling on the D4 tension: the functionality stands as it works, a pre-guard world keeps its one undoable delete, and no migration is planned

## 2026-09-13-ai-bot-chat

The AI Bot Chat window and the Grok Prompt Editor: a per-person window that loads only the current
day's messages, asks the Grok API for a suggested reply or a reaction analysis, and shows every
answer as a *pending* card behind an explicit ✅ / ❌ / 🔄 verification step. Approval only enables
"Send to Person"; nothing is delivered or labelled without a human click.

*2 docs.*

- [`AI_BOT_CHAT_DESIGN_2026-09-13.md`](2026-09-13-ai-bot-chat/AI_BOT_CHAT_DESIGN_2026-09-13.md) — Why the feature is four small `bot_*` service files plus one Qt bridge rather than slots on the ratcheted `HistoryBridge`, why the Prompt Editor is a separate grid window (layout v4) rather than a panel inside Bot Chat, and the one-active-label rule expressed as a single `set_for` write shared by the AI-confirm and manual-click paths. §4 carries the post-implementation size table, re-measured against the RULE 16 OWNED set.
- [`BOT_CHAT_DEFECTS_2026-09-13.md`](2026-09-13-ai-bot-chat/BOT_CHAT_DEFECTS_2026-09-13.md) — The defect round against the shipped feature, found by reading the new code against the repo's existing invariants rather than against its own tests. Six ordered by blast radius: the label store read off an attribute `HistoryService` does not have (labelling was dead in the app while green in the suite, because the archive *double* had invented the attribute — a test-design bug as much as a product one); a message could be delivered into whichever chat the browser happened to have open, the only irreversible act in the feature and the one `chat_sync` already guards for reads; the label write bypassed the global undo timeline, the Label Manager refresh and the People count; "no messages today" conflated a closed world with the archive's clock-derived day boundary; the API key was unreachable from the UI while the error named a field that did not exist; and one CC 9 parser. §Outcome records the execution, including the bridge split the method budget forced (the Prompt Editor is its own window, so it is now its own bridge) and the two further bugs the new tests found rather than the reading did.
