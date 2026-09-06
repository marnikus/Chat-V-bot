# Extra Pause status + Attach Image: active-chat targeting & visual confirmation

Date: 2026-09-06

## FEATURE #1 — "Extra Pause" action block: ALREADY EXISTS (no code change)

The block palette already ships **⏸️ Custom Pause** (`actions/pause.py`,
block_id `PAUSE`), which matches the request exactly:
* user-configurable `duration_ms` (default 1000);
* draggable into any position of the stack (palette entry in
  `ui/js/stack-dnd.js` `BUILTIN_BLOCKS`);
* runs inline between any two steps of a user's sequence (engine executes
  blocks in order for each user), and per repeat-cycle.

User confirmed (2026-09-06): *no change wanted* — item closed as-is.
(If the running app predates the PAUSE entry, updating the build shows it.)

---

## BUG #2 — Attach Image sends to the main gallery instead of the private chat

### Verified page structure (from the saved session HTML)

* One conversation shell per chat: `<app-chat>` owns the tab strip, the
  messages area (`.message-container` nodes), the composer
  (`app-message-form` with `textarea[placeholder='Сообщение']` and the
  three suffix buttons `send` / `image` / `insert_emoticon`) and the hidden
  upload input right after the form:
  `…</app-message-form><input id="file" type="file" …></footer>` — the file
  input is **per conversation, not global**.
* Saved snapshots show one composer mounted; the live app can legitimately
  keep more than one chat panel in the DOM (only the active one visible),
  which is why a **global first-match** `input#file[type='file']` /
  `…suffix button` can resolve to the **main-room** composer while the
  private chat is the one the user sees and types into. Text messages work
  because they are typed into the visible textarea; the file-input path has
  no such implicit "active" anchor today.

### Fix — resolve the ACTIVE conversation and act inside it

New context probe (one CDP evaluate) that mirrors what a human sees:

1. find the **visible** composer: an `app-message-form` whose
   `textarea[placeholder='Сообщение']` is on-screen (`offsetParent != null`);
   fall back to the first composer, then to the first `app-chat`;
2. inside that scope locate the **image button** (suffix `button` whose
   `mat-icon` ligature text is `image`) and the **hidden file input**
   (`input#file[type='file']`);
3. return a unique **CSS path** for each (tag + `:nth-of-type` walk up the
   tree), plus the shell path used to scope the send verification.

All later steps then operate on those exact paths:
* the dialog click (BUG #3) targets the active conversation's image button;
* `DOM.setFileInputFiles` targets the active conversation's own input — so
  even with several composers mounted the file lands in the private chat;
* "did the image send" verification counts `.message-container` **inside the
  same shell** (`<shellPath> .message-container`) instead of globally;
* when the probe cannot resolve (single-composer layout, selector drift),
  the pipeline falls back to today's global selectors with a logged warning
  — never a silent skip.

If only one composer exists, the probe still works (scope = that composer)
and the fallback simply is not needed.

---

## BUG #3 — Attach Image has no visual confirmation before clicking

### Fix — use the shared visual-confirmation runner for the button click

The dialog-open step now runs through `backend/visual_click.find_and_click`
exactly like every find-and-click block (per docs/AGENT_RULES.md):

1. **FIND** — red outline on the detected image button, logged;
2. pause (`confirm_pause_ms`, default 700 ms) so the user can confirm;
3. **CLICK** — orange outline on the click target, then the real click.

Exposed on the **Attach Image** Tune panel for parity with every other
block: `highlight_enabled` (default ON) and `confirm_pause_ms` (default
700) — with a disabled path available for users who want the old silent
click. Logs stream through `engine.report` (small report-adapter so the
shared runner needs no signature change).

---

## Files touched

* `backend/media_handler.py` — active-chat context probe (CSS paths),
  scoped dialog click + injection + verification, visual confirmation,
  fallbacks, stage logging.
* `actions/attach_image.py` — `highlight_enabled`, `confirm_pause_ms`
  settings + schema labels.
* `ui/js/stack-dnd.js` — ATTACH_IMAGE defaults/labels for the two new
  settings.
* `tests/test_attach_image.py` — context-probe fake (single- and
  two-composer layouts), scoped-selector assertions, overlay/confirmation
  flags, fallback test, schema round-trip.
* `docs/EXTRA_PAUSE_STATUS_AND_ATTACH_TARGETING_DESIGN_2026-09-06.md` (this).

## Acceptance

* With a private chat open, the block's image button click + file injection
  happen **inside the visible conversation**, and verification counts that
  conversation's messages — image lands in the private chat, not the room.
* The image-button click draws red → pause → orange overlays and logs the
  two phases (off when `highlight_enabled` is unchecked).
* Multi-composer DOM (probe returns chat_count>1) resolves the visible one;
  probe failure degrades to global selectors with a warning.
* FEATURE #1 closed: Custom Pause already provides the Extra Pause block.
