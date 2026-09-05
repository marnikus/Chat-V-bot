# Design — Visual Confirmation for “Find & Click” blocks + “Tab Main” does-nothing bug

Date: 2026-09-05
Scope: `actions/custom_find.py`, `backend/dom_probe.py`, `backend/action_engine.py`,
`actions/click_main_tab.py`, `actions/click_back.py`, `ui/js/stack-dnd.js`

---

## 1. Problem analysis

### 1.1 Feature — no visual verification

Today `CUSTOM_FIND` performs the whole operation inside **one** JavaScript probe
(`build_probe(..., click=True)`): the element is located, checked and clicked in a
single synchronous pass. Consequences:

* the user never sees *which* element was matched — only a text log line;
* find and click are indistinguishable in the log: if the selector matches the wrong
  node, the click silently lands on the wrong place;
* there is no pause between “found” and “clicked”, so nothing is observable even at
  human speed.

### 1.2 Bug — “Tab Main” block does nothing, silently

`ActionEngine.execute()` (Phase 3) is:

```python
queue = await self._memory.get_queue()     # users WHERE messaged = 0
...
for user in queue:                         # ← the ONLY driver of the block stack
    ok = await self._execute_for_user(user, has_skip)
```

The block stack is executed **once per queued user**. When the user table is empty
(fresh DB, or every user already messaged, or a stack that has no `SCROLL_PARSE`
block at all — exactly the saved `Tab Main` stack in `config.json`), `queue == []`,
the `for` body never runs and **not a single block executes**.

Worse, the log message in that situation is:

```python
if has_scroll and scroll_parser and not queue:
    self.log_msg.emit("⚠ No users in queue — nothing to run", "warn")
else:
    self.log_msg.emit(f"▶ Running stack on {len(queue)} user(s)")
```

With no `SCROLL_PARSE` in the stack, `has_scroll` is `False`, so the *else* branch
runs and prints `▶ Running stack on 0 user(s)` — followed immediately by
`✅ Stack execution complete`. To the user this reads as a successful run: **no error,
no visual indication, nothing happens**. This is precisely the reported symptom.

So the bug is *not* in `CustomFind` — that action is never invoked. Any user-independent
stack (tab clicks, navigation, DOM checks) is currently unrunnable.

---

## 2. Design

### 2.1 Execution model fix — “standalone run”

A stack is *user-driven* only if it actually consumes a user. Introduce an explicit
notion:

```
USER_SCOPED_BLOCKS = {"SCROLL_PARSE", "CONDITIONAL_SKIP", "CLICK_USER",
                      "TYPE_MESSAGE", "CLICK_SEND", "ATTACH_IMAGE"}
```

Rules in `ActionEngine.execute()`:

1. Build the queue as today.
2. If the queue is empty **and** the stack contains no user-scoped block →
   run the stack **once** against a synthetic `UserRecord(nick="—")`
   (“standalone run”). Log it explicitly.
3. If the queue is empty **and** the stack *does* need users → emit a loud
   `⚠ No users in queue` warning naming the blocks that require a user, instead of
   the misleading `Running stack on 0 user(s)`.
4. Never write memory (`mark_messaged`) for the synthetic user.

This keeps normal per-user runs byte-identical while making user-independent stacks
(the `Tab Main` case) work and, most importantly, **never silent**.

### 2.2 Two-phase Find & Click with visual confirmation

`CUSTOM_FIND` is split into two CDP round trips.

**Phase 1 — FIND (no click).**
Probe locates the element, reports `found / not found`, `total` matched nodes,
visibility, clickability, and **draws a thin RED (`#ff2d2d`) 2 px outline** over the
matched element's bounding rect. The matched node is *stashed* in the page
(`window.__cfStash`) so phase 2 acts on the exact same element — no re-query, no risk
of matching a different node. Then the action `await asyncio.sleep(confirm_pause_ms)`
so the human can see the highlight.

**Phase 2 — CLICK (only if `click_enabled`).**
A second probe resolves the click target (the stash root, or `click_selector` inside
it), re-checks clickability, logs `clickable: yes/no`, draws a thin
**ORANGE (`#ff9500`) 2 px outline** over the *click target* rect, waits a short beat,
then dispatches `.click()`. Result is logged as success/failure separately from the
find result.

Overlay implementation (`backend/dom_highlight.py` → injected JS helper
`window.__cfHighlight(el, color, ms, label)`):

* one `div` per highlight, `position:fixed`, `pointer-events:none`,
  `z-index:2147483647`, `outline:2px solid <color>`, `background:transparent`
  (outline only — never covers the element, so the subsequent `.click()` still hits
  the real target);
* an optional small corner caption (`FOUND` / `CLICK`) in the same color;
* auto-removed with `setTimeout` after `ms`, and defensively cleared at the start of
  each new find so overlays never accumulate;
* all overlays are tagged `data-cf-highlight` for bulk cleanup.

Because the outline is drawn on a separate, pointer-events-none element, it cannot
intercept the click or change layout.

### 2.3 New block settings

| key | default | meaning |
|---|---|---|
| `highlight_enabled` | `true` | draw the red/orange outlines |
| `confirm_pause_ms` | `700` | pause after FIND so the user can verify |
| `highlight_ms` | `1200` | how long each outline stays on screen |

Exposed in `config_schema()` and in the UI block defaults/labels so they are editable
and persist through the existing preset round-trip (`to_dict()` serialises all
instance attrs automatically).

Backwards compatibility: saved presets in `config.json` lack these keys; the
constructor defaults apply, so old blocks gain the feature automatically.

### 2.4 Log contract

```
🔍 FIND phase: element 'div[role=tab].tab-item' text inside 'p.chat-title' matching "Гостиная"
🔍 Selector matched 7 node(s)
✅ FIND success: matched node #3 “Гостиная” — visible, clickable  🟥 red outline drawn
⏸ Holding 700 ms for visual confirmation…
🖱 CLICK phase: target = div.tab-item
✅ CLICK target is clickable  🟧 orange outline drawn
✅ CLICK success — click dispatched on “Гостиная”
```

Failures mirror the same shape (`❌ FIND failed: … candidates: …`,
`❌ CLICK failed: element not clickable (hidden / pointer-events:none)`).

`ClickMainTab` / `ClickBack` reuse the same two-phase helper so the built-in tab
blocks get identical visual confirmation.

---

## 2.5 Two further root causes found while implementing

Building the executable test harness surfaced two more defects that also
contributed to “Tab Main does nothing”:

**(a) `click_selector` equal to the find selector.** The saved `Tab Main` block
has `click_selector = "div[role='tab'].tab-item"` — the *same* selector used to
find the element. A CSS selector only matches **descendants**, so
`root.querySelector(clickSel)` returned `null`, and the click was skipped. The
click probe now falls back to the root itself when `root.matches(clickSel)`, and
records a `note` explaining it.

**(b) `log_msg.emit(msg, level)` raised `TypeError`.** `ActionEngine.log_msg` is
declared `Signal(str)` but three call sites passed a second `level` argument.
Any run that hit one of those lines (notably the empty-queue path) threw
`TypeError: log_msg(QString) only accepts 1 argument(s)`, which was swallowed by
the generic `except Exception` handler and surfaced only as a vague `❌ Error:`
line. Those call sites now emit a single string.

---

## 3. Test plan

* Unit: probe builders emit syntactically valid JS (`node --check`-style eval of the
  expression shape), stash/highlight helpers present, colors correct.
* Unit: `interpret_find` / `interpret_click` message + level matrix
  (not found / found-hidden / found-disabled / found-ok / clicked / click-failed).
* Unit: engine runs a stack once with no users when no user-scoped block is present,
  and warns (does not silently pass) when user-scoped blocks are present.
* End-to-end: the real `Tab Main` block from `config.json` is executed by a real
  `ActionEngine` against a fake CDP client that replays the generated probes in a
  shared JS DOM — asserting the red outline, the pause, the orange outline and
  exactly one click on the correct node.
* Manual: run the `Tab Main` block against the live chat page — expect red outline on
  the tab, a pause, then orange outline and the tab switching.

### Results

`tests/test_find_click_visual.py` (22 tests) and
`tests/test_engine_standalone_run.py` (8 tests) — all green.

```
$ python3 tests/test_find_click_visual.py && python3 tests/test_engine_standalone_run.py
Ran 22 tests — OK
Ran  8 tests — OK
```
