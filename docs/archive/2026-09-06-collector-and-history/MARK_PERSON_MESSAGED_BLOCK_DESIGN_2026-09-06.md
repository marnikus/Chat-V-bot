# "Mark Person as Messaged" block — mark the {{nick}} person Done

Date: 2026-09-06

## 1. Feature request (user, verbatim intent)

> add block mark person as "messaged" — new Action block feature. It marks
> the nick from memory if exist in memory. memory-driven, single person
> per run — not the queue.

So: a block that flips **one person — the nick saved in this run's
{{nick}} memory (Pick Person / an earlier Click User)** — to Status ✅
Done in the People list. It does NOT read the queue.

## 2. How marking works today (background for the design)

Who marks & when (verified in code):
* **ActionEngine** (the run driver) marks automatically in exactly two
  places: (1) queue mode — after the whole stack finished OK for a queued
  person, `mark_messaged(user.nick)` + live `person_marked` grid update,
  before the next person; (2) "Use Person from Memory" single-target mode —
  after the single pass finished OK, the memory target is marked the same
  way. A failed pass marks nobody (the person stays New → retried later).
* The grid's **manual toggle** (bridge `set_messaged`) is separate.
* No action block marks anyone today (Click User only *remembers* a nick
  via `note_selected`).

The new block covers the flows where the engine's automatic marking does
not fit — e.g. a Pick Person → … → Mark stack that does not click the
person (no Click User), a standalone "single person per run" flow, or an
explicit mark at the end of a custom stack.

## 3. Behaviour (locked from the request + safety)

1. **Target = memory nick.** The block marks `engine.selected_nick` (the
   `{{nick}}` person) — never the queued user. It is standalone-capable
   (not user-scoped): [Pick Person → Mark Person as Messaged] runs with
   zero people in the queue.
2. **No nick in memory → FAIL with a clear ❌** (same wording family as
   Click User "Use Person from Memory"): nothing is marked blindly.
3. **Person not in the People list → FAIL ❌** "not in the People list —
   nothing marked" (the request's "if exist in memory").
4. **Already messaged → OK, informational** ("already messaged — nothing
   to change"): idempotent, so it never breaks a run on a Done person.
5. **Marked now → ✅ + live grid row update** (same `person_marked`
   signal the engine uses for automatic marking).
6. **Repeat Loop + Pick Person**: each cycle marks the picked New person
   Done, so the next cycle picks the next New person; when Pick Person
   matches nobody (all New are Done) the cycle ends like an empty queue
   (a small generic engine rule) instead of looping over the stale
   selection.

## 4. Design

* `backend/action_engine.py`:
  * new public `mark_person_messaged(nick) -> str` on the engine —
    looks up the person, returns `"missing"` / `"already"` / `"ok"`
    (marking + `person_marked.emit` on `"ok"`) / `"error"`. Precedent:
    blocks call engine methods (`note_selected`).
  * generic cycle guard in `_execute_cycle`: when a Pick Person exists but
    matched nothing and the stack is standalone-bound with an empty queue,
    end the cycle with `"empty"` (stops Repeat Loops) instead of looping
    over the previous selection forever.
* `actions/mark_messaged.py` — `MARK_MESSAGED` "Mark Person as Messaged"
  ✅; reads the saved nick, calls `engine.mark_person_messaged`, maps the
  status to the reports above. Registered in `actions/__init__.py`.
* `ui/js/stack-dnd.js` — block entry (defaults: none beyond pre-delay /
  enabled).
* `tests/test_mark_person_messaged.py` (new).

## 5. Acceptance

* [Pick Person → Mark Person as Messaged] with New people: the picked
  person ends Status Done; the others stay untouched; works with an empty
  queue; Repeat Loop stops after all New people are done.
* Empty memory → ❌; nick missing from People list → ❌; already Done →
  OK/info; no side effects on failures.
* All existing suites stay green (flag-free default; engine guard only
  fires for standalone-bound Pick-Person stacks with no match).
