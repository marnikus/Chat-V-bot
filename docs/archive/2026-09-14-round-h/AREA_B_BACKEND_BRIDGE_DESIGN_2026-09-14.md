# Area B design — the backend/bridge spine: the worst maintainability in the project

Round H · 2026-09-14 · owns `backend/**/*.py` (except `backend/js/`) and `bridge/**/*.py`
Part of [`ROUND_H_DESIGN_2026-09-14.md`](ROUND_H_DESIGN_2026-09-14.md).
Source of numbers: [`reports/CODE_QUALITY_METRICS_2026-09-14.md`](../../../reports/CODE_QUALITY_METRICS_2026-09-14.md),
`/tmp/audit_h.json`, `/tmp/coverage_h.json`. **Plan only — nothing implemented.**

## 1. Why this area is second

Area A is bigger, but this is where maintainability risk concentrates on
code the application depends on every session: 62 files / 10,326 lines, **4 of
the project's 4 files over 500 lines**, and the **worst MI in the tree** —
`bridge/history_bridge.py` at 24.9 against a project mean of 68.05. Its coverage
is also the worst among load-bearing modules (66.4%): the file the UI talks to
for every archive operation is the file the suite reaches least.

The three problems — size, maintainability, coverage — overlap on the same
files, which is what makes this a coherent area rather than a list.

## 2. Measured state

### 2a. Files over 300 lines in `backend/` + `bridge/`

| Lines | MI | Coverage | Class shape | File |
|---:|---:|---:|---|---|
| 601 | 35.3 | 97.8% | `HistoryQuery` 310 / 14 / 0.74 · `PersonPageRequest` 97 / 7 | `backend/history_query.py` |
| 544 | **24.9** | **66.4%** | `HistoryBridge` 467 / 31 / 0.86 | `bridge/history_bridge.py` |
| 514 | 54.9 | 96.8% | 5 embedded JS payloads, 198 lines | `backend/dom_highlight.py` |
| 511 | 40.9 | 85.8% | `ConfigManager` 177 / 20 / 0.87 | `backend/config_manager.py` |
| 486 | 44.2 | 100% | `Router.__init__` 8 params · `_build_router_class` 51 LOC | `bridge/router.py` |
| 474 | 46.1 | 91.7% | 53-line JS payload + dialog path | `backend/media_handler.py` |
| 426 | 40.9 | 90.7% | `ChatParser` 133 / 13 / **0.94** | `backend/chat_parser.py` |
| 333 | 39.7 | — | Round G split: façade + 5 parts | `bridge/stack_bridge_parts.py` |
| 332 | 37.5 | — | | `bridge/file_bridge.py` |
| 331 | 36.7 | **65.2%** | `CDPClient` 208 / 21 / 0.91 | `backend/cdp_client.py` |

### 2b. The two step-one targets, in detail

**`bridge/history_bridge.py`** — module docstring: *"the message archive: reads,
deletions, media, clipboard"*, and the file carries an `ideal-size:` note
pinning the `HistoryBridge` ratchet (467 LOC / 44 methods in `rule16_gate.py`).
The 31 methods sort into four clean responsibilities:

| Group | Members | LOC |
|---|---|---:|
| reads | `history_open`, `history_page` + `_history_page` 22, `history_search` + `_history_search` 15, `history_stats`, `userdb_page` 17, `userdb_stats`, `_person_request` 16 | ~135 |
| deletions | `history_delete_person` **44**, `history_clear_person` **38**, `history_delete_message` **31**, `history_purge_deleted` 15, `history_restore_person` 12, `history_merge` 12, `_people_snapshot`/`_refresh_people` | ~165 |
| media & clipboard | `media_path`, `media_restore`, `media_folder`, `open_media_folder` 15, `copy_media` 18, `copy_text`, `_to_clipboard` 17, `_copy_file_to` 14, `_qt_clipboard` 11 | ~110 |
| settings | `get_history_settings`, `save_history_settings`, `detect_my_nick` | ~27 |

**`backend/history_query.py`** — the largest file in the project (601). Two
responsibilities are visible in the layout: the FTS/LIKE **search back-end**
(`_search` 49, `_fts_query`, `_like_escape`, `_snippet`) and the **row
projection** (`_person_item` 19, `_apply_specs`, `_item_media` 15, `_stat_int`,
`_day_bounds` 15) mixed into `HistoryQuery` (310 / 14 / 0.74) beside
`page` 53 / `around` 26 / stats. It is also the module the mutation job measures,
and it is where the last surviving mutant lives (`HistoryQuery._my_nicks`,
mutant 7).

## 3. Steps

### H-B1 — `bridge/history_bridge.py` 544 → wire facade + 4 parts

Same pattern Round F/G used for `stores/history_repo.py` and
`services/db_deletion*`, and the one `StackBridge`/`ScrollParse` used in G7:

```
bridge/history_bridge.py            # façade: EVERY @Slot kept, bodies delegate
bridge/history_bridge_read.py       #   ~150 lines — open/page/search/stats/userdb
bridge/history_bridge_delete.py     #   ~180 lines — person/message delete, clear, purge, restore, merge
bridge/history_bridge_media.py      #   ~150 lines — media paths, folder, copy, clipboard helpers
bridge/history_bridge_settings.py   #   ~60 lines  — history settings, detect_my_nick
```

Contract rules:

* **Every `@Slot` name and signature stays on `HistoryBridge`** — the QWebChannel
  wire surface is pinned by the frontend (`bridge/history_bridge.js` callers in
  `ui/js/history-*.js`, and `tests/test_history_bridge.py`). Properties and
  signals stay too. The facade may shrink to ~15 substantive methods because the
  bodies move, and the `RATCHET` entry is lowered in the same commit.
* Parts receive the bridge as their host (the `self.p._x` pattern Round G
  established in `backend/scroll_parser_*`), or as an explicit narrow protocol.
* **Tests first.** The three delete slots are the least covered 113 lines in the
  file (file coverage 66.4%): write the missing-cancel/refusal/undo-ticket tests
  against the *existing* code before moving it (§16.5: *"Touch a hotspot only
  with tests that lock current behaviour first"*).

Targets: file ≤ 200 lines, each part ≤ 200, MI ≥ 45 (from 24.9), coverage ≥ 90%
(from 66.4%), no function > 30 LOC (the 44/38/31 slots stand).

### H-B2 — `backend/history_query.py` 601 → three modules, one survivor closed

```
backend/history_query.py          # façade + HistoryQuery's page/around/stats/list_persons
backend/history_query_search.py   # FTS/LIKE back-end: _search, _fts_query, _like_escape, _snippet
backend/history_query_rows.py     # row → JSON: _person_item, _apply_specs, _item_media, _stat_int, _day_bounds
```

* Private helpers may move freely: `tools/metrics/dump_public_api.py` skips
  `_`-prefixed names, and the F0 ruling of 2026-09-13 lifted the AREA-D freeze —
  but the module qualname `backend.history_query` must remain a *file* (packages
  are skipped by the dumper), which this split preserves.
* Close `_my_nicks` mutant 7 with a test that fails on the mutant (the mutation
  job already selects the sort-path suite; add the case where it belongs).
* Re-pin the `RATCHET` row if `HistoryQuery`'s LOC/method counts change (they
  should fall, so the ratchet tightens to the new measured values).

Targets: facade ≤ 350 lines; `HistoryQuery` ≤ 10 methods; MI ≥ 50.

### H-B3 — `backend/config_manager.py` 511 → defaults+merge / IO / migration

`ConfigManager` (177 / 20 / 0.87) mixes: reading `config/*.json`, merging over
shipped defaults, migrating old shapes, validating, and notifying. Split by
responsibility, keeping the class as the façade the app constructs. Coverage is
85.8% — the migration branches are the gap.

Target: ≤ 300 lines, `ConfigManager` ≤ 15 methods, coverage ≥ 90%.

### H-B4 — `backend/dom_highlight.py` 514 → payload module

Five embedded JS payloads (69 + 35 + 21 + 62 + 11 = 198 lines at lines 39/203/242/267/403) sit
inside Python control flow. Move them into `backend/dom_highlight_js.py` as
module-level constants — §16.1.5's exception exists so payload *length* does not
force a split of the builder, not so payloads live in the middle of behaviour.
The Python side keeps its CC/nesting budget.

Target: ≤ 300 lines of Python; the payload module carries the `ideal-size:` note
for the literal it hosts.

### H-B5 — the remainder of the 400-line band

* `bridge/router.py` 486 / MI 44.2 — `Router.__init__` takes **8 params**
  (§19.4: parameter object) and `_build_router_class` (51 LOC) already got its
  three registration phases in G6; the constructor is what is left. It is the
  project's most dependent module (Ce 20, I 0.95), so this is the one place a
  signature change ripples — do it with the `AppDeps`/`BridgeContext` objects
  G4 introduced rather than a new one.
* `backend/media_handler.py` 474 / MI 46.1 — the 53-line JS payload joins
  `dom_highlight_js.py`'s pattern; the dialog-driving Python splits from the
  attachment flow.
* `backend/chat_parser.py` 426 / `ChatParser` LCOM **0.94** — parsing and
  settle/timing policy (`settle_after_top` 31 LOC) are different jobs sharing a
  class.

### H-B6 — `backend/cdp_client.py` 331 / MI 36.7 / coverage 65.2%

Every CDP call in the application goes through this file, and a third of its
statements are never executed by the suite. Split transport (`connect`,
`_receive_loop`, `send`, `add_binding`, script injection) from event dispatch
(`_dispatch_event`, `off_event`, listener tables) — and write the missing tests
**first**, because the split is otherwise an unverifiable rewrite of the
transport everyone depends on.

Target: coverage ≥ 85%; `CDPClient` ≤ 15 methods.

## 4. Sequencing inside the area

1. H-B1 and H-B6 are the two with a *coverage* problem — tests first, split
   second. They also carry the most risk.
2. H-B2 unblocks the mutation job's widening (Area D, H-D1) and is independent
   of H-B1.
3. H-B3/H-B4/H-B5 are mechanical splits; they can land in any order, one commit
   each, each with its own RULE 18 re-measure.

## 5. Verification battery (every step)

```bash
.venv/bin/python tools/metrics/current_audit.py > /tmp/audit_b.json   # MI, LOC, LCOM
.venv/bin/python tools/metrics/rule16_gate.py --with-clones           # ratchet rows lowered in-step
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/python -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
for f in tests/test_*.js; do node "$f"; done                          # bridge slots are JS-called
```

Plus, for a split that touches a pinned surface
(`history_bridge`'s slots, `router`'s constructor): the corresponding
`dump_public_api`/`stores_api` golden is refreshed **inside the same commit**,
with the diff justified here (§16.2's anti-gaming discipline applies; a lifted
freeze is not a licence to shrink assertions). Note `bridge/` already carries a
frozen `CLONE_BASELINE` group with `db_bridge.py` (shared import header) — a
split that copies the header into a new file joins that group and must be
checked with `--with-clones`.

## 6. Cross-area notes

* **Area C calls into this area** and vice versa: `stores/history_*` (C) is what
  `HistoryQuery` (B) queries; `bridge/undo_bridge.py` (B) drives
  `services/undo_service.py` (C). **Frozen interfaces:** `HistoryQuery`'s public
  method signatures, `HistoryQueryService`/`store` API, and
  `UndoService.push/undo/redo/apply_command/attach` may not change shape in
  either area this round. Internal extraction only.
* `bridge/bot_*.py` and `services/bot_*.py` are split across areas (bridge files
  here, service files in C). They are already inside the size ideals (73–147
  LOC) and are **not** targets.
* `tools/metrics/rule16_gate.py`'s `OWNED`/`RATCHET`/`SMELL_FILES` rows for
  this area's functions are edited here, in the commit that renames them.
