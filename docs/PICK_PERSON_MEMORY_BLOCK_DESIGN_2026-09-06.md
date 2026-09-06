# New "Pick Person" action block — pick a saved person and remember the nick

Date: 2026-09-06

## 1. Request

New action block: **take a person from the People list and save its nick in
Memory** (the run's remembered nick, i.e. what `{{nick}}` resolves to).
The pick rule is chosen with **radio buttons**:

1. any **random** un-messaged person (Status New);
2. any **random** already-messaged person (Status Done) — user corrected:
   not "the first messaged", a random one;
3. the **first person in Order (#)**, exactly starting from #1.

User confirmations:
* options 1 and 2 both mean *any random* person of that status;
* option 3 means exactly the person with Order # = 1;
* the block only *remembers* the nick (feeds `{{nick}}` in later block
  fields: Find & Click "Text it must contain", tab names, Type Message…);
  it does not click/open the person — navigation stays in other blocks;
* when the chosen rule has no matching person → **warn and skip** (step
  continues; the remembered nick is left unchanged).

## 2. Design

### 2.1 New block — `actions/take_person.py`, block_id `TAKE_PERSON`

A driver-style block (like Repeat Loop / Conditional Skip — no per-user
clicking, no real page interaction):

* `pick_mode` ∈ `random_new` (default) | `random_done` | `order_first`;
* helper `choose(rows, engine)` → a nick or `None`:
  * `random_new`    — `random.choice` over `rows` with `messaged == False`;
  * `random_done`   — `random.choice` over `rows` with `messaged == True`;
  * `order_first`   — `engine.queue_order(rows)[0]` when the list is
    non-empty (`queue_order` is the exact Order (#) column order → its first
    entry is #1; a person with no Order number can never be picked here);
  * empty pool → `None`.
* `config_schema()` documents the setting (used for parity/tests); the UI
  renders it as **radio buttons**.

### 2.2 Engine — runs it once per cycle, like a driver block

`backend/action_engine.py`:

* after the queue is built and the Order (#) override applied, a new
  `_run_take_phase()` walks the stack in order and, for every **enabled
  TAKE_PERSON**, resolves a nick and calls `note_selected(nick)`
  (the existing `{{nick}}` memory, cleared at each Run press). One block
  run per **cycle** — a Repeat Loop re-picks every cycle.
  * nick found → `🎯 Picked “X” … — remembered for {{nick}}`;
  * no match   → `⚠ Pick Person: no … person in the list — skipped`
    (warn + skip, previous selection kept).
* TAKE_PERSON is added to the engine-level blocks skipped inside the
  per-user loop (SCROLL_PARSE / REPEAT_LOOP already are) so it never
  re-randomizes once per queued user.
* TAKE_PERSON is **not** user-scoped: a stack that is only Pick Person +
  Find & Click / tabs still runs standalone once (like today's Repeat Loop
  stacks), and later `{{nick}}` fields resolve to the picked person.

### 2.3 UI — radio buttons (`ui/js/stack-dnd.js`)

* `BUILTIN_BLOCKS` entry:
  `{ block_id:'TAKE_PERSON', name:'Pick Person', icon:'🎯',
     defaults:{pick_mode:'random_new', enabled:true},
     radios:{pick_mode:['random_new','random_done','order_first']},
     radio_labels:{pick_mode:{random_new:'Any random un-messaged person (Status New)',
                              random_done:'Any random already-messaged person (Status Done)',
                              order_first:'The first person in Order (#) — exactly #1'}},
     labels:{pick_mode:'Pick a person from the list and remember its nick:'}, … }`
* config panel: a **radio group** for `pick_mode` (new small generic
  branch: same data-key binding as the existing checkboxes/selects, so it
  round-trips through history/undo/presets without extra plumbing).
* card summary shows the rule, e.g. `pick: random New` / `pick: random Done`
  / `pick: Order #1`.

### 2.4 Which blocks can remember a nick in Memory today (the second question)

One shared memory — the engine's remembered nick, exposed to every block
field as `{{nick}}`, cleared at the start of each Run press:

| Block | Remembers when… |
|---|---|
| **Click User** | after it clicks a person (`note_selected`) — existing behaviour |
| **Pick Person (new)** | when it picks by the chosen rule (this feature) |

Every other block **consumes** the memory: Find & Click "Text it must
contain…", Return to Main / Click Main Tab tab names, Type Message text
(and composer), etc. When nothing has been remembered yet, `{{nick}}`
falls back to the current step's queued user — unchanged.
Separately, the **People list DB** (UserMemory) persists every person seen,
which is the pool these blocks pick from.

## 3. Files touched

* `actions/take_person.py` (new) — block + `choose()`.
* `backend/action_engine.py` — `_run_take_phase()` + engine-level skip set.
* `ui/js/stack-dnd.js` — block entry, radio rendering, summary label.
* `tests/test_take_person.py` (new).
* `docs/PICK_PERSON_MEMORY_BLOCK_DESIGN_2026-09-06.md` (this).

## 4. Acceptance

* The three radio rules behave as specified (random New / random Done /
  exactly Order #1).
* Choosing stores the nick so later `{{nick}}` fields use it; nothing is
  clicked by the block itself.
* No matching person → warn + skip (run continues, selection unchanged).
* Saved stacks/presets round-trip the setting; existing suites stay green.
