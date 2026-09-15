# The connection picker — master/detail redesign, round 6

*2026-09-13. Implements the "Choose AI connection" concept: a two-column
picker whose only closing action is **Select**, with a preset step that is
explicitly separate from confirming.*

---

## 1. What the report is really asking for

Strip the styling away and there are three distinct complaints. Only the first
is cosmetic.

### 1.1 The popup confirms too early (behaviour)

Today `select(id)` loads a row into the form *and* nothing else, while
`bot_use_connection` is a separate button — but the report's users read the
click itself as the commitment, and the ⚙ popup gives no way to say "I am just
looking". The requested model is a **two-stage** one that every OS file picker
uses:

| Stage | Action | Effect |
|---|---|---|
| Browse | click a row | loads it into the form. Nothing is activated. Popup stays open. |
| Commit | **Select** | saves the edits, makes it the active connection, closes. |

So `viewed` (which row the form is showing) and `active` (which connection
prompts actually run on) become **two different pieces of state**. Conflating
them is the bug; the fix is to name them apart and let only one button move
`active`.

### 1.2 Presets are ambiguous (behaviour)

"Apply Preset Settings" must *fill the form and stay open*, so the user can
review and hand-edit what it wrote. Applying is emphatically **not** selecting.

A "preset" here is a **recommended configuration for a provider** — model plus
endpoint, the values most users want. This is new: `bot_presets` is the *prompt*
preset library (I-32) and must not be touched or confused with it. Naming them
apart matters more than the feature: `bot_presets.py` stays prompt wordings;
provider defaults live on the `ProviderSpec` that already holds them.

That also means the preset card needs no storage at all. `ProviderSpec.model`
and `.url` *are* the recommended preset. The card reads them; Apply copies them
into the form fields.

### 1.3 Everything is one flat column (visual)

The current form is a single stack of `label`/`input`. The report wants
master/detail, a real header and footer, and one button system. That is CSS and
markup, plus a modest amount of render code.

### 1.4 Kimi

The mockup shows three providers. Kimi is OpenAI-compatible —
`POST https://api.moonshot.ai/v1/chat/completions`, bearer auth, reply at
`choices[0].message.content` — so it is **one row in the `PROVIDERS` table** and
zero new code. Verified against Moonshot's docs (Sept 2026). This is exactly the
"adding a provider is a table entry" claim the provider module was designed
around, so it is worth doing as proof.

---

## 2. Decisions

### 2.1 `viewed` vs `active`, and a dirty flag

`BotSettings` gains three pieces of state: `viewed` (id in the form), `dirty`
(the form differs from storage) and `testing`. `selected` is renamed `viewed`
throughout, because the old name is precisely the confusion the report
describes.

* Clicking a row when `dirty` warns before discarding — the report asks for a
  warning *only* when edits would be lost, so a clean switch stays silent.
* **Select** saves, then activates, then closes — in that order, because
  activating an unsaved edit would run prompts on values the user cannot see.
* **Cancel / ✕ / outside-click** close without touching `active`.

### 2.2 Select is disabled until the connection is valid

The report asks for it. "Valid" is the store's existing `problem()` — no new
validation rule, and therefore no second definition of "usable" to drift.
A keyless seeded row is *viewable* but not *selectable*, which is exactly the
distinction the seeding round introduced.

### 2.3 One button component

`.ui-btn` with three modifiers (`--primary`, `--ghost`, `--danger`) fixes
height, radius, padding, font and focus ring; only colour varies. The existing
`.btn-small` / `.btn-success` / `.btn-danger` classes stay untouched for the
rest of the app — this popup opts in. Rewriting the global button system would
be a repo-wide visual change nobody asked for.

### 2.4 What is NOT built

* **No preset storage.** §1.2 — the spec table already holds the values.
* **No new bridge slots.** `bot_connections`, `bot_save_connection`,
  `bot_use_connection`, `bot_delete_connection`, `bot_test_connection` cover
  every action in the report. Select = save + use, two calls the UI sequences.
* **No `<select>` anywhere.** The provider chooser stays `DarkSelect`.

---

## 3. Shape

```
┌ Choose AI connection ───────────────────────────────────── ✕ ┐
│ Select a connection, adjust its settings, then confirm.      │
├──────────────────────┬───────────────────────────────────────┤
│ CONNECTIONS  3 saved │ Grok                    ● Ready to use │
│ ┌──────────────────┐ │ ┌───────────────────────────────────┐ │
│ │▌Grok    viewing  │ │ │ Recommended preset                │ │
│ │  Active·grok-4.3 │ │ │ Grok · standard chat configuration│ │
│ └──────────────────┘ │ │ [ Apply Preset Settings ]         │ │
│ │ Google AI        │ │ │ Fills the fields below; stays open│ │
│ │ Gemini 2.0 Flash │ │ └───────────────────────────────────┘ │
│ │ Kimi             │ │ Provider [DarkSelect]  Model [____]   │
│ │ API key required │ │ API key  [••••••] 👁   Endpoint [___] │
│ [ + New connection ] │                                       │
├──────────────────────┴───────────────────────────────────────┤
│ [Delete connection]        [Test] [Cancel] [Select]          │
└──────────────────────────────────────────────────────────────┘
```

Files: `bot-settings.js` 314 → ~300 after extracting the row/detail rendering
into `bot-connection-view.js` (~150). Over RULE 18's 300 otherwise, and the
render half is a genuine second responsibility.

---

## 4. Risks

| Risk | Pin |
|---|---|
| A row click activates something | `test_browsing_rows_never_activates_anything` |
| Apply closes the popup, or counts as Select | `applying a preset fills the fields and keeps the popup open` |
| Select activates without saving the visible edits | `select saves BEFORE it activates` |
| Cancel leaves the active connection changed | `cancel closes without changing the active connection` |
| Delete removes the wrong row | round-4 test kept |
| The Kimi row breaks the frozen provider contract | `tests/unit/services/test_bot_chat_service.py` provider table tests |
| Prompt presets confused with provider presets | `test_the_provider_preset_is_not_a_prompt_preset` |

---

## 5. Outcome

Shipped. `viewed` and `active` are now separate state and **Select** is the
only action that closes on confirm; row clicks, preset choice, Apply and Test
all leave the popup open and the active connection untouched. Recorded as
**I-33** in the System of Record.

Files: `ui/index.html` (two-column markup), `ui/css/bot-chat.css` (dark
master/detail + the `.ui-btn` component), `ui/js/bot-settings.js` (314 code
lines, controller) and the new `ui/js/bot-connection-view.js` (152, drawing).
Kimi is one row in `PROVIDERS`.

Two test helpers in `test_bot_bridge.py` had hardcoded the seeded provider
titles and a literal connection count, so adding a provider broke three
unrelated tests. They now derive both from `PROVIDERS`, which is what made
the Kimi row a genuine one-line change.

**Verification.** JS 82 passed (was 76) + 17; Python 3002 passed with only the
known pre-existing `test_saved_tab_main_preset_is_user_independent` failure;
RULE 16 gate clean, 0 new clone groups. The three headline behaviours were
proved by deliberately reintroducing each regression — a row click that
activates, an Apply that closes, a Select that skips the save — and confirming
the matching test failed each time, then restoring.

Not verified: pixel rendering. QtWebEngine cannot start in this sandbox
(`QRhiGles2: Failed to create context`, no Vulkan), so the CSS is reviewed
against the real token set in `variables.css` rather than screenshotted.


---

## 6. Round 6b — four defects the first pass left

The redesign was right in intent and wrong in four places. Each had a cause
worth recording.

### 6.1 Clicking a connection closed the popup

The headline behaviour — browsing is not choosing — was implemented in the
controller and then defeated by the dismiss handler ten lines below it.

The dismiss handler asked, on the bubble phase, "is the clicked node inside
the popup?". But the list's own delegated handler runs FIRST and re-renders
the rows, so by the time the question was asked the clicked node had been
replaced and detached. `closest()` on an orphan walks up to no popup at all,
the click was judged to be outside, and the popup closed.

The fix is to decide "inside" during the **capture** phase, before any
handler can redraw, and read that flag on the way back up.

The test suite could not have caught this: the DOM stub's `textContent = ''`
dropped children without clearing their `parentNode`, so `closest()` kept
succeeding on detached nodes — the stub was strictly more forgiving than a
browser. Both that and capture-phase listeners are now modelled, and
`clickConnection` fires the real three-step path (document capture → element
handler → document bubble) instead of poking one handler directly.

### 6.2 There was no way to add a connection without activating it

Select does save-then-activate-then-close, which is right for "use this
one" and useless for "add a second key and carry on". Save is back, as a
secondary button: it stores and re-renders, and does not activate or close.
Select remains the only action that closes on confirm.

### 6.3 The popup was cut off

`place()` clamped the horizontal axis and not the vertical: `top` was
`anchor.bottom + 6` unconditionally. A gear low in the window pushed the
footer — every confirming action — off the bottom edge. It now clamps both
axes, flips above the anchor when below will not fit, and pins to the top
when neither will; the panel is capped at `90vh` so it can never be bigger
than the space being fitted.

### 6.4 White fields

This app has **no global `input` rule** — every window styles its own fields
by id or class. A bare `<input>` in a new panel therefore inherits the
browser default: white. The popup now paints its own with `--bg-input` /
`--text-primary` / `--border-focus`, the same tokens the composer and label
editors use, so matching the app is a consequence of sharing the palette.

**Verification.** JS 88 passed (was 82) + 17; Python 3002 with only the known
pre-existing failure; RULE 16 gate clean; RULE 18 re-checked — controller 310
code lines, view 184, no function over 20. §6.1 and §6.3 were each proved by
reverting the fix and watching the new test fail.


### 6.5 The close cross floated and resized

The header is a flex row holding a text block and the ✕. The text block had
no flex sizing, so its width was content-driven — it grew and shrank with
however the title and subtitle happened to wrap — and the cross was pushed
right with `margin-left: auto`, which positions it relative to that moving
box. The button was also a plain flex item, so its neighbour could squeeze
it, and `.ui-btn--icon` set a width but no height while the header's
`align-items: flex-start` declined to stretch it. Hence: floating *and*
resizing.

The fix inverts which element absorbs the slack. The headings get
`flex: 1 1 auto; min-width: 0` and the button `flex: none`, so the cross is
pinned by the layout rather than pushed by a margin, and a long title
ellipsizes inside its own box instead of shoving the button off the edge.
`.ui-btn--icon` now states `height: 28px` so it is square and matches the
shared button height in every context. The key-reveal button, the popup's
other icon button, gets the same pin.


### 6.6 The real cause: inheriting `.layout-menu`'s element selectors

§6.5 fixed the header's flex arithmetic and the cross was still broken,
because the flex arithmetic was never the cause.

The popup sets `class="bot-settings-backdrop layout-menu"` to reuse the
Bookmarks panel chrome — position, border, radius, shadow. That also drags
in, from `sash-layout.css`:

```css
.layout-menu button { display: block; width: 100%; text-align: left; }
```

`.layout-menu button` is specificity (0,1,1). A bare `.ui-btn` is (0,1,0)
and **loses**. So every one of the popup's nine buttons was silently forced
to `display:block; width:100%`: the ✕ stretched across the whole header,
leaving the headings a few pixels wide — the title disappeared and the
subtitle wrapped one word per line, exactly as reported. The footer was
stacking vertically for the same reason.

The `.ui-btn` component, the connection rows and the preset chips are now
all scoped under `.bot-settings` (0,2,0), which outranks the inherited rule,
and the component explicitly restates `width:auto` and
`display:inline-flex` to undo what it inherits.

**The general lesson, worth more than the fix:** reusing another
component's class for its *panel* styling also inherits its *element*
selectors. `.layout-menu` was chosen so this popup would match Bookmarks by
construction, and the same decision quietly imposed Bookmarks' idea of what
a button is. A new component nested inside a borrowed one must either scope
its own rules above the host's element selectors, or not borrow the class.

A test now computes specificity directly and fails if any `.ui-btn`,
`.bot-provider` or `.bot-preset-opt` rule scores at or below
`.layout-menu button`.
