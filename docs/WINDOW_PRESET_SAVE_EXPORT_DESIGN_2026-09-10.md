# Window Preset Save, Export, and Import — Design

Date: 2026-09-10
Status: **implemented design**
Feature: named, persistent window-grid presets with portable JSON export/import.

## 1. Problem and current-state research

The application already has a versioned sash-tree model (`ui/js/sash-core.js`),
a DOM/persistence layer (`ui/js/sash-grid.js`), and built-in layout choices
(Default/A/B/C). The current tree contains the exact window order, nested split
directions, and percentage allocations, and `LayoutBridge` persists the last
working tree in the session store. That solves last-session recovery, but not
the requested named/transferable snapshots:

- the layout menu has no user-created window preset list;
- there is no portable document contract containing screen/window metadata;
- there is no export/download or import/preview path;
- the existing `PresetStore` already owns stack and message-template data and
  is a 17-method compatibility class, so adding another responsibility to it
  would violate its boundary and the code-quality rule against growing an
  already-overlarge legacy class;
- `LayoutBridge` owns grid persistence, but adding file/preset CRUD to it would
  make layout validation, storage, and UI transfer responsibilities less
  cohesive.

The current quality audit records `LayoutService` at 184 class LOC / 10 methods
and `LayoutBridge` at 167 class LOC / 8 methods; both are already over the
repository's preferred class-LOC threshold. This design therefore adds small
collaborators instead of expanding those classes. Radon is not installed in
this checkout, so a numeric `radon cc -s` run is a post-implementation gate;
the existing audit's values are the baseline above.

## 2. Goals and non-goals

### Goals

1. Save the current tree, window states, normalized window bounds, screen
   snapshot, and grid metadata under a user-supplied name.
2. Persist named presets in an atomic, app-owned JSON file so they survive a
   restart without changing the existing stack/template file.
3. Define a human-readable `.json` document that can be copied between
   machines and app installations.
4. Export any saved preset with a browser download and import a local file.
5. Validate an imported document before changing the live grid and show a
   visual preview plus a clear error for malformed/incompatible files.
6. Apply the tree's percentage allocations on the target screen; use normalized
   bounds only for preview/diagnostics, so a different resolution does not
   replay stale absolute pixels.
7. Refresh the Grid view menu and its window-preset quick chips from a signal
   immediately after save, delete, or import—no page reload. Keep the language
   URL-bookmark toolbar separate from Grid view.

### Non-goals

- Persisting application data, Chrome tabs, stack blocks, or message history in
  a window preset.
- Moving the native Qt file dialog into the backend. Qt WebEngine already has a
  safe local file input and download mechanism; using it keeps exported files
  portable and keeps Python free of platform-specific dialog code.
- Encoding absolute pixel positions as the source of truth. They are included
  as a snapshot, not used to size the target grid.
- Adding another undo history. Applying a preset uses the existing grid save
  path and global history entry.

## 3. Portable JSON contract

File format identifier: `chat-v-bot.window-preset`
Document schema: `1`
Grid tree version: the current `SashCore.VERSION` (currently `3`).

Example shape:

```json
{
  "format": "chat-v-bot.window-preset",
  "schema_version": 1,
  "app_version": "0.1.0",
  "name": "Research desk",
  "created_at": "2026-09-10T12:00:00",
  "updated_at": "2026-09-10T12:00:00",
  "grid": {
    "type": "sash-tree",
    "version": 3,
    "window_count": 12,
    "sizes_unit": "percent",
    "tree": {
      "t": "split",
      "dir": "col",
      "children": [],
      "sizes": []
    }
  },
  "windows": [
    {
      "id": "stats",
      "title": "Stats",
      "state": "open",
      "bounds": {"x": 0.0, "y": 0.0, "width": 0.25, "height": 0.3}
    }
  ],
  "window_states": {"closed": [], "minimized": []},
  "screen": {"width": 1400, "height": 900, "device_pixel_ratio": 1}
}
```

Contract rules:

- `format`, `schema_version`, non-empty `app_version`, `name`, `grid.type`,
  `grid.sizes_unit`, and `screen` are required.
- `grid.tree` is validated with the existing `LayoutService`; legacy tree node
  spelling and older grid versions are upgraded by the same migration path.
- `window_count` and `windows[].id` must describe exactly the current known
  windows once each. Bounds are finite normalized values in `[0, 1]`; no
  absolute pixels are required to restore a layout.
- `window_states.closed` and `.minimized` contain only known ids and cannot
  overlap. A closed window is never minimized.
- An app-version difference is retained and displayed as compatibility context;
  it is not a reason to reject a valid schema-1 file. An unknown future schema,
  unknown grid type, invalid tree, or wrong window set is rejected before apply.
- The stored named preset is the canonical document. Export writes the same
  document with indentation and a `.json` suffix, so it is human-readable and
  standalone.

## 4. Structure and responsibilities

```text
services/window_preset_service.py
  pure document validation/canonicalisation and compatibility metadata
stores/window_preset_store.py
  one atomic config/window_presets.json file; CRUD only
bridge/window_preset_bridge.py
  QWebChannel slots/signals for save/list/load/delete
bridge/router.py
  publishes the new domain bridge; no domain logic
ui/js/sash-grid.js
  builds/validates/applies a portable snapshot; tree remains the source of truth
ui/js/window-presets.js
  Grid view menu section, quick chips, save/load/delete, download, file input,
  preview modal
ui/js/url-toolbar.js
  language URL-bookmark controls in their separate toolbar
ui/index.html + ui/css/*
  separate language-bookmark toolbar, Grid view menu, and preview surface
```

`ConfigManager` wires the new store into its existing load/save lifecycle, but
stack/template presets remain untouched. The bridge never accepts an invalid
snapshot into the store: it canonicalises and validates first, then atomically
flushes the store. The UI validates a file before preview and validates again
inside `SashGrid.applyPortablePreset` before applying it, so both the preview
and the final mutation are guarded.

## 5. UI flow

### Save

1. User opens **Window presets** and presses **Save current**.
2. The shared name dialog requires a non-empty name.
3. `SashGrid.createPortablePreset(name)` captures the canonical tree, states,
   normalized bounds, and screen metadata.
4. The bridge validates/persists the document and emits
   `window_preset_list_updated`.
5. The Grid view menu and its window-preset quick chips render the new preset
   immediately and a success log names the saved preset; language bookmarks stay
   in their separate toolbar.

### Load / export

Each saved row has **Restore**, **Export**, and **Delete** actions. Restore
shows the same preview (and a screen-size note when the source and target
screens differ), then applies only after confirmation. Export obtains the
canonical stored document, serializes it with indentation, and starts a
`window-preset-<safe-name>.json` download.

### Import

The Import button opens an `accept=".json,application/json"` file input. The
file is read as text, parsed, validated, and rendered in the preview modal.
Invalid input leaves the current grid unchanged and reports the specific
reason in the panel/log. Confirming a valid preview applies the tree and
states, then stores it under the validated document name so it becomes a
visible quick preset without a reload.

### Cross-resolution behavior

The tree contains percentages and remains the restore source of truth. The
normalized bounds are multiplied by the current preview/grid dimensions only
for the preview. A different source screen is reported as informational, not
silently treated as an error.

## 6. Validation and failure invariants

- Invalid JSON, wrong format/schema, missing fields, future grid versions,
  unknown windows, duplicate windows, invalid bounds, and invalid states are
  rejected with an actionable message.
- No invalid import changes `SashGrid.root`, window-state sets, localStorage,
  backend session state, or named presets.
- A failed atomic store write does not report success; the prior file remains
  intact.
- A missing/empty preset list is rendered as an explicit empty state, not as a
  broken panel.
- Import/apply is idempotent with respect to the tree: the validated tree is
  cloned before assignment, and the ordinary `_save()` path persists the
  resulting layout plus global history.

## 7. Test-first plan

Before implementation changes, add focused tests that exercise real behavior:

- `tests/test_window_preset_service.py`: valid canonical document, malformed
  JSON, future schema, wrong grid/window set, invalid bounds/state, version
  mismatch warning, and cross-resolution metadata.
- `tests/test_window_preset_store.py`: atomic save/list/load/delete and restart
  round trip in a temporary config directory.
- `tests/unit/bridge_safety/test_window_presets.py`: bridge slot round trips,
  signal refresh, invalid-save refusal, missing-load/delete behavior.
- `tests/test_window_presets.js` and `tests/test_window_preset_ui.js`: execute
  the real `sash-grid.js` and `window-presets.js` behavior against DOM/file
  stubs; assert that valid imports apply, invalid imports do not, preview is
  generated, and saved entries render.

Existing grid persistence, SashCore, bridge parity, and store split suites
remain the regression gate. The tests must fail if validation or application
is removed; source-string-only assertions are not sufficient for behavior.

## 8. Quality gates and rejected shortcuts

Targets for new Python code:

- every new function ≤30 physical LOC, ≤4 non-`self` parameters, Radon CC ≤10,
  cognitive complexity ≤15, nesting ≤4;
- new classes ≤150 LOC and ≤15 direct methods;
- focused tests cover every new production path; no new duplication or unused
  imports.

Rejected shortcuts:

- **Do not add window CRUD to `PresetStore`**: it is already a compatibility
  class over the method-count target and would couple unrelated preset types.
- **Do not add all slots to `LayoutBridge`**: it is already over the class-size
  target; a separate bridge keeps the QWebChannel domain boundary clear.
- **Do not store only `localStorage`**: that fails restart/profile transfer.
- **Do not restore absolute pixel rectangles**: that fails the different-screen
  acceptance criterion and can hide windows off-screen.
- **Do not apply before preview/validation**: that turns a malformed backup into
  a destructive UI mutation.
- **Do not use a second undo shortcut/history**: global history is the existing
  contract.

Post-implementation verification includes `python -m compileall` on touched
Python packages, focused Python tests, all existing SashCore/grid/bridge JS
suites, and `radon cc -s` on every touched production Python file once Radon
is available.
