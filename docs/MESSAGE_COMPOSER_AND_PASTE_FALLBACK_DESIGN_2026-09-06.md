# Message block: “use composer text” checkbox + paste/Ctrl+V typing fallback

Date: 2026-09-06

## 1. Problems

### FEATURE — message from the Message Composer window
The ⌨️ Type Message block only ever types the text stored *inside the block*
(a single-line field in its Tune panel). The big **Message Composer**
window already holds the message the user is working on (and `{{nick}}`
variables), but a block cannot reference it — the user must copy the text
into every block, and any composer edit must be mirrored by hand.

Request: a checkbox on the Type Message block “use text from the Message
Composer window”; when on, the block sends the composer’s current text
instead of its own stored text.

### BUG — “Textarea value injection failed (page did not accept input)”
During a run the message step logs
`❌ Textarea value injection failed (page did not accept input)` and the
step FAILs. The current injector sets `.value` through the native prototype
setter and dispatches `input`/`change` — some pages (and some message
content, e.g. raw CR / U+2028 which break the generated JS string) reject
that, and there is **no verification and no fallback**.

Request: when direct injection is not accepted, the block should put the
text on the clipboard and paste it with **Ctrl+V** into the selected
(focused) field.

## 2. Design

### 2.1 Type Message block — `use_composer` checkbox

Backend:
* `ActionEngine` keeps the live composer text (`self.composer_text = ""` in
  `__init__`). `Bridge.save_message()` already receives every composer
  keystroke — it now also writes `engine.composer_text`, so blocks read the
  *current* window text at the moment they run (no run-start snapshot).
* `actions/type_message.py`:
  * new plain setting `use_composer: bool = False` (round-trips through
    `to_dict()`, presets and undo history like every other setting);
  * `execute()` picks `text = engine.composer_text` when `use_composer` is
    on, else `self.message`; the existing `{{nick}}` replacement applies to
    whichever source won;
  * empty composer text under `use_composer` → clear warning (same as empty
    block text today);
  * `config_schema()` gains `use_composer` (boolean).

Frontend (`ui/js/stack-dnd.js`):
* `BUILTIN_BLOCKS` TYPE_MESSAGE entry: `defaults` gain
  `use_composer: false`, label “Use text from the Message Composer window”.
  `_migrateBlock()` back-fills it onto every existing/preset/history block.
* Tune panel renders the block’s own message as a real multi-line
  `<textarea>` (typed text is no longer forced onto one line). When
  `use_composer` is checked the textarea is disabled and the label notes
  that the composer window supplies the text; toggling the checkbox
  re-renders the panel so the field state follows.
* Block card summary: with `use_composer` on, the card shows
  “text: Message Composer” instead of the stored message text.
* Textarea contents are HTML-escaped when injected into the panel
  (`_esc()`), like every other user string.

### 2.2 Typing fallback chain — `backend/message_injector.py`

`type_message()` becomes a verified, multi-strategy pipeline; the first
strategy whose result **verifies** wins, and the log states which one was
used:

1. **Native setter + input events** (current approach, kept as the fast
   path). Rebuilt so the text is embedded with `json.dumps(ensure_ascii=True)`
   instead of hand-rolled escapes — raw CR / U+2028 / U+2029 previously
   broke the injected JS string itself, which is one real cause of the
   “page did not accept input” failure.
2. **Clipboard → Ctrl+V paste** (the requested behaviour): focus the field,
   select its content, grant clipboard permissions for the current origin
   (`Browser.grantPermissions`: clipboardReadWrite/clipboardSanitizedWrite),
   write the text with `navigator.clipboard.writeText`, then dispatch a
   real `Ctrl+V` through `Input.dispatchKeyEvent` (rawKeyDown + keyUp). The
   paste inserts the text with the full event sequence a human paste
   produces, which value-injection-hostile editors accept.
3. **CDP `Input.insertText`** — types into the focused editable at the
   browser level (works for textareas and contenteditable fields; needs no
   clipboard permission).

After each strategy a verification snippet reads the field’s current value
(`textarea.value` / `textContent`) and compares it (normalised) with the
intended text. Only a verified write counts as success; a failed step logs
the reason and the next strategy runs. If everything fails, the error
message now names the attempts instead of the old bare line.

`click_send()` and the probe/search helpers are untouched. The report
messages keep the existing `⌨️ Typed N char(s)…` success wording so run
logs stay familiar.

## 3. Files touched
* `actions/type_message.py` — `use_composer`, composer-text selection,
  schema.
* `backend/action_engine.py` — `composer_text` attribute.
* `backend/bridge.py` — `save_message()` mirrors text onto the engine.
* `backend/message_injector.py` — verified fallback pipeline
  (setter → Ctrl+V paste → insertText).
* `ui/js/stack-dnd.js` — block default/label, textarea field, checkbox
  behaviour, summary, HTML escaping.
* `ui/css/stack.css` (or config styles) — textarea row styling if needed.
* `tests/test_message_block_composer.py` (new), design doc.

## 4. Acceptance
* Type Message block has a “use Message Composer text” checkbox; when on,
  the run sends the composer window’s current text and the block’s own text
  is ignored (its panel field is disabled while checked).
* A message that the page rejects via value injection is still delivered:
  the injector copies it and pastes with Ctrl+V into the focused message
  field (and, if the clipboard is unavailable, inserts it via CDP).
* The success log reports how the text got in; a full failure lists the
  attempted methods.
* Existing Python + Node suites stay green.
