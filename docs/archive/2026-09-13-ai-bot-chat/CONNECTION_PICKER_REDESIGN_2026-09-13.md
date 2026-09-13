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
