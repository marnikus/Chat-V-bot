# Grid persistence, global undo, window restore, and sortable people table

Date: 2026-09-05  
Status: implementation design, written before code changes

## 1. Scope and audited failure points

The current UI is a PySide6 `QMainWindow` containing a Qt WebEngine page. The
page renders a split-tree grid through `ui/js/sash-core.js` and
`ui/js/sash-grid.js`. The Python bridge persists state in `config.json`.

The audit found four concrete causes:

1. `SashCore` serializes nodes with the field `t` (`leaf` / `split`), while
   `Bridge._validate_grid_tree()` only reads `type`. Every drag/resize payload
   therefore reaches the bridge as an unknown node type.
2. The grid owns `grid_layout_history` and `undo_grid_layout` /
   `redo_grid_layout`, while the action stack has a different history and
   different controls. This creates two competing undo systems.
3. The grid has a JavaScript pixel clamp, but its flex children and the
   persisted tree do not enforce a minimum usable width/height consistently.
   A resize can still commit a zero or nearly-zero neighbor.
4. `MainWindow` always calls `resize(1400, 900)` and never stores/restores its
   geometry. The people table has no header sort state or sort interaction.

## 2. Data contracts

### 2.1 Grid node contract

`SashCore` remains the model authority and `t` is the canonical node key:

```json
{"t":"leaf","id":"people"}
{"t":"split","dir":"row","children":[...],"sizes":[50,50]}
```

The Python validator accepts the old `type` spelling for existing hand-written
or previously saved payloads, then normalizes it to `t` before storing. New
payloads are never written with `type`. Validation also enforces the exact set
of seven window ids, valid directions, positive sizes summing to 100, and the
maximum tree depth.

### 2.2 One global undo history

The single persisted history is `state.undo_history` with
`state.undo_history_index`:

```json
{
  "kind": "stack" | "grid",
  "value": [/* action blocks */] | "{\"v\":1,\"tree\":{...}}"
}
```

The history is chronological, capped at 100 entries, deduplicated against the
current entry, and truncates its redo tail when a new edit follows an undo.
Stack edits and grid edits occupy the same timeline. The normal `Undo` / `Redo`
buttons and `Ctrl+Z` / `Ctrl+Y` invoke only this history. A grid change is no
longer undone by a grid-specific API or shortcut; it is just the next global
entry. Legacy `stack_history` and `grid_layout_history` values are read once
for migration but are not written or used as separate histories.

Undo/redo returns an envelope so the UI knows which state to restore. A stack
entry updates `StackDnD`; a grid entry is validated and applied by
`SashGrid`. Both paths update the same button state.

## 3. Window geometry persistence

`MainWindow` receives the existing `ConfigManager`. On construction it reads
`state.window_geometry` and restores `{x, y, width, height}` if all values are
finite and dimensions are positive. Otherwise it uses the current default
`1400 × 900` size. On `closeEvent`, before emitting shutdown, it writes the
current normal-window geometry to that state and saves `config.json`.

The values are stored alongside the last session and presets in the same JSON
settings file. Saving is best-effort; an unwritable config must not prevent
close. Maximized/fullscreen state is not persisted as geometry because the
requirement is the exact normal position and size.

## 4. Minimum grid constraints

`SashCore.MIN_SIZE` becomes a shared minimum percentage floor used by
normalization and validation. The DOM layer also uses a usable pixel minimum
(`MIN_PX`, 96 px) and calculates a legal interval for the resized pair before
applying flex growth. All split children receive `min-width: MIN_PX` and
`min-height: MIN_PX` through the sash CSS, while the outer grid/split/window
containers retain `min-width: 0` / `min-height: 0` where needed for overflow
handling. The effective constraint is applied in both row and column axes, so
neither a horizontal neighbor nor a vertical neighbor can disappear.

A simulated resize uses the same clamp as pointer resizing. Persisted sizes are
normalized after clamping, ensuring a later render cannot reintroduce a zero
panel.

## 5. Sortable People/User Memory table

`UserTable.sort` holds `{key, direction}` for the session. The keys are
`nick`, `gender`, `registered`, `messaged`, `first_seen`, and
`last_messaged`; Actions and the selection checkbox are intentionally
non-sortable. Every sortable `<th>` gets a button with `data-sort`, a visible
`▲` / `▼` indicator, and `aria-sort`. Clicking the same header reverses the
direction; clicking a different header starts ascending. The stable comparator
uses case-insensitive text for nick/gender/status and timestamps for dates,
with empty values ordered after populated values. The sort is applied after the
nick filter and before rendering, and re-rendering from backend updates keeps
it while the app is running.

## 6. Implementation order

1. Add this design and update the settings/history contract.
2. Fix grid node normalization and persistence; add regression coverage.
3. Replace grid-specific undo controls with the global timeline and wire both
   stack and grid edits to it.
4. Add geometry save/restore in `MainWindow`.
5. Add shared minimum constraints and resize clamping.
6. Add sortable table markup, rendering, comparator, and styles.
7. Run Python syntax checks, the pure Node sash suite, focused UI/static tests,
   and the available full test suite. Report unavailable optional dependencies
   separately.

## 7. Verification matrix

- A real drag produces a `t` payload, `save_grid_layout` accepts it, and a
  reload restores the same tree.
- A `stack → grid → stack` edit sequence is undone in reverse order by the
  same `Ctrl+Z` command; redo follows the same timeline.
- A row and a column sash stop at the pixel minimum; the persisted model has no
  non-positive sizes.
- Geometry round-trips through a temporary `ConfigManager` and invalid stored
  geometry falls back safely.
- Each People header toggles sort order, timestamps sort chronologically, and
  sorting remains active after `users_updated` rerenders the table.
