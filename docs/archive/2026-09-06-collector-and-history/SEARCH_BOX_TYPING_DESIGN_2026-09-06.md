# Type into the users-list search (Поиск) box — verified focus + text

Date: 2026-09-06

## 1. Problem (user report)

"I can not click and insert text in the field of the search bar, same as I
do in the textarea for private msg… what is the problem?"

Diagnosis (verified against code + saved HTML):

1. **No block can type into the search bar.** The only typing block, Type
   Message, is hard-wired to the private-message textarea
   (`backend/message_injector.py`: `textarea[placeholder='Сообщение']` /
   `textarea#mat-input-1`). Find & Click only clicks. So there is currently
   *no* path to put text into the `.search-field` input.
2. **The search input matches no textarea selector.** "Поиск" is a floating
   `<mat-label>`, not a `placeholder` attribute (confirmed: the input tag
   has no `placeholder`). `input[placeholder='Поиск']` matches nothing.
3. **`#mat-input-189` / `#mat-input-9` ids are unstable** — Angular
   regenerates them every time users-list mounts (same root cause as the
   "returning to chat resets the lazy list" issue). Selectors must be
   structural: `.search-field input[matinput]`.
4. **Latent setter bug for `<input>`:** `_try_set_value` only falls back to
   the `HTMLInputElement` value setter when the `HTMLTextAreaElement`
   setter is missing — but that setter always exists, so typing into an
   `<input>` would call the textarea prototype's setter on it.

User requirement (confirmed): the block must **verify** — (a) the field
was really clicked and the cursor is inside it (focus), and (b) the text
really landed in the search box (value read-back), with each stage logged.

## 2. Design

### 2.1 Generalize the verified typing chain — `backend/message_injector.py`

* Split `type_message`'s strategy ladder into a reusable
  `type_into_field(cdp, text, selectors, label, report, typing_speed_ms)`
  that keeps the exact same three strategies + verification:
  1. native **value setter on the element's OWN prototype**
     (`HTMLInputElement` for `<input>`, `HTMLTextAreaElement` for
     `<textarea>`) + `input`/`change` events;
  2. real **Ctrl+V paste** (clipboard write + key events);
  3. **CDP `Input.insertText`**.
  After focusing, **verify the cursor is inside**: `document.activeElement
  === the field`; if not, real-click the element center (`get_element_rect`
  + `click_at`) and re-verify focus before typing. After every strategy,
  **read back the value** (existing `_field_value`) and compare.
* New stable selectors:
  `SEARCH_SELECTOR = ".search-field input[matinput]"`,
  `SEARCH_FALLBACK = "input[maxlength='20']"`.
* `type_message(...)` becomes a thin wrapper over `type_into_field` with
  the textarea selectors — signature and messages unchanged (existing
  suites stay green).
* New `type_search(cdp, text, report)` wrapper → types into the search
  box with focus verification, logs "field focused / cursor inside" and
  "text in search box — list is filtering", returns bool.

### 2.2 New block — `actions/search_users.py`, block_id `SEARCH_USERS`

"🔍 Search Users": one setting `text` (label "Search text — {{nick}} =
selected user"). Runs the verified `type_search`. Not user-scoped, so a
stack of just Search Users runs standalone once (page-state block like tab
clicks). `{{nick}}` expands through the engine's existing per-step
mechanism (a picked/clicked person's nick can be typed straight into
search). Enabled toggle inherited.

### 2.3 UI — `ui/js/stack-dnd.js`

`BUILTIN_BLOCKS` entry with defaults/labels; card summary shows
`search: "…"` when text is set.

## 3. Files touched

* `backend/message_injector.py` — generalized chain, prototype fix, search
  selectors, `type_search`.
* `actions/search_users.py` (new) + `actions/__init__.py` registration.
* `ui/js/stack-dnd.js` — block entry + summary.
* `tests/test_search_users.py` (new) + design doc.

## 4. Acceptance

* A run of Search Users with text "X": logs the field found → focus
  verified (cursor inside; real-click fallback when needed) → text entered
  (value read-back equals "X"). Returns OK only when text actually landed.
* If the field cannot be focused or text never lands → FAIL with the stage
  named (same vocabulary as Type Message).
* Type Message behaviour is byte-identical (all existing suites pass).
