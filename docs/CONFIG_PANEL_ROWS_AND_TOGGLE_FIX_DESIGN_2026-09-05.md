# Block Config panel: toggle-bar fix + two-column row layout — design

Date: 2026-09-05

## 1. Problems reported

### BUG — On/Off toggle bar renders broken
In the Block Config panel the **Enabled — On/Off toggle bar** (the last row of
every block's settings) looks wrong: the switch's track renders far too wide
and, when enabled, the blue "on" highlight reads as a bar that extends beyond
the expected switch bounds instead of a small pill with a sliding knob.

The user asks: make the toggle **shorter and of a fixed width, identical to the
On/Off switch shown on the Action Stack rows** (the `.toggle-switch` used in
each `.stack-item`).

### UI FIX — config rows are misaligned / hard to scan
In the Scroll & Parse config panel (and every other block's panel) the
label/value rows are ragged: a value control starts wherever its own label's
text happens to end, so the "value" column is not a column at all. There is no
visual grouping between the label and its control.

The user asks for:
1. a clean **two-column layout per row** — label in the left column, value
   control in the right column, starting on the same x for every row;
2. **alternating (zebra) row background tones** so each label–value pair reads
   as one group;
3. **consistent vertical spacing** between rows.

## 2. Root-cause analysis (from the shipped CSS/JS)

### Toggle bar
`ui/js/stack-dnd.js` renders the bar as
`<div class="form-row form-row-check form-row-enabled">` containing a text
`<label>` **and** `<label class="toggle-switch"><input …></label>`.

In `ui/css/stack.css`:

* `.form-row-enabled label { flex: 1; }` — the bar is a flex row
  (inherited `.config-panel .form-row { display: flex; … }`) and this rule
  applies `flex: 1` to **both** labels. The switch label therefore grows to
  fill roughly half the panel width: a ~150–250 px "track" with the blue
  checked state painted across it. That is the "blue highlight bar extends
  beyond the expected bounds".
* `.config-panel label { min-width: 130px; }` prevents the switch from ever
  shrinking below 130 px even if the flex-grow were removed.
* `.form-row-enabled .toggle-switch { width: 44px; height: 24px; }` (plus the
  16 px knob / `translateX(18px)` overrides) made this variant bigger than the
  `.toggle-switch` used on stack rows (36×20, 14 px knob, `translateX(16px)`),
  which is why it does not match the "Block action in stacking" switch.

### Row alignment
`.config-panel .form-row` is `display: flex`; `.config-panel label` only has
`min-width: 130px`, so the label's real width is driven by its text length
(long labels in Scroll & Parse exceed 130 px and simply push the control
further right). The value control is placed immediately after the text label,
so controls start at a different x on every row. There is no row background
(zebra) at all, and vertical rhythm comes only from `margin-bottom`.

## 3. Design of the fix

### 3.1 Toggle bar (`ui/css/stack.css`)
Replace the `.form-row-enabled` block so the switch keeps a **fixed size
identical to the stack-list `.toggle-switch`** and never flex-grows:

* `.config-panel .form-row-enabled` → explicit `display:flex`, accent left
  border, `--bg-input` background, consistent padding/radius (the visual
  "bar").
* only the **text label** grows: `.form-row-enabled > label:first-child
  { flex: 1; min-width: 0; }` (min-width 0 so the long text can wrap instead
  of widening the row).
* the switch: `.form-row-enabled .toggle-switch { flex: 0 0 auto;
  min-width: 0; width: 36px; height: 20px; }` — same metrics as
  `.toggle-switch` on the stack rows; knob metrics stay the base 14 px /
  `translateX(16px)`.
* delete the old 44×24 knob/translate overrides.

Specificity note: all overrides are written as `.config-panel .form-row-enabled …`
(0,3,0) so they beat both `.config-panel .form-row` (grid, 0,2,0) and
`.config-panel label` (0,1,1).

### 3.2 Two-column rows + zebra (`ui/css/stack.css` + `ui/js/stack-dnd.js`)
**Layout** — every standard row becomes a CSS grid with a fixed *ratio*
label/value split:

```css
.config-panel .form-row {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); /* ~40% / 60% */
  align-items: center;
  column-gap: var(--gap-md);
  padding: 6px 10px;
  margin: 0;
  border-radius: var(--radius-sm);
}
```

All labels get `min-width: 0` + `overflow-wrap: anywhere` so a long label wraps
inside its own column and **cannot** push the value column; all inputs/selects
get `width: 100%; min-width: 0` so they fill the value column. The value column
therefore starts at the same x for every row.

**Vertical spacing** — `#blockConfigForm` becomes a scrollable flex column with
a single uniform `gap`, replacing per-row `margin-bottom`:

```css
.config-panel #blockConfigForm {
  flex: 1 1 auto; min-height: 0;
  overflow-y: auto;
  display: flex; flex-direction: column;
  gap: 6px;
}
```

(This also fixes long Scroll & Parse panels being clipped by the
`overflow:hidden` panel frame — the form now scrolls.)

**Zebra striping** — `_showConfig()` numbers only the actual two-column field
rows and adds `zebra-0` / `zebra-1` classes (head row, the CUSTOM_FIND stacked
constructor rows and the On/Off bar keep their own distinct styling):

```css
.config-panel .form-row.zebra-0 { background: rgba(255,255,255,.02); }
.config-panel .form-row.zebra-1 { background: rgba(255,255,255,.05); }
```

Special rows keep working via higher-specificity overrides:
`.config-panel .form-row--stack { display:flex; flex-direction:column; … }` and
`.config-panel .form-row-enabled { display:flex; … }`.

## 4. Files touched

* `ui/css/stack.css` — grid rows, zebra rules, form container gap/scroll,
  `.form-row-enabled` bar + fixed 36×20 switch, removed 44×24 overrides.
* `ui/js/stack-dnd.js` — `_showConfig()` adds the alternating `zebra-0/1`
  classes to field rows (one counter, no DOM queries).
* `tests/test_config_panel_rows.js` (new) — node test that executes the REAL
  shipped `ui/js/stack-dnd.js` against a DOM stub (project RULE 8), renders a
  Scroll & Parse panel, and asserts:
  * zebra classes alternate on field rows and are absent from the head / On-Off
    bar rows;
  * the On-Off bar renders `form-row-enabled` + `toggle-switch` +
    `data-key="enabled"`;
  * `ui/css/stack.css` defines the two-column grid, the zebra rules, and the
    fixed 36×20 non-growing switch, and no longer contains the 44×24 override.

## 5. Acceptance

* The On/Off toggle in the Block Config panel is a small fixed 36×20 switch,
  pixel-identical to the switch on the Action Stack rows; the blue "on" state
  never paints beyond the pill's rounded track.
* In the Scroll & Parse (and every other) config panel every row is two clean
  columns: labels start together on the left, controls start together on the
  right.
* Rows alternate subtle background tones and are evenly spaced; the panel
  scrolls when the block has many settings.
* Existing python + node suites stay green.
