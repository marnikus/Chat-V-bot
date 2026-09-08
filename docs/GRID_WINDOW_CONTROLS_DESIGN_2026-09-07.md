# Grid Window Management Controls — Design

> ⚠️ **SUPERSEDED (2026-09-08).** The window-control part of this design was
> replaced after user testing: minimize now docks the title strip at the
> bottom edge (releasing the grid slot like a close), the full-grid
> "maximized" state is removed, and the controls are a ─/□ toggle pair plus
> ✕. See `docs/WINDOW_CONTROLS_MINIMIZE_DOCK_FIX_DESIGN_2026-09-08.md`
> (implemented) for the current model. Kept here for history.

Date: 2026-09-07
Status: implementation design, written before code changes
Feature request: every window in the grid must support close/reopen, minimize/maximize, and a top-bar dropdown listing all windows with open/closed state icons.

## 1. Problem statement

The flexible sash grid (SashGrid + SashCore) currently supports drag-and-drop rearrangement, sash resizing, and preset layouts, but has no per-window window-manager controls:

- No way to close a window to save space (except Block Config which uses a hidden class as a special case).
- No dropdown that lists all available windows with open/closed state.
- No minimize / maximize to manage screen space.

Requested behaviors:

1. Each window can be closed, releasing its grid space; closed windows can be reopened.
2. Top bar has a dropdown menu listing all available windows, each item shows icon indicating open/closed state, click toggles.
3. Each window supports minimize (collapse to save space) and maximize (expand to full available area) with restore.

## 2. Current state audit

- `ui/index.html`: 10 panels inside `#sashGrid`, each `.panel` with `h3.win-title` containing drag grip. Only Block Config has a close button (`#closeConfigBtn`) and pin button.
- `ui/js/sash-core.js`: pure model, WINDOWS = 10 entries (stats, filters, stack, config, composer, people, log, history, userdb, collector), VERSION=2, defaultTree etc. No window open/closed state — tree always contains all windows.
- `ui/js/sash-grid.js`: DOM layer, renders split tree, moves persistent panel elements into `.sash-window` wrappers. Handles hidden windows by detecting `.panel.hidden` or `display:none` and adding `.sash-win-hidden` class to wrapper (display:none) and `.sash-hidden` to adjacent sashes. Persistence via `SashCore.serialize()` in localStorage `chatbot.sashLayout.v1` + backend `grid_layout`.
- `ui/css/sash-layout.css`: styles for `.sash-window`, `.sash-win-hidden`, sashes, drag visuals, layout menu.
- `ui/css/layout.css`: header, panels.
- Backend `bridge.py`: grid layout validation, canonical payload, `save_grid_layout`, `get_grid_layout`, global undo history (stack/grid/people).
- `config_manager.py`: state holds `grid_layout`, `block_config_pinned`, `undo_history`, etc.

Gaps:
- No generic closed set — only Block Config hidden detection.
- No minimize/maximize state.
- No windows dropdown.
- Title bars have no window controls besides Block Config's special buttons.

## 3. Design — Data model

### 3.1 Window states (frontend)

SashGrid gains three pieces of state:

- `closedWindows: Set<string>` — ids of windows currently closed. Closed = panel hidden + wrapper `.sash-win-hidden` (releases space). Stored in localStorage `chatbot.sashWindows.closed.v1` (JSON array).
- `minimizedWindows: Set<string>` — ids collapsed to title-bar only. Stored `chatbot.sashWindows.minimized.v1`.
- `maximizedWindow: string|null` — single window that is maximized to full grid. Stored `chatbot.sashWindows.maximized.v1`.

Invariants:
- A closed window cannot be minimized or maximized. Closing a minimized/maximized window clears those flags.
- Maximized takes precedence: when a window is maximized, all other windows are visually hidden (but their closed/minimized states remain in memory).
- Minimized windows stay in tree, keep their allocated size, but content is collapsed and flex is forced to minimal height (title bar only).
- Closed windows stay in tree (size preserved) but wrapper is `display:none`, so siblings expand — same as current Block Config behavior.

Persistence:
- Frontend: three localStorage keys + synchronous save on every state change.
- Backend: optional — extend `state` in config.json with `window_states: {closed:[], minimized:[], maximized:null}`. Bridge adds `get_window_states()` and `save_window_states(json)`. If bridge present, SashGrid loads authoritative copy on init and saves to it on change (similar to grid layout). No bridge = localStorage only.
- Undo: window open/close is NOT part of global undo timeline initially (to keep scope small). Could be added later as kind 'window'. For now, global history remains stack/grid/people.

### 3.2 SashCore unchanged

SashCore stays pure split-tree model (VERSION remains 2). Window open/closed is overlay state managed by SashGrid DOM layer, not by tree structure. This avoids migration and keeps tests green. Tree always contains all WINDOWS.

If needed later, VERSION could bump to 3 with window_states in payload, but not required for MVP.

## 4. UI — Window controls

### 4.1 Title bar controls

Every `.win-title` gets a `.win-controls` container on the right side (flex, after spacer). Buttons:

- Minimize: `<button class="win-btn win-minimize" title="Minimize"><span class="material-icons">minimize</span></button>` — toggles minimized. When minimized, icon changes to `crop_square` or `fullscreen_exit`? Use `expand_less` / `expand_more`? Spec says minimize collapses. Use `minimize` for minimize, and when minimized show `crop_square`? Simpler: toggle between `minimize` and `fullscreen_exit`? We'll use `minimize` (collapse) and `add`? Better: `remove` for minimize, `fullscreen` for maximize. Let's use Material Icons:
  - minimize: `minimize` (or `expand_less`)
  - maximize: `crop_square` / `fullscreen`
  - restore: `fullscreen_exit`
  - close: `close`

Behavior:
- Click close → `closeWindow(id)` — adds to closed set, hides panel, sync hidden, save, log.
- Click minimize → `toggleMinimize(id)` — if minimized, restore; else minimize. Adds/removes class `sash-win-minimized`.
- Click maximize → `toggleMaximize(id)` — if already maximized, restore; else maximize. Adds class `sash-window-maximized` and body class `sash-has-maximized`.

Injection: SashGrid after building DOM (in `_buildNode` or post-render) ensures each panel's title has controls. For panels that already have custom buttons (stack, config, people, log, etc.), controls are inserted before existing buttons or after spacer.

CSS for minimized:
- `.sash-window.sash-win-minimized > .panel > :not(.win-title) { display:none }`
- `.sash-window.sash-win-minimized { flex: 0 0 auto !important; min-height: 32px !important; }`
- The title bar stays visible, panel content hidden.

CSS for maximized:
- When `.sash-grid.sash-grid-maximized` has a maximized window:
  - All `.sash-window:not(.sash-window-maximized)` → `display:none`
  - All `.sash` → `display:none`
  - `.sash-window.sash-window-maximized` → `flex:1 1 100% !important; position:relative; z-index:10;`
- Alternatively, make maximized window `position:fixed` covering grid area below header, but flex approach simpler.

### 4.2 Windows dropdown menu (top bar)

Header currently has:
- App title, My Nick input, layoutMenuBtn (grid_view), tab select, status dot, connect btn.

Add new button:
- `id="windowsMenuBtn"` with icon `view_in_carousel` or `window` or `widgets`, title "Windows — open/close, minimize, maximize".
- Menu container `id="windowsMenu"` with class `windows-menu layout-menu` (reuse layout-menu styles) positioned fixed.

Menu structure:
- Title: "Windows — click to toggle open/closed"
- List: one row per window (10 entries). Each row:
  - icon indicating state:
    - closed → `visibility_off` or `radio_button_unchecked`
    - open → `visibility` or `check_circle` (or `radio_button_checked`)
    - minimized → `minimize` overlay
    - maximized → `fullscreen`
  - window icon (from WIN_ICONS) + title
  - state text: "Open", "Closed", "Minimized", "Maximized"
  - Right side: quick actions? For MVP, single click toggles open/closed. Additional small buttons for minimize/maximize could be added.

Click behavior:
- If closed → openWindow(id) (removes from closed set, shows panel)
- If open → closeWindow(id)

Also need to update menu live when state changes (re-render menu content).

Menu placement: same logic as layout menu — fixed below button.

### 4.3 Integration with existing Block Config close

Existing `#closeConfigBtn` currently unpins and hides panel via StackDnD. Keep it but make it call `SashGrid.closeWindow('config')` so state is tracked in closed set as well. Pin button stays.

## 5. Implementation steps

1. Docs: this file.
2. CSS (`sash-layout.css`):
   - Styles for `.win-controls`, `.win-btn`
   - `.sash-win-minimized`
   - `.sash-grid-maximized`, `.sash-window-maximized`
   - `.windows-menu` and items `.wm-item`, `.wm-icon`, `.wm-state`
   - Ensure title bar flex layout accommodates controls.

3. HTML (`index.html`):
   - Add windows menu button in header next to layoutMenuBtn.
   - Add windows menu container `<div id="windowsMenu" class="layout-menu windows-menu hidden">...</div>` similar to layoutMenu, but dynamic content.

4. JS (`sash-grid.js`):
   - Add storage keys constants.
   - Add state fields: `closedWindows`, `minimizedWindows`, `maximizedWindow`.
   - Methods: `_loadWindowStates()`, `_saveWindowStates()`, `closeWindow(id)`, `openWindow(id)`, `toggleWindow(id)`, `minimizeWindow(id)`, `restoreMinimized(id)`, `toggleMinimize(id)`, `maximizeWindow(id)`, `restoreMaximize()`, `toggleMaximize(id)`, `showAllWindows()` update to clear closed/minimized/maximized.
   - Update `_loadTree`? Keep separate.
   - Update `render()` to apply window states after building skeleton.
   - Update `_syncHidden()` to consider closed set as well as panel hidden class.
   - Add `_ensureWindowControls()` that injects control buttons into each title bar if not present.
   - Add `_setupWindowsMenu()` similar to `_setupLayoutMenu()` but dynamic list.
   - Update `flushPersistence()` to also flush window states.
   - Update `_loadFromBackend()` to also load window states if bridge provides `get_window_states`.
   - Update `resetToDefault()` to clear window states.
   - Ensure drag still works (controls ignore drag).
   - Logging via LogConsole.

5. Backend (optional but nice):
   - `config_manager.py`: add default `window_states` in state? Could reuse existing state dict without default, handled by bridge.
   - `bridge.py`: add `get_window_states`, `save_window_states`, signal `window_states_changed`? Minimal: add slots that read/write `state.window_states`.

6. Tests:
   - Manual: open app, close each window via X, verify dropdown shows closed icon, click to reopen, verify space released/restored.
   - Minimize each window, verify collapses to title bar, space saved.
   - Maximize each window, verify full area, restore works.
   - All windows closed → grid shows empty placeholder? At least no crash.
   - Persistence: reload page, verify closed/minimized/maximized restored from localStorage.
   - Drag after minimize/maximize still works.
   - Block Config pin still works.

## 6. Edge cases & invariants

- Closing the last visible window: allowed, grid becomes empty (show placeholder text or just blank). Reopen via menu works.
- Minimized window still draggable via title bar.
- Maximized window: drag disabled while maximized (since it's full-screen).
- Sash resize while minimized: minimized window keeps minimal size, resize affects other windows.
- Double-click sash while minimized windows present: should still reset to even sizes for visible windows.
- Backend absent: localStorage only, no crash.
- Corrupt localStorage window state JSON: fallback to empty sets.
- Window controls must not interfere with existing header buttons (stack run/pause/stop, etc.) — they are in title bar, separate.

## 7. Files changed

- `docs/GRID_WINDOW_CONTROLS_DESIGN_2026-09-07.md` — this doc
- `ui/index.html` — windows menu button + menu container
- `ui/css/sash-layout.css` — new styles for controls, minimized, maximized, windows menu
- `ui/js/sash-grid.js` — state management, controls injection, menu, persistence
- `ui/js/sash-core.js` — no change (or optional VERSION bump if we decide to embed states)
- `backend/bridge.py` — optional slots for window_states persistence
- `backend/config_manager.py` — optional default for window_states

## 8. Verification matrix

- [ ] Each window has close (X), minimize (—), maximize (☐) buttons in title bar
- [ ] Close hides window and releases grid space, sash touching it disappears
- [ ] Closed window appears as closed (icon) in Windows dropdown, click reopens
- [ ] Dropdown lists all 10 windows, shows open/closed/minimized/maximized icons
- [ ] Minimize collapses window to title bar only, saves space
- [ ] Maximize expands window to full grid area, hides others, restore returns
- [ ] Restore after maximize returns to previous layout
- [ ] Windows menu toggle works for all windows
- [ ] Persistence: reload restores closed/minimized/maximized states
- [ ] Reset to default clears all window states and shows all windows
- [ ] No JS console errors, drag-and-drop still works, sash resize still works
- [ ] Block Config pin and close still work
