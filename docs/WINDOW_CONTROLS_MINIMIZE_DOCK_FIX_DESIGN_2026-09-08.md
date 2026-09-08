# Window Controls — Minimize-to-Bottom-Strip Redesign (bugfix)

Date: 2026-09-08
Status: design, written before code changes
Supersedes the window-control part of `docs/GRID_WINDOW_CONTROLS_DESIGN_2026-09-07.md`
(maximize-to-full-grid and in-place minimize are removed).

Fixes the bug report: "MINIMIZE / MAXIMIZE / CLOSE — Window Control Icons Work
Incorrectly".

---

## 1. Problem statement (from the bug report)

| # | Issue | Priority |
|---|-------|----------|
| 1 | Minimize does not shrink the window fully — it "leaves space" | 🔴 Critical |
| 2 | Other open windows do not fill the freed space | 🔴 Critical |
| 3 | Maximize only appears after minimize (visibility/toggle confusion) | 🟠 High |
| 4 | Minimize / maximize / close icons look messy / non-standard | 🟠 High |
| 5 | No hover tooltips on the icons | 🟡 Medium |

Required behavior (FULL SPEC in the report):

* **Minimize** — the window collapses so only its title bar remains visible;
  the freed grid space goes to the other open windows; the icon changes to the
  maximize/restore glyph (□) after minimizing.
* **Maximize (Restore)** — brings the minimized window back to its previous
  size; the icon changes back to minimize (─) after restoring.
* **Close** — closes the window completely; it can be reopened from the
  top-bar Windows dropdown; freed space is redistributed to the remaining
  windows.
* Icons must follow standard window-control conventions:
  `─` minimize (horizontal line), `□` maximize/restore (square outline),
  `✕` close — small, evenly sized/spaced, with hover tooltips, matching the
  dark UI theme.

User decisions (asked 2026-09-08):

1. **Control set = single toggle pair + Close**: one control shows `─`
   (Minimize) while the window is open and becomes `□` (Maximize/Restore)
   after the window is collapsed; exactly one of `─`/`□` is shown at a time,
   plus `✕` Close. (Matches the report's FULL SPEC section.)
2. **Minimized windows dock as a title strip at the bottom edge** of the grid
   area (classic MDI style), so other open windows expand into ALL the freed
   space and no empty band is left behind.
3. **Remove the "maximize to full grid area" state entirely** — windows have
   exactly three states: open, minimized, closed.

---

## 2. Why the current implementation is wrong

Current state (commit 2671ad8):

* `minimizeWindow()` keeps the minimized `.sash-window` **inside the flex
  tree** and only forces `flex: 0 0 auto; min-height: 32px; max-height: 36px`
  (CSS `.sash-window.sash-win-minimized`).
  * In a *column* split that mostly works, but in a *row* split
    (e.g. `people | log`, `history | userdb | collector`, `labels | dbconn`,
    which is most of the default layout) the window's width only shrinks to
    its title text and the row band keeps its allocated height. The strip is
    clamped to ~36 px height at the top of the band while the rest of the band
    below stays **empty** — the other windows in that split never receive the
    space, and neither do windows in sibling splits. This is exactly the
    reported "minimize leaves empty space but the window is not fully shrunk".
  * The old full-grid maximize state (`maximizedWindow`,
    `.sash-window-maximized`) adds a third, confusing state; per user decision
    it is removed.
* Title-bar buttons: two controls are always injected (`─` and `□`) and their
  glyphs shift (`─`→`□` when minimized, `□`→`❐` when grid-maximized). The
  `❐` glyph (U+2750) is not reliably present in the UI fonts and the
  minimized bar shows two square-ish glyphs next to each other — messy,
  non-standard.
* Tooltips exist (`title="Minimize"` etc.) but are terse and duplicated.

The existing **close** path already does the right thing with space: the
closed window's wrapper is given `.sash-win-hidden` (`display: none`), sashes
touching it are hidden, and empty splits collapse — siblings expand to fill
the freed space (verified by `tests/test_sash_webengine.py`, "config closed →
log width grows"). The redesign reuses that proven mechanism for minimize.

---

## 3. Target model

### 3.1 Window states

Exactly three per window:

| State   | Meaning                                                        |
|---------|----------------------------------------------------------------|
| open    | Panel visible in the grid at its normal slot                   |
| minimized | Content + title bar leave the grid; a slim strip is docked at the bottom edge. Grid space is released (same mechanism as closed). |
| closed  | Window hidden; can be reopened from the Windows dropdown       |

Invariants:

* minimized ∩ closed = ∅.
* Minimizing an open window releases its grid slot (wrapper hidden), other
  open windows expand exactly like they do when a window is closed.
* The window keeps its tree position/size while minimized, so restoring puts
  it back where it was (titles, sizes, sash layout untouched).
* No "maximized" state anymore. Old persisted `maximized` values (localStorage
  `chatbot.sashWindows.maximized.v1`, backend `window_states.maximized`) are
  ignored on load and dropped on the next save.

### 3.2 Title-bar controls (open windows)

Each `.win-title` shows two compact icon buttons on the right:

1. `.win-toggle` — the minimize/restore toggle:
   * open window: glyph `─`, tooltip `Minimize <Window Title>`; click →
     `SashGrid.minimizeWindow(id)`.
   * (while minimized the title bar itself is not visible in the grid — the
     window is docked — so the `□` state is only ever visible on the dock
     strip / in the Windows menu, per the FULL SPEC.)
2. `.win-close` — glyph `✕`, tooltip `Close <Window Title>`; click →
     `SashGrid.closeWindow(id)`.

Visual spec (bug #3):

* Buttons are square, equal size (20×20 CSS px), no border, subtle 3 px
  radius hover background, glyphs vertically/horizontally centered, drawn in
  the existing monospace font stack at ~13 px so `─`, `□`, `✕` align.
* Default glyph color `--text-muted`; hover brightens to `--text-primary`.
* Close hover keeps a red tint (`--red-dim` background, `--red` glyph) — a
  standard close affordance.
* Tooltip = native `title` attribute (hover tooltip).
* The controls are appended after the window's own title-bar buttons
  (spacer + controls), so existing buttons (Action Stack run/pause/stop,
  Block Config pin, …) are untouched.

### 3.3 Minimized dock (bottom strip)

A dedicated dock bar `.sash-min-dock` is inserted once, right after
`#sashGrid` inside `.app-layout` (so it is a normal flex child of the app
column: header → url toolbar → grid (flex:1) → dock).

* Hidden (`display:none`) when no window is minimized.
* Contains one chip `.sash-min-chip` per minimized window, in the canonical
  window order:
  `[ ▤ Window Title ]  [ □ ] [ ✕ ]`
  * chip body click → restore (maximize) the window (tooltip on the label);
  * `□` button → restore; `✕` button → close the window.
* Chip styling reuses the title-bar language: dark header background,
  uppercase 11 px label, border + radius, hover accent — visually consistent
  with the window title bars and the dark theme.

### 3.4 Windows dropdown (top bar)

* One row per window with a state glyph + colored badge:
  * open → `●`/Open, minimized → `─`/Minimized, closed → `○`/Closed.
* Row click:
  * closed → open; open → close; minimized → restore (friendlier).
* Per-row quick buttons (right side): the toggle (`─` minimize / `□`
  restore) and the close/open button (`✕` close / `●` open). Maximize
  quick-button and `❐` glyph removed.
* "Show all" clears minimized + closed; "Hide all" closes everything and
  clears minimized.

### 3.5 Persistence

* localStorage:
  * `chatbot.sashWindows.closed.v1` — unchanged;
  * `chatbot.sashWindows.minimized.v1` — unchanged format;
  * the old `chatbot.sashWindows.maximized.v1` key is no longer written or
    read.
* Backend `window_states` payload becomes `{"closed": [...], "minimized":
  [...]}`. `bridge.get_window_states` / `save_window_states` and the
  `config_manager` default are updated; old stored `maximized` entries are
  tolerated (ignored).
* Corrupt JSON → fall back to empty sets (unchanged behaviour).

---

## 4. Implementation plan

### 4.1 `ui/js/sash-grid.js`

* Delete the whole `maximizedWindow` state: fields, `STORAGE_MAXIMIZED`,
  load/save paths, `maximizeWindow/restoreMaximize/toggleMaximize/isMaximized`,
  `_syncMaximized`, and every `_syncMaximized()` call.
* `minimizeWindow(id)`:
  * guards: known id, not closed, not already minimized;
  * `minimizedWindows.add(id)`;
  * `_applyStates()` → (a) `_syncHidden()` marks the wrapper
    `.sash-win-hidden` (space released), (b) `_syncEmptySplits()` collapses
    now-empty splits, (c) `_renderDock()`, (d) `_updateWindowsMenu()`,
    (e) `_checkEmptyGrid()`;
  * `_saveWindowStates()`; log `🗕 Minimized …`.
* `restoreMinimized(id)` / `toggleMinimize(id)`: delete from set, same
  `_applyStates()` + `_flashLanded(id)`; log `🗖 Restored …`.
* `closeWindow(id)`: if the window was minimized, drop it from
  `minimizedWindows` first (and re-render the dock); unchanged otherwise.
* `openWindow(id)`: unchanged.
* `showWindow(winId)` (used by history/collector jumpers): closed → open;
  minimized → restore; else just ensure panel visible.
* `showAllWindows()` / reset: clear minimized as before.
* `_syncHidden()`: `shouldHide = closed || minimized || panelHidden`;
  minimized windows get `sash-win-hidden` (they do NOT get
  `sash-win-closed`/panel `.hidden`).
* `_setupVisibilityWatch()`: recompute with the minimized set included so the
  MutationObserver cannot un-hide a minimized wrapper.
* `_checkEmptyGrid()`: distinguish "all closed" vs. "all minimized" hints
  (minimized → “restore from the strip at the bottom”).
* Window-controls injection (`_ensureWindowControls`):
  * only two buttons now: `.win-toggle` + `.win-close`;
  * `_updateWindowControlIcons(title, id)`: toggle glyph `─` and tooltip
    `Minimize <Title>` (or `□` / `Restore <Title>` when minimized for safety),
    close glyph `✕` tooltip `Close <Title>`;
  * keep hiding the legacy `#closeConfigBtn` when present.
* New dock methods:
  * `_ensureDock()` — create `.sash-min-dock#sashMinDock` after `#sashGrid`,
    called once in `init()`;
  * `_renderDock()` — rebuild chips from `minimizedWindows` (sorted by
    `SashCore.WINDOWS` order), wire chip clicks (restore) and chip buttons
    (restore / close), toggle the dock `hidden` class.
* Windows menu (`_renderWindowsMenu`): drop maximized branch and `❐`;
  quick actions = toggle + close/open as in 3.4.
* `getWindowStates()` → `{closed: [...], minimized: [...]}`.

### 4.2 `ui/css/sash-layout.css`

* Remove `.sash-window.sash-win-minimized …`, `.sash-grid-maximized …`,
  `.sash-window.sash-window-maximized …` rules (maximize-full-grid + in-place
  minimize are gone).
* Retune `.win-controls .win-btn` to the two-button spec (equal 20 px hit
  boxes, centered glyphs, hover tints) and rename the state classes used by
  JS (`.win-toggle`, `.win-close`).
* Add the dock styles:
  * `.sash-min-dock` — `flex: 0 0 auto`, header-dark background,
    `border-top`, horizontal flex, `overflow-x: auto`, hidden class support;
  * `.sash-min-chip`, `.smc-label`, chip hover, chip `.win-btn` sizing;
  * `.sash-min-dock-label` (optional “🗕 Minimized” caption).
* Keep `.sash-window.sash-win-hidden { display:none }` (shared by closed and
  minimized), `.sash.sash-hidden`, `.sash-split-hidden`.

### 4.3 `ui/index.html`

* Update the Windows dropdown header/captions only (structure stays).
* Update `#windowsMenuBtn` tooltip wording (remove “maximize to full grid”
  phrasing).

### 4.4 Backend (`backend/bridge.py`, `backend/config_manager.py`)

* `get_window_states`: return `{"closed": …, "minimized": …}` (ignore any
  stored `maximized`).
* `save_window_states`: accept/validate `closed` + `minimized` only.
* `config_manager` default `window_states` → `{"closed": [], "minimized": []}`.

### 4.5 Tests (`tests/test_sash_grid_window_controls.js`, new)

Node test against the real shipped `ui/js/sash-grid.js` + `ui/js/sash-core.js`
with a small DOM stub that executes the actual render pipeline. Asserts:

1. Every rendered window has exactly `.win-toggle` (`─`, tooltip
   `Minimize …`) and `.win-close` (`✕`, tooltip `Close …`).
2. `minimizeWindow(id)`:
   * adds the id to `minimizedWindows`, persists to localStorage;
   * marks the window's `.sash-window` wrapper `.sash-win-hidden`
     (⇒ grid space released, the *same* class the verified close path uses);
   * does NOT add the panel-level `.hidden` / `sash-win-closed` classes;
   * creates a dock chip with the window title, a `□` restore button and an
     `✕` close button; the dock is visible.
3. `toggleMinimize` / dock chip click restores: wrapper un-hidden, dock chip
   gone, localStorage updated, window back to `●/Open` in the menu.
4. `closeWindow` on a minimized window removes it from the dock + sets it
   closed.
5. No `.sash-window-maximized`/`maximizedWindow` leftovers; old localStorage
   `…maximized.v1` values are ignored on load.
6. Windows menu shows correct state glyph/badge per state; quick buttons
   wired.
7. `showAllWindows` clears minimized + closed and empties the dock.
8. Static CSS contract: `.sash-window.sash-win-hidden{display:none}` present,
   minimized/docked CSS present, obsolete `.sash-win-minimized` /
   `.sash-window-maximized` rules absent.

Existing tests (grid persistence, `test_sash_webengine.py`) must stay green —
they exercise the close path and generic grid code that is unchanged.

---

## 5. Behaviour matrix (acceptance)

| Action | Result |
|---|---|
| Click `─` on an open window | Window content + title leave the grid; a slim title strip appears in the bottom dock; all remaining open windows expand into the freed space (same code path as close ⇒ verified geometry); no empty band remains anywhere. |
| Click `□` on the docked strip (or the strip label, or the menu toggle) | Window returns to its previous slot/size; strip disappears. |
| Click `✕` | Window closes; reopenable from Windows dropdown; space redistributed (unchanged). |
| Dropdown | Shows ● Open / ─ Minimized / ○ Closed per window with badges + quick buttons; row click opens/closes/restores sensibly. |
| Icons/tooltips | Standard `─` `□` `✕` glyphs, equal size/spacing, dark theme, hover tints, `title` tooltips on every icon. |
| Reload | minimized/closed sets restored from localStorage/backend; old `maximized` value ignored. |
| Drag & drop / sash resize | Unchanged; minimized windows are excluded from drag targets while hidden (as closed ones already are). |

---

## 6. Files changed

* `docs/WINDOW_CONTROLS_MINIMIZE_DOCK_FIX_DESIGN_2026-09-08.md` (this file)
* `ui/js/sash-grid.js` — state model + dock + controls + menu rework
* `ui/css/sash-layout.css` — control icons, dock styles, remove obsolete rules
* `ui/index.html` — caption/tooltip wording
* `backend/bridge.py` — `window_states` closed/minimized only
* `backend/config_manager.py` — default `window_states`
* `tests/test_sash_grid_window_controls.js` — new regression tests
