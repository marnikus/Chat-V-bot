# Round G — closing measurement and RULE 16 / RULE 18 re-check

**Date:** 2026-09-13 · **Branch:** `arena/01a09b51-chat-v-bot` ·
**Commits:** `dfe1b08`, `b128ced`, `16f6190`, `7c3fd87`, `759b772`,
`13ea21d`, `f4f2c74`, `a80c563`

All eight steps G0–G8 are implemented. This is the re-check RULE 16 §16.7
and RULE 18 require at the end of a round, measured on the tree as it
stands, not carried forward from the plan.

---

## 1. Did each step meet its own exit metric?

| Step | Exit metric | Result | |
|---|---|---|---|
| G0–G3 | package splits, gate/path repairs, doc rewrites | done | ✅ |
| **G4** | wide-param tail 51 → ≤35, worst ≤8 | 51 → **52**, worst **20** | ❌ **not met — see §3** |
| **G5** | mutmut widened to ~6 modules, ≥70%, every survivor killed or argued | 1 → **7** modules, **90.0%**, 40 survivors argued in `setup.cfg` | ✅ |
| **G6** | max cognitive ≤15, ≤5 functions at CC 10 | **15** and **5** | ✅ |
| **G7** | clone groups 12 → 10 | **10** | ✅ |
| **G8** | five files to MI ≥45, none growing >10% | **4 of 5**; `window_preset_service` argued as an artefact | ⚠️ **4/5, argued** |

## 2. The six metric families, measured

| Family | Threshold | Measured | |
|---|---|---:|---|
| Cyclomatic complexity | ≤ 10 | max **10**, mean 2.97, **0** above | ✅ |
| Functions at the CC ceiling | — | **5** (was 16) | ✅ |
| Cognitive complexity | ≤ 15 | max **15**, **0** above | ✅ |
| Nesting depth | ≤ 4 | **4**, 0 above | ✅ |
| Function LOC | ≤ 20–30 | mean 9.48, median 7, p90 20; **38** over 30 (1.8%); max 122 (§16.1.5 JS literal) | ⚠️ tail |
| RULE 18.1 band (4–20 LOC) | aim | **62.6%** | ⚠️ |
| Parameters | ≤ 3–4 | **52** over 4, worst 20 | ❌ see §3 |
| Class LOC | ≤ 200–300 | **7** over 300, max 457 | ⚠️ |
| Methods per class | ≤ 10–15 | **26** over 15, max 44 | ⚠️ |
| Line coverage | ≥ 80% | **91.07%** | ✅ |
| Branch coverage | ≥ 75% | **87.05%** | ✅ |
| Mutation score | ≥ 70% | **90.0%** (360/400 reached) | ✅ |
| Test : code | ~1:1 | **1.56 : 1** | ✅ |
| Duplication | — | **2** exact groups, 26 lines; 10 baselined | ✅ |
| Maintainability index | ≥ 45 | mean **68.68**; **28** files below 45 | ⚠️ backlog |
| Suite | green | **2,856 passed**, 3 skipped, 897 subtests | ✅ |
| RULE 16 gate | clean | owned functions fit, ratchet intact, no stale overrides, 0 new clones | ✅ |
| Public API | unchanged | no removed or changed symbols | ✅ |

## 3. G4 is the one step that did not meet its number, and the number is wrong

The tail went 51 → 52, not 51 → 35. This is reported rather than
massaged, because G4's finding was that **the metric cannot see a façade**.

The five widest non-`actions/` functions already own a parameter object
and keep the long signature as their documented public contract —
`scroll_parser.parser` (19 params) has `ScrollOptions`/`from_options`,
`chat_parser` (14) has `SyncOptions`/`run_sync`, `history_repo` (13) has
`WriteContext`, `visual_click` (12) has `ClickRequest`/`run_click`,
`media_handler` (10) has `AttachOptions`/`attach_with_options`. Counting
those as debt double-counts work that is already finished. The remaining
bulk is the 15 `actions/` block `__init__`s, where the parameter list *is*
the schema: it mirrors `config_schema()` and `BUILTIN_BLOCKS` in
`ui/js/stack-dnd.js`, and §16.1.1 explicitly forbids collapsing it behind
`**kwargs`.

G4 did introduce the three genuinely missing concepts — `PaneSignatures`,
`ScanFindings`, `ElementMatch`/`Overlay`. The count rose by one because
`services/run/queue.py` (G8) carries a mixin method over the line.

**Recommendation for a future round:** change the measurement, not the
code. A parameter-count audit should exempt a signature that has a
documented parameter-object twin, and should count a block `__init__`
once per schema rather than once per parameter. Chasing 52 → 35 under
the current definition would mean either deleting façades that exist, or
`**kwargs` that the rules forbid.

## 4. What round G actually found, in one line each

Three of the eight steps found a **gate that was measuring nothing**, and
that is the round's real result:

* **G5** — `mutmut` had been pointed at a file G3 deleted. It reported
  99.37% over 159 mutants and was silently measuring 1/190th of the tree.
* **G6** — the exemption records carried `dom_probe.build_probe` at
  cognitive 17 for three reports running. It is 8. Meanwhile the true
  outlier, `history_delete_person` at 16, was in no report at all.
* **G3/G7** — a package split broke every hardcoded path string in
  `rule16_gate.py` and `test_rule16_new_code.py`, and the substring filter
  **failed open**.

The corollary, which now has three independent confirmations in this
codebase: *a quality gate that cannot fail is indistinguishable from no
gate, and it is the passing ones that need auditing.* Every gate touched
this round was made to fail first — the canary function, the deliberately
inverted `_panel_reject` mutant, the deletion guard whose test did not
exist — before its green result was believed.

## 5. Backlog, ranked, for the next round

1. **26 classes over 15 methods, 7 over 300 LOC** — the largest remaining
   family, and the honest read of `bridge/history_bridge.py` (MI 25.8,
   563 LOC, 44 methods). It is a QWebChannel slot table, so the split
   must preserve the slot contract; that is a round of its own.
2. **28 files under MI 45** — now a ranked list rather than a guess:
   `history_bridge` 25.8, `db_deletion_flow` 32.7, `media_fetch` 33.0,
   `collector_tick` 33.6.
3. **The parameter-audit definition** (§3 above) — fix the measurement.
4. **Churn and bug density remain unmeasurable** — git history is 2
   commits deep. Nothing in the code can fix this; it needs full history.
