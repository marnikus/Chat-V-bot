# AI Connections popup and the dark dropdown — round 5

*2026-09-13. Fixes the reported bug "AI Connection Controls Implemented in Wrong
Window", and the four UI defects reported with it.*

---

## 1. What is actually wrong

Round 4 moved keys, models and endpoints out of the Prompt Editor into an AI
Connections window — but left a **connection selector** in the editor header,
and built both windows out of native `<select>` elements. The screenshots show
the result:

| Reported | Root cause |
|---|---|
| AI connection selector sits in the Prompt Editor | Round 4 split the *storage* but kept a *chooser* in the editor. Two windows can now change which AI runs, so "where do I set this?" has two answers. |
| Only Grok is offered | Connections are created by the user. A fresh install has **none**; an upgraded install has exactly the one adopted from legacy `grok.*` settings. Google is a supported provider with no row to select. |
| Selecting a connection shows no model / no API key | Those fields exist only in the AI Connections window. From the editor's dropdown there is nothing to reveal. |
| Dropdowns are white browser menus | A native `<select>` popup is drawn by the OS. No CSS in this repo can darken it. |
| Preset dropdown does not match Bookmarks | Same cause. |

The last one is the interesting bug. `select { background: #12141c }` styles the
*closed box only*; the open list is a native widget. Every dark dropdown in this
app is therefore a **div menu**, which is exactly what the Bookmarks popup
(`#layoutMenu`) already is. The fix is not more CSS — it is to stop using
`<select>`.

---

## 2. Decisions

### 2.1 One home for connections: the popup

The Prompt Editor loses the AI-connection row entirely. Its ⚙ button stays and
is the *only* entry point. Prompts run on the **active connection**, chosen in
the popup — one setting, one place, which is the whole point of the split the
bug report is asking us to finish.

Consequence: `bot_prompt_connections` and `bot_use_connection_for_prompts` lose
their only callers and are deleted. The settings side already has
`bot_connections` and `bot_use_connection`; keeping both pairs would be two ways
to do one thing (RULE 5) and two slots that can disagree.

### 2.2 Every provider is always selectable

`ConnectionStore.all()` seeds **one connection per provider** the first time it
is read, keyless. A keyless connection is not hidden — I-29 already requires it
to be listed with its `problem()` ("no API key") — so Grok *and* Google are in
the list from the first launch, each revealing its own model and key field when
selected. Adding a provider to `bot_providers.PROVIDERS` adds a row; there is no
second list to keep in sync.

Seeding is not adoption. Legacy adoption (round 4) still runs first and wins, so
an upgraded install keeps its real key and does not gain a duplicate blank row.

### 2.3 The dark dropdown is a shared component

A new `ui/js/dark-select.js` builds the same structure the Bookmarks popup uses
— an anchored `.layout-menu` panel of `button` rows with a `.lm-sub` subtitle —
over a hidden value. Both the preset chooser and the provider chooser use it, so
"matches Bookmarks" is true by construction rather than by two copied
stylesheets.

It is a *component*, not a framework: `DarkSelect.attach(host, {onPick})` and
`.setOptions(list, value)`. Roughly 120 lines, which is under RULE 18's file
floor on purpose — it is one widget.

Why not restyle `<select>`: impossible, see §1. Why not `appearance:none` plus a
hand-rolled `<option>` list: that *is* this component, minus the reuse.

### 2.4 The popup is anchored, not a modal

`#botSettingsBackdrop`'s full-screen modal becomes a `.layout-menu`-classed
panel placed under the ⚙ button by the same arithmetic `_setupLayoutMenu` uses,
dismissed by an outside click. The bug report names the Bookmarks popup as the
interaction reference; this is that interaction.

---

## 3. Shape after the change

```
Prompt Editor          tabs · preset (dark) · text · variables · Save/Cancel · ⚙
        ⚙ ───────────▶ AI Connections popup
                         connection list   (Grok · Google · any the user added)
                         provider (dark) · name · API key (masked) · model · URL
                         + New · Test · Delete · Use for prompts · Save
```

`bot-prompt.js` 413 → ~330 lines (the connection half leaves).
`bot-settings.js` 225 → ~250 (gains placement + two dark selects).
`bot_prompt_bridge.py` 13 → 11 methods.

---

## 4. What could break, and what pins it

| Risk | Pin |
|---|---|
| The editor silently keeps writing the active connection | A test asserts the editor bridge has no `bot_use_connection_for_prompts`, and that the markup has no `botConnSelect` |
| Seeding overwrites a real key with a blank row | `test_seeding_never_touches_a_configured_connection`, plus the adoption tests from round 4 |
| A seeded row is treated as usable and sends a keyless request | `problem()` is unchanged; `client_for` still refuses with `grok_no_key` |
| The dark dropdown drifts from Bookmarks | Its CSS *is* `.layout-menu`'s, extended — not redeclared |
| A dropdown becomes unreachable by keyboard | `role="listbox"`, Enter/Escape/arrows, and a test for each |

---

## 5. Outcome

Executed as designed. Every acceptance box in the report is closed.

| Reported | Fix | Pinned by |
|---|---|---|
| Selector in the wrong window | Editor's connection row deleted; `bot_prompt_connections` and `bot_use_connection_for_prompts` removed from the bridge | `test_the_editor_cannot_choose_a_connection_either`, `test_the_editor_markup_has_no_connection_dropdown` |
| Only Grok offered | `ConnectionStore._seed_missing` gives every provider a keyless row on first read | `TestConnectionsAreSeededPerProvider` (6) |
| No model / no key shown | Both live in the popup's form; picking a provider fills in its defaults | `picking a provider fills in its default model and endpoint` |
| White browser dropdowns | `ui/js/dark-select.js`, built from `.layout-menu` + `.lm-sub` — the Bookmarks panel's own classes | `tests/test_dark_select_js.js` (17) |
| Preset dropdown mismatched | Same component | `the preset menu is built from the Bookmarks panel classes` |

Two things the implementation found that the design had not:

* **The ⚙ was wired twice.** `bot-prompt.js` and `bot-settings.js` both bound
  the same button, so a toggle opened and closed it in one click. The opener now
  belongs to the window that owns it. A modal `open()` had hidden this; a toggle
  exposed it immediately.
* **The JS DOM stub handed every module a bare `<div>`.** It ignored the `id`
  and `class` the page declares, so no test could tell a popup that *reuses* the
  Bookmarks panel from one that merely resembles it, and `closest('#id')` never
  matched. `realEl()` now reads both off the markup — which is what makes the
  "it IS the Bookmarks panel" assertions meaningful rather than decorative.

* **The popup was a child of `<main class="sash-grid">`, so the grid deleted
  it.** Reported from the running app: the ⚙ opened nothing at all.
  `SashGrid.render()` ends in `gridEl.replaceChildren(frag)`, which discards
  every child of `<main>` and re-adds only the **registered window panels**
  (`winBotChat`, `winBotPrompt`, …). The popup is not a grid window, so it was
  destroyed during boot; `getElementById` then returned `null`, `init()` hit its
  own `if (!this._els.backdrop) return` guard, and the button was never wired.
  Nothing threw, and every other assertion in the suite still passed — the
  element the tests asked for was fabricated by the stub, not read from a live
  DOM. It now sits beside `#layoutMenu`, outside `<main>`, which is where the
  Bookmarks popup it was modelled on had been all along. Pinned by
  *the popup lives OUTSIDE the sash grid, or it is destroyed on boot*, verified
  by reverting the move and watching it fail.

  The general rule this encodes: **anything inside `<main>` that is not a
  registered sash window is deleted on the first render.** Overlays belong
  outside it.

Also removed: `aria-modal="true"`. It was a lie once the dialog stopped trapping
focus, and a screen reader would have announced a modal the user could click
straight out of.

### Gates

* RULE 16 gate **clean**, 0 new clone groups, 0 stale baseline entries.
* Full Python suite **3002 passed**, 1 known pre-existing failure
  (`test_engine_standalone_run`), unrelated.
* JS: `test_bot_chat_js.js` 71 → **76**, new `test_dark_select_js.js` **17**.
* Feature coverage **97.6%** (baseline 97%).
* RULE 18: every new function inside 4–20 lines. Files: `dark-select.js` 193
  and `bot_connections.py` 231 are mid-band; `bot-prompt.js` **406 → 354** now
  that the connection half has left; `bot-settings.js` 314 and `bot-chat.js` 396
  carry stated reasons. No file grew past its previous waiver.
