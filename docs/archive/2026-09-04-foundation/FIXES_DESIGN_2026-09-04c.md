# Fix Design — People-List Deletion + Drag-and-Drop Stack Reordering

**Date:** 2026-09-04 (third round)
**Status:** Design → implemented → verified
**Scope / source:** These fixes exist as commit `192cc14` on branch
`arena/01a06df1-chat-v-bot`; we **port only the requested features** from it
onto our branch (`arena/01a06dc5-chat-v-bot`), adapting them to the newer
session-restore / single-store architecture already on this branch.

- **BUG — "Clear All" (and "Reset Messaged") in User Memory do nothing**
- **FEATURE — delete an individual nick (not only delete all)**
- **FEATURE — action-stack blocks reorderable by drag & drop with clear
  visual feedback**

---

## 1. Root-cause analysis (same defects confirmed on this branch)

### 1.1 Dead people-list buttons
`ui/index.html` contains `resetMsgBtn` and `clearMemBtn`, but an exhaustive
grep of `ui/js/**` shows **no listener is ever bound** to them — the backend
slots (`Bridge.reset_messaged` / `Bridge.clear_memory` → `UserMemory`
`reset_messaged` / `clear_all` → `_refresh_users`) already work. Two secondary
defects make it worse:
1. The table is only populated *after connecting to a Chrome tab*; there is no
   `refresh_users()` bridge slot for the UI to fill it at startup.
2. Destructive actions cannot be confirmed (Qt WebEngine has no usable
   `window.confirm`); the app's own `#confirmModal` must be reused.

### 1.2 No per-nick deletion
`UserMemory` only exposes `clear_all()`. Per-row buttons are cosmetic (only log
lines), and the nick is interpolated into inline `onclick` attributes, so any
nick containing `'` or emoji breaks the row markup. Fix must be delegated and
`data-*`-based; add backend `delete_user` / `delete_users` / `set_messaged`.

### 1.3 Drag & drop reordering unreliable / invisible
`ui/js/stack-dnd.js` fetches **SortableJS from a CDN at runtime**. Inside
QWebEngineView on a `file://` page that request fails silently (no
`onerror` handler) → dragging does nothing offline. Even when loaded, feedback
is minimal (`opacity:.3` ghost) — the target slot is never shown. DOM-child
indices also risk corruption from the `.stack-empty` placeholder node.

---

## 2. What we port (and how it adapts to this branch)

| Piece (from 192cc14) | Applies here | Adaptation |
|---|---|---|
| `backend/user_memory.py` `get_user`/`delete_user`/`delete_users`/`set_messaged` | clean (file identical to base) | none |
| `backend/bridge.py` `users_deleted` signal + `refresh_users`/`delete_user`/`delete_users`/`set_user_messaged` slots | merge | add to this branch's rewritten bridge (which also has session-state slots) |
| `ui/js/user-table.js` rewrite (init, confirmations, selection, filter, delegated rows) | clean (file identical to base) | needs `PresetsUI.confirm` (ported below) |
| `ui/js/presets-ui.js` generic `confirm(title,text,okLabel,onYes)` + `confirmDelete` refactor | merge | keep this branch's `promptName` and custom-block methods |
| `ui/js/stack-drag.js` (new, dependency-free Pointer-Events engine) + `ui/css/stack-drag.css` | clean (new files) | copy verbatim |
| `ui/js/stack-dnd.js` reorder integration (pos badge, `_attachDrag`, `moveBlock`, Alt+↑/↓, delegated remove) | merge | keep this branch's `CUSTOM_FIND`/`custom_name`, `setCustomBlocks`, session `notifyEdited()` |
| `ui/index.html` table controls + stack-hint + css/js includes | merge | keep this branch's URL toolbar / custom-blocks / no-settings layout |
| `ui/js/app.js` `UserTable.init()`, boot `refresh_users()`, `users_deleted` | merge | keep session-restore init |
| `ui/css/table.css`, `ui/css/stack.css` additions | clean | apply |
| `docs/…`, `README.md` | docs | adapt |

Not ported (out of scope): `ui/devpreview` mock page — this branch's UI is
verified through the jsdom bridge harness instead.

---

## 3. Acceptance checks

1. **Clear All** click → in-app confirm → backend `clear_memory` → table empty;
   **Reset Messaged** click → confirm → `reset_messaged`; both reflected live.
2. **Per-nick delete**: row 🗑 Delete → confirm → `delete_user`; also a multi-row
   selection → "Delete selected (n)" → `delete_users`; nicks with quotes/emoji
   work; select-all respects the live nick filter.
3. **Drag & drop**: pointer-drag a stack card — floating tilted clone follows
   the cursor, source becomes a dashed pulsing slot, siblings slide apart, a
   glowing insertion bar + "N → M" badge show the exact landing slot, release
   commits the reorder and keeps selection/highlight in sync; no network needed.
4. Existing session-restore, presets, and custom-block features still pass
   (regression harness).
