# {{nick}} in any field: the remembered selected-user nickname

Date: 2026-09-06

## 1. Problem

The run only substitutes `{{nick}}` inside one place today: the **Type
Message** block's text (`actions/type_message.py`), and even there it uses
the *queued* user nick of that step.

Everything else treats the marker literally: if the user types `{{nick}}`
into a **Find & Click** match-text field ("Text it must contain…"), a
**Return to Main / Click Main Tab** "Tab name (text match)" field, or any
other text field, the run searches for the literal characters `{{nick}}`
and fails.

Real need (user request): the moment a **Click User** block selects a
person, that **nickname stays remembered until the next selection happens**,
and any block field using the `{{nick}}` marker resolves to that remembered
nickname. Example from the user: a "close tab" Find & Click whose
"Text it must contain" field is `{{nick}}` — it must match the tab/row of
the user selected earlier in this loop.

## 2. Design

### 2.1 Engine remembers the last selected user — `backend/action_engine.py`

* `ActionEngine.__init__`: new attribute `self.selected_nick = ""`.
* `ActionEngine.note_selected(nick)`: sets `self.selected_nick = nick`
  (no-op when empty) and notes it in the run trace.
* reset to `""` at the start of every `execute()` run press, so a fresh run
  never leaks a nick from the previous one.
* **Click User** (`actions/click_user.py`) calls `engine.note_selected(user_nick)`
  right after the physical click succeeds (`find_and_click_exact` returns OK,
  before tab verification) — clicking the row IS the selection.

### 2.2 One shared resolution rule

`{{nick}}` always resolves to the run's current selected nickname, with the
current step's queued user as fallback (so stacks without any Click User —
and all existing Type Message behaviour — keep working unchanged):

    nick = engine.selected_nick or user_nick   (engine may be None → user_nick)

This matches "remembered until the next selection": blocks placed *before*
the next Click User in a later repeat cycle see the previous selection;
blocks after a successful click see the person just selected.

### 2.3 Every text field honours the marker — engine-level expansion

Rather than editing a dozen blocks individually, the **engine expands the
marker on the block's string settings immediately before the block runs**
and **restores the original literal `{{nick}}` afterwards** (per step, so
the stored config/presets/history are never mutated and the next repeat
cycle re-expands with the then-current nick):

* in `_execute_for_user`, right before `block.execute(...)`: copy every
  string attribute containing `{{nick}}`, replace with the resolved nick,
  run the block, then restore the originals in a `finally`.
* only `vars(block)` strings are touched; underscore-internal/class/None
  values are skipped. Blocks already skip special block ids, so expansion
  applies to exactly the blocks that execute.
* **Type Message**: its internal `replace("{{nick}}", user_nick)` stays as
  the engine-less fallback (unit tests) and is upgraded to use the
  resolved rule (`engine.selected_nick or user_nick`) when an engine is
  present, so composer text honours the remembered nick too. The engine
  expansion and the internal replace never fight: after expansion the
  message holds no literal `{{nick}}`, so the internal replace is a no-op.

### 2.4 UI hints — `ui/js/stack-dnd.js`

The marker works in every text field automatically, but the user must know
it exists. Add `({{nick}} = selected user)` to the labels that are natural
match-text targets:

* Find & Click → "Text it must contain…"
* Return to Main / Click Main Tab → "Tab name (text match)"
* Type Message → "Message text" (already hints `(use {{nick}})`, reworded
  to the shared phrasing)

Python `config_schema` labels mirror the JS labels for consistency.

## 3. Files touched

* `backend/action_engine.py` — `selected_nick`, `note_selected()`, reset on
  run start, per-step expand/restore in `_execute_for_user`.
* `actions/click_user.py` — call `note_selected()` after a successful click.
* `actions/type_message.py` — resolved-nick rule instead of raw `user_nick`.
* `ui/js/stack-dnd.js` — label hints; (schema labels in the two actions).
* `tests/test_nick_placeholder.py` (new) + doc.

## 4. Acceptance

* After Click User clicks "Anna", every `{{nick}}` in any block field of the
  same run resolves to "Anna"; after a later Click User clicks "Bella", the
  marker resolves to "Bella" (remembered until the next selection).
* Blocks before the first Click User (or in a stack with none) fall back to
  the step's queued user — identical to today's Type Message behaviour.
* A new run press forgets the remembered nick.
* Existing stacks/presets are unaffected; settings round-trip untouched
  (expansion is temporary per step).
