# Repeat Loop action block — design

Date: 2026-09-05

## 1. Problem

Pressing **Run** executes the action stack exactly **once**: one collect
phase (Scroll & Parse) followed by messaging every queued person. To harvest
the *next* batch of people the user must click Run again by hand.

Request: add a new **Repeat Loop** action block whose setting sets the number
of times the whole run repeats, so after pressing Run the stack plays N
cycles automatically instead of just once.

## 2. Requirements

* A new stack block “Repeat Loop” (icon 🔁) with one setting: the number of
  run cycles (the “play loop” count).
* When present and enabled, clicking Run executes the whole stack N times —
  each cycle re-runs the collect phase (Scroll & Parse: scroll-only seek
  first, fall back to adding people when nobody is waiting) and then works
  through the queued people.
* With no Repeat Loop block (or it is disabled / count ≤ 1) behaviour is
  byte-for-byte what it is today: exactly one cycle.
* The block is a **marker**, like `CONDITIONAL_SKIP`: it has no per-user
  action; the engine reads its `repeat_count` once at run start.
* Stop (and Pause) must stay honoured *between* cycles, not only inside one.
* A cycle that finds no work (empty queue on a user-scoped stack) ends the
  loop early instead of spinning through the remaining cycles.

## 3. Design

### 3.1 The block — `actions/repeat_loop.py`

```python
class RepeatLoop(BaseAction):
    block_id = "REPEAT_LOOP"
    name = "Repeat Loop"
    icon = "🔁"
    def __init__(self, repeat_count: int = 2, **kw):
        kw.pop("pre_delay_ms", None)      # marker: no pre-delay
        super().__init__(pre_delay_ms=0, **kw)
        self.repeat_count = max(1, int(repeat_count))
```

Registered by importing it in `actions/__init__.py` (registry auto-discovery
via `__init_subclass__`). `to_dict()` round-trips `repeat_count` (plain
attribute) so presets / undo history / the Tune panel all work unchanged.

### 3.2 Engine — `backend/action_engine.py`

* Helper `_repeat_cycles()`: first **enabled** `REPEAT_LOOP` block in the
  stack → `max(1, int(repeat_count))`, else `1`.
* `execute()` keeps the one-time setup (run id, tracer, banners, `finally`
  cleanup) but delegates the phases to `_execute_cycle()`. When
  `_repeat_cycles() > 1` the cycle body runs that many times with a
  `🔁 Cycle i/N` banner; `repeat == 1` takes the identical single-pass path
  (no extra banners) so existing behaviour and messages are preserved.
* `_execute_cycle()` returns an outcome so the driver can decide:
  * `worked`  — a queue (or a standalone synthetic user) was processed;
  * `stopped` — Stop was requested (break the loop);
  * `empty`   — the stack needs users but the queue is empty (loud warning
    is emitted once inside the cycle; loop ends early);
  * `empty_stack` — nothing to run.
* Stop/Pause are checked at the top of every cycle (`_wait_if_paused` +
  `_stop_requested`), mirroring the checks that already exist per user.
* `_execute_for_user()` skips `REPEAT_LOOP` the same way it skips
  `SCROLL_PARSE` and `CONDITIONAL_SKIP` markers.
* `USER_SCOPED_BLOCKS` does NOT include `REPEAT_LOOP` (it is a driver block,
  like `PAUSE`, not a per-person step).

### 3.3 Frontend — `ui/js/stack-dnd.js`

`BUILTIN_BLOCKS` gains a `REPEAT_LOOP` entry (defaults `{repeat_count: 2,
enabled: true}`, label “Number of loop cycles (how many times the whole run
repeats)”). The existing `_migrateBlock()` back-fills `repeat_count` on any
legacy stack that has the block, and the add-menu / Tune-panel / presets /
undo machinery then work for free.

### 3.4 Interaction with Scroll & Parse (why it does what the user wants)

Each cycle starts a fresh collect phase. Scroll-only mode first seeks an
already-known un-messaged person (none after cycle 1, because everyone found
was just messaged) and then falls through to *adding new people* — which is
exactly the “drain the backlog, then resume harvesting” circle the user
described, now driven automatically by one Run press.

## 4. Files touched

* `actions/repeat_loop.py` (new), `actions/__init__.py` (import).
* `backend/action_engine.py` (cycle driver + marker skip).
* `ui/js/stack-dnd.js` (BUILTIN_BLOCKS entry).
* `tests/test_repeat_loop.py` (new), docs this file.

## 5. Acceptance

* Stack with a Repeat Loop block (count N) → Run executes N full cycles.
* Without the block / disabled / count ≤ 1 → exactly one cycle (current
  behaviour unchanged; standalone, empty-stack and empty-queue messages
  intact).
* Stop between cycles ends the run; a cycle with no work ends the loop.
* The block round-trips through presets and undo; its Tune-panel label and
  summary are readable.
* Existing Python + Node suites stay green.
