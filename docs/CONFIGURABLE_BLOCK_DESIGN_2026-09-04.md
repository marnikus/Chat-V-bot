# Design — Configurable Action Block Constructor ("Find & Click")

**Date:** 2026-09-04 (fourth round)
**Status:** Design → implemented → verified
**Scope:** Make the Action Stack's *configurable search-and-click constructor*
a first-class, clearly understandable feature that satisfies every point of the
request, and prove each capability works (previous rounds' implementations
were reported non-working — we verify with a runnable workflow harness, not
with assumptions).

## 1. Understanding the request

Wanted: a UI-created, reusable action block that
1. finds a web element by a CSS selector,
2. supports **two separate search fields** — the clickable "box"
   (e.g. `div[role='tab'].tab-item`) and a *different* element used to
   confirm the match (text inside the box, e.g. `p.chat-title`),
3. can click the found element or not,
4. has a user-defined custom name ("Find Settings Button"),
5. is savable as a preset and reusable later,
6. is removable when no longer needed,
7. lets the user type the CSS selectors themselves.

## 2. Audit of the current branch (what already exists)

This branch already ships a `CUSTOM_FIND` block ("Find & Click") whose
**every requested capability maps to a live code path** — built during the
earlier "session restore / single preset store" round:

| Request | Implementation |
|---|---|
| CSS search field 1 (the box) | `selector` → DOM probe `querySelectorAll` |
| CSS search field 2 (confirm text element) | `label_selector` → inner element text is read for the match |
| Click / don't click | `click_enabled` (+ `click_selector` to click an inner element instead) |
| Custom name | `custom_name` (shown on card + in logs) |
| Save as reusable preset | `Save Block as Preset` → `bridge.save_custom_block` → persisted in the single `config.json` store |
| Reuse later | chip click / top of **+ Add** menu re-inserts the full config |
| Remove presets | chip `×` → confirm modal → `bridge.delete_custom_block` |
| User-defined selectors | plain-text CSS inputs |

Backing it: `actions/custom_find.py` (execute via `backend/dom_probe.py`
probe), registration in `actions/__init__.py`, UI builder in
`ui/js/stack-dnd.js`, preset chips + menus in `ui/js/presets-ui.js`, storage
slots in `backend/bridge.py` (`list/save/delete_custom_block` →
`config.json`), session restore of the chips in `ui/js/app.js`.

**Workflow probe (jsdom, real UI + stub bridge) currently passes** for:
add → select → name it → set both selectors + text → save (no prompt needed
once named) → chip appears → click chip reuses the full config in a new stack
→ chip × → confirm → `delete_custom_block`. So the feature is functionally
alive.

## 3. Gaps found (why it still reads as "hardcoded / not a constructor")

1. **The stack card shows a raw `key=value` dump** for the block
   (`name="…" · selector=… · label_selector=… · match_text=… · click=on`)
   instead of a human sentence — nothing communicates "two search fields".
2. **Config fields are generic, order is arbitrary and labels are vague**
   (`Element to find (CSS)` / `Text element inside (CSS)`), and there is no
   hint explaining the two-field model. A user does not see that field ① is
   the box and field ② is the separate text/confirm element.
3. **Save button is not context-aware**: it always says "Save Block as
   Preset", even when the current block is already a saved preset (should be
   "Update preset"). There is also no visual confirmation of which mode ran.
4. Missing dedicated user documentation for the constructor workflow
   (README covers it thinly under an unrelated heading).

## 4. Design of the changes (all UI/docs; zero backend-logic risk)

1. **Human-readable card summary** for `CUSTOM_FIND` blocks in the stack
   (replaces the k=v dump; other blocks keep theirs). Examples:
   - click mode: `Find “Settings” inside p.chat-title in div[role='tab'].tab-item → click the found box`
   - click-inner mode: `… → click .btn inside it`
   - verify mode: `… → check only, no click`
   `_esc()`-ed like the current summary (user text stays safe).
2. **Constructor-style config panel** for `CUSTOM_FIND` only (other blocks are
   untouched):
   - fields laid out stacked (label over input), full width, canonical order:
     name → ① box selector → ② confirm/text selector → match text → click
     toggle → (optional) inner click selector → pre-delay;
   - explicit labels: "Element to find — the clickable box (CSS)" /
     "Separate text element inside the box to confirm (CSS)";
   - a small hint under the two search fields explaining the two-field model;
   - an icon+description header line showing what the block currently does.
3. **Context-aware save button**: when the current `custom_name` already
   exists among saved presets the button reads "Update preset “name”"; for a
   never-saved name it reads "Save as new preset". The button label is kept
   in its own span (icon preserved).
4. **README**: dedicated section documenting create → name → two search
   fields → click/verify → save → reuse → update/delete, including the
   example "Find Settings Button".

## 5. Follow-up (user preference): circular create / save / delete buttons

The stack header **＋ button** and the config panel's **save** control were
initially small square/rectangular buttons. Per user preference the controls
around newly added action blocks are now **round icon buttons**:

- `#addBlockBtn` — circular accent **＋** (opens the + Add menu → create a new
  constructor block);
- `#saveCustomBlockBtn` — circular **bookmark** save/update button (tooltip +
  inline caption still distinguish “Save as new preset” vs “Update preset
  “name””);
- `#deleteBlockBtn` — new circular **🗑** that removes the currently selected
  block from the stack (re-render, panel close, session snapshot).

Style lives in `layout.css` (`.btn-round`, `.btn-round--accent`,
`.btn-round--danger`); verified by the constructor harness assertions 0a–0c
and 16–17c.

## 6. Acceptance / verification plan

- jsdom workflow harness (extended from the audit probe): the full
  constructor lifecycle through the real DOM, asserting each bridge payload,
  chip/menu refresh, per-key config edits, update-vs-new button state, and
  human-readable summary text.
- Regression: existing jsdom UI harnesses (people-list merge + general UI)
  must stay green; every `ui/js/*.js` passes `node --check`.
- Backend: engine round-trip (build `CUSTOM_FIND` from a config dict →
  `to_dict()` keeps all fields incl. quotes/emoji), and Bridge
  save/list/delete custom block persistence across a fresh `ConfigManager`
  (single `config.json`) instance.
