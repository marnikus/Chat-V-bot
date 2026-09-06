# Attach Image: open upload dialog, select & send — with jpg/gif/png support

Date: 2026-09-06

## 1. Problem

The Attach Image block currently injects a file straight into the hidden
`input#file` via CDP `DOM.setFileInputFiles` and reports success — but the
user reports **nothing gets attached/sent in practice**. Manual use works:
open the image upload (dialog), pick the file (double-click, or select and
Enter) and the image sends itself. The block must behave like that human
flow, and it must cover **all common image formats** (today the default
pattern is `*.jpg` only, so a folder of `.gif`/`.png` files matches
nothing).

## 2. Verified page facts (from saved session HTML)

* The message form has **three icon buttons inside
  `div.mat-mdc-form-field-icon-suffix`**: `send` (`type=submit`), `image`
  and `insert_emoticon` (ligature text, unique per button).
* The hidden file input is stable: `<input id="file" type="file"
  style="display:none" accept="image/*">` — `accept="image/*"` already
  allows jpg/jpeg/png/gif.
* Own chat messages render as `div.message-container.my-message-background`
  (images as `app-chat-image` inside), so "an image was really sent" is
  observable as a new message container after injection.
* User-confirmed: choosing a file in the dialog **sends the image
  immediately** — no extra send click needed.

## 3. Design

### 3.1 The block settings (`actions/attach_image.py` + `ui/js/stack-dnd.js`)

| Setting | Default | Type | Meaning |
|---|---|---|---|
| `folder_path` | (existing) | text | unchanged |
| `file_pattern` | `*.jpg, *.jpeg, *.png, *.gif` | text | comma-separated patterns/extensions, case-insensitive (`gif`, `*.GIF`, `*.png, *.jpg` all accepted) |
| `rotation_mode` | `sequential` | select | `sequential` / `random` (existing param, now exposed in the Tune panel) |
| `simulate_dialog` | `true` | checkbox | open the upload dialog first (click the site's `image` button) like a human, then choose the file |
| `verify_timeout_ms` | `8000` | number | wait for the image message to actually appear in chat (`0` = skip verification) |

### 3.2 New attach pipeline (`backend/media_handler.py`)

`attach_image(...)` becomes an explicit, stage-logged pipeline; each stage
fails loudly with its own message instead of the current silent success:

1. **Folder scan** — parse `file_pattern` into extensions/patterns
   (comma/space separated; bare `gif` → `*.gif`; case-insensitive
   `fnmatch` over `listdir`, so `.JPG` matches too). No match → clear
   error listing what was found vs the wanted formats.
2. **Pick** — `sequential` (first alphabetical) or `random`.
3. **Open the dialog (only when `simulate_dialog` on)** — click the site's
   image button through the shared visual runner (`find_and_click` on
   `.mat-mdc-form-field-icon-suffix button`, child `mat-icon` text
   `image`, exact). This reproduces the human "open upload window" step
   and lets the app run its own open-listener. If the button is missing we
   log a warning and continue with direct injection (never a silent skip).
4. **Inject the file** — probe `input#file[type='file']`, then
   `DOM.setFileInputFiles`, exactly as today but with a **readback**:
   evaluate `input.files.length`; if it is not `1`, fail loudly
   ("injection did not stick") — this catches the silent node-id-0 no-op
   failure mode.
5. **Verify the send** — while `verify_timeout_ms > 0`, poll the number of
   `.message-container` nodes (and/or `app-chat-image`/`img` presence);
   when it grows the image is in the chat → success. On timeout → FAIL with
   a message that names the stage, so a live session pinpoints exactly what
   the site did (e.g. "site did not send automatically — use a Click Send
   block after Attach Image or disable verification").

`CLICK_SEND` remains a separate block — users who find the site needs a
send nudge can put it right after ATTACH_IMAGE (verification then passes).

### 3.3 Compatibility

* Old saved stacks with `file_pattern: '*.jpg'` still load and now also
  match nothing extra — but the *new* default covers jpg/jpeg/png/gif.
* `rotation_mode` is already a constructor param (dead in the UI); now it
  is editable and round-trips like every other setting.
* Blocks with the setting OFF (`simulate_dialog=false`,
  `verify_timeout_ms=0`, custom pattern) reproduce today's direct-inject
  behavior for people who need it.

## 4. Files touched

* `backend/media_handler.py` — pattern parsing, dialog click, readback,
  send verification, stage logging.
* `actions/attach_image.py` — new settings + schema (labels mention
  formats and the dialog checkbox).
* `ui/js/stack-dnd.js` — ATTACH_IMAGE defaults/labels/options/checkbox.
* `tests/test_attach_image.py` (new) — pattern parser, fake-CDP injection
  (success, readback-fail), send verification (arrives / times out),
  schema round-trip.
* `docs/ATTACH_IMAGE_DIALOG_FORMATS_DESIGN_2026-09-06.md` (this file).

## 5. Acceptance

* With the defaults, the block attaches a `.jpg`/`.jpeg`/`.png`/`.gif`
  (any case) from the folder and the image message appears in the chat.
* When `simulate_dialog` is on, the site's image button is clicked first
  (dialog-equivalent) before the file is set.
* Every failure names its stage in the run log (folder, pattern, button,
  input, readback, send-verify).
* OFF/legacy settings keep the old direct-inject behavior.
