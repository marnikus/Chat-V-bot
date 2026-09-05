# Click User: “Respect the Order (#) column” checkbox

Date: 2026-09-06

## 1. Problem

A messaging run picks its targets from what Scroll & Parse happens to have
in front of it that cycle:

* **scroll-only / seek mode** stops the scroll at the first waiting person
  the *page* shows (DOM order) and messages exactly that one — so if the
  chat page is sorted by activity, the person clicked is “some random New
  person”, not the first of the People list;
* **collect mode** queues the people seen this scroll (sorted A–Z, so
  ordering matches the list only for the page-visible subset).

The People list already has an authoritative **Order (#)** column (the
same serialization the engine would queue — A–Z under an enabled Scroll &
Parse block, newest-discovered first otherwise, numbered 1 = first
processed … N = last, only for Status-New people). There is no way to tell
the Click User block “just work the People list in that Order”.

## 2. Request (user-confirmed)

Add a checkbox to the **Click User** block. When it is ON, the run still
processes every person with Status New, but **strictly in the Order (#)
column order** — the person with #1 is clicked first, then #2, #3 … N —
instead of following whichever order the page/list happened to show that
run. (Confirmed choice: “Message everyone in Order (#) sequence”.)

## 3. Design

### 3.1 Block setting — `actions/click_user.py`

New plain setting `respect_order: bool = False`:
* label: “Respect the Order (#) column — message people 1, 2, 3… N in list
  order”;
* `config_schema()` gains the checkbox; `to_dict()` round-trips it like
  every other setting (presets / undo history / engine snapshots).

The block’s own `execute()` is unchanged — it still clicks the exact nick
it is asked for (visual runner + tab confirmation). The ordering is an
**engine queue** decision so backend bookkeeping (mark_messaged per user)
always matches the person actually processed.

### 3.2 Engine — `backend/action_engine.py`

In `_execute_cycle()`, after the collect phase produced its queue and
*before* the per-user loop:

* if any **enabled CLICK_USER** in the stack has `respect_order=True`:
  * fetch the current People Memory rows (`get_all()`),
  * rank them with the exact same `queue_order()` used to draw the # column
    (A–Z under an enabled Scroll & Parse block; newest-first otherwise) —
    only un-messaged people are ranked, matching the table,
  * replace the cycle queue with those ranked records;
  * log `🔢 Respecting the Order (#) column — running N user(s) in list
    order (#1 first)`.
* otherwise the queue is exactly what it is today (no behavioural change).

Empty queue stays empty: if the collect/seek phase found nobody un-messaged
on the page this cycle, the engine does NOT invent a queue from memory-only
rows (people stored from earlier sessions but not currently visible) — that
would only produce a run of failing clicks. Waiting people surface in a
later cycle/run once they are on the page again.

Consequences, all intended:
* #1 of the list is always the first person clicked; #2 second; etc.
* People stored from earlier sessions who are **not** currently on the
  page now join the run queue too (the People list is the queue); if a
  person is not visible, their click step fails with the existing explicit
  log and the run continues with the next # (per-user failures never abort
  the queue). A later cycle/run retries them once they are back on the
  page.
* `Repeat Loop` still works: cycle 1 messages #1…#N that succeed; once the
  list has no Status-New people left, the next cycle finds an empty queue
  and ends the loop cleanly.
* CONDITIONAL_SKIP / enable toggles / mark_messaged semantics unchanged.

### 3.3 Frontend — `ui/js/stack-dnd.js`

* `BUILTIN_BLOCKS` CLICK_USER entry: `defaults` gain `respect_order:false`,
  labels gain “Respect the Order (#) column…”. `_migrateBlock()` back-fills
  it onto every existing/preset/history block (generic mechanism).
* Boolean rows render as a normal checkbox in the Tune panel (existing
  generic path — no special casing needed).
* Card summary: `respect_order=false` adds nothing; when true it shows
  “respect Order (#)”.

## 4. Files touched

* `actions/click_user.py` — `respect_order` + schema.
* `backend/action_engine.py` — list-order queue replacement in
  `_execute_cycle()`.
* `ui/js/stack-dnd.js` — default/label/summary.
* `tests/test_click_user_order.py` (new), docs this file.

## 5. Acceptance

* Checkbox ON: a run clicks every Status-New person in the exact Order (#)
  sequence — #1 first, #2 next, … N last — regardless of page/DOM order
  and including waiting people not seen this scroll.
* Checkbox OFF (default): behaviour identical to today.
* The setting round-trips through block dicts/presets and shows in the
  Tune panel; existing suites stay green.
