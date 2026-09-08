# Code generation rules for this repository

Rules an AI agent (or a human) MUST follow when adding or changing code here.

---

## RULE 1 — All find-and-click goes through the shared visual runner

> **Any action block that locates a DOM element and clicks it MUST call
> `backend.visual_click.find_and_click(...)` (or `find_and_click_exact(...)`).
> Never call `element.click()` from a hand-rolled probe inside a block.**

The runner is the single place that implements the mandatory two-phase,
visually confirmed click:

| Phase | What is logged | What is drawn |
|---|---|---|
| **FIND** | success/failure, node count, candidates, visibility | thin **RED** outline on the detected element, then a pause |
| **CLICK** | whether the target is clickable, then the click result | thin **ORANGE** outline on the click-target area, then the click |

### Why it is centralised

* every block behaves identically, so the log is predictable;
* the element found in phase 1 is stashed and reused in phase 2, so the click
  can never land on a different node than the one the user saw highlighted;
* overlays are `pointer-events:none` with a transparent background, so they can
  never intercept the click or shift layout;
* fixing or improving the confirmation UX happens in exactly one file.

### Correct

```python
from backend.visual_click import find_and_click

class MyBlock(BaseAction):
    async def execute(self, user_nick, cdp, engine=None):
        await self.pre_delay()
        return await find_and_click(
            cdp,
            selector=self.selector,
            label_selector=self.label_selector,
            match_text=self.match_text,
            click_selector=self.click_selector,
            highlight_enabled=self.highlight_enabled,
            confirm_pause_ms=self.confirm_pause_ms,
            label=f"my thing “{self.match_text}”",
            engine=engine,
        )
```

### Incorrect — do not do this

```python
raw = await cdp.evaluate("document.querySelector('.x').click()")   # ✗ no logging
raw = await cdp.evaluate(build_probe(..., click=True))             # ✗ no overlays
```

### Required params on every such block

Expose these so the behaviour stays configurable and preset-storable:

```python
highlight_enabled: bool = True     # draw the outlines
confirm_pause_ms: int = 700        # pause after FIND so the user can look
```

Blocks currently compliant: `CUSTOM_FIND`, `CLICK_MAIN_TAB`, `CLICK_BACK`,
`CLICK_USER`, `CLICK_SEND`.

### Overlay colour convention

| Colour | Constant | Meaning |
|---|---|---|
| **RED** `#ff2d2d` | `COLOR_FIND` | element detected during the FIND phase |
| **ORANGE** `#ff9500` | `COLOR_CLICK` | the area about to be clicked |
| **GREEN** `#00c853` | `COLOR_COLLECT` | a person matched the filter and was collected |

For pure visual confirmation with **no** click, use
`backend.dom_highlight.build_highlight_probe(...)`. It never touches the click
stash and never calls `scrollIntoView` — moving the viewport during a parse
would corrupt the scroll position tracking.

---

## RULE 2 — Report every step through `engine.report()`

Blocks receive the running `ActionEngine`. Use `engine.report(message, level)`
(`info` / `success` / `warn` / `error`) for each meaningful step. These lines
reach the UI log console *and* the JSONL run trace. A block that fails silently
is a bug — always say why.

---

## RULE 3 — Block settings are plain instance attributes

`BaseAction.to_dict()` serialises every public instance attribute, which is what
makes settings round-trip through presets. So:

* store configuration as `self.foo = ...` in `__init__`, with a default value;
* accept unknown keys via `**kw` so **older presets keep loading**;
* describe each field in `config_schema()` so the UI can render it;
* mirror the defaults/labels in `ui/js/stack-dnd.js` (`BUILTIN_BLOCKS`).

Never read settings out of the global config from inside a block when they
belong to that block — the block owns its own parameters.

---

## RULE 4 — Distinguish "empty" from "broken"

An empty result must be reported distinctly from a failure. The engine follows
this rule (empty queue vs. user-dependent stack vs. standalone run); blocks must
too. Never let a no-op path end with a success-looking log line.

---

## RULE 5 — Long-running work reports progress incrementally

Anything that loops over many items (scrolling, parsing, batch actions) must
surface each result **as it happens**, not in a batch when the loop ends. The
Scroll & Parse pipeline takes an `on_collect` callback, which the engine wires
to `person_collected()` → `person_found` signal → `users_updated`, so the table
updates live.

Two matching requirements:

* a callback into the UI must never be able to kill the pipeline — wrap it in
  `try/except` and log a warning;
* support both sync and async callbacks (`asyncio.iscoroutine(...)`).

---

## RULE 6 — Filtered-out entities must not persist

When a pipeline filters items, only the items that **pass** may be written to
storage. Never persist "everything we saw" for bookkeeping convenience — that is
exactly how rejected people ended up in the users table and survived across
runs.

Symmetry is the rule: if there is an `on_collect` hook, there must be an
`on_reject` hook that *destroys* any stored record for the rejected item. A
re-run under a stricter filter must make the list **shrink**, never grow.

Invariant to preserve: *after any run, storage contains only entities that pass
the currently configured filter.*

---

## RULE 7 — Stop must be honoured by every long-running loop

A stop flag checked only in the outermost loop is not a stop. Long-running
phases must accept a `should_stop` predicate and check it:

* at the top of each iteration, **and**
* inside any inner wait/poll loop, so a stop during a multi-second timeout is
  prompt.

Distinguish "stopped" from "failed" in the return value — reusing `None` for
both produced a bogus "lost the page context" error.

---

## RULE 8 — Tests execute the real thing

JavaScript probes are tested by running them through `tests/js_harness.js`
against a DOM stub, not by asserting on generated strings. Pipelines are tested
against a fake CDP client that behaves like the real page, including lazy
loading. If a test would pass with the feature deleted, it is not a test.

## RULE 9 — a guard that skips work must not stall the stack

A setting that makes a phase decline to do its work is only allowed to skip
*that work*, never the phases downstream of it. When Scroll & Parse skips
collection because of the backlog guard, `_run_collect_phase()` still returns
`await self._memory.get_queue()`, so the people already waiting are worked
through. If it returned `[]` instead, ticking the checkbox would quietly stop
the entire pipeline — the exact opposite of what the user asked for.

Two corollaries:

* **Fail open.** Counting the backlog fails open to `0` at both layers
  (`ActionEngine.backlog_count()` and `ScrollParse._read_backlog()`), so a
  counting error can never silently stop collection.
* **Skipping is success.** A skipped run returns `ActionResult.OK`, not a
  failure — the guard firing is correct behaviour.

Note the asymmetry, which is intended: a *normal* collect phase returns only the
people it just collected, while a *skipped* one returns the whole waiting queue.

## RULE 10 — one control per decision

A setting must not duplicate a decision another setting already makes. The
Scroll & Parse block used to have both four tri-state filter selects *and* an
"Also apply Filter panel criteria" checkbox, so a person could be rejected by
rules that were not visible in the block being looked at — which makes "why was
this person dropped?" unanswerable from the block config. The selects are now
the only source of truth.

When a setting is retired, the constructor must accept and **discard** its key
(`kw.pop(dead, None)`), because `BaseAction.to_dict()` re-emits `self.config`
and would otherwise write the dead key back into presets forever.

## RULE 11 — "don't add" must still mean "do the work"

Scroll-only mode (`scroll_only`) scrolls the page hunting for someone already in
the list who is not yet messaged, and adds nobody. Two invariants:

* **A seek writes nothing.** No `on_collect`, no `on_reject`, no purge. A target
  that fails the filter is passed over, never destroyed — it is being judged for
  suitability right now, not for membership.
* **A seek still counts newly rendered people** for stall detection. Seek mode
  cannot short-circuit on `nick in known_nicks` (a target is by definition
  already known, so that guard would skip exactly who we are hunting), but if it
  also stopped counting new arrivals the scroll would stall out before reaching
  a target further down the list.

An empty target set falls through to normal collection, so the mode drains the
backlog and then resumes harvesting instead of becoming a permanent off-switch.

## RULE 12 — one global history for every editable surface

The action stack, grid layout and people list share ONE chronological undo
history (`state.undo_history` / `state.undo_history_index`). Each entry is
tagged with `kind: "stack"` / `kind: "grid"` / `kind: "people"`, so one
`Ctrl+Z` always reverses the most recent edit regardless of which panel
produced it. There must be no separate undo/redo controls or shortcuts. The
common push logic owns deduplication, truncate-on-branch, and the 100-entry
cap.

People-list entries (delete / delete-selected / clear-all / status toggle /
reset-messaged) are reversible commands stored as
`{kind:"people", value:{before:[…], after:[…]}}` — full-row snapshots of both
halves. `undo()` reverses the TIP people entry with its `before` half and
`redo()` re-applies its `after` half, so a people action is undone in ONE
step even when stack/grid edits surround it in the timeline. Automatic engine
side-effects (a run marking people messaged, filter purges, live collection)
are NOT recorded — only explicit user actions.

Legacy per-surface history keys may be read for migration only; new edits must
never write them.

## RULE 13 — never persist state you cannot read back

`Bridge.save_grid_layout()` validates the tree (version, node shape, sizes
summing to 100, and the exact window set) and REJECTS anything invalid, leaving
the previously stored layout untouched. Storing an unreadable layout would
brick the UI on every subsequent start — a bad payload must cost the user one
failed save, not their whole layout.

Corollary for "reset to default": restoring the default tree is not enough when
a hidden panel releases its grid space. `resetToDefault()` also un-hides every
window, and any window that can be shown while empty needs an empty state
(RULE 4) so it does not look broken.

## RULE 14 — the archive is not the queue

`users` (chatbot.db) answers *"who should I message under the current
filter"* and may shrink at any time — filters purge it, People-list edits
delete from it, undo rewrites it.

`persons` / `messages` (history.db) answer *"what was actually said"*. Ordinary
collection is append-only/idempotent; unrelated People-list/filter edits must
not erase history. Explicit **Clear History / Delete Person** are authorized
clean-slate commands (2026-09-09 requirement): they physically remove messages,
all per-person tracking and, for Delete, the person row. They must use the
service reset boundary, not a bulk tombstone. The same chat is re-collected on
the next scan. Individual-message deletion remains a separate operation.

Undo snapshots belong outside the active archive (`db_trash/history_undo`).
The collector/parser/normal repository matching path MUST NEVER read those
snapshots or use undo history as an already-seen registry. Only explicit undo
or legacy storage conversion can read that store. Undo merges with current
rows without duplicates; it does not restore obsolete DOM/full-scan pointers.
Runtime caches, session counters and stale push/UI epochs must be invalidated
at a reset without touching unrelated conversations or pause/run preferences.

The two stores are joined **by nick at read time only** — clicking a nick in
User Memory looks the person up in the archive; it never copies data between
the two databases.

## RULE 15 — nothing is archived without the two-step gate

A message may be written to a person's history **only** when both checks
pass, and the checks must be re-applied on every path that saves (heartbeat
tick, live `__cvbPush` batch, `COLLECT_HISTORY` block):

1. the conversation on screen contains exactly two nicks — mine and that
   person's (a third author ⇒ it is not a private chat);
2. the active tab is a private tab whose title names that same person.

The gate lives in one place, `backend/chat_parser.verify_private()`, and it
fails **closed**: an agent that cannot report who wrote what collects
nothing, and a refused check disarms the push channel until a tick verifies
the conversation again. Never “save it anyway and clean up later” — a
polluted history cannot be un-mixed.

Historical-name clarification (2026-09-08): the two **participant identities**
may include previous spellings of the user's own nickname. Only previously
declared My Nick values / archived self-nickname metadata are trusted as self
aliases; arbitrary author strings and push-supplied alias lists are not. A
current browser self override requires scoped two-member roster evidence.
Unknown authors, other peers and real third participants still fail closed.
Normalize a known historical self's direction before dedupe without rewriting
the original sender name. The optional numeric counter hint never disables
actual author/roster validation. Already trusted self names may be retained as
independent identity preferences across a clean-slate reset; they are not
message hashes/counts/pointers. Explicit undo of an isolated archive snapshot
is not permission to collect from an unverified chat.

Media follows the same ownership rule: bytes are filed under the
conversation they belong to (`saved_media/<Latin nick>/images|gifs/
YYYY-MM-DD_NNN.ext`), never in an anonymous global pile, and the UI shows
the saved file rather than the remote URL.

Attachment components (`app-chat-image` / `.image-wrapper`) can be nested
inside `.message-text`, `span.message` or `[data-message-text]`. Never exclude
all images merely because they descend from a text payload. Keep attachment
classification separate from caption/emoji extraction, and defer an attachment
whose image/URL has not rendered. Text-selector changes must be tested against
both legacy media markup and the supplied `tests/fixtures/person_media.html`.

Committed cache-state changes must reach the open history window, including
idle-batch completions; new live rows must not retain pre-download media DTOs.
Use one truthful media-info shape with local path/state/error and generation
checks on bridge/UI replies. Missing or failed previews must not silently look
cached, and a renderer callback failure must not break media storage.
