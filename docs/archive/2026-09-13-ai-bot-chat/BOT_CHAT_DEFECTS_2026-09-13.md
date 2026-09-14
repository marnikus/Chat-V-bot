# AI Bot Chat — defect round (2026-09-13)

Follow-up to `AI_BOT_CHAT_DESIGN_2026-09-13.md`. The feature shipped green
(2869 passed, RULE 16 gate clean, coverage above baseline), so this round is
**not** about the metrics. It is about what the tests did not ask.

Everything below was found by reading the new code against the repo's existing
invariants rather than against its own tests. They are ordered by blast radius,
worst first, and that order is the implementation order.

---

## P1 — the reaction labels never reach the database (feature-dead)

`BotChatService.labels` reads the label store off the archive:

```python
store = getattr(self.archive, "labels", None)      # bot_chat.py
return ReactionLabels(store) if store is not None else None
```

`HistoryService` has **no** `labels` attribute. It stores the label store as
the private `self._labels` (`services/history/__init__.py:27`, written by
`bind_labels`). Verified against the real object:

```
>>> HistoryService(cdp=None)
has .labels attr: False      has ._labels attr: True
```

So in the running app `self.labels` is always `None`, `apply_reaction` always
returns `Err("bot_no_world")`, and **no reaction label can ever be applied** —
by the AI or by a manual click. The entire labelling half of the feature is
dead on arrival.

Why every test passed anyway: `tests/unit/services/test_bot_chat_service.py`
defines `FakeArchive(db=None, labels=None)` with a **public** `labels`
attribute. The double invented an interface the real collaborator does not
have, and then the suite verified the double. This is the single most valuable
finding of the round and it is a *test-design* bug as much as a product one.

**Fix.** Stop asking the archive at all. The label store's owner in the bridge
layer is `BridgeContext.label_store()` — the same accessor `LabelBridge` uses,
lazily built and world-bound. `BotChatService` takes the store as a
constructor dependency (`labels=`) instead of digging a private attribute out
of a neighbour. The bridge passes `ctx.label_store()`.

**Pin.** A test that asserts against the **real** `HistoryService` that the
service does not depend on an attribute it does not have — i.e. constructing
`BotChatService` with a real `HistoryService` as archive and a real
`LabelStore` must still apply a label. A double may not stand in for the
collaborator whose interface is the thing under test (RULE 8).

## P2 — a message can be delivered to the wrong person (data-safety)

`deliver(cdp, text)` types into whatever chat tab happens to be open and
clicks send. Nothing checks that the open tab belongs to `nick` — the nick is
not even a parameter. The window's person is chosen in the UI (User Memory
click); the browser's open tab is chosen by whatever the user or a run last
did. They drift apart trivially: load Anna in Bot Chat, click another chat in
the browser, approve, send → Anna's AI-written message goes to someone else.

The repo already treats this exact class of mistake as a first-order hazard:
RULE 15's private gate and `chat_sync`'s `verify_partner` refuse with
`partner_mismatch` when `norm(state["partner"]) != norm(self.nick)` before
*reading* a conversation. Writing to the wrong person is strictly worse than
reading the wrong one, and it is the only irreversible action in this feature —
there is no undo for a sent message.

**Fix.** `deliver(cdp, nick, text)` probes the page (`ChatParser.state()`) and
refuses with `bot_wrong_chat` unless the open tab's partner matches `nick`,
reusing `backend.chat_text.norm` for the comparison, exactly as `chat_sync`
does. An unreadable probe refuses too: this gate fails **closed**, like RULE
15's. The bridge slot gains the nick, and the JS sends `this.nick` with it.

## P3 — the label write bypasses the global undo timeline (RULE 12 / I-10)

`ReactionLabels.apply()` calls `store.set_for()` directly. Every other label
mutation in the app goes through `LabelBridge._labels_edit`, which snapshots
before/after, pushes ONE `labels` entry via `ctx.undo.push`, emits
`LabelsChanged` and `PeopleChanged`, and only then reports success.

Consequences of the bypass, all three real:
1. **Ctrl+Z cannot reverse an AI label.** RULE 12 says *every* editable surface
   records onto the one timeline; this one does not.
2. **The Label Manager panel does not refresh** — no `LabelsChanged` emitted,
   so the pills in the other window go stale until something else reloads them.
3. **The People queue's count goes stale** — labels can hide people from the
   queue, which is precisely why `_labels_edit` emits `PeopleChanged`.

Note the module docstring of `bot_reactions.py` *claims* "one call is one
reversible entry on the global timeline (RULE 12)". It is one call, but nothing
ever pushed it. A docstring asserting an invariant the code does not implement
is worse than no docstring.

**Fix.** `BotChatService.apply_reaction` takes an injected `edit` callable —
the bridge passes `LabelBridge._labels_edit` — so the AI path reuses the *same*
one-entry-per-mutation transaction as the manual path instead of re-deriving
it. No new undo plumbing, no second way to write a label. When no editor is
wired (pure service tests), it falls back to the direct write, which keeps the
service usable headless without duplicating the transaction logic.

## P4 — `today()` disagrees with how the archive dates a message

`today_key()` is `date.today().isoformat()`. The archive does **not** date
rows that way: `stores/history_repo_identity.resolve_days` walks the page's
`HH:MM` stamps backwards from `now`, so a message can be stamped yesterday
while the wall clock says today, and it resolves days relative to an injected
`now` rather than the process clock.

The practical failure is the midnight window and the "no messages today" dead
end: at 00:10 the window says "no messages with X today to work from" although
the conversation two minutes old is stamped the previous day. For a feature
whose whole premise is "only the current day's new session messages", silently
showing an empty day is the worst available answer.

**Fix (deliberately small).** Keep the day filter — it is the requirement — but
stop hiding an empty result behind a dead end: `today()` reports
`empty_reason` distinguishing *no rows at all today* from *archive closed*, and
`suggest_reply` includes the day in the error so the user can see which day was
searched. Re-dating the archive is out of scope and would be a change to
`resolve_days`, which the collector owns. Recorded here rather than silently
left: **the day boundary is the archive's, not the clock's.**

## P5 — `GrokSettings.api_key` is unreachable, and the error says otherwise

The API key is read from config section `grok`, key `api_key`. Nothing in the
UI writes it (`grep -rn "api_key" ui/` → no hits). So the only way to use the
feature is to hand-edit `settings.json`. Worse, the error text sends the user
somewhere that cannot help:

```python
return Err("grok_no_key", "no Grok API key — set it in the Prompt Editor window")
```

The Prompt Editor window has no key field. The message is false.

**Fix.** Add the connection fields (API key, model) to the Prompt Editor
window, which is the natural home and already the "Grok settings" surface, with
the key rendered as a password input and never echoed back into a log line.
`GrokSettings` gains the matching `save` path. The error message then becomes
true rather than being reworded to hide the gap.

## P6 — `reply_text` is CC 9 for parsing four fields

Measured worst new function. It is not over the gate (≤10), but §18.1 wants
4–20 lines and low branching, and the shape — a chain of `isinstance` /
truthiness guards each returning a different `Err` — is exactly the "validate
then extract" pattern that reads better as a small table. This is the one
purely stylistic item in this round and it is last on purpose: RULE 19 says
size/shape work comes after correctness, and I will only do it if P1–P5 leave
the file inside its budget.

---

## Implementation order and gates

1. P1 — inject the label store (product + the double that hid it)
2. P2 — recipient verification in `deliver`
3. P3 — route the write through `_labels_edit`
4. P4 — honest empty-day reporting
5. P5 — key/model fields in the Prompt Editor
6. P6 — only if the budget allows

Each step lands with the test that would have caught it. Closing gates are the
ones the feature already has to pass: full suite, all JS suites,
`tools/metrics/rule16_gate.py` (with the OWNED table updated for every new or
renamed function), coverage at or above the 90.98 / 87.08 this feature left,
and a RULE 18 re-measure of every file touched.

---

## Outcome (executed)

All six landed. Measured, not asserted:

| # | Defect | Fix | Pinned by |
|---|---|---|---|
| P1 | label store read off `archive.labels`, which does not exist → labelling dead in the app | injected `labels=` (`ctx.label_store()`) | `TestRealArchiveInterface` — drives the **real** `HistoryService` |
| P2 | message could be delivered to whoever's chat was open | `deliver(cdp, nick, text, parser)` + `check_recipient`, fails closed | `TestTheRecipientIsVerified`, `TestTheSendGateOverTheWire` (gate not mocked out) |
| P3 | label write bypassed the undo timeline, Label Manager and People count | routed through `LabelBridge._labels_edit` | `TestTheWriteIsOneUndoableEdit`, `TestTheLabelWriteIsUndoable` |
| P4 | "no messages today" hid both a closed world and the archive's day boundary | `empty_detail` + `is_open` check | `test_the_two_empty_causes_do_not_share_a_message` |
| P5 | API key unreachable from the UI; error named a field that did not exist | key/model in the Prompt Editor, write-only | `TestGrokConnectionSettings` (asserts the field exists in `index.html`) |
| P6 | `reply_text` CC 9 | extracted `first_choice` → CC 8 / 3 | `TestFirstChoice` |

**The split that fell out of P5.** Adding the connection slots pushed `BotBridge`
to 16 methods, one over RULE 16. The fix was not an override but the separation
the feature already required of the UI: the Grok Prompt Editor is its own
window, so it is now its own bridge (`bridge/bot_prompt_bridge.py`, 110 lines /
10 methods), leaving `BotBridge` at 155 lines / 9 methods. The shared req_id
plumbing became the public `schedule()` rather than being copied. The router's
duplicate-signal guard then caught the naive version of the split — both
bridges declaring `bot_reply_ready` — which is why the editor owns only
`bot_prompts_changed` and previews answer on the chat bridge's signals, the
`req_id` pattern already keeping the two windows' answers apart.

Two further product bugs were found *by* these tests rather than by reading:
`_chat_bridge()` handed out a fresh `BotBridge` per call, so a preview emitted
its answer into an object nobody was connected to (now cached); and the
connection slots read `service.grok.settings`, which a swapped-in fake
transport made unreachable (now read from the config, which outlives any one
transport).

### Closing gates

* Full suite **2893 passed**, 2 skipped, 1 xfailed, 897 subtests — the one
  failure is the pre-existing `test_engine_standalone_run.py`, untouched here.
* All 27 Node suites pass (`tests/test_bot_chat_js.js` 25/25).
* `tools/metrics/rule16_gate.py`: all owned functions fit, ratchet intact;
  clone baseline updated with the reason the new file joins the bridge-header
  group.
* Coverage **91.01% line / 87.11% branch** — above the 90.98 / 87.08 this
  feature left, and above the 80 / 75 floors.
* RULE 18: every touched file 110–253 lines (`ui/js/bot-chat.js` 326 carries
  its `ideal-size:` reason); worst function CC 8; largest class 114 LOC / 10
  methods; `bot_*` remains one prefix family (4 service files, `bridge/` at 16
  files is held by its own established families).
