# Fix Design — User-Memory Deletion & Drag-and-Drop Stack Reordering

**Date:** 2026-09-04 (second round)
**Status:** Designed → Implemented → Verified (headless browser harness)
**Scope:**
- **BUG #4** — “Clear All” (and “Reset Messaged”) in the *User Memory* people list do nothing.
- **FEATURE #5** — Delete an individual nick (and an arbitrary multi-selection), not only “delete them all”.
- **FEATURE #6** — Action-Stack blocks must be reorderable by drag & drop, with a *clearly visible* effect while dragging and a highlight of the slot the block will occupy when released.

---

## 1. Understanding the problem — root-cause analysis

### BUG #4 — “Clear All” / “Reset Messaged” are dead buttons

The buttons exist in the markup:

```html
<!-- ui/index.html -->
<button id="resetMsgBtn" class="btn-small">Reset Messaged</button>
<button id="clearMemBtn" class="btn-small btn-danger-text">Clear All</button>
```

An exhaustive grep over `ui/js/**` shows **no listener is ever attached** to either id:

| id | markup | JS listener | backend slot | verdict |
|----|--------|-------------|--------------|---------|
| `resetMsgBtn` | ✅ present | ❌ **none** | ✅ `Bridge.reset_messaged()` | dead button |
| `clearMemBtn` | ✅ present | ❌ **none** | ✅ `Bridge.clear_memory()` | dead button |

So the whole click → bridge → SQLite chain is broken at the very first link. The
backend half (`Bridge.clear_memory` → `UserMemory.clear_all` → `_refresh_users`)
is fine and already re-emits `users_updated`; only the wiring is missing.

Two secondary defects make the panel look broken even when data changes:

1. **The table is never populated at startup.** `Bridge._refresh_users()` is
   only awaited from `_do_connect`, `_do_reset`, `_do_clear`. Before the user
   connects to a Chrome tab the table permanently shows the “No users
   discovered yet” placeholder even though `chatbot.db` may hold hundreds of
   rows. There is **no `refresh_users` slot** the UI could call on boot.
2. **Confirmation is impossible.** `Clear All` is destructive, and Qt WebEngine
   does not reliably support `window.confirm()`. The repo already solved this
   for presets with the in-app `#confirmModal` + `PresetsUI.confirmDelete`; the
   people list must reuse it instead of a browser dialog.

### FEATURE #5 — no way to delete one nick

`UserMemory` exposes only `clear_all()` (`DELETE FROM users`) — it is
all-or-nothing:

```python
async def clear_all(self) -> int:
    cur = await self._db.execute("DELETE FROM users")
```

There is no `delete_user`, no bridge slot, and the per-row buttons that *do*
exist are cosmetic — they only print to the log console:

```js
_action(type, nick) {
  if (type === 'message') LogConsole.log(`👤 Manual message: ${nick}`, 'info');
  else LogConsole.log(`⏭ Skipped: ${nick}`, 'warn');
}
```

The row markup also interpolates the nick straight into an inline
`onclick="UserTable._action('message','…')"` attribute. Nicknames on this
platform routinely contain apostrophes, quotes and emoji
(`m_Винкельчпок 😋`, `хвастаюсь попкой`), so a single `'` in a nick produces a
**syntax error inside the attribute** and the row's buttons stop working
entirely. Any per-row delete must therefore be delegated, not inlined.

### FEATURE #6 — drag & drop reordering is unreliable / invisible

`ui/js/stack-dnd.js` delegates reordering to **SortableJS fetched from a CDN at
runtime**:

```js
_initSortable() {
  if (typeof Sortable === 'undefined') {
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/sortablejs@1.15.0/Sortable.min.js';
    s.onload = () => this._createSortable();
    document.head.appendChild(s);
  }
}
```

Failure modes, all of which end with *“drag does nothing”*:

1. The UI is loaded as `file://…/ui/index.html` inside `QWebEngineView`. A
   `file://` document requesting a remote script is blocked or fails silently in
   many Chromium/QtWebEngine configurations, and **`s.onerror` is not handled**,
   so `_createSortable()` is simply never called and no error is surfaced.
2. The app is an *offline desktop automation tool*; requiring internet access
   for a core editing gesture is wrong by design.
3. Even when the CDN load succeeds, the visual feedback is minimal: the
   stylesheet only defines `.sortable-ghost { opacity:.3 }` and
   `.sortable-chosen { box-shadow: … }`. **Nothing indicates the slot the block
   will land in** — the user cannot see the resulting position before releasing.
4. `onEnd` mutates the array with the raw DOM indices
   (`this.stack.splice(evt.oldIndex, 1)`). Those indices count *all* element
   children of `#stackList`, which also hosts the `.stack-empty` placeholder
   node, so the mapping is only accidentally correct.
5. Re-rendering with `innerHTML` after every change destroys and recreates the
   nodes Sortable holds references to.

**Conclusion:** replace the CDN dependency with a self-contained, dependency-free
Pointer-Events reorder engine that ships with the app and provides explicit,
loud visual feedback.

---

## 2. New structure — design

### 2.1 Module map

| File | Status | Responsibility |
|------|--------|----------------|
| `backend/user_memory.py` | edited | + `delete_user`, `delete_users`, `set_messaged`, `get_user` |
| `backend/bridge.py` | edited | + `refresh_users`, `delete_user`, `delete_users`, `set_user_messaged` slots; `users_deleted` signal |
| `ui/js/stack-drag.js` | **new** | `StackDrag` — dependency-free pointer-based reorder engine with live insertion preview |
| `ui/css/stack-drag.css` | **new** | Drag visuals: lifted card, gap animation, glowing insertion bar, drop-slot highlight, landing flash |
| `ui/js/user-table.js` | rewritten | Selection checkboxes, per-row delete, bulk delete, search, toolbar wiring, delegated events, HTML-safe nicks |
| `ui/js/stack-dnd.js` | edited | Drop SortableJS; render stable DOM; delegate reordering to `StackDrag`; keyboard reordering |
| `ui/js/app.js` | edited | `UserTable.init()`, initial `refresh_users()`, `users_deleted` signal |
| `ui/js/presets-ui.js` | edited | Generic `PresetsUI.confirm(title, text, okLabel, onYes)` re-used by the people list |
| `ui/index.html` | edited | People-list toolbar (search, selection counter, Delete selected), select-all + checkbox column, new css/js includes |
| `ui/css/table.css` | edited | Selection column, selected-row styling, toolbar, danger buttons |

### 2.2 Interface contracts

**Python — `UserMemory`**

```python
async def delete_user(self, nick: str) -> bool          # True if a row was removed
async def delete_users(self, nicks: list[str]) -> int   # number of rows removed
async def set_messaged(self, nick: str, messaged: bool) -> bool
async def get_user(self, nick: str) -> UserRecord | None
```

`delete_users` executes a single parameterised `DELETE … WHERE nick IN (…)`
statement (chunked at 500 placeholders) inside one transaction.

**Python — `Bridge` slots (JS-callable)**

```python
@Slot()                 def refresh_users()             # emits users_updated + stats_updated
@Slot(str)              def delete_user(nick)           # one nick
@Slot(str)              def delete_users(nicks_json)    # JSON array of nicks
@Slot(str, bool)        def set_user_messaged(nick, messaged)
```

New signal `users_deleted = Signal(str, int)` → `(json_of_nicks, count)` so the
UI can drop its selection state for rows that no longer exist.

**JS — `UserTable`**

```js
UserTable.init()                 // wire toolbar + delegated row events (once)
UserTable.render(users)          // re-render, preserving selection & filter
UserTable.selected               // Set<string> of selected nicks
UserTable.deleteNick(nick)       // confirm → bridge.delete_user
UserTable.deleteSelected()       // confirm → bridge.delete_users
UserTable.clearAll()             // confirm → bridge.clear_memory
UserTable.resetMessaged()        // confirm → bridge.reset_messaged
```

**JS — `StackDrag` (new engine)**

```js
StackDrag.attach({
  container,            // scrollable element holding the items
  itemSelector,         // '.stack-item'
  handleSelector,       // '.drag-handle' (null ⇒ whole card draggable)
  ignoreSelector,       // controls that must not start a drag
  onReorder(from, to),  // commit callback — array move semantics
  onPreview(from, to),  // optional live callback (used for the status badge)
});
StackDrag.detach()
```

### 2.3 Drag interaction model (FEATURE #6)

Pointer Events (`pointerdown`/`pointermove`/`pointerup` + `setPointerCapture`)
are used rather than HTML5 drag-and-drop, because HTML5 DnD gives no control
over the drag image in QtWebEngine and behaves inconsistently on `file://`.

Lifecycle:

| Phase | Behaviour | Visual |
|-------|-----------|--------|
| `pointerdown` on handle/card | record origin, cache item rects | cursor `grabbing` |
| move > **4 px** | drag officially starts | source card becomes a **drop slot** (dashed accent outline, inner glow, keeps its height); a **floating clone** is appended to `<body>` |
| `pointermove` | clone follows the cursor 1:1; target index = first item whose vertical midpoint is below the pointer | clone is lifted: `scale(1.03)`, `rotate(-1.2deg)`, strong shadow, accent border, `cursor: grabbing`; every other card **slides** (`transform: translateY(±h)`, 180 ms `cubic-bezier(.2,.8,.2,1)`) to open the gap; a **glowing insertion bar** (accent gradient, pulsing) is drawn exactly at the release position; a **position badge** (`3 → 5`) follows the cursor |
| near top/bottom edge | container auto-scrolls (proportional speed, `requestAnimationFrame`) | — |
| `Escape` | drag cancelled, nothing committed | everything animates back |
| `pointerup` | clone animates into the drop slot, then `onReorder(from,to)` commits and the stack re-renders | landed block flashes (`drop-landed` keyframes, 600 ms) and the log console records `↕ Moved “Type Message” 3 → 5` |

Correctness rules:

- Indices are read from `data-idx` on the item, never from DOM child position,
  so placeholder/empty nodes cannot corrupt the mapping.
- `onReorder` uses array-move semantics — `splice(from,1)` then
  `splice(to,0,item)` where `to` is already expressed in *post-removal*
  coordinates — and is a no-op when `to === from`.
- The engine is re-attached after each render but keeps no node references, so
  `innerHTML` re-rendering is safe.
- Clicking a card (no movement) still selects it and opens the config panel;
  a click is suppressed only if the pointer actually moved past the threshold.
- **Keyboard fallback:** with a block selected, `Alt+↑` / `Alt+↓` move it, so
  reordering also works without a pointer.

### 2.4 People-list UI (BUG #4 + FEATURE #5)

```
┌ User Memory ─────────────── [🔍 filter] [n selected] [Delete selected] [Reset Messaged] [Clear All] ┐
│ ☐ │ Nick │ Gender │ Reg? │ Status │ First Seen │ Messaged │ Actions                                │
│ ☑ │ Ann  │ ♀      │ ✅   │ 🆕 New │ 12:04      │ —        │ [Mark done] [🗑 Delete]                 │
```

- Header checkbox selects/deselects every **currently visible** (filtered) row.
- The counter and “Delete selected” button are disabled while nothing is
  selected; the button label carries the count (`Delete selected (3)`).
- Every destructive action goes through the in-app `#confirmModal`
  (`PresetsUI.confirm`) — never `window.confirm`.
- Selection survives re-renders (`Set<nick>` intersected with the new rows).
- All row content is escaped through `textContent`; nick values travel in
  `data-nick` attributes and are read by a single delegated listener.

---

## 3. Acceptance checks

1. **Clear All** → confirm dialog → table empties, stats reset to 0/0/0, log
   shows `🗑 Cleared N users`, and the rows are gone from `chatbot.db` after a
   restart.
2. **Reset Messaged** → confirm → every row shows `🆕 New`, `Done` stat is 0.
3. **Delete one nick** (🗑 on a row) → confirm → only that row disappears; other
   rows and their state are untouched; works for nicks containing `'`, `"` and
   emoji.
4. **Delete selected** → tick 3 rows (including via the header checkbox) →
   confirm → exactly those 3 rows are deleted, counter resets, selection clears.
5. **Drag & drop** → grab a block, and while the mouse moves: the dragged card
   visibly lifts and follows the cursor, the remaining cards slide apart, a
   glowing bar marks the exact slot, and a badge shows `from → to`; on release
   the stack order matches the preview, the moved block flashes, and Run/Save
   use the new order. Works with **no network access**.
6. **No CDN dependency** — `grep -r "cdn.jsdelivr" ui/` returns nothing.
