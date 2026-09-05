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
