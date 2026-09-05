# Flexible Grid Window System ("Sash Layout") — Design

**Date:** 2026-09-05
**Status:** Approved for implementation
**Feature request:** every content sub-window (Chat Composer, People/User Memory,
Terminal Log Console, plus Stats, Filters, Action Stack, Block Config) must be
freely draggable, splittable, mergeable and resizable; the top menu bar (app
header + URL/Language/Presets toolbar) stays pinned.

---

## 1. Problem & current state

`ui/index.html` today has a **hard-coded static layout** (four fixed flex
zones, none of which the user can change):

```
┌────────────────────────────────────────────┐
│ header  (app title, tab select, connect)   │  pinned
├────────────────────────────────────────────┤
│ URL toolbar (URL Presets, chips)           │  pinned
├──────────┬─────────────────────────────────┤
│ sidebar  │ center                          │
│ stats    │ action stack                    │
│ filters  │ block config (hidden)           │
├───────────────────────────────────────────┤
│ composer                                   │
├────────────────────────┬───────────────────┤
│ user memory (table)    │ log console       │
└────────────────────────┴───────────────────┘
```

Zone heights/widths are fixed CSS (`220px` sidebar, `260px` bottom strip,
`380px` log column). Windows cannot move across zones, cannot split/merge,
cannot be resized.

### Constraints discovered during audit

| # | Fact | Consequence |
|---|------|-------------|
| C1 | Panels are `.panel` divs whose **internal state lives in the DOM** (composer textarea, log entries, rendered table rows, open menus) | Panels must be **re-parented, never re-created**. The grid builds *wrapper* nodes around the persistent panel elements. |
| C2 | Three floating overlays (`#presetPicker`, `#addBlockMenu`, `#varMenu`) are `position:absolute` with **viewport coordinates** from `getBoundingClientRect()` | They only work because panels are currently *non-positioned* (containing block = viewport) — and they get clipped by `.panel { overflow:hidden }`. Fix: switch all three to `position: fixed` (coords are already viewport-based) → safe wherever a panel sits in the grid, no clipping. |
| C3 | `#blockConfigPanel` is toggled with the `.hidden` class by `stack-dnd.js` | A hidden window must collapse cleanly. CSS `:has()` (Chromium ≥105; Qt WebEngine in PySide6 ≥6.6 is Chromium 112): `.sash-window:has(> .hidden) { display:none }`. Flexbox then redistributes the space to visible siblings automatically — no JS change in `stack-dnd.js`. |
| C4 | `StackDrag` (block reordering) listens for `pointerdown` on `#stackList` only, window dragging listens on panel title bars (`h3`) | No event conflict; both engines coexist. Drag-from-title ignores `button/input/select/textarea` targets so the run/pause/stop/filter buttons keep working. |
| C5 | Qt WebEngine (Chromium 112) | `:has()`, `replaceChildren`, Pointer Events all supported. No polyfills. |
| C6 | Repo rules: pure logic must be executable by tests (`docs/AGENT_RULES.md` RULE 6) | Tree model lives in a **DOM-free module** (`ui/js/sash-core.js`) with a UMD export so `node` can `require()` the *shipped file* directly. |

---

## 2. Chosen architecture: **split tree (nested splitters with sashes)**

### Why a split tree and not a fixed CSS Grid with row/column spans

| Criterion | CSS Grid + spans | Split tree |
|---|---|---|
| Drop next to / above / below → "new column/row" | Requires a bento-style grid reflow algorithm (find a free cell, shift existing spans) — O(n²) fiddly logic, many degenerate cases | Trivial: *split the target leaf in half* |
| Window spanning multiple rows/columns (Layout C: log console as full-height side column) | Requires explicit `grid-row: span 2` bookkeeping + reflow on every edit | **Emerges for free from nesting** — a leaf next to a sub-split spans its whole height |
| Edge resize, structure preserved, neighbors adapt proportionally | Tricky (must decide which track resizes) | Local operation: two sibling flex-grows change, flexbox normalizes the rest |
| "Same row" merging (drop Chat onto People's row) | Needs row detection + span merge | Insert as a sibling in the parent split |
| Serialization / persistence | Complex (cell map) | The tree *is* the serialisation |

The split tree is the same structure used by desktop window managers and
IDE layout systems; every requirement in the feature request maps to a small
local operation on it.

### 2.1 Data model

```js
// Leaf — one window
{ t: 'leaf', id: 'composer' }

// Split — N (≥2) children laid out in one direction
{ t: 'split',
  dir: 'row' | 'col',      // 'row' = side-by-side (vertical sash),
                           // 'col' = stacked     (horizontal sash)
  children: [ node, node, … ],
  sizes:    [ 50, 50, … ]  // percent per child, sums to 100
}
```

* `dir: 'row'` → children left→right, sash is vertical (`col-resize` cursor).
* `dir: 'col'` → children top→bottom, sash is horizontal (`row-resize` cursor).
* N-children (not binary) keeps "insert into a row/column" a flat array
  insert and matches CSS flex directly.

Windows (7, fixed set — `SashCore.WINDOWS`):
`stats, filters, stack, config, composer, people, log`.

A valid tree is a permutation of the 7 window ids, depth < 12, every split
has `sizes.length == children.length`, all sizes > 0.

### 2.2 Pure operations (`sash-core.js`, no DOM)

| Op | Meaning (feature request) | Tree effect |
|---|---|---|
| `moveWindow(root, draggedId, drop)` | **THE drop operation** (see below) | Atomic *move* (never a copy): insert at the drop spot, then remove the original node **by identity**. |
| `splitLeaf(root, targetId, newId, dir, newFirst)` | **Split**: drop on an edge of a window | Target leaf is replaced by `{split, dir, [target,new], [50,50]}` (order per `newFirst`). Parent keeps the same space → "Chat Composer takes left half, People Memory takes right half". |
| `insertAtSplitIndex(root, refId, index, newId, donorId)` | **Merge into a row/column**: drop into the *center* of a window | New leaf inserted in the target's parent split; the *donor* (default: the target) gives up half its size. |
| `insertSibling` / `insertBetween` | Convenience wrappers over the above | — |
| `removeNode(root, node)` / `removeLeaf(root, id)` | Used by `moveWindow` | A 2-child split that loses a child **collapses** to the remaining child; a 3+-child split **renormalises** its sizes (neighbours adapt proportionally). |
| `setSplitSizes(root, childId, sizes)` / `setSplitSizesByPath(root, path, sizes)` | **Resize commit** | Replace a split's `sizes` array (normalised). |
| `nodeAtPath` / `parentPath` / `leafPaths` / `normalizePath` | Path addressing (used by the DOM layer and resize commit) | — |
| `normalizeSizes(sizes)` | — | Clamp each ≥ 0.5, scale so sum = 100. |
| `validate(tree, ids)` / `leafIds(tree)` / `findNode(tree,id)` | Persistence safety | Full structural validation incl. leaf-id **set equality** (duplicates & missing windows rejected), size sums ≈ 100, depth limit. |
| `defaultTree()`, `layoutA()`, `layoutB()`, `layoutC()` | Preset layouts | See §5. |

**Why insert-then-remove (implementation finding):** removing first makes the
drop target's location ambiguous — a *center* drop on a window whose sibling
row had exactly two members would collapse that row out of existence, so
"drag log onto people" would stack them full-width instead of keeping their
row. Inserting first (targets located in the pre-removal tree, where they are
stable) and then removing the original node **by identity** (never "first
leaf with this id" — the inserted copy could come first in traversal order)
makes every drop a move, and the shared row survives sibling swaps.

All mutators mutate the in-memory tree in place and return it (single source
of truth; the DOM layer re-renders wrappers on commit, re-parenting the
persistent panels — C1).

### 2.3 DOM structure rendered from the tree

```html
<main class="sash-grid" id="sashGrid">
  <div class="sash-split sash-col">                 <!-- root split -->
    <div class="sash-window" data-win="composer">   <!-- leaf -->
      <div class="panel composer-panel" id="winComposer"> …persistent… </div>
    </div>
    <div class="sash sash-h"></div>                 <!-- sash, 6px hit area -->
    <div class="sash-window" data-win="people">
      <div class="panel table-panel" id="winPeople"> …persistent… </div>
    </div>
  </div>
</main>
```

* `.sash-grid` — `flex:1; min-height:0` → everything below the pinned
  header/URL toolbar. **Nothing above the grid is a drag target** (requirement 4).
* `.sash-split` — `display:flex; flex-direction: row|col`; children get
  `flex: <size> 1 0%` (percent drives proportional layout at any window size).
* `.sash-window` — leaf frame; `:has(> .hidden)` hides a window and lets
  flexbox redistribute (C3).
* `.sash` — 6px flex child, visual 2px line; `cursor: col-resize|row-resize`.

---

## 3. Drag & drop (window rearrangement)

### 3.1 Pickup

* Handle: the window **title bar** (the panel's `h3`), with a `drag_indicator`
  grip icon on the left. Whole bar is grabbable; `button/input/select/textarea`
  inside it (run/stop, search, close-config) do **not** start a drag (C4).
* Pointer Events + 4px threshold (same feel as `StackDrag`); left button only.
* On pickup:
  * floating **clone** of the window follows the cursor 1:1 (`position:fixed`,
    translate3d, glow + shadow);
  * if the panel has > ~350 descendants (big table / long log) a compact
    **ghost card** (icon + title, 240×56) is used instead — keeps dragging fast;
  * source window dims to 35% with a dashed accent outline (`.sash-drag-source`);
  * **rects of all visible windows + all sashes are cached** once (`getBoundingClientRect`);
    the grid never scrolls (viewport-locked) so the cache stays valid;
  * `body.sash-dragging` disables text selection.
* **Escape cancels** (restores source), pointerup on the cursor applies the
  highlighted drop.

### 3.2 Drop zones (hit test, per pointer position)

```
        ┌────────────── T ──────────────┐
        │  top strip    │  center  │     │
        ├──────┬──────────────────┬────┤
        │ left │                   │right│   strip thickness
        │      │     (center)      │     │  Z = clamp(0.22·min(Tw,Th), 20, 44)px
        ├──────┴───────────────────┴────┤
        │            bottom strip       │
        └───────────────────────────────┘
```

| Pointer location | Drop spec | Result |
|---|---|---|
| Left/right strip of T | `edge` (dir `row`, new window left/right) | **Splits T in half** → T + dragged side by side. Requirement: "dropping a window next to another on the same row splits that row". |
| Top/bottom strip of T | `edge` (dir `col`, new above/below) | Splits T into a stacked pair. |
| **Center** of T (T has a parent split P) | `sibling` before/after T — side chosen by pointer vs T's midpoint along P's axis | **Joins T's row/column**: T's split gains a child. This is the *merge* case (two windows become siblings of the same row). |
| Center of T, T is the **root** (whole grid is one window) | `edge` along dominant axis, side = pointer side | Splits the root. |
| On a **sash** | `between` (insert between the sash's two children, side by pointer half) | Inserts the window into the row/column at that exact gap. |
| Over the dragged window itself | — | No drop (indicator hidden). |

Ambiguity policy (documented in the hint tooltip): an edge strip always
*split-s the hovered window*; to *insert between* two neighbours, drop on the
centre of either neighbour or on the sash.

### 3.3 Live feedback during drag

* hovered window gets an accent outline (`.sash-drag-target`);
* a glowing **drop indicator bar** shows the exact split/insert line:
  edge → bar across T at its 50% on the split axis; sibling → bar at T's
  outer edge spanning the *whole parent split*; sash → bar along the sash
  spanning the whole split;
* a **badge** next to the cursor names the outcome:
  `"Message Composer → left of Action Stack"` / `"… between Stats and Filters"`.

### 3.4 Commit

1. Map spec → `SashCore` op (§2.2).
2. Re-render wrapper tree (panels re-parented, state intact — C1).
3. Persist to `localStorage["chatbot.sashLayout.v1"]`.
4. Flash the landed window (`outline` pulse) + one log line:
   `🧩 Composer → left of Action Stack (new row split)`.

---

## 4. Resizable edges (sashes)

* Every sash is a 6px hit area (2px visible line, accent on hover/active).
* **Pointer down on sash** between siblings i, i+1 of split P (dir D):
  * `body.sash-resizing` locks cursor + selection;
  * per pointermove (row case; col is mirrored):
    ```
    rect    = P.getBoundingClientRect()
    others  = Σ widths of the other children (display:none → 0)
    span    = rect.width − others − (n−1)·sashW
    xStart  = rect.left + Σ widths before i + i·sashW
    bound   = clamp(pointerX, xStart+MIN, xStart+span−MIN)   MIN = 64px
    wA, wB  = bound − xStart , span − (bound − xStart)
    ```
    Live: set `flex-grow` of children i, i+1 to `wA, wB` (others keep theirs).
    Flexbox then normalises — **neighbouring windows adapt proportionally,
    grid structure is preserved** (requirement 3), no re-render, no layout
    invalidation of panel content.
  * Double-click a sash → that split resets to even sizes.
* **Pointer up:** measure every child's real px size, convert to percents of
  the visible span, `normalizeSizes`, `SashCore.setSplitSizes`, re-render,
  persist.

---

## 5. Preset layouts (feature request "Example Layout Scenarios")

A `📐` **Layouts** menu in the pinned header (dropdown, `position: fixed`)
applies one click to a full 7-window tree. The three spec layouts are the
*hero* placement (Composer / People / Log); utility windows get sensible
spots so the grid always tiles the viewport:

* **Default** (mirrors today's static layout):
  `col [ row [ col [stats, filters] | col [stack, config] ] , composer ,
  row [people | log] ]` — sizes ≈ 17/83, 46/24/30, 35/65, 70/30, 70/30.
* **Layout A — stacked rows** (spec "3 rows, 1 column each"):
  `col [ stats, filters, stack, config, composer, people, log ]`
  → composer / people / log are each a **full-width row**.
* **Layout B — split top row** (spec "row 1 split"):
  `col [ row [composer | people], log, row [ row [stats|filters] | stack ] ]`
  → **row 1: Composer | People side by side; row 2: Log full width**.
* **Layout C — side column** (spec "Terminal spanning both rows"):
  `col [ row [ col [composer, people] | log ], row [ row [stats|filters] | stack ] ]`
  → **Log Console spans the full height of the hero section** (both composer
  and people rows) as a tall right-side column.

Choosing a preset replaces the tree, re-renders, persists. The user's manual
arrangement always wins until the next preset choice.

---

## 6. Persistence & safety

* `localStorage["chatbot.sashLayout.v1"] = JSON.stringify({v:1, tree})`,
  written on every drop / resize / preset commit (try/catch — private Qt
  profiles without storage fall back to in-memory only).
* On start: parse → `SashCore.validate(tree, WINDOWS)` (leaf-id set equality,
  sizes, depth) → use it, else `defaultTree()`. A corrupted layout can never
  brick the UI.
* Versioned key: future schema changes read the old key gracefully.

---

## 7. Files

| File | Change |
|---|---|
| `ui/js/sash-core.js` | **new** — pure tree model + ops + presets (UMD, node-testable) |
| `ui/js/sash-grid.js` | **new** — DOM layer: render, drag, sash resize, persistence, layout menu |
| `ui/css/sash-layout.css` | **new** — grid/sash/window/drag-visual styles |
| `ui/index.html` | panels moved into `#sashGrid` (old static zones removed), ids `winStats…winLog`, grip icons in title bars, `📐 Layouts` button in header |
| `ui/css/layout.css` | `.panel` title-bar treatment in grid context; fixed top row untouched |
| `ui/css/stack.css`, `ui/css/composer.css` | pickers/menus `position: absolute → fixed` (C2) |
| `tests/test_sash_core.py` | **new** — runs the *shipped* `sash-core.js` through `node` (RULE 6) |
| `tests/test_sash_webengine.py` | **new** — offscreen Qt WebEngine loads `index.html`, asserts real DOM + simulated drops/resizes, zero JS console errors |
| `README.md` | new "Flexible Grid Layout" usage section |

**Unchanged:** all backend modules, `stack-drag.js` (block reorder),
`stack-dnd.js`, `user-table.js`, `log-console.js`, `presets-ui.js`,
`composer.js`, `url-toolbar.js` — the panels they touch are only moved in
the DOM, never re-created.

---

## 8. Risk register

| Risk | Mitigation |
|---|---|
| Panel state lost by re-render | Panels are persistent DOM nodes re-parented into leaf wrappers; only wrapper skeleton is rebuilt (C1). |
| Floating pickers clipped/misplaced after a move | `position: fixed` + already-viewport-based coordinates (C2). |
| Hidden Block-Config window leaves a hole | `:has(> .hidden)` → `display:none`; flexbox redistributes (C3). |
| Drag vs. in-title buttons conflict | ignoreSelector on `button,input,select,textarea` (C4); 4px threshold keeps clicks clean. |
| Big clone (500-row table) janks the drag | ghost-card fallback above 350 descendants. |
| Corrupt localStorage layout | full structural validation, versioned key, default fallback (§6). |
| Resize math drift at small sizes | 64px hard minimum per child; commit recomputes sizes from measured px. |
| Qt WebEngine feature gaps | only Chromium ≥105 features used (§1, C5). |

---

## 9. Tests (implemented & passing)

1. **`tests/test_sash_core.py`** — 21 tests, node, the *shipped* file:
   default & A/B/C trees validate; edge drop = "left half / right half";
   `moveWindow` is a move, not a copy (no duplicates, 2-child row survives a
   sibling swap, 3-child renormalisation, split collapse); sash drops between
   sub-split groups; `setSplitSizes(ByPath)` + `normalizeSizes`; Layout C
   structure (log spans a 2-window col split); corrupt/invalid/duplicate/
   wrong-sum deserialisations rejected; serialize round-trip stable.
2. **`tests/test_sash_webengine.py`** — offscreen PySide6, **real Chromium**
   (skips itself when QtWebEngine is unavailable):
   * page loads with **zero JS console errors**, fake QWebChannel bridge
     (exact slot signatures of `backend/bridge.py`)
   * 7 windows rendered, Block Config hidden, header + URL toolbar pinned
     **above** the grid (measured rects)
   * `simulateDrop` → tree validates AND the rendered DOM shows the split
     side-by-side (real layout rects)
   * sash drag via dispatched **PointerEvents** → boundary lands at the
     pointer fraction (~35% measured), sizes commit to tree + `localStorage`
   * window drag via dispatched **PointerEvents** → dragging state, clone,
     glowing indicator, badge, dimmed source all present mid-drag; drop
     commits; **Escape cancels** with the layout untouched
   * double-click a sash → split resets to even sizes
   * preset C → log window's rendered height ≥ composer+people (real span)
   * full page **reload** restores the persisted layout
3. Verified on real Chromium 112 (Qt WebEngine, PySide6 6.6.3): screenshots
   of Default / A / B / C all match the spec scenarios.
4. Manual smoke checklist: drag each window to every position, resize every
   sash, hide/show Block Config mid-layout, Escape-cancel, double-click sash.
