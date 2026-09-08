# Label Badge Interaction — Assign / Edit / Delete + Quick Assign on Person Click — Design

Date: 2026-09-08
Status: implementation design, written BEFORE the code changes (AGENT_RULES
process) — see “Implementation status” at the end for the code and test map.
Feature request / bug report:

1. **BUG (critical)** — clicking a label badge in the Label Manager (“Rude”,
   “no responding”) opens the *edit* flow (recolour). The user expects the
   click to **assign that label to the selected person immediately**.
2. **Feature (high)** — three clearly separated click zones per label entry:
   badge = assign, “edit” text = edit (rename/colour), ✕ = delete everywhere.
3. **Feature (high)** — quick assign: click a person row in People → the
   Label Manager highlights that person as the target → click a badge → the
   pill appears in the person's row. No dropdown, no dialog, no confirmation.

---

## 1. Problem statement

Today the Label Manager has four sections: Active Labels, Create New Label,
Filter By Labels, Assign To Person. The Active Labels entry for one label is
`[badge] 3 ✕`:

* the badge itself opens the colour picker (`recolor`) — so the most
  clickable thing on the row does NOT do what a “badge of a person-tag”
  most plausibly should (assign it), it edits instead;
* “edit” and “assign” share the same visual surface, so the user cannot
  tell from looking at the entry which click does what;
* assigning still requires Section 4 (dropdown + tick + press Assign) even
  though the system already knows which person the user just clicked —
  three extra steps after selecting the person;
* when the user clicks a person in the People table, the Label Manager
  window may be closed or showing nothing about that person, so the quick
  path “person → badge → done” is not possible.

## 2. Current state audit

| Piece | Where | Behaviour today |
|---|---|---|
| Active Labels badge | `ui/js/labels.js` `renderActive()` | click → `recolor()` (colour picker) — the bug |
| Per-entry delete ✕ | same | `label_delete` — correct, keep |
| Count chip (“3”) | same | visible per entry — moved into tooltips by this design |
| Assign target | `Labels.person` + `renderAssign()` | set by nick-cell click (People), row click (Storage), 🏷 buttons, Section 4 dropdown |
| People row click | `ui/js/user-table.js` | only the **nick cell** reacts (opens history + `Labels.setPerson`); the rest of the row does nothing |
| Storage row click | `ui/js/history-db.js` | whole row reacts (`Labels.setPerson` + open history) — already correct |
| Label Manager window | `ui/js/sash-grid.js` `openWindow()` | opens un-hovered, without stealing focus — safe to auto-open |
| Backend slots | `backend/bridge.py` | `label_assign`, `label_unassign`, `label_update`, `label_delete` all exist as ONE undo entry each (`_labels_edit`) — **no backend change needed** |
| Immediate pill update | `labels_changed` → `Labels.applyState` → `repaintTables()` | already wired in `app.js` — the pill in the person's row appears as soon as the backend round-trip lands |

## 3. Guiding decisions

### D1 — Three click zones, one entry (visual spec)

```
┌────────────────────────────────┐
│ [no responding]  edit  ✕       │
│  ↑                ↑     ↑      │
│  ASSIGN toggle    EDIT  DELETE │
└────────────────────────────────┘
```

* **badge** = assign the label to `Labels.person` (Section 4 and the filter
  checkbox lists are untouched);
* **“edit”** = small muted text button → inline rename/colour editor
  (D3), no new window, no modal;
* **✕** = delete the label from the whole system (unchanged).

All three zones are separate DOM nodes with their own listeners; no click
handler is ever attached to the entry wrapper, so a future zone can never
accidentally inherit another zone's behaviour.

### D2 — Badge click is a TOGGLE on the current target

Clicking the badge of a label the person already carries **un-assigns** it;
clicking a label they don't carry **assigns** it. Rationale:

* the bug report asks for “assign immediately”, and toggle is the
  least-surprising instant behaviour (second click = instant undo, matching
  the app's one-click-undo culture — RULE 12 covers the backend anyway);
* the current state is visible before the click: assigned badges wear the
  label colour as a ring + a ✓ and a stronger fill, and the tooltip says
  “click to remove from …” vs “click to assign to …”.

When **no person is selected**, a badge click assigns nothing; it logs a
warn, flashes the Active Labels section and pulses the target chip — the
user must click a person first (the chip says exactly that).

### D3 — Inline edit mode inside Active Labels

“edit” swaps the entry for an inline editor row: name input (prefilled),
colour swatch button (opens the existing `ColorPicker`), Save and Cancel.
Enter = save, Escape = cancel. Save calls the existing
`bridge.label_update(id, name, color)` with unchanged fields passed as `''`
(the backend treats `''` as “keep”). Duplicate names stay refused by the
backend exactly as `label_create` refuses them.

### D4 — The Label Manager follows every person click (quick assign)

`Labels.setPerson()` becomes the single funnel for “this person is now the
label target”. It:

1. sets `Labels.person` and re-renders the manager (badges re-ring, chip
   updates, Section 4 dropdown syncs);
2. opens the Label Manager window through `SashGrid.openWindow('labels')`
   (no-op when already open; it does NOT steal focus) — this is what makes
   “click person → click label → done” possible with the manager closed;
3. calls `UserTable.markLabelTarget()` / `HistoryDb.markLabelTarget()` so
   the person's row wears the accent bar in BOTH tables instantly.

In addition the People table gets a whole-row click: clicking anywhere on a
row (except the checkbox cell, action buttons and pill ✕) targets that
person for labelling, exactly like Storage already does. Clicking the nick
cell keeps its existing behaviour (opens the person's history too).

The pill appearing in the person's row requires no new plumbing: the
backend already broadcasts `labels_changed` after every mutation and
`repaintTables()` redraws both tables.

### D5 — The per-entry count chip moves into tooltips

The visual spec shows exactly three zones. The “N person(s)” info is
preserved as tooltip text on the badge and on “edit”, instead of a fourth
visual element.

### D6 — No backend changes

Every mutation used here already exists as a bridge slot and already goes
through `_labels_edit` (single global-undo entry). This change is UI-only:
`ui/js/labels.js`, `ui/js/user-table.js`, `ui/js/history-db.js`,
`ui/index.html`, `ui/css/labels.css`, `tests/test_labels_ui_js.js`.

### D7 — DOM rules unchanged

Label names are user text: every node is still built with
`createElement`/`textContent` only (the UI test stub throws on `innerHTML`),
nicks travel in `data-nick`, and listeners are attached per-node (no inline
`onclick`). The assignable badge is given `role="button"` + `tabindex` and
reacts to Enter/Space so it is keyboard-reachable.

## 4. Component changes

### 4.1 `ui/js/labels.js`

* new state: `editing` (label id being edited), `editName`, `editColor`;
* `renderActive()` rewritten:
  * per label → `label-manage-item` containing the pill (click = toggle,
    `role=button`, tooltip with count + action), a `label-manage-edit`
    “edit” button, and the existing `label-del` ✕;
  * assigned-to-target pills get class `assigned` (ring, ✓, stronger fill);
  * the label being edited renders a `label-edit-row` instead
    (input + colour swatch + Save + Cancel);
* new: `toggleAssign(id)`, `startEdit(id)`, `saveEdit()`, `cancelEdit()`,
  `renderTarget()` (target chip), `flashTargetHint()` (warn path);
* `setPerson(nick, options)` extended: default-open the window
  (`options.focus === false` opts out for the Section 4 dropdown path),
  re-render active + assign sections, call both tables' `markLabelTarget`;
* `pill()` accepts `options.title` (full tooltip override) and sets
  `role="button"` only for the manager badge (table pills unchanged).

### 4.2 `ui/index.html`

Active Labels section title becomes:

```html
<div class="label-section-title">Active Labels
  <span class="label-section-hint">badge = assign · edit = rename/colour · ✕ = delete everywhere</span>
  <span id="labelAssignTarget" class="label-target-chip">click a person to quick-assign</span>
</div>
```

### 4.3 `ui/css/labels.css`

* `.label-manage-item` three-zone spacing; `.label-manage-edit` muted text
  button; `.label-manage-item .label-pill.assigned` ring/✓ styles;
* `.label-edit-row` + `.label-edit-input` + `.label-edit-color`;
* `.label-target-chip` (+ `.on` state) with a pulse animation used by the
  warn path;
* `tr.row-label-target` accent left bar for both tables;
* `.label-section-flash` animation for the no-target warn path.

### 4.4 `ui/js/user-table.js`

* `<tr>` carries `data-nick` and the `row-label-target` class when
  `Labels.person === nick`;
* delegated click: new row branch (after nick-cell and button branches)
  → `Labels.setPerson(row.dataset.nick)` for clicks outside `.col-select`
  and `.row-actions`;
* new `markLabelTarget(nick)` — in-place class move + `scrollIntoView
  (block:'nearest')` (no full re-render, no `CSS.escape` needed).

### 4.5 `ui/js/history-db.js`

* rows render with `row-label-target` when `Labels.person === nick`;
* new `markLabelTarget(nick)` mirroring `UserTable` (list is `this._els.body`).

### 4.6 `tests/test_labels_ui_js.js`

New tests (against the real modules + DOM stub + real CSS):

1. badge click with a target → exactly one `label_assign(nick, id)`;
2. badge click when already assigned → `label_unassign`;
3. badge click with no target → no bridge call, warn path;
4. each entry has exactly one pill, one “edit”, one ✕;
5. “edit” opens the inline editor (input prefilled, Save/Cancel); Save with
   a new name + colour → `label_update` with the changed fields and `''`
   elsewhere; Cancel → no calls; Enter saves, Escape cancels;
6. ✕ still deletes system-wide and never assigns;
7. assigned badge wears the `assigned` class and a ✓;
8. `setPerson` syncs the chip + Section 4 dropdown and calls the tables'
   `markLabelTarget` (source-level assertion for the table modules);
9. People-table row carries `data-nick` and the target class
   (source-level).

## 5. What deliberately does NOT change

* Section 4 (Assign To Person checkboxes + Assign button) — kept as the
  bulk editor; it stays in sync with the badge toggle through
  `Labels.person`.
* Filter section, Create New Label, the pill renderer for the two tables,
  and all backend slots — untouched.
* Table pill ✕ semantics (“this person only”) — untouched.

## 6. Risks / edge cases

* **Same nick in two tables** — target highlight is applied in both; both
  mark methods are in-place class moves, idempotent.
* **Window auto-open noise** — `openWindow` is a no-op when the window is
  already visible, so repeated person clicks log nothing.
* **No backend** (UI opened standalone) — `_bridge()` guards every
  mutation and logs “Not connected to backend — labels unchanged”.
* **Rename to a duplicate** — backend silently keeps the old name; the
  re-render shows the authoritative state, so the editor never displays a
  lie.

## 7. Implementation status

Implemented 2026-09-08 on this branch:

| File | Change |
|---|---|
| `docs/LABEL_BADGE_ASSIGN_EDIT_DELETE_DESIGN_2026-09-08.md` | this document |
| `ui/js/labels.js` | three-zone Active Labels, badge toggle-assign, inline edit mode, target chip, `setPerson` funnel |
| `ui/index.html` | Active Labels title hint + `labelAssignTarget` chip |
| `ui/css/labels.css` | zone styles, assigned ring, editor row, target chip, row highlight, flash animation |
| `ui/js/user-table.js` | row `data-nick`, whole-row click → quick-assign target, `markLabelTarget`, target row class |
| `ui/js/history-db.js` | target row class, `markLabelTarget` |
| `tests/test_labels_ui_js.js` | tests for all three zones, toggle, editor, target sync |
