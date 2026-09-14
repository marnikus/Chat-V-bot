# Porting "AI Prompt Editor, Connections & Presets" onto the refactored tree

The feature was built on `arena/01a09cb8-chat-v-bot`, which forked from **H2**
(`d3e6245`) and was finished before Round H steps H3–H7 moved code around.
This records what the port needed, and the re-validation against RULE 16 and
RULE 18 afterwards.

## 1. Method: merge, don't replay

Ten feature commits, ~9,500 lines across 55 files, plus six design documents.
A `git merge` keeps that history and those documents; replaying the diff by
hand would discard both and invite transcription errors. The merge produced
**one** conflict.

Before merging I checked the actual collision surface — the files the feature
touched that H3–H7 had also changed:

| File | Outcome |
|---|---|
| `backend/config_manager.py` | auto-merged (2 routes added to `_SECTION_ROUTES`) |
| `bridge/router.py` | auto-merged (3 bridges + `V4_WINDOW_IDS`) |
| `tools/metrics/rule16_gate.py` | **conflict** — both branches edited the clone baseline |

Everything else was disjoint: the feature's new modules import **nothing** that
H3–H7 relocated, which I verified by scanning every new `.py` for imports of
the moved names rather than waiting for a crash.

## 2. The three adaptations

**(a) The send path.** `services/bot_chat.py` imported `click_send` from
`backend.message_injector`. H5 split that file and the send-button half now
lives in `backend/send_button.py`. Each name is imported from the module that
defines it, per the convention the rest of the tree adopted in that round.

**(b) Two test files monkeypatched the same two-step.** This is the dangerous
one: patching a name on a module that no longer owns it is a **silent no-op**,
not an error. The tests would have kept passing while exercising the real
`click_send`. Each half is now patched where it is defined.

**(c) The clone baseline.** Both branches edited it and both were right:
H3 merged two bridge import-header groups (a dead `import os` left
`history_bridge.py` with a header identical to the others), and the feature
added `bot_bridge.py` to the shared header. I kept both facts and then
**re-measured** — a baseline is a promise that a group is understood, so a
hand-written union is worthless unless the scanner confirms it. It did:
`0 new group(s), 0 stale`.

## 3. Re-validation

### RULE 16 — quality gates

| Gate | Result |
|---|---|
| Test suite | **3,077 passed**, 4 skipped, 1 xfailed, 903 subtests |
| Node harness | **28/28 files green** |
| Line coverage | **91.47%** (was 91.17 — up) |
| Branch coverage | **87.52%** (was 87.15 — up) |
| Cyclomatic | max **10** / mean 2.96 / **0** over |
| Cognitive | max **15** / **0** over |
| Nesting | max **4** / **0** over |
| Clones | 0 new, 0 stale |
| `rule16_gate.py` | owned functions fit, ratchet intact, no stale overrides |
| Public API | no removed or changed symbols |

`vulture` and `pylint` were missing from the sandbox and the gate was
reporting `NOT CHECKED (tool missing — not a pass)`. I installed both and
re-ran: still clean. An unrun linter is not a passing linter.

### RULE 18 — ideal sizes

The feature was clearly written to these rules; nothing needed resizing.

- **Files:** all 13 new modules are ≤305 lines (`bot_chat.py` 305, then 231,
  193, 185 …). Tree files ≥400 LOC remains **2**, both documented artefacts.
- **Functions:** **zero** over 30 lines.
- **Classes:** largest is `BotChatService` at 147 LOC / 11 methods. Nothing
  approaches the 200–300 LOC or 10–15 method guidance.
- **Parameters:** zero functions with >4 declared parameters. Four have
  `params_effective > 4` — all parameter objects, which is RULE 19 §19.4's
  prescribed remedy and only visible at all because of the H6 metric fix.
- **Modules:** `services/` gains a `bot_*` **prefix family** of 9 files, which
  RULE 18.3 counts as one module. Mean tree MI 69.38 (was 69.32).

### Behaviour, not just green tests

Tests passing after a port can mean the tests moved with the bug. I checked the
feature's own stated invariants against the ported code:

- **The Router's `QMetaObject` publishes all 23 `bot_*` slots and signals.**
  A bridge that fails to register is invisible to every Python test but dead on
  the wire — this is the check H1 added for exactly that reason.
- **`analyze_reaction` cannot write a label**; only `apply_reaction` does
  (verified against the source, not the docstring).
- **`ReactionLabels.apply` makes exactly one reaction active** through a single
  `set_for`, so the previous label is cleared inside the same reversible undo
  entry rather than in a second write.
- **The recipient gate fails closed through the split send path.** Driving
  `deliver()` with the browser on Boris's chat while addressing Anna: the page
  received **nothing**. With the right chat open it typed and clicked. This is
  the direct proof that adaptation (a) is behaviourally correct.
- **Grid v4 agrees across the boundary:** `GRID_VERSION = 4` in
  `services/layout_service.py` and `const VERSION = 4` in `ui/js/sash-core.js`.
  A mismatch here silently discards users' saved layouts.

## 4. Honest notes

- **Coverage of the new modules is 89–100% per file**, so the feature raised
  the tree average rather than diluting it. `bot_grok.py` at 89.6% is the
  lowest — it is the HTTP transport, where the uncovered lines are network
  error branches.
- **I did not re-run mutation testing** on the new modules. The job covers 10
  files and these 13 are not among them; the AI feature's `bot_reactions.py`
  and `bot_chat.py` are pure decision logic of exactly the kind that job is
  for, and adding them (with their suites — see the setup.cfg note about
  sources without suites scoring a false pass) is the obvious next step.
- **The UI is verified by its 28-file Node harness and by static checks**
  (every `bot-*.js` and `dark-select.js` is referenced by `index.html`, both
  panels declared). It has not been exercised in a real browser here: the
  sandbox has no GPU, which is the same limitation that makes
  `test_grid_in_real_webengine` skip.
