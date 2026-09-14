# Round I — closing

Branch `arena/01a09b51-chat-v-bot`. Steps I1–I8, one commit per step group,
each verified green before the next began.

| Step | Commit | Subject |
|---|---|---|
| I1 | `47dfa93` | Hygiene, and the guard that would have caught F2 |
| I2 | `0ec3126` | Single-source the two logic duplications (F4) |
| I3 | `36a81fa` | Extract `PresetApplier` from `file_bridge` |
| I4 | `6ac9d1a` | Split `StackBridge` by cohesion; close the two worst coverage holes (F6) |
| I5–I6 | `b1c8e3c` | Correct the Round H record (F1); the tree-wide duplication tail |
| I7–I8 | this commit | Docs budget, archive index, final re-measurement |

## Every audit finding, and its disposition

| # | Finding | Outcome |
|---|---|---|
| F1 | Round H's closing table does not reproduce | **Corrected.** Worse than stale — measuring at Round H's own commit gives today's numbers, so the figures were wrong when written (targets restated as results). Both columns now shown. |
| F2 | Duplicate `ElementMatch`/`Overlay` in `dom_highlight.py` | **Fixed** (360→309), and the blind spot closed by a new tree-wide guard. |
| F3 | `export.py` keeps `import os` function-local to dodge the clone scanner | **Fixed.** The justification was measurably false: hoisting produced 0 new clone groups. |
| F4 | Two R0801 logic duplications | **Fixed**, plus six more the audit's scope never scanned. 10 → 4 tree-wide. |
| F5 | Two stale `# ideal-size` headers | **Fixed — three**, not two; `bot_chat.py` was missed because the AI port landed after the audit. |
| F6 | `send_button.py` 21.1%, `history_media.py` 37.6% | **Fixed.** 100% and 89%. |
| F7 | Gate green with tools present; vulture 7 / pylint 2 as inventory | **Inventoried and reduced.** Vulture 7 → 5, all five protocol-fixed and argued per-finding. |
| F8 | `docs/README.md` test count wrong; `AGENT_RULES.md` over budget | **Fixed.** Count corrected (now 193/30, re-measured at the end); rules file paid down by extraction, as its own §18.4 instructed. |

## Results against the six metric families

| Family | Measure | Result |
|---|---|---|
| Complexity | max CC | No function over 10. Every refactor checked RULE 19 order first; in all four cases (file_bridge 9, stack_bridge 8, cdp_client 8) complexity bottomed out *before* size, so size was the right lever. No function's CC rose. |
| Size | files ≥400 | **2** (`router.py` 530, `history_schema_repair.py` 461), each with an `# ideal-size:` header re-derived from measurement. None over 500. |
| Coupling / cohesion | LCOM | Drove two splits rather than line count: `StackBridge` (21 components once ubiquitous `ctx`/`_log` are discounted) and the `file_bridge` collaborator. §18.2's "LCOM wins over size" was respected — no cohesive class was scattered. |
| Tests | line / branch | **92.19% line, 88.40% branch** (gates ≥80 / ≥75), up from 91.53%. 3120 passing, 193 test files. |
| Code smells | duplication, dead code | R0801 10 → 4, all four argued. Vulture 7 → 5, all five protocol-fixed. Clone gate 0 new, 0 stale. |
| Maintainability | mean MI | **69.38 → 69.60.** `file_bridge` 37.5→50.3, `stack_bridge` 39.4→50.7. |

## Growth budget

| | SLOC | vs baseline |
|---|---|---|
| I0 baseline | 26,569 | — |
| after I1 | 26,524 | −45 |
| after I2 | 26,539 | −30 |
| after I3 | 26,610 | +41 |
| after I4 | 26,660 | +91 |
| after I6 | 26,662 | **+93 (0.35%)** |

Largest single step +71 (0.27%), inside the 0.5% per-step cap; the round used
0.35% of its 2% allowance.

## Three things worth carrying forward

1. **A guard written before a refactor is worth more than one written after.**
   I3 added the `FileBridge`/`StackBridge` metaobject contract *before*
   touching either file, and proved it non-vacuous against a deleted `@Slot`
   decorator — the case where the Python attribute survives and every ordinary
   test still passes. I4's mixin split then relied on it directly.

2. **Two of the "cleanups" were latent bugs.** The duplicated `UserRecord`
   import shim would have produced two different classes in one process if
   `stores.user_memory` were ever absent; and `_persist_app_settings` held no
   reference to its `create_task`, so the GC could collect a settings write
   mid-flight. Neither was in the audit.

3. **Measure at the commit, not from the plan.** F1's root cause was a table
   of intentions presented as results. Every number in this round came from a
   command that is written down next to it, and the before/after pairs come
   from the same command.

## Not done — remaining backlog

* **17 files at MI < 45** (worst: `cdp_client.py` 36.7, `label_assignments.py`
  37.7, `history/mutate.py` 37.8). MI 45 is a Round-I target, not a RULE 16
  gate; none of these is over 400 lines and none has a function over CC 10, so
  each needs a cohesion argument rather than a split-by-size. `cdp_client` was
  measured this round (LCOM4 = 4, mean method body 7.6 lines) and is a
  cohesive protocol client — a future round should argue it, not slice it.
* **14 files at 300–399 LOC** — below the point where RULE 18 demands action.
* **Mutation testing** was not re-run this round; `setup.cfg`'s recorded
  844/1139 = 74.1% predates the new tests.
* `AGENT_RULES.md` remains ~63 lines over its self-imposed budget, with the
  next two extraction candidates named in §18.4.
