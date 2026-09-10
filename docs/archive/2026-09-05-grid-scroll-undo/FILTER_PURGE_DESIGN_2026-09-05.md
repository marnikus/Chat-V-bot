# Design — Rejected people must never enter the list (and must be purged)

Date: 2026-09-05
Scope: `backend/action_engine.py`, `backend/scroll_parser.py`,
`actions/scroll_parse.py`, `backend/bridge.py`, `ui/js/*`

---

## 1. Reproduction

A page with two women (Anna, Zoe) and two men (Boris, Igor), filter = "must be
female", `min_new_users=1` so the first run stops early. Run, stop, run again:

```
--- after run 1: DB has 2 ---
     Anna       gender=female
     Boris      gender=male      ← filtered out, yet stored
--- after run 2: DB has 4 ---
     Zoe        gender=female
     Igor       gender=male      ← filtered out, yet stored
     Anna       gender=female
     Boris      gender=male
```

This matches the report exactly: re-running grows the list, and men appear even
though the filter is "female only".

---

## 2. Root causes

### 2.1 The engine persists **everyone it saw**, not everyone it collected

`ActionEngine._run_collect_phase()`:

```python
# Persist everyone we saw, so the "already messaged" memory keeps working.
for person in result.all_people:          # ← ALL, including rejected
    await self._memory.upsert_user(person)
```

`result.all_people` is every person the parser laid eyes on; `result.collected`
is the filtered subset. Writing `all_people` puts every rejected man straight
into the `users` table. The UI table renders `memory.get_all()`, so they show up.

The comment explains the intent — remembering who was already messaged — but
that only requires *collected* people, who are the only ones ever messaged.

### 2.2 Rejected people are never removed

Nothing deletes a person who fails the filter. So:

* anyone stored by 2.1 stays forever;
* anyone stored by an **earlier run under a laxer filter** also stays, even once
  the filter is tightened. Re-running can therefore only ever grow the list.

The requirement is explicit: a person confirmed *not* to pass the filter must be
**removed/destroyed as an entity**, not merely skipped.

### 2.3 Stop does not stop the scroll

`ActionEngine.stop()` sets `_stop_requested`, which is only checked in the
per-user loop (phase 3). The collect phase and `ScrollParser.collect()` never
look at it, so pressing **Stop** mid-scroll lets the parser run to completion
and then persist everything. This is why "stop then re-run" is the trigger that
makes the bug obvious.

---

## 3. Design

### 3.1 Persist only what passed the filter

`_run_collect_phase()` upserts `result.collected` — never `all_people`. Each
person is already upserted live by `person_collected()` as they are found, so
the end-of-run pass becomes a cheap idempotent safety net.

### 3.2 Purge rejected people as they are confirmed

`ScrollParser` gains an `on_reject(record, reason)` callback, fired the moment a
person fails the filter — symmetrical with the existing `on_collect`. The engine
wires it to `person_rejected()`:

```python
async def person_rejected(self, record, reason):
    removed = await self._memory.delete_user(record.nick)   # destroy the entity
    self.person_removed.emit(json.dumps({...}))             # UI drops the row
```

`delete_user()` already exists and is a no-op when the nick is absent, so this
both **prevents** new bad entries and **cleans up** ones stored by earlier runs
or under an older, laxer filter. That is what makes a re-run *shrink* the list
back to correctness instead of growing it.

`CollectResult` gains `rejected_people` and `purged` so the outcome is
inspectable and traceable.

A new block param `purge_rejected` (default `True`) allows switching the
destructive behaviour off; when off, rejected people are still never added.

### 3.3 Make Stop actually stop

`ScrollParser` accepts a `should_stop` predicate, checked

* at the top of every scroll iteration,
* inside the settle/lazy-load poll loop (so a stop during a 2.5 s wait is
  prompt).

The engine passes `lambda: self._stop_requested`. `CollectResult.stopped` records
it, the collect phase returns an empty queue on stop, and the run ends with a
clear "stopped by user" message rather than silently proceeding.

### 3.4 UI

New `person_removed` signal → `Bridge` → `UserTable.onPersonRemoved()` removes
the row immediately (and drops it from the selection), then `_refresh_users()`
reconciles. The log states why: `🗑 Removed “Boris” — not female`.

---

## 4. Invariant

> After any run, the users table contains **only** people who pass the currently
> configured filter. A rejected person is never inserted, and any existing
> record for them is deleted.

Tests assert this end-to-end across a stop/re-run cycle and a filter tightening.

---

## 5. Test plan

* rejected people are never persisted (the exact reproduction above);
* pre-existing rejected records are purged on the next run;
* tightening the filter shrinks the list;
* `purge_rejected=False` still refuses to add them;
* Stop interrupts scrolling promptly, mid-settle, and persists nothing new;
* a delete failure never aborts the parse;
* `purge_rejected` round-trips through presets.
