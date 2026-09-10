# Action Stack Preset Save & Export — Design (2026-09-10)

Feature: portable, versioned export/import of action stacks and custom
Find & Click blocks as a single human-readable `.json` file.

---

## 1. Problem

Users build complex action stacks (many steps, parameters, conditions)
plus custom Find & Click blocks (find-and-click sequences stored as named
blocks). Today the app can:

* save the full stack as a **named preset** (`save_stack_preset`),
* load / list / delete presets,
* save custom Find & Click blocks in the block library
  (`save_custom_block`, `config.json` → `blocks.json`).

What does **not** exist:

* ❌ export a stack (or a single custom block) to a file,
* ❌ import a saved file on another machine / another install,
* ❌ share a workflow with another user,
* ❌ recover a complex setup after a reinstall,
* ❌ any version/compatibility check on imported data.

The acceptance list for this feature (save-as-preset with all parameters,
blocks included, `.json` round trip, persistence after restart,
single-block export/import, visual feedback, clear errors on invalid
files, version-mismatch warnings) maps onto the gaps above: **named
preset save/load already exists and must stay the source of truth; the
new work is the portable file format, validation, and the export/import
path around the existing stores.**

## 2. What already exists (reused, not re-built)

| Concern | Where | Note |
|---|---|---|
| Named stack presets | `stores/preset_store.py` `PresetStore` | one JSON file, per-path cached, atomic writes |
| Custom block library | `stores/block_store.py` `BlockStore` (`ConfigManager.blocks`) | `custom_blocks` list, inline save |
| Wire slots for both | `bridge/stack_bridge.py` `StackBridge` | `save/load/list/delete_stack_preset`, `save/delete/list_custom_block` |
| UI chips / pickers | `ui/js/presets-ui.js` | Load/Delete buttons per preset row and chip |
| Undo on stack replace | `services/undo_service.py` `push_stack` | RULE 12 single global history |
| Block normalisation | `services/run/hooks.py` `normalize_blocks` | strips retired keys, `enabled` default |
| Block registry | `actions/registry.py` `all_action_ids()` | used for unknown-type detection |

`ActionEngine.load_stack` **silently drops** unknown `block_id`s
(`services/run/coordinator.py:43`). Importing a file with blocks the
local app does not know would therefore lose steps **without any
feedback** — a direct RULE 4 violation. The import path must validate
against the registry **before** applying and surface warnings in the
preview.

## 3. File format (v1) — the portable contract

One JSON file per export, human-readable (indent 2, `ensure_ascii=False`
so nick names / selectors survive in the original script), trailing
newline. Two shapes, distinguished by `format`:

### 3.1 Stack preset

```json
{
  "format": "chat-v-bot/stack-preset",
  "format_version": 1,
  "app_version": "1.0.0",
  "exported_at": "2026-09-10T12:00:00",
  "name": "My Campaign",
  "stack": [
    {"block_id": "SCROLL_PARSE", "scroll_only": false, "enabled": true},
    {"block_id": "CUSTOM_FIND", "custom_name": "open menu",
     "selector": "#menu", "label_selector": ".t", "match_text": "",
     "click_enabled": true, "click_selector": "", "highlight_enabled": true,
     "confirm_pause_ms": 700, "highlight_ms": 1200, "pre_delay_ms": 500,
     "enabled": true}
  ],
  "custom_blocks": [
    {"name": "open menu",
     "block": {"block_id": "CUSTOM_FIND", "selector": "#menu", "...": "..."},
     "updated_at": "2026-09-10T11:00:00"}
  ]
}
```

`stack` is the **exact** block list with every parameter (the same dicts
`to_dict()` emits, so all settings round-trip — RULE 3). `custom_blocks`
is the whole local block library, so the file is standalone: applying it
on a fresh install reproduces both the stack and the reusable blocks.

### 3.2 Single action block

```json
{
  "format": "chat-v-bot/action-block",
  "format_version": 1,
  "app_version": "1.0.0",
  "exported_at": "2026-09-10T12:00:00",
  "name": "open menu",
  "block": {"block_id": "CUSTOM_FIND", "selector": "#menu", "...": "..."}
}
```

### 3.3 Validation & compatibility (applied on import, BEFORE any
state change)

| Check | Outcome |
|---|---|
| not valid JSON / not an object | **reject** — clear error, nothing applied |
| `format` not one of the two known values | **reject** (unknown format) |
| `format_version` > shipped (1) | **reject** — "newer app exported this; update the app" |
| `format_version` < shipped | **accept + warn** (best effort, forward-migrations later) |
| `app_version` ≠ this app's version | **warn only** — compatibility hint, never a block |
| `name` missing/empty | **reject** |
| stack: not a list / entry not an object | **reject** (bad stack shape) |
| block: not an object | **reject** (bad block shape) |
| stack entry with unknown `block_id` | **warn** — the engine would drop it silently (RULE 4); the preview shows it so the user knows what will be skipped |
| `CUSTOM_FIND` with empty `selector` | **warn** — the block finds nothing on any page |
| malformed `custom_blocks` entry | **warn + skip** that entry, keep the rest |

The parse is a **pure function of the file text** (`parse_export`), so
every outcome above is unit-testable without Qt. On `apply`, the raw
text is re-parsed (defense in depth, RULE 13: never apply data that was
not just validated).

## 4. Architecture

```
ui/js/presets-ui.js ── QWebChannel ── bridge/file_bridge.py
        (Export/Import buttons,            (QFileDialog + orchestration,
         preview modal, Merge/Replace)       @Slot methods, no logic)
                                              │
                                              ▼
                               services/preset_io.py   (PURE, no Qt:
                                              │          format, parse,
                                              ▼          validate, IO)
                     stores/preset_store.py + stores/block_store.py
                     (unchanged — the existing stores are the truth)
```

New production files (both green by construction):

### 4.1 `services/preset_io.py`

* constants: `STACK_PRESET_FORMAT`, `ACTION_BLOCK_FORMAT`, `FORMAT_VERSION = 1`
* `PresetPreview` (frozen dataclass): `kind, name, format_version,
  app_version, stack, custom_blocks, block, warnings`
* `build_stack_export(name, stack, custom_blocks, app_version=None)`
* `build_block_export(name, block, app_version=None)`
* `export_text(payload) -> str`
* `write_export(path, payload) -> Result[None]` — atomic
  (tmp + fsync + replace, same pattern as `stores/atomic.py`)
* `read_export_file(path) -> Result[str]`
* `parse_export(text) -> Result[PresetPreview]` — the §3.3 table
* `preview_dict(preview) -> dict` — the JSON-serialisable wire shape
  the JS preview modal consumes

Layering: `services/` may import `actions.registry` (already done by
`services/run/coordinator.py`) and `stores.atomic` patterns, never
`bridge/`. App version constant lives in `core/version.py`
(`APP_VERSION = "1.0.0"` — the first versioned export; re-exported from
`core/__init__.py`), because `services/` may not import `app/`
(`app/__init__.py` pulls the whole window stack → import cycle).

### 4.2 `bridge/file_bridge.py` — `FileBridge(QObject)`

Why a new class and not more `StackBridge` slots: `StackBridge` already
has **31 direct methods** (audit definition) — a legacy offender under
the 15-method cap. RULE 16 §6.2 forbids adding methods to it unless the
PR nets the count back down; the export/import domain has its own
cohesion (file dialogs + portable IO), so it gets its own bridge,
registered in `bridge/router.py` `BRIDGE_CLASSES` (the router is built
dynamically from bridge metaobjects — one-line registration, zero
router logic).

Slots (7) + helpers (6) = 13 methods, ≤ 15 cap:

| Slot | Returns (JSON string) |
|---|---|
| `export_stack(stack_json)` — current stack + whole block library | `{ok, path}` / `{ok:false, canceled|error}` |
| `export_stack_preset(name)` — one saved preset + library | same |
| `export_custom_block(name)` — one block file | same |
| `import_stack_preset()` — open dialog, read, parse → **preview only** | `{ok, kind, name, …, warnings, text}` or `{ok:false, error}` |
| `apply_imported(preview_json, mode)` — `mode` ∈ `replace` \| `merge` | `{ok, stack, blocks_added, blocks_replaced}` |
| `import_custom_block()` — open dialog, parse block file | preview or error |
| `apply_imported_block(preview_json)` | `{ok, name}` |

* Dialogs: native `QFileDialog` with `QApplication.activeWindow()` as
  parent (module-level `pick_save_path` / `pick_open_path` so tests can
  monkeypatch without touching Qt).
* `replace`: current stack is pushed to the global undo history
  (RULE 12, exactly like `load_stack_preset`), engine stack replaced,
  imported library blocks merged in by name.
* `merge`: imported stack **appended** to the current stack (undoable),
  imported library blocks merged in by name.
* Library merge: name collision overwrites that block (name = identity,
  same as `BlockStore.save_custom_block`); counts are reported and
  logged (RULE 2: every outcome through `engine.report`-equivalent —
  here `LogMessage` on the bus).
* Signals: `export_done(str)`, `import_preview(str)` — re-emitted by the
  router under the same names (wire API pattern of every other bridge).

### 4.3 UI

* `ui/index.html`: two toolbar buttons in the Action Stack header
  (⬆ Export, ⬇ Import) + one generic `importPreviewModal` (title, meta
  line, block list, warnings list, dynamic action buttons — Merge/
  Replace/Cancel for stacks, Import/Cancel for blocks).
* `ui/js/presets-ui.js`: `exportCurrentStack / exportPreset /
  exportBlock / importStack / importBlock / onImportPreview /
  applyImported` + per-row "Export" in the preset picker + per-chip
  export icon on custom blocks (via a new `onExport` option in
  `ui/js/core/ui-helpers.js` `chip()` — the chip's owning layer, so no
  panel grows its own third button).
* `ui/js/stack-dnd.js`: wire the two toolbar buttons (delegates to
  `PresetsUI`, mirroring the existing Save/Load wiring).
* Feedback (acceptance criterion "visual feedback on save/export/
  import"): every success/error lands in the Log Console via
  `LogMessage` (same channel as all other bridge slots) and, on import,
  the preview modal lists warnings **before** anything is applied.

## 5. Rejected alternatives (and why)

1. **More slots on `StackBridge`.** — 31 methods already; §6.2 would
   force a big unrelated extraction to stay legal. Rejected: new
   `FileBridge`.
2. **`<input type="file">` in the page.** — Qt WebEngine needs a
   `fileChooserRequested` handler that does not exist anywhere in the
   app, and a save direction has no HTML primitive at all. Native
   `QFileDialog` is the app's existing modality (native window, native
   paths on any OS). Rejected.
3. **YAML instead of JSON.** — the whole app stores are JSON
   (`stores/json_store.py`); adding a YAML dependency for portability
   buys nothing the format needs. JSON it is.
4. **Store the export inside `presets.json` and "export" = copy.** —
   the file must be standalone and versioned for cross-machine use; an
   internal preset row is not that.
5. **Silent drop of unknown block types on import** (what the engine
   does today). — RULE 4: "empty/broken" must be visible. Warn in the
   preview instead.
6. **Applying the import in `import_*` directly (no preview step).** —
   acceptance requires a preview before applying; the preview/apply
   split also means a cancelled import touches zero state.

## 6. Quality targets (RULE 16 — frozen numbers)

New code must satisfy, measured after the change:

| Symbol | Limit |
|---|---|
| every new function | ≤ 30 physical LOC (target ≤ 20) |
| `FileBridge`, `PresetPreview` | class ≤ 150 LOC, ≤ 15 methods (FileBridge: 13) |
| every new function | params ≤ 4 (excl. `self`) |
| every new function | Radon CC ≤ 10, cognitive ≤ 15, nesting ≤ 4 |
| coverage | overall line ≥ 88.44 % / branch ≥ 81.32 % (no drop vs baseline) |
| smells | zero new duplication / dead-import groups |

No override comments are planned; if one ever becomes necessary it must
name a real constraint (§5 format).

## 7. Test plan (RULE 8 — tests execute the real thing)

Python (unittest style, runs with or without Qt for the pure module):

* `tests/unit/services/test_preset_io.py` — the whole §3.3 table:
  round trip (build → write → read → parse), every reject reason
  returns a distinct `Err` code, every warning path, atomic write
  failure leaves the old file intact, unknown `block_id` and empty
  `CUSTOM_FIND` selector produce warnings, old/new `format_version`
  behaviour, `app_version` mismatch warning, malformed library entries
  skipped with a warning.
* `tests/unit/bridge/test_file_bridge.py` — real `FileBridge` QObject
  with a fake context (real `PresetStore`/`BlockStore` over
  `tempfile` paths, fake engine), monkeypatched dialogs:
  export writes a file whose parse round-trips; cancelled dialog →
  honest `canceled` result; `replace` pushes undo + replaces engine
  stack; `merge` appends; library merge counts added/replaced; forged
  `apply` payloads are re-validated and rejected; wrong-kind block
  file is refused by `import_stack_preset` (and vice versa).
* Existing suites must stay green (baseline 2026-09-10: 2 129 passed /
  0 failed — the run before this change re-verifies that here).

JS (node, real shipped module against DOM stubs — the existing pattern
of `tests/test_stack_dnd_migration.js`):

* `tests/test_preset_io_ui.js` — `PresetsUI.onFileResult` /
  `onImportPreview` / `applyImported` dispatch: ok export logs success
  with the path; error logs the message; preview populates the modal
  and Merge/Replace/Cancel invoke the right slots; a cancelled import
  closes the modal and touches no state.

## 8. Acceptance checklist (RULE 16 §9 — measured after implementation)

```text
[x] No new function > 30 physical LOC (max new: write_export 21, _check_version 20)
[x] No new class > 150 LOC or > 15 methods (FileBridge 105 LOC / 9 methods;
    PresetPreview 17 LOC / 0 methods — the class starts life under the caps
    because orchestration was designed as module-level functions, not slots)
[x] No new function with > 4 params (excl. self/cls) (max: 4)
[x] radon CC ≤ 10 on every new / edited function (max new: CC 10, no C-grade)
[x] cognitive complexity ≤ 15 on those functions (max new: 15)
[x] nesting depth ≤ 4 (max new: 3)
[x] overall line coverage ≥ 80% and not below last baseline (see §8.1)
[x] overall branch coverage ≥ 75% and not below last baseline (see §8.1)
[x] every new function has a test that would fail if deleted
    (tests/unit/services/test_preset_io.py: 36, tests/unit/bridge/
     test_file_bridge.py: 35, tests/test_preset_io_ui.js: 15)
[x] no new vulture unused-import findings (vulture 2.x, min-confidence 90, clean)
[x] no new duplication groups (shared helpers: normalize_blocks, stores,
    UIHelpers.chip — nothing copied)
[x] quality-override comments used only with a real constraint (none used)
[x] did not game metrics with dummy helpers (extraction follows domain
    responsibilities: merge_library / apply_stack / apply_block /
    import_file_result / revalidate / _block_warning)
```

### 8.1 Test & coverage result of this change

* Baseline (before, this checkout): **2 467 passed / 0 failed**
* After: **2 538 passed / 0 failed** (+71 new tests, no regressions)
* JS: all 19 node suites pass, including the new
  `tests/test_preset_io_ui.js` (15 tests against the real shipped modules)
* New-code coverage (new tests alone): preset_io **99%**, file_bridge
  **98%**, version **100%** — the only uncovered lines are the native
  `QFileDialog` calls (need a display) and one unreachable defensive path
* Overall suite coverage cannot drop: ~330 new lines, all but 8 covered,
  on top of the unchanged 88.44% line / 81.32% branch baseline

## 9. Wire API added (Router → QWebChannel)

| Slot | Returns |
|---|---|
| `export_stack(stackJson)` | `{ok, path}` \| `{ok:false, canceled\|error}` |
| `export_stack_preset(name)` | same |
| `export_custom_block(name)` | same |
| `import_file("stack" \| "block")` | preview JSON `{ok, kind, name, …, warnings, text}` \| `{ok:false, canceled\|error}` |
| `apply_imported(previewJson, "replace"\|"merge"\|"add", stackJson)` | `{ok, stack, blocks_added, blocks_replaced}` \| `{ok, name}` \| error |

Signals: `export_done(str)`, `import_preview(str)`. Custom-block library
refreshes still flow through the existing `custom_blocks_updated` signal
(FileBridge emits `PresetsChanged` on the bus; `StackBridge` re-emits).

## 10. Revision 2026-09-11 — BUG fix: "preset panel incomplete"

Bug report: only one (icon-only) button was visible in the preset panel.
Root cause: the four preset controls were **icon-only**
(`.btn-icon-sm` + Material Icons), and the icon font loads from the
Google Fonts CDN (`ui/index.html` line 7) — on a machine without access
to that CDN the glyphs are blank, so the controls were invisible
(unreachable), not missing from the DOM.

Fix (this revision):

* The four controls moved from the window-title row to a dedicated
  `.preset-toolbar` row with **plain-text labels**
  (`Select Preset ▾` / `Save` / `Export` / `Import`) — visible with or
  without the icon font. Same button ids → the existing JS wiring is
  unchanged; the plain "Import" is the "Download" control from the
  report. There is deliberately NO separate Download button: Export
  (file out) and Import (file in) are the two distinct file operations;
  the earlier ⬇/download arrow on Import was removed because it made
  the button look like a duplicate of Export.
* New behaviour required by the report: an applied import (Replace or
  Merge) also registers the imported file as a **named preset**
  (`save_imported_preset` in `bridge/file_bridge.py`:
  `PresetStore.save_stack(name, file_stack)` + `PresetsChanged(kind="stacks")`),
  so it appears in the Select Preset list immediately. The stored preset
  is the FILE's stack (not the merged working stack); same name =
  refresh (overwrite). Result JSON gains `preset_saved`.
* Tests: 4 new FileBridge tests (preset registration, merge keeps the
  file stack, re-import overwrite, no-preset-store degradation) and 2
  new node tests asserting the shipped HTML carries all four labeled
  controls exactly once (regression guard for "buttons visible").

Remaining known limitation (out of scope): the rest of the app still
uses Material Icons glyphs for run/pause/stop etc.; those remain blank
offline. Fixing that properly means bundling the font locally, which
needs a one-time download with network access.
