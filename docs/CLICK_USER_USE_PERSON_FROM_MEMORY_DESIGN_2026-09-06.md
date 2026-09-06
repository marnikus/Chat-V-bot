# Click User "Use Person from Memory" — click the {{nick}} person, not the queue

Date: 2026-09-06

## 1. Feature request (user, verbatim intent)

Add a checkbox **"Use Person from Memory"** to the Click User (👤) block:

> When enabled — the block does NOT iterate through the person queue.
> Instead, it uses the nick already saved in `{{nick}}` memory from a
> previous block in the same run, finds and clicks that specific person
> directly. Use case: another block (e.g. Search Users / Pick Person) has
> already identified and stored the target person, and Click User just
> needs to act on that saved nick.
>
> When disabled (default) — current behavior: works through the queue.

The user's earlier requirement ("i need verify and be sure …") and the
"blocks that remember a nick" answer both still stand: `{{nick}}` memory =
`engine.selected_nick`, written by Pick Person (phase 2c) and by Click User
itself after a successful click, cleared on every Run press.

## 2. Behaviour decisions (locked from the spec)

1. **New checkbox** on Click User: `use_person_from_memory`, default **off**
   → existing stacks/behaviour byte-identical.
2. **On = no queue iteration.** The engine switches that cycle to a
   **single-target pass**: the stack runs exactly ONCE, regardless of how
   many people the queue/People list holds. Click User's target = the nick
   saved in memory this run.
3. **No saved nick → safe failure, never a blind click.** If memory is empty
   (no Pick Person before it and nothing clicked yet) the block reports
   `❌ Use Person from Memory: no person is saved in memory this run …`
   and fails. The ❌ names what can save a nick (Pick Person, or an earlier
   Click User) so the user can fix the stack.
4. **Success marks the person messaged** (Status → Done, live grid row
   refresh) — exactly like a queue run marks the person it worked. This is
   what makes **Repeat Loop + Pick Person** automatic: each cycle picks a
   random New person → clicks → messages → marks Done → next cycle picks the
   next New person. On a failed pass nothing is marked.
5. Re-clicking the same person stays valid: tab verification already treats
   "a tab titled with the nick is open" as success (not only count growth).
6. `respect_order` and Scroll & Parse are irrelevant/untouched in this mode:
   the person comes from memory, not from the list order.

## 3. Design

### 3.1 Block — `actions/click_user.py`

* `__init__` gains `use_person_from_memory: bool = False`; `config_schema`
  gains the checkbox (label "Use Person from Memory — click the person saved
  as {{nick}} this run, without the user list").
* In `execute()`: when the flag is on, resolve the target:
  `nick = getattr(engine, "selected_nick", "") or ""`; if empty → report the
  ❌ above and return FAIL. Otherwise click `nick` through the shared
  visual-confirmation runner + new-tab verification, exactly as today, then
  `note_selected(nick)` (same person — harmless re-remember).
* When off: `nick = user_nick` — untouched path.

### 3.2 Engine single-target mode — `backend/action_engine.py::_execute_cycle`

* `single_target = any(enabled CLICK_USER with use_person_from_memory)`.
* When true, after Phase 2c (Pick Person) the cycle bypasses the queue
  logic entirely:
  * log `▶ Single-target: Click User opens the person saved in memory` and
    announce the saved nick (or that none is saved and the block will fail
    safely);
  * build a one-element queue with the synthetic user = saved nick
    (`UserRecord(nick=selected)`, messaged=False) so later `{{nick}}`-less
    blocks still have a user context;
  * execute the stack once (`has_skip` honoured as in a normal run);
  * on OK **and** a real saved nick → `mark_messaged(selected)` +
    `person_marked.emit(selected)`; skip the per-user mark of a synthetic
    user when no nick exists;
  * outcome `"worked"` (Repeat Loop re-runs the whole cycle → Pick Person
    re-picks next cycle).
* Queue/needs-user/standalone branches are untouched for stacks without the
  flag (default). No changes to USER_SCOPED_BLOCKS.

### 3.3 UI — `ui/js/stack-dnd.js`

* CLICK_USER `defaults` gains `use_person_from_memory:false`; `labels` gains
  a clear label; summary maps the key to `target: {{nick}} memory` (nothing
  shown when off).

## 4. Files touched

* `actions/click_user.py` — checkbox + memory-target resolution.
* `backend/action_engine.py` — single-target cycle branch.
* `ui/js/stack-dnd.js` — block entry + summary.
* `tests/test_click_user_memory.py` (new).
* This doc.

## 5. Acceptance

* Checkbox off → all existing Click User suites stay green; queue flows,
  respect_order, tab verification, nick remembering unchanged.
* Checkbox on + a Pick Person (or prior Click User) saved a nick → the run
  executes the stack ONCE (not per queued person), the saved person is the
  one found/clicked (exact match, red → orange visual flow), the tab is
  verified, and the person ends up Status Done; logs say the target came
  from memory.
* Checkbox on, memory empty → ❌ log naming the cause; nothing clicked;
  nobody marked.
* Repeat Loop + Pick Person + memory Click User + Type Message → each cycle
  works a different New person until none are left.
