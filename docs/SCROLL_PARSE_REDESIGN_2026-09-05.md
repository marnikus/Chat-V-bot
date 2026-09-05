# Design — "Scroll & Parse" as an integrated pipeline + shared visual confirmation

Date: 2026-09-05
Scope: `actions/scroll_parse.py`, `actions/click_user.py`, `backend/scroll_parser.py`,
`backend/criteria_engine.py`, `backend/action_engine.py`, `backend/visual_click.py`,
`ui/js/stack-dnd.js`, `docs/AGENT_RULES.md`

---

## 1. Current state (what we are changing)

### 1.1 `SCROLL_PARSE` is a hollow marker

```python
class ScrollParse(BaseAction):
    async def execute(...):
        engine.report("📜 SCROLL_PARSE … — runs in parse phase")
        return ActionResult.OK        # ← does nothing
```

The real work lives in `ActionEngine._run_parse_phase()`, which runs *before* the
per-user loop, and `_execute_for_user()` explicitly `continue`s past the block.
Consequences:

* the block's position in the stack is meaningless — it always runs first;
* its settings (`max_scrolls`, `scroll_pause_ms`) are read by `Bridge.run_stack()`
  by digging through the raw JSON, not by the block itself;
* the pipeline is split across three files, so scroll → filter → collect → click is
  not observable or testable as one unit.

### 1.2 Scrolling cannot tell "still loading" from "end of list"

`ScrollParser.parse()` scrolls a fixed `max_scrolls` times and stops after
`stall_threshold` (3) consecutive scrolls that yielded no *new nicks*. Because the
list is lazy-loaded through a CDK virtual viewport, a slow network response looks
exactly like the end of the list — the parser either quits early or keeps scrolling
past the bottom, burning the full 50 iterations.

Nothing observes `scrollTop` / `scrollHeight`, which is the only reliable signal for
"we are at the bottom and nothing more is coming".

### 1.3 Filters are global, not per-preset

`CriteriaEngine` holds one list of criteria for the whole app, saved through
`bridge.save_criteria()`. A stack preset therefore cannot carry its own filter — the
requirement is explicitly that *filter criteria should be storable as a param in
presets*.

### 1.4 Ordering ignores "not yet messaged"

`UserMemory.get_queue()` returns `WHERE messaged=0 ORDER BY first_seen DESC`. There
is no A–Z ordering and no un-messaged-first priority across the *collected* list.

### 1.5 `CLICK_USER` has no visual confirmation and no tab check

It still uses the old single-pass `build_probe(..., click=True)`: no red/orange
overlays, and it returns OK as soon as `.click()` did not throw — it never verifies
that a chat tab actually opened.

---

## 2. Design

### 2.1 The block owns the pipeline

`SCROLL_PARSE` becomes a real executing block that runs the whole
**scroll → detect → filter → collect → queue** pipeline and reports every step. The
engine keeps a *collect phase* purely as a scheduling hook: when the stack contains a
`SCROLL_PARSE` block, the engine executes that block first (so the queue exists before
the per-user loop), then uses the list the block produced. All logic — settings,
filtering, ordering — lives in the block and its collaborator `ScrollParser`.

```
ActionEngine.execute()
  ├─ collect phase   : SCROLL_PARSE.run_pipeline(cdp, memory, engine) → CollectResult
  ├─ queue           : result.queue        (already filtered + sorted)
  └─ per-user loop   : remaining blocks, incl. CLICK_USER
```

### 2.2 STEP 1 — scroll & detect new persons

`ScrollParser.parse()` is rewritten around an explicit *settle* loop instead of a
blind stall counter:

1. Extract the currently rendered `user-item` nodes.
2. Scroll the viewport by `scroll_delta_y`.
3. Wait up to `load_timeout_ms` (default 2500 ms), polling every `poll_ms`
   (default 150 ms), for **either**
   * new nicks to appear (lazy load finished → continue), **or**
   * `scrollTop` to stop changing *and* no new nodes (→ candidate end-of-list).
4. Confirm end-of-list only when `scrollTop + clientHeight >= scrollHeight - 4`
   **and** a further settle window produced nothing new. This distinguishes
   "still loading" from "bottom reached".

A single JS probe returns nodes *and* scroll geometry in one round trip:

```js
{ users: [...], scrollTop, scrollHeight, clientHeight, atBottom, count }
```

`max_scrolls` remains as a safety valve, but the normal exit is the geometric
bottom check, and every decision is logged (`⏳ still loading…`, `⏹ bottom reached`).

### 2.3 STEP 2 — filter & collect, with preset-storable criteria

Filtering moves into a small pure helper, `PersonFilter`, built from **block
parameters** so it round-trips through the existing preset machinery
(`BaseAction.to_dict()` already serialises every instance attribute):

| block param | values | meaning |
|---|---|---|
| `filter_female` | `any` \| `yes` \| `no` | must / must not be female |
| `filter_registered` | `any` \| `yes` \| `no` | must / must not be registered |
| `filter_guest` | `any` \| `yes` \| `no` | must / must not be guest |
| `filter_anonymous` | `any` \| `yes` \| `no` | must / must not be anonymous |
| `use_panel_filters` | bool | also apply the global Filter-panel criteria |

Tri-state strings (not booleans) are required so that "don't care" is
distinguishable from "must be false" — the defaults reproduce the example in the
request: female = yes, registered = no, guest = yes, anonymous = no.

`use_panel_filters` keeps the existing global Filter panel working: when true the
block ANDs its own rules with `CriteriaEngine.evaluate_user()`. `PersonFilter`
returns a per-person *reason* (`"not female"`, `"registered"`, …) so rejections are
explained in the log rather than silently dropped.

De-duplication: the parser keeps `known_nicks`, and the collector additionally skips
anyone already in the collected list, so a person is only ever added once.

### 2.4 STEP 3 — queue ordering

The collected list is ordered by

```python
sorted(people, key=lambda p: (p.messaged, p.nick.casefold()))
```

`messaged` is `False < True`, so **not-yet-messaged people sort to the top**, and
within each group the order is A–Z, case- and locale-insensitively (`casefold`).

**Early finish.** Per the spec, once at least `min_new_users` (default 1) *new
un-messaged* people have been collected, the block stops scrolling and returns OK
immediately — no need to walk the entire list before messaging can start. Setting
`min_new_users` to 0 means "always scroll to the end".

### 2.5 STEP 4 — click on person, confirm the new tab

`CLICK_USER` is rebuilt on the shared visual runner and gains tab verification:

1. Count the chat tabs currently open (`tab_selector`, default
   `div[role='tab'].tab-item`).
2. Find the person's `user-item` by **exact** nick on `.primary-text`, draw the
   **red** overlay, pause.
3. Draw the **orange** overlay on the click target (`.user-container`) and click.
4. Wait `tab_pause_ms` (default 800 ms), then re-count the tabs and confirm the count
   increased **or** a tab whose title matches the nick now exists. Only then is the
   step marked done; otherwise it fails with an explicit
   `❌ no new tab appeared` message.

### 2.6 REFACTOR — visual confirmation as a shared module

The logic introduced for "Find & Click" is promoted to a first-class shared module
so *every* find-and-click block uses it:

```
backend/dom_highlight.py   — JS overlay + two-phase probes (red / orange)
backend/visual_click.py    — VisualClick: the reusable async runner
                             (find_and_click(), plus find_and_click_exact())
```

`actions/find_click_runner.py` is kept as a thin re-export shim so nothing that
imports it breaks.

Blocks converted to the shared runner: `CUSTOM_FIND`, `CLICK_MAIN_TAB`,
`CLICK_BACK` (done previously) and now **`CLICK_USER`** and `CLICK_SEND`. Each gets
`highlight_enabled` / `confirm_pause_ms` params.

The rule is written down for future code generation in **`docs/AGENT_RULES.md`**:

> Any action block that locates a DOM element and clicks it MUST go through
> `backend.visual_click.find_and_click(...)`. Never call `element.click()` from a
> hand-rolled probe. The runner guarantees: find logged → red outline → pause →
> clickability logged → orange outline → click logged.

---

## 3. Test plan

* **Scroll**: lazy-load simulated by a fake CDP whose node list grows only after N
  polls — the parser must wait rather than declare the end; bottom geometry must end
  the loop; `max_scrolls` must cap a list that never ends.
* **Filter**: the tri-state matrix, the default profile from the request, rejection
  reasons, and combination with the global panel criteria.
* **Collect**: duplicates skipped across scrolls; early finish after `min_new_users`.
* **Order**: un-messaged first, then A–Z, case-insensitive, incl. Cyrillic.
* **Click person**: red then orange overlay, exact-nick match (no prefix collisions),
  new-tab confirmation success and failure paths.
* **Presets**: a `SCROLL_PARSE` block round-trips all filter params through
  `to_dict()` and reconstructs identically.

---

### Results

```
$ python3 tests/test_find_click_visual.py       # 22 tests — OK
$ python3 tests/test_engine_standalone_run.py   #  8 tests — OK
$ python3 tests/test_scroll_parse_pipeline.py   # 31 tests — OK
```

Plus an end-to-end run of a `SCROLL_PARSE` → `CLICK_USER` stack through a real
`ActionEngine`, verifying: lazy-load waiting, the rejection of a non-matching
person, the early finish, the ordered queue, the red/orange overlays on the
person row, and the new-tab confirmation.

---

## 4. Backwards compatibility

* Old presets lacking the new keys get the constructor defaults.
* `ActionEngine._run_parse_phase()` and `Bridge.run_stack()`'s manual `ScrollParser`
  construction are removed; the block builds its own parser from its own settings.
* The global Filter panel keeps working through `use_panel_filters`.
