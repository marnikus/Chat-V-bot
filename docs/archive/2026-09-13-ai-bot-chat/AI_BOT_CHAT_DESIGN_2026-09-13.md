# AI Bot Chat + Prompt Editor (Grok) — design, 2026-09-13

Feature request: two new windows — an **AI Bot Chat** that loads the current
day's messages of one person, asks Grok for a suggested reply or a reaction
analysis, and a **Prompt Editor** that edits the two prompt templates. Nothing
is sent and no label is applied without an explicit user click.

This doc is the RULE 16.6 §2 record: the structure, the measured numbers, and
the shortcuts that were rejected.

---

## 1. Where the code goes, and why

| Layer | File | Why there |
|---|---|---|
| Grok HTTP | `services/bot_grok.py` | one transport, `Result`-returning (core/result.py). No Qt, no bridge import. |
| Prompt templates | `services/bot_prompts.py` | pure text + `ConfigManager` section `grok`. |
| Reaction labels | `services/bot_reactions.py` | writes through the existing world-bound `LabelStore` — labels already live in the world DB (RULE 14). |
| Orchestration | `services/bot_chat.py` | "today's messages → prompt → Grok → payload" and the verified send. |
| Wire | `bridge/bot_bridge.py` | one more domain bridge in `BRIDGE_CLASSES`; the Router publishes its slots unchanged. |
| UI | `ui/js/bot-chat.js`, `ui/js/bot-prompt.js`, `ui/css/bot-chat.css`, two panels in `ui/index.html` | same shape as the History window. |

`services/bot_*.py` is **one prefix family** in RULE 18 §18.3 terms: the four
files share the `BotChatService` vocabulary and a single direction of imports
(`bot_chat` → `bot_grok`, `bot_prompts`, `bot_reactions`; none imports back).

### Rejected alternatives

* **A new `stores/` file for the prompts.** `tools/metrics/stores_modules.py`
  ratchets `stores/` at 15 effective modules and fails on any undeclared file;
  a prompt template is two strings, so it rides the existing settings store
  under a `grok` section instead of buying a 16th module.
* **Embedding the Prompt Editor inside the Bot Chat panel.** The request
  forbids it, and the grid already gives every panel its own window frame.
* **Adding the slots to `HistoryBridge`.** It is ratcheted at 467 LOC / 44
  methods and may not grow (RULE 16.5).

---

## 2. Grid layout version 4

Two windows are added (`botchat`, `botprompt`), so `GRID_VERSION` goes
3 → 4 in `services/layout_service.py` and `ui/js/sash-core.js` together. A v1,
v2 or v3 payload holding exactly that version's window set is **upgraded**, not
rejected (`LayoutService._window_set_ok`), so nobody loses their arrangement —
the same contract v2 and v3 got, now proved for v3→v4 in
`tests/test_grid_layout_v2_migration.py`.

---

## 3. The two flows, and the gates on them

```
SUGGEST REPLY   load today's messages -> Grok -> pending bubble
                  approve (v)  -> "Send to Person" becomes enabled
                    click Send -> type_message + click_send over CDP
                  reject  (x)  -> retry icon -> ask Grok again

ANALYZE REACTION last inbound message -> Grok -> {reaction, confidence, why}
                  confirm (v)  -> apply EXACTLY ONE label to the person
                  reject  (x)  -> retry -> re-analyze
                  manual click on another label -> it becomes the only active
```

Invariants the tests pin:

1. **No label without a click.** `bot_analyze_reaction` never writes; only
   `bot_apply_reaction` does. (Acceptance: "No labels applied without user
   confirmation".)
2. **Exactly one active reaction label.** `ReactionLabels.apply()` computes the
   person's full id list, drops the other two reaction ids, and calls
   `LabelStore.set_for` once — so the previous label is disabled in the same
   reversible undo entry (RULE 12) rather than in a second write.
3. **The latest manual decision wins.** The manual path is the same
   `bot_apply_reaction` call, so a later click always overwrites an earlier AI
   application; the AI path has no way to write behind the user's back.
4. **Approval is not sending.** `bot_send_message` is a separate slot; the UI
   enables its button only after the tick, and the acceptance test drives the
   JS module to prove the disabled button sends nothing.
5. **Empty is not broken** (RULE 4): a day with no messages answers
   `{"items": [], "empty": true}`, a missing archive answers an error signal.

---

## 4. Sizes measured after implementation

`python3 tools/metrics/rule16_gate.py` (the owned set below) and
`radon cc -s` on each new file:

| File | Lines | Worst function | LOC | CC |
|---|---:|---|---:|---:|
| `services/bot_grok.py` | 119 | `reply_text` | 12 | 9 |
| `services/bot_prompts.py` | 117 | `is_usable` | 9 | 5 |
| `services/bot_reactions.py` | 123 | `parse` | 14 | 6 |
| `services/bot_chat.py` | 170 | `deliver` | 19 | 7 |
| `bridge/bot_bridge.py` | 142 | `BotBridge.bot_apply_reaction` | 12 | 3 |

Every new function is ≤ 19 LOC, ≤ 3 parameters, CC ≤ 9, cognitive ≤ 8 and
nesting ≤ 3; the largest new class is `BotChatService` at 88 LOC / 8 methods
and the most methods are `BotBridge`'s 12 — all inside RULE 16's 150 / 15.
`ReactionLabels.apply` was split (`_one_reaction` computes the id set, `apply`
writes it) when the first version measured CC 11. The numbers are
re-measured by `tests/test_rule16_new_code.py` through the OWNED table, so this
table cannot rot into fiction.

---

## 5. Tests

| File | Proves |
|---|---|
| `tests/unit/services/test_bot_chat_service.py` | today's-messages slice, prompt rendering, Grok failure is an error not a crash, reaction parsing |
| `tests/unit/services/test_bot_reactions.py` | one active label, manual override, no write without confirm |
| `tests/test_bot_bridge.py` | every slot is on the Router, answers carry the caller's `req_id`, approval does not send |
| `tests/test_bot_chat_js.js` | the shipped JS wires to the real element ids; the Send button stays disabled until approval |

Each would fail if the code under it were deleted (RULE 8).
