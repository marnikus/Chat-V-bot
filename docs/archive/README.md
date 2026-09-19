# Archived docs — historical, not current

Every design, plan and root-cause doc this repository has produced, grouped by
the date and topic they were written for. **Nothing here is the spec.** The
current spec, invariants and flows live in
[`docs/current/SYSTEM_OF_RECORD.md`](../current/SYSTEM_OF_RECORD.md); the rules
live in [`docs/current/AGENT_RULES.md`](../current/AGENT_RULES.md).

An archived doc is true *as of the date in its folder name*. Do not edit one to
catch up with the code — write a new dated doc instead (RULE 17).

The dated groups below preserve design history; implementation status is recorded
in each round, not implied by the presence of a plan.

| Group | Docs | What it covers |
|---|---:|---|
| [`2026-09-19-round-i-seams/`](#2026-09-19-round-i-seams) | 2 | Next cycle: reviewed six-area seams/testability audit; only Area A authorized, first transport slice implemented, remaining gates explicit. |
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
| [`2026-09-13-ai-bot-chat/`](#2026-09-13-ai-bot-chat) | 6 | The AI Bot Chat window and the Grok Prompt Editor: the four-service + bridge design, the six-defect round, multi-provider settings with the variable library and the blank-media fix, named connections with prompt presets and the history scope, the settings-popup home with the dark-select rebuild, and the browsing-vs-choosing connection-picker redesign. |
| [`2026-09-13-round-f/`](#2026-09-13-round-f) | 1 | Round F's parameter-object step (F5): the abandoned `_v2` attempt it replaced, the in-place migration pattern, the 19 migrated signatures, and the seven `stores/` functions a frozen contract blocks. |
| [`2026-09-13-round-g-write-gate/`](#2026-09-13-round-g-write-gate) | 7 | Round G: the complete post-Round-F tail inventory with fresh measurements, the prioritised G1–G7 step plan, and the executed steps G1–G7 — the red suite at HEAD and the `WriteTurn` union fix (F3c), the two worst-file family splits under the lifted freezes, the flow/injector splits plus the ladder and constructor reductions, and the wide-parameter continuation that took the >4-param walker from 51 to its 18-entry floor, the test-debt step that took the three undo modules to 100% and paid the F6b module-wide mutation run, the hygiene step that zeroed the tree's cognitive-17 offenders and paid the rules file back inside its budget, and the backlog step that gave the JavaScript side its first coverage measurement, migrated all seven deferred stores wide-parameter offenders (the >4-param walker 18 → its documented 11-entry floor, the stores API baseline refreshed in-step), took `HistoryExportService` from 21 to 14 methods and split `StackBridge`/`ScrollParse` into wire facades plus cohesive parts with zero golden drift. |
| [`2026-09-13-rules-appendices/`](#2026-09-13-rules-appendices) | 1 | Detail moved out of [`docs/current/AGENT_RULES.md`](../current/AGENT_RULES.md) to keep it inside its §18.4 reading budget — RULE 19's remediation ladder and worked case studies. |
| [`2026-09-13-speed-multiplier/`](#2026-09-13-speed-multiplier) | 1 | The global wait-speed multiplier: one coefficient scaling every user-facing wait of a run, and why the semantics are global rather than positional. |
| [`2026-09-14-round-h/`](#2026-09-14-round-h) | 5 | Round H (plan only, not implemented): the 2026-09-14 re-measurement against the six metric categories, why the un-gated JavaScript frontend is now the biggest structural problem, and the four areas — frontend, backend/bridge spine, services/stores cohesion, verification — each with its own file ownership, steps, targets and owner decisions. |
| [`2026-09-14-round-h-area-d/`](#2026-09-14-round-h-area-d) | 1 | Round H Area D implementation (verification): mutation from 1 module to a platform measurement (widened job 159→910 reachable + second job over pure bot family), the RULE 8 double audit that would have caught FakeArchive.labels, a per-file coverage floor with ratchet so global average stops hiding message_injector_send.py at 21.1%, and baseline/doc currency (RULE 16 §16.3 re-quoted to 92.64/88.03, RULE 18.2 corrected). |

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

*1 doc.*

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

*3 docs.*

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

---

## 2026-09-13-round-f

Round F's wide-parameter step (F5), recorded on its own because the plan it replaced arrived from
another branch describing work that was never wired: eight of nine dataclasses with exactly one
reference (their own definition) and an `append_v2()` nobody called. This folder holds the corrected
plan — migrate in place, update every call site in the same commit, measure the metric afterwards —
and the record of the two passes that took the repo-wide count of >4-parameter functions from 70 to
51, with the seven `stores/` survivors itemised against the frozen contract that blocks each.

*1 doc.*

- [`F5_PARAMETER_OBJECTS.md`](2026-09-13-round-f/F5_PARAMETER_OBJECTS.md) — The parameter-object step: the `_v2` pattern that produced 230 dead lines and why it was rejected, the in-place migration pattern this repo follows instead, the 19 migrated signatures across two passes, the three traps a naive pass-through walks into (`_touch_cursor`'s deliberate field overrides, `_same_conversation`'s narrower object, the four facade twins a contract test keeps alive), and the seven-function floor the AREA B / AREA D golden files impose

---

## 2026-09-13-round-g-write-gate

Round F closed its eight steps; this folder inventories everything it left open — re-measured from
the tree rather than quoted from reports — and starts the round that works the list. Two findings
head it: the suite is **red at HEAD** (a config-split test that skips on a pristine clone meets the
`config/blocks.json` the squash-merge tracked, in a shape it never handled), and residual risk
**F3c** is the only open item that is a live product-bug class: `WriteTurn`'s single `held` flag
desyncs from the world gate's depth the moment two write transactions overlap on one connection,
after which every writer on that world waits 15 s and fails OPEN — the exact bug class the gate was
added for. Step G1 fixes both. Mid-round the owner lifted every AREA freeze (ruling F0, recorded
in the plan's §1c) and the round continued: G2 splits the two worst files, G3 the flow and
injector families plus two oversized constructors, and G4 lands the wide-parameter
continuation — the >4-param walker drops from 51 to its 18-entry floor — each step with its
own doc below; G5 then paid the test-debt batch, G6 the hygiene and docs
reconciliation, and G7 the backlog — the round is complete, every step executed.

*4 docs.*

- [`ROUND_G_DESIGN_2026-09-13.md`](2026-09-13-round-g-write-gate/ROUND_G_DESIGN_2026-09-13.md) — The full tail inventory with evidence per item (red baseline, F3c, the frozen five and the two contract-sanctioned split mechanisms the AREA D snapshot admits — base-class extraction and private-helper extraction — with an honest appraisal of what each can and cannot do for `chat_sync.py`, the unfrozen structural tail, the test-quality tail including the never-exercised `_migrated_entry`, and the hygiene/docs tail), the prioritisation that puts correctness before mass, the G1–G7 step plan with the F0 owner decision gating G2, and G1's executed design: the test redesigned around the production `BlockStore` and machine-independent invariants, and `WriteTurn` rebuilt as the union of a set of writer tasks — why a per-task *count* leaks (per-statement `begin`, per-commit `end`), why `drop()` still clears everything, and five tests of which the three that matter fail against the pre-fix flag version
- [`G2_CHAT_SYNC_SCROLL_PARSER_DESIGN_2026-09-13.md`](2026-09-13-round-g-write-gate/G2_CHAT_SYNC_SCROLL_PARSER_DESIGN_2026-09-13.md) — Step G2, executed: the two worst files in the tree became prefix families once ruling F0 lifted the AREA-B/D freezes — `backend/chat_sync.py` (807 LOC, MI 11.35) into a seam plus five siblings and `backend/scroll_parser.py` (706 LOC, the 532/39 `ScrollParser`) into a facade plus four, every function moved verbatim. The AREA-D golden was refreshed in-step with a conservation proof (10 ownership moves, 0 losses, identical payloads) and the blocks twin byte-identical; three forced test accommodations are enumerated with reasons — including the stores-import counter bump 40 → 42 that only the full suite's five-area walk can see — and the outcome table records 2808 passed with coverage at 90.94% line / 87.01% branch
- [`G3_FLOW_LADDER_CTOR_DESIGN_2026-09-13.md`](2026-09-13-round-g-write-gate/G3_FLOW_LADDER_CTOR_DESIGN_2026-09-13.md) — Step G3: the §16.5 design doc for the `Collector` landmine and three further targets — `services/db_deletion_flow.py` (509) into a seam plus three siblings; `backend/message_injector.py` (484) into a seam plus three, its 70-line typing ladder redesigned per §19.5 into a context dataclass, one shared acceptance check and three per-rung attempts with byte-identical wording; `Collector.__init__`'s 26-assignment counter block moved to `collector_states.init_run_counters` (no new method on the 40-method class); and `ScrollParse.__init__` rebuilt as a `_KNOB_CASTS` table plus a `locals()` loop with the RULE 3 wire signature untouched — proven by a HEAD parity run and a byte-identical block golden. Records the clone-baseline maintenance (the `_rep` pair moved with the split, one deletion-family header pair added) and the rules/notes reconciliation it owes
- [`G4_PARAM_OBJECTS_DESIGN_2026-09-13.md`](2026-09-13-round-g-write-gate/G4_PARAM_OBJECTS_DESIGN_2026-09-13.md) — Step G4, executed: the F5 parameter-object pattern continued outside `stores/` — eight waves take the >4-parameter walker from 51 down to its 18-entry floor (11 documented RULE 3 constraints, among them the nine block `__init__`s now carrying §16.4 `quality-override` comments on their def lines, plus the 7 deferred `stores/` offenders). Request objects land in `backend/parser_requests` and `backend/probe_requests`, `services/db_deletion_policy`, `services/wiring_requests`, `services/run/requests`, `services/history/requests` and `services/collector_states`; `BridgeContext` becomes a dataclass in place and `ApplicationLifecycle` takes an `AppDeps`; `ScrollParser` goes options-first. The AREA-D golden is refreshed under a conservation proof (removed = ∅, exactly the 14 approved payload changes, 9 added classes), the blocks twin stays byte-identical, the stores-import ledger records a sanctioned decrement 42 → 41, and the outcomes table records 2808 passed with coverage at 91.09% line / 87.06% branch
- [`G5_TEST_DEBT_DESIGN_2026-09-13.md`](2026-09-13-round-g-write-gate/G5_TEST_DEBT_DESIGN_2026-09-13.md) — Step G5, executed: the test-quality tail from §1e — 20 new tests (`tests/integration/services/test_undo_history_world_gaps.py`) take `undo_history.py`, `undo_world.py` and `undo_apply.py` to 100% line and branch and reduce the `undo_service.py` gap to the provably unreachable pair 159–160 (documented, not pragma'd); coverage rises to 91.30% line / 87.43% branch at 2 828 passed. F6b pays the runtime F6 declined to quote: the widened-selection mutmut run over all 1 141 `history_query.py` mutants scores 563 killed / 578 survived (49.3%) with a per-cluster triage (Class A: lines the narrow pre-commit selection never executes; Class B: weakly asserted; zero survivors in F6's narrow target functions) and records the full-suite run plus an edges-strengthening pass as Round H candidates. The `dbconn` rewind asymmetry stays parked pending an explicit owner ruling, with the recommended shape written down
- [`G6_HYGIENE_DESIGN_2026-09-13.md`](2026-09-13-round-g-write-gate/G6_HYGIENE_DESIGN_2026-09-13.md) — Step G6, executed: the hygiene ledger — three stale `ideal-size:` notes corrected to measured LOC and the other three measured accurate, the four pylint W0611 unused imports removed, both cognitive-17 offenders reduced per RULE 19 §19.5 (`bridge/router.py::_build_router_class` into its three named registration phases; `SettingsStore.get`'s defaults-tree restart into `_from_defaults`) leaving zero functions over the cognitive fail line tree-wide, the standing `handle_push`-never-awaited RuntimeWarning eliminated by awaiting the binding coroutine the CDP dispatcher owns, `AGENT_RULES.md` paid 763 → 728 lines by the §18.4 extract-first rule (RULE 19's ladder and case studies moved to the new rules-appendices appendix, every norm kept inline), and both doc maps redrawn
- [`G7_BACKLOG_DESIGN_2026-09-13.md`](2026-09-13-round-g-write-gate/G7_BACKLOG_DESIGN_2026-09-13.md) — Step G7, the backlog: the JS coverage instrumentation (`tools/metrics/js_coverage.py` — sourceURL-pragma mirror so V8 attributes the `new Function`/`vm`-eval'd frontend sources, UTF-16-correct offset mapping, union merge across the 28 Node tests) and its first measurement — 24 files / 10 109 LOC at **80.2%**, six files never loaded by any test, 12 embedded Python-side JS payloads (420 lines) inventoried but unreachable by V8, recorded in `reports/JS_COVERAGE_BASELINE_2026-09-13.md` with the ruling that this is a denominator, not a gate; plus the executed adjudication of the 7 deferred `stores/` wide-parameter offenders — all migrated (`LineIdentity`, `AppendRequest`, widened `PaneSignature`, `MediaRecoveryRequest`, `MediaOptions`; walker 18 → 11, the stores API baseline refreshed in-step under the F0 ruling, the import budget ledgered 41 → 44) — the `HistoryExportService` 21 → 14-method pass, and the cohesion passes: `StackBridge` 330/31 LCOM\* 0.89 → wire facade 122/23 0.667 + five parts, `ScrollParse` 300/14 0.92 → 150/7 0.778 + `ScrollRunPart` 0.545 with ZERO golden drift (step doc §2–§4)

---

## 2026-09-13-rules-appendices

The second rules-appendices group: detail moved out of
[`docs/current/AGENT_RULES.md`](../current/AGENT_RULES.md) to keep it inside its
§18.4 reading budget (the 2026-09-11 group holds the RULE 1 appendix).

- [`RULE19_REMEDIATION_LADDER.md`](2026-09-13-rules-appendices/RULE19_REMEDIATION_LADDER.md) — RULE 19's ASCII ladder and the worked case studies for every step (`db_deletion_flow`'s phase refusals, `actions/registry` dispatch, the lookup tables, the FTS5/`LIKE` back-end pair, `StackFacts`, `PersonPageRequest`, the two long-and-flat functions `_delete_unlocked` and `_run_type_strategies`, and G6's router phase-extraction) — extracted when the rules file was paid from 763 back to 728 lines
## 2026-09-13-ai-bot-chat

The AI Bot Chat window and the Grok Prompt Editor: a per-person window that loads only the current
day's messages, asks the Grok API for a suggested reply or a reaction analysis, and shows every
answer as a *pending* card behind an explicit ✅ / ❌ / 🔄 verification step. Approval only enables
"Send to Person"; nothing is delivered or labelled without a human click.

*6 docs.*

- [`AI_BOT_CHAT_DESIGN_2026-09-13.md`](2026-09-13-ai-bot-chat/AI_BOT_CHAT_DESIGN_2026-09-13.md) — Why the feature is four small `bot_*` service files plus one Qt bridge rather than slots on the ratcheted `HistoryBridge`, why the Prompt Editor is a separate grid window (layout v4) rather than a panel inside Bot Chat, and the one-active-label rule expressed as a single `set_for` write shared by the AI-confirm and manual-click paths. §4 carries the post-implementation size table, re-measured against the RULE 16 OWNED set.
- [`BOT_CHAT_DEFECTS_2026-09-13.md`](2026-09-13-ai-bot-chat/BOT_CHAT_DEFECTS_2026-09-13.md) — The defect round against the shipped feature, found by reading the new code against the repo's existing invariants rather than against its own tests. Six ordered by blast radius: the label store read off an attribute `HistoryService` does not have (labelling was dead in the app while green in the suite, because the archive *double* had invented the attribute — a test-design bug as much as a product one); a message could be delivered into whichever chat the browser happened to have open, the only irreversible act in the feature and the one `chat_sync` already guards for reads; the label write bypassed the global undo timeline, the Label Manager refresh and the People count; "no messages today" conflated a closed world with the archive's clock-derived day boundary; the API key was unreachable from the UI while the error named a field that did not exist; and one CC 9 parser. §Outcome records the execution, including the bridge split the method budget forced (the Prompt Editor is its own window, so it is now its own bridge) and the two further bugs the new tests found rather than the reading did.
- [`PROVIDERS_VARIABLES_MEDIA_2026-09-13.md`](2026-09-13-ai-bot-chat/PROVIDERS_VARIABLES_MEDIA_2026-09-13.md) — The third round: multi-provider AI settings (Grok + Google Gemini), the prompt variable library, and the bug where GIFs rendered as blank messages. The bug's root cause is the interesting one — Bot Chat had hand-written a second archive query and dropped the `media` join, so the fix was to delete it and read through `HistoryQuery.page` like every other window, then draw with the DB window's own `mediaNode`; the test doubles had to grow the REAL `HistoryQuery` before any of it could be proven. Providers are a data table rather than a class hierarchy (two APIs differing in four expressions), with Gemini's `finishReason` read so a safety refusal is reported as a refusal instead of an empty answer, and per-provider key storage so switching cannot delete a key or a template. The variable library also reverses an earlier mistake: an unknown placeholder used to make a template "unusable" and silently restore the shipped default, destroying the user's work as they typed — it is now a visible warning. §4 records the outcome, the bridge split RULE 16 forced, and the plaintext-key limitation stated rather than hidden.
- [`CONNECTIONS_PRESETS_SCOPE_2026-09-13.md`](2026-09-13-ai-bot-chat/CONNECTIONS_PRESETS_SCOPE_2026-09-13.md) — The fourth round, which mostly corrects a modelling mistake from the third: settings were keyed by *provider*, so a user could hold one Grok configuration, when what they actually want is "Grok grok-4.3" beside "Grok grok-2 (cheap)" beside "work Gemini". A **connection** is now a named instance of a provider, stored through the `named_*` CRUD the app already uses for stack presets, which buys atomic writes and restart persistence for free; the provider stays what it always was, a vendor wire format that is code. Round out: keys, models and endpoints move into their own AI Connections window (the Prompt Editor now only *chooses* a connection), prompt templates gain saved presets under the same storage, and the Bot Chat window gets a "today's messages only" checkbox that travels with every request — list, suggest, analyze and preview alike — because a scope that changed only what the user sees while the model read something else would be worse than no scope at all. Both scopes stay capped, and the window reports the cap, so a silently shortened history is never invisible.
- [`CONNECTIONS_POPUP_DARK_SELECT_2026-09-13.md`](2026-09-13-ai-bot-chat/CONNECTIONS_POPUP_DARK_SELECT_2026-09-13.md) — The fifth round, fixing what the fourth left half-done: connection *storage* had moved out of the Prompt Editor but a connection *chooser* stayed behind, so two windows could change which AI runs and the user had to guess which won. The editor now holds prompt controls only and the ⚙ popup is the single home for "which AI, which key, which model". Two smaller defects have the more interesting causes. Only Grok was selectable because a connection is user-created and a fresh install has none — Google was a provider the app supported and the UI could not reach, fixed by seeding one keyless row per provider (visible, flagged "no API key", refused by `client_for` until a key exists). And the dropdowns were white on a black app because no CSS can theme a native `<select>`: the open list is drawn by the OS. The fix was to stop using one — `dark-select.js` rebuilds the Bookmarks popup's own `.layout-menu` / `.lm-sub` classes as a shared component, so "matches Bookmarks" holds by construction rather than by two stylesheets kept in step by hand. The round also caught the ⚙ being wired by both modules at once, and a test-stub that handed every module a bare `<div>` — which is why no test had been able to notice any of it.
- [`CONNECTION_PICKER_REDESIGN_2026-09-13.md`](2026-09-13-ai-bot-chat/CONNECTION_PICKER_REDESIGN_2026-09-13.md) — The sixth round, and the first whose core defect is conceptual rather than technical: the popup could not tell *browsing* from *choosing*. Clicking a connection to look at it was read by the app as committing to it, so a user comparing three connections had already changed the answer by the time they finished reading. The fix names the two states apart — `viewed` is what the form shows, `active` is what prompts run on — and gives the second exactly one mover: **Select**, the only button that closes on confirm. The same confusion had a second victim in presets, where choosing and applying were one gesture; they are now a highlight and a separate **Apply Preset Settings** button that writes the fields and leaves them editable, because a value the app filled in silently is a value the user cannot check. Also here: a two-column master/detail layout, one `.ui-btn` component so a row of buttons differs only in semantic colour, and Kimi — which cost a single row in the `PROVIDERS` table, the payoff of that table existing. Adding it broke three unrelated tests that had hardcoded the provider list, which is its own small lesson about what a test should derive rather than restate.

## 2026-09-13-speed-multiplier

The SPEED_MULTIPLIER action block and the `actions/speed.py` helpers behind it: one float coefficient
(1.0 = normal, 0.5 = 2x faster, 2.0 = 2x slower) scaling every user-facing wait of the run — pre-delays,
pauses, visual-confirmation holds, page waits, scroll pacing, attach verification and history chunk pauses.
The semantics are global (last enabled SPEED block wins, resolved at run start) rather than positional,
because Scroll & Parse runs at cycle level before the per-user loop, so "blocks below it" could never scale
the longest waits of all.

*1 doc.*

- [`SPEED_MULTIPLIER_DESIGN_2026-09-13.md`](2026-09-13-speed-multiplier/SPEED_MULTIPLIER_DESIGN_2026-09-13.md) — The semantics decision and its rationale, the full inventory of which waits scale and which do not (stop slices, retry backoff, protocol gaps and cosmetic highlight durations are out of scope), the rejected `ScrollOptions.speed_multiplier` field (it would force a 20th parameter onto a RULE 16.5 legacy constructor), and the RULE 16 measurements.

---

## 2026-09-14-round-h

Round H — the plan for the round after G, written from a fresh measurement of the
whole tree against the six metric categories the owner works from (complexity,
size/volume, coupling/cohesion, tests, smells, maintainability). **Plan only: no
production code was changed to produce it.** The headline finding is that the
Python side has been driven to a clean state (0 functions over CC 10, 0 over
cognitive 15, mean MI 68.05, 3,172 tests green, mutation 99.37%) while the
**JavaScript frontend — 30 files / 11,865 lines — sits outside every size gate
the repository has**, holding the largest file (1,361 lines), the largest class
(69 methods) and the largest function (205 lines) in the project.

*5 docs.*

- [`ROUND_H_DESIGN_2026-09-14.md`](2026-09-14-round-h/ROUND_H_DESIGN_2026-09-14.md) — The prioritisation: the frontend first (un-gated mass and the weakest verification floor), then the backend/bridge spine (`bridge/history_bridge.py` MI 24.9 / 66.4% covered and `backend/history_query.py` 601 lines), then services/stores cohesion (17 genuinely incoherent classes as distinct from 7 delegation facades), then verification debt. Defines the four areas, their disjoint file ownership, the frozen interfaces between them, the shared-file protocol for `tools/metrics/rule16_gate.py`, the three owner decisions the evidence forces, and what is deliberately out of scope.
- [`AREA_A_FRONTEND_JS_DESIGN_2026-09-14.md`](2026-09-14-round-h/AREA_A_FRONTEND_JS_DESIGN_2026-09-14.md) — Area A, all 30 JS files measured: the two god objects (`SashGrid` 1,331 LOC / 69 methods, `StackDnD` 1,168 / 58, `_showConfig` 180 LOC), the 50 functions over 30 lines (9.2% against Python's 1.7%), the six files never loaded by any test (1,220 LOC including `app.js`), and the six steps — a JS size tool, a JS gate mirroring RULE 16, the two splits, harnesses for the never-loaded files, and the coverage lift — with the load-order constraint `ui/index.html` imposes on every split.
- [`AREA_B_BACKEND_BRIDGE_DESIGN_2026-09-14.md`](2026-09-14-round-h/AREA_B_BACKEND_BRIDGE_DESIGN_2026-09-14.md) — Area B: the four files over 500 lines in `backend/`+`bridge/`, the four-way responsibility split of `HistoryBridge` (reads / deletions / media / settings) with the QWebChannel slot surface kept on the facade, the search-vs-projection split of `history_query.py` plus its last mutation survivor, and the coverage-first steps for the two files the suite reaches worst (`history_bridge` 66.4%, `cdp_client` 65.2%).
- [`AREA_C_SERVICES_STORES_DESIGN_2026-09-14.md`](2026-09-14-round-h/AREA_C_SERVICES_STORES_DESIGN_2026-09-14.md) — Area C: the measured separation between the 7 delegation facades (73–86% one-line methods — do not split) and the 17 genuinely incoherent classes; the run family, the undo family and the DB/world family decomposed by phase and by operation; the four store planners (cohesive but 306–407 LOC) extracted by named helper module; and the dense-file pass that a lines-only sort cannot see (`window_preset_service` MI 30.6 in 326 lines, `run/progress` 31.0, `history/mutate` 34.9).
- [`AREA_D_VERIFICATION_DESIGN_2026-09-14.md`](2026-09-14-round-h/AREA_D_VERIFICATION_DESIGN_2026-09-14.md) — Area D, no production files: mutation from one module to a platform measurement (the second job, and the measured 159 → 910 reachable-mutant widening sequenced after Area B), the RULE 8 double audit that would have caught the fake which hid the dead label store, a per-file coverage floor with a ratchet so the global average stops hiding `message_injector_send.py` at 26.3%, and the baseline/document currency work (RULE 16 §16.3 still quotes the 2026-09-10 floors).

---

## 2026-09-14-round-h-area-d

Round H Area D implementation — verification debt closed without touching production.

*1 doc.*

- [`AREA_D_IMPLEMENTATION_2026-09-14.md`](2026-09-14-round-h-area-d/AREA_D_IMPLEMENTATION_2026-09-14.md) — What landed: H-D1 mutation platform (job1 widened 159→910 reachable + job2 over pure bot family 9 files, report `reports/MUTATION_REPORT_2026-09-14.md` with explicit reachable arithmetic), H-D2 double audit (`tools/metrics/double_audit.py` + `tests/test_double_audit.py`, FakeArchive.labels pinned), H-D3 per-file floor (`file_coverage_floor.py` 208 lines + ratchet 15 files, test `test_file_coverage_floor.py`), H-D4 baseline/doc currency (AGENT_RULES §16.3 re-quoted 90.44/84.38→92.64/88.03, §18.2 corrected 186→208 files and 507→511, doc maps updated), H-D5 smell ratchet (`smell_inventory.py` 7 vulture findings with delete/protocol disposition, 13 clone groups, 4 boundary crossings, 11 wide params). All tools respect RULE 18 ideals and RULE 16 gates; verification battery included.


## 2026-09-19-round-i-seams

- [`ROUND_I_DESIGN_2026-09-19.md`](2026-09-19-round-i-seams/ROUND_I_DESIGN_2026-09-19.md) — corrected audit, six-area roadmap, ownership/dependencies and Area A exit gates. B–F are proposals only.
- [`AREA_A_IMPLEMENTATION_2026-09-19.md`](2026-09-19-round-i-seams/AREA_A_IMPLEMENTATION_2026-09-19.md) — first transport slice, tests, baseline failures and pending work; not full Area A completion.
