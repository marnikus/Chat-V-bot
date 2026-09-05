# Design — Backlog guard: don't collect new people while a backlog exists

Date: 2026-09-05
Scope: `actions/scroll_parse.py`, `backend/scroll_parser.py`,
`backend/action_engine.py`, `backend/user_memory.py`, `ui/js/stack-dnd.js`

---

## 1. The requirement

> Add a checkbox to the config: **Scroll & Parse must not add new people if at
> least X persons with a not-messaged status already exist in the list.**

Two settings:

| param | type | default | meaning |
|---|---|---|---|
| `skip_if_backlog` | checkbox | `false` | enable the guard |
| `backlog_threshold` | number | `5` | the X above |

Rationale: there is no point harvesting more people while a pile of un-messaged
ones is already waiting. Scrolling the virtual list is slow and visually noisy,
and every collected person is another row the user has to work through.

---

## 2. Current behaviour

`ScrollParse.run_pipeline()` always scrolls. Nothing consults the existing
backlog. The only related setting is `min_new_users`, which is a **different**
thing and the two must not be confused:

| setting | question it answers | when it acts |
|---|---|---|
| `min_new_users` | "how many new people is enough for **this** run?" | *during* the scroll — stop early once N new un-messaged are collected |
| `backlog_threshold` (new) | "should this run collect **at all**?" | *before* the scroll — skip entirely if N un-messaged already exist |

They compose naturally: the guard decides whether to start, `min_new_users`
decides when to stop.

---

## 3. Design

### 3.1 Where the check happens

At the **top** of `run_pipeline()`, before a single scroll is issued — the whole
point is to avoid the scrolling work, so checking afterwards would be useless.

```
run_pipeline()
  ├─ backlog = await engine.backlog_count()      # un-messaged rows in memory
  ├─ if skip_if_backlog and backlog >= threshold:
  │     └─ return CollectResult(skipped=True, backlog=backlog)   # no scrolling
  └─ …normal scroll → filter → collect…
```

### 3.2 Counting the backlog

`UserMemory.count_unmessaged()` runs a single `SELECT COUNT(*) … WHERE
messaged=0`, rather than materialising every row through `get_all()`.

The engine exposes an async `backlog_count()` hook, mirroring the existing
`person_collected` / `person_rejected` / `is_stopping` hooks the block already
discovers via `getattr`. It degrades gracefully: if the memory object lacks
`count_unmessaged` it falls back to counting `get_all()`, and any failure
returns `0` (fail open — a counting error must never silently stop collection).

`run_pipeline()` also accepts an explicit `backlog=` argument so the behaviour
is directly testable without an engine.

### 3.3 What a skipped run returns

Skipping means **"do not add new people"** — emphatically *not* "do nothing".
The people already waiting must still be worked through, otherwise enabling the
checkbox would stall the whole stack.

So `CollectResult` gains `skipped: bool` and `backlog: int`, and
`_run_collect_phase()` returns the **existing un-messaged queue** from memory
when the run was skipped:

```python
if result.skipped:
    return await self._memory.get_queue()      # work the backlog, add nobody
```

The downstream blocks (`CLICK_USER`, `TYPE_MESSAGE`, …) then process the
backlog exactly as usual.

### 3.4 Consequences of skipping

Because no scrolling happens, nothing is filtered and therefore nothing is
purged. That is consistent: purging is the verdict of *evaluating* a person, and
in a skipped run no one is evaluated. Documented so it is not mistaken for a
regression of the previous fix.

`ScrollParse.execute()` (the standalone path, when the block is run outside the
collect phase) returns `OK` for a skipped run — the guard firing is a correct
outcome, not a failure.

### 3.5 Logging

The guard must be loud, since "nothing happened" is otherwise indistinguishable
from a bug — the exact failure mode of the earlier "Tab Main" issue:

```
⏸ Backlog guard: 7 un-messaged person(s) in the list ≥ threshold 5
   — skipping collection, no new people will be added
   (work through the backlog, or lower/disable the guard to collect more)
```

and when it passes:

```
✅ Backlog guard: 2 un-messaged person(s) < threshold 5 — collecting
```

The threshold check is `>=`: "at least X persons exist" is the stated trigger.

### 3.6 Edge cases

* `backlog_threshold <= 0` with the guard on would block every run forever;
  clamped to a minimum of 1 and warned about.
* Guard off (default) — behaviour is byte-identical to today.
* The count is of **un-messaged** rows only; messaged people are history and
  must not hold collection back.

---

## 4. Test plan

* guard off → always collects (no regression);
* backlog ≥ threshold → no scrolling at all, nobody added, existing queue still
  returned so the stack keeps working;
* backlog < threshold → collects normally;
* boundary: `backlog == threshold` skips (the "at least X" reading);
* messaged people never count toward the backlog;
* a counting failure fails open (collects) rather than stalling;
* threshold clamped when `<= 0`;
* both params round-trip through presets and appear in the UI schema.
