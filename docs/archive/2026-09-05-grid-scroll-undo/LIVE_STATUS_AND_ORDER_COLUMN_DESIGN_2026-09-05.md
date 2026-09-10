# Live People status refresh + undo timestamp erase + Order (#) column

Date: 2026-09-05

## 1. Problems

### BUG A — People statuses only refresh after restart

The table re-renders only when the backend emits `users_updated`. That
signal is emitted by the people-list *handlers* (`_do_reset`, `_do_clear`,
`_do_delete_*`, `_do_set_messaged`, `_do_apply_people`, live
`person_found`/`person_removed`) — but **never after the engine marks a
person messaged during a run**. `ActionEngine._execute_cycle` writes
`memory.mark_messaged(nick)` straight into SQLite with no signal, so after
a run the rows that were processed keep showing “New” (and the stats
“Queued/Done” counters stay stale) until the app restarts.

Confirmed by probe: `mark_messaged()` → 0 `users_updated` emissions.

### BUG B — “New” people keep their messaged timestamp

Two writers set `messaged=0`:

* `UserMemory.reset_messaged()` (the **Reset Messaged** button) executes
  `UPDATE users SET messaged=0` and **leaves `last_messaged` (and
  `message_count`) untouched** — a “New” row still shows its old message
  time in the Messaged column.
* `set_messaged(nick, False)` (per-row ↩ Undo) already clears
  `last_messaged` — correct.

Because of BUG A the UI may also show a row as “New” while the DB already
has `messaged=1`; the user then clicks “✔ Done” on an already-Done row,
and the recorded undo entry has `messaged=1` in its “before” half — so
undoing appears to “not reset the status”, and the timestamp from the run
remains.

### FEATURE C — Processing Order (“#”) column

There is no way to see in which order the algorithm will process people.

## 2. Requirements

1. Every status change refreshes the table + stats immediately (per-person
   during a run, not only at run end).
2. Undoing/removing a messaged status must clear the flag **and erase the
   timestamp**; a person whose status is “New” never shows a message time.
3. New “Order” column: processing position 1 = first, N = last, dynamic,
   sortable with the existing ▲▼ arrow headers. People that are **not**
   “New” (already messaged) have **no number**.

## 3. Design

### 3.1 Real-time refresh after the engine marks a person

* `ActionEngine` gains `person_marked = Signal(str)`. It is emitted right
  after `mark_messaged()` succeeds in `_execute_cycle` (inside the existing
  `if ok and not standalone:` guard).
* `Bridge` connects it to a new `_on_person_marked()` that schedules
  `_refresh_users()` (same pattern as `_on_person_found`). The refresh
  re-emits `users_updated` + `stats_updated`, so the row flips to
  ✅ Done and the Done counter rises the moment the person is processed.
* `Bridge` also schedules one `_refresh_users()` on `engine.stack_complete`
  (final sync; covers every run shape).

### 3.2 Erasing the timestamp whenever the flag goes off

* `UserMemory.reset_messaged()` becomes
  `UPDATE users SET messaged=0, last_messaged=NULL` — the Reset Messaged
  button now clears the message time of every person it un-marks
  (`message_count` is a historical counter and stays untouched, matching
  the per-row ↩ Undo behaviour).
* UI guard in `UserTable._row()`: the Messaged cell renders the timestamp
  only when `u.messaged && u.last_messaged`, otherwise `—`. Any legacy row
  (messaged=0 yet timestamped) can no longer look inconsistent.
* With BUG A fixed, the undo history’s “before” half of a ✔ Done action is
  always the true on-screen state; undoing a ✔ Done restores
  `messaged=0` + `last_messaged=NULL` in one Ctrl+Z (already verified for
  the pure path; now it is also correct for the run-stale flow).
* Audit result: all other status-bearing surfaces (✅/🆕 badge, row-new
  tint, Queued/Done/Total stats, ✔/↩ button label) derive from
  `users_updated`/`stats_updated`, so the single missing emitter was the
  engine run path (BUG A). Registered/gender/etc. change only via live
  collection, which already refreshes per person.

### 3.3 Order column — the selector algorithm, exposed

The engine builds its run queue two ways (see `ActionEngine._execute_cycle`):

* an **enabled SCROLL_PARSE block** → the collect pipeline orders people
  with `person_filter.sort_people` (un-messaged first, then A–Z,
  casefold) and only un-messaged people enter the queue;
* **no SCROLL_PARSE** → `UserMemory.get_queue()`: `WHERE messaged=0
  ORDER BY first_seen DESC` (newest discovered first).

The Order column must show exactly that priority, so:

* `ActionEngine.queue_order(users) -> list[nick]` implements the two
  branches above (messaged people are never numbered).
* `Bridge._refresh_users()` builds a `nick → rank` map from it and adds
  `"order": rank|None` to every row of the `users_updated` payload (a
  defensive fallback uses `memory.get_queue()` when the engine cannot
  answer, e.g. test harnesses).
* Because the rank depends on the current stack, `_refresh_users()` is
  also scheduled after every backend stack change
  (`push_global_history("stack", …)` and stack undo/redo via
  `_apply_global_entry`), so the numbers re-label live when a Scroll &
  Parse block is added/removed/toggled/undone.

Frontend:

* `ui/index.html`: new `<th data-sort="order">#` after the select column
  (tooltip “Processing order — 1 = first to be processed”, ▲▼ arrows like
  every other sortable header).
* `UserTable._row()`: new narrow `col-order` cell — a **number only for
  un-messaged people**, `—` for everyone else.
* `UserTable._sortValue()` handles `order` as a number; rows without an
  order stay at the end in either direction (existing empty-value
  semantics). Clicking the header sorts 1→N / N→1 with the arrows.
* Placeholder rows’ `colspan` 8 → 9.

Scroll-only seek mode picks whichever un-messaged person the live page
shows first (DOM order); that cannot be known while the app is at rest, so
the at-rest numbers use the deterministic queue baseline above.

## 4. Files touched

* `backend/action_engine.py` — `person_marked` signal + emit;
  `queue_order()`.
* `backend/bridge.py` — `_on_person_marked`, stack_complete refresh,
  `order` in the `users_updated` payload, refresh on stack history writes.
* `backend/user_memory.py` — `reset_messaged()` clears `last_messaged`.
* `ui/index.html` — `#` header.
* `ui/js/user-table.js` — order cell, sort value, Messaged display guard,
  colspan 9.
* `tests/test_people_undo.py` (reset expectations), new
  `tests/test_live_status_and_order.py`.
* Docs this file.

## 5. Acceptance

* During a run each processed person flips to ✅ Done as it is messaged
  (no restart needed); Queued/Done stats move live.
* Reset Messaged (and per-row ↩ Undo) leave people New with **no**
  timestamp; ✔ Done then Ctrl+Z restores New with the timestamp erased.
* The People table has a sortable `#` column; un-messaged people carry
  1..N according to the selector algorithm (A–Z when a Scroll & Parse
  block is enabled, newest-first otherwise), messaged people show `—`;
  numbers re-render dynamically on every change (status flip, delete,
  undo/redo, stack edit).
* Existing suites stay green.
