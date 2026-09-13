# Round H — plan

**Baseline:** [`reports/CODE_QUALITY_METRICS_2026-09-13-roundH.md`](../../../reports/CODE_QUALITY_METRICS_2026-09-13-roundH.md)
**Branch:** `arena/01a09b51-chat-v-bot` · **From:** `e7328e1`

## The thesis

Complexity, coupling, dead code and tests are all closed. `corr(LOC, MI) =
−0.819` says the remaining debt is **file length**, and 10 of the 12 files at
≥400 LOC account for the whole MI backlog. Round H splits those files.

**RULE 19 order still governs each step**: nesting → cyclomatic → cognitive →
size. Size is last because it is a *symptom*. In this round complexity is
already clean, so for once size genuinely is the cause — but each step still
re-checks the first three before touching length.

## The rule every step obeys

From AGENT_RULES §18.2, settled in G3 and reconfirmed by this audit:

> **When size and LCOM disagree, LCOM wins.**

A cohesive class is made *shorter*, never *scattered*. Splitting
`HistoryBridge` (LCOM 0.31) into pieces that share state through back-references
would raise coupling to lower a line count — the exact anti-pattern §16.2
"anti-gaming" forbids. Every step below states which of three shapes applies:

* **(a) family split** — the file holds two or more independent concerns that
  do not share state. Move one out. (`progress`→`queue` in G8 was this.)
* **(b) depth extraction** — the file is one cohesive thing, but individual
  method bodies carry inline detail that belongs in named helpers or a
  collaborator object. The class keeps its identity and gets shorter.
* **(c) artefact** — the length is a data/JS payload or a delegation facade,
  and the honest action is a written argument, not a refactor. (§16.1.5.)

No step may grow the total line count of the tree by more than 2%, and none may
add a module whose only content is re-exports.

## Steps

Each step is one commit, self-contained, with the full verification set green
before the next begins: suite, coverage, `rule16_gate.py --with-clones`,
`dump_public_api.py --diff`, and `radon cc -s` before/after on every function
touched.

---

### H1 — `bridge/history_bridge.py` 563 LOC / MI 25.8 → target ≤ 350 LOC, MI ≥ 45
**Effort: ~14 h. Shape: (b) depth extraction, NOT a split.**

The worst file in the tree and the one the previous round misdiagnosed. LCOM
0.31: the 31 `@Slot` methods are genuinely one object, and the QWebChannel
contract means their names and signatures are the public API — §18.5 already
records this. So the class stays.

What makes it long is that nearly every slot inlines the same three-part body:
validate the argument, define an `async def work()` closure, hand it to
`_run_async`. 48 functions in 563 lines.

1. Measure how many slots share the exact `clean = " ".join(...)` /
   `if self.ctx.archive is None` preamble. G6 already extracted
   `_record_person_deletion`; find the rest of that family.
2. Extract the argument-validation preamble into one guard helper returning the
   cleaned nick or `None`, with the error emission inside it.
3. Move the pure payload-building (the `json.dumps({...})` shapes) to
   module-level functions — they touch no state, which is why the file has 17
   module-level helpers already.
4. Do **not** create `history_bridge_read.py` / `_write.py`. The slots are one
   channel object; splitting them needs a back-reference and raises coupling.

**Exit:** ≤ 350 LOC, MI ≥ 45, all 31 slot names and signatures byte-identical
in `dump_public_api.py --diff`, LCOM no worse than 0.31.

---

### H2 — `services/db_deletion_flow.py` 527 LOC / MI 32.7 → ≤ 300 LOC each part
**Effort: ~12 h. Shape: (a) family split.**

Already 29 flat top-level functions in an explicit phase pipeline —
validate → switch → detach → revalidate → remove → prune → finalize →
reconcile. That is a sequence of *independent* phases, not one cohesive object,
so this is the cleanest family split available.

1. Confirm the phase boundaries by data flow: each phase takes `(lifecycle,
   st)` and mutates `_DeleteState`. Phases that never call each other can move.
2. Split into `db_deletion_flow.py` (the orchestrator + `_DeleteState` +
   `_PhaseRefusal`) and two phase modules along the measured boundary.
3. `_PhaseRefusal` must stay with the orchestrator — G6 recorded that a
   control-flow exception subclassing `Exception` is disarmed by an enclosing
   `except Exception`, and the `raise` must remain outside the broad `try`.
4. Re-point the clone baseline entries by *moving* them, not re-adding.

**Exit:** no part over 300 LOC, every part MI ≥ 45, the deletion-guard tests
(including `test_deletion_sharing_guard.py`) green, public API unchanged.

---

### H3 — `stores/media_fetch.py` 462 / 33.0 and `services/collector_tick.py` 446 / 33.6
**Effort: ~14 h. Shape: (a) for media_fetch, (b) for collector_tick.**

`media_fetch` holds three independent download strategies (page `fetch()`,
authenticated Python, CDP network capture) plus `_NetworkWatch`. The strategies
share only the owner reference — a family split.

`collector_tick` is one pipeline; expect depth extraction instead. Measure
before deciding, and record which shape applied.

Note: this file was at 398 SLOC against a 400 ceiling in G6 and the shared
helpers went to `media_layout`. Check `media_layout` is still the right home
before adding to it.

**Exit:** both under 300 LOC, both MI ≥ 45.

---

### H4 — `backend/config_manager.py` 509 / 41.0 → ≤ 300
**Effort: ~10 h. Shape: (a) family split.**

Five owner classes (`_Owner`, `_SettingsOwner`, `_ListOwner`, `_DictOwner`,
`_NamedOwner`, 169 LOC together) plus a 177-LOC `ConfigManager` plus two
module helpers. Mean CC **1.9** — nothing here is hard, there is just a lot.

The owner hierarchy is a self-contained type family with no dependency on
`ConfigManager`; move it to `backend/config_owners.py`. Verify direction with
an import graph first: if any owner reaches back into the manager, the split is
invalid and this becomes a (b).

**Exit:** both files under 300 LOC, MI ≥ 45 each, `ConfigManager`'s public
surface unchanged.

---

### H5 — the remaining ≥400 LOC tail, triaged
**Effort: ~16 h. Shape: mixed, one ruling per file.**

`history_repo_lifecycle` 450, `chat_parser` 441, `history_schema_repair` 440,
`message_injector` 482, `router` 508, `media_handler` 480, `dom_highlight` 590.

Several are expected to be **(c) artefacts** and the step must say so rather
than refactor them:
* `dom_highlight` 590 LOC at MI **54.8** — the highest MI of the twelve, which
  is the signature of a JS-payload file. Likely §16.1.5, like `dom_probe`.
* `router.py` 508 at mean CC **1.8** — a composition root of 44 tiny
  registrations. Splitting a composition root scatters the composition.
* `history_schema_repair` — a migration ledger. Migrations are append-only
  history; deleting or merging them is a correctness risk, not a cleanup.

For each of the seven: state (a), (b) or (c) with the measurement that decides
it. Refactor the (a)s and (b)s; write the argument for the (c)s into the module
docstring so the next audit does not re-litigate it.

**Exit:** every file ≥400 LOC is either under 400 or carries a written
artefact argument naming the measurement.

---

### H6 — teach the audit what it keeps mis-measuring
**Effort: ~8 h. Shape: tools, not production code.**

Three metrics in `tools/metrics/` have now produced a false headline each:

1. **LCOM ignores `cls`** — scored `LayoutService` 1.00 (worst in tree) when it
   is 0.73. Fix: walk `self`, `cls` and the class name, and count intra-class
   call edges as cohesion.
2. **Method count cannot see a facade** — ranked eight already-decomposed
   classes as the biggest god classes. Fix: report delegation ratio beside
   method count, and exclude ≥60%-delegating classes from the god-class list.
3. **Parameter count cannot see a parameter object** — §4 of the baseline. Fix:
   exempt a signature whose module defines a documented parameter-object twin;
   count a block `__init__` once per schema.

Then re-run the audit and correct any report claim the fixes invalidate.

**Exit:** the three metrics produce the numbers this audit arrived at by hand;
`tests/` covers each fix with a case that fails against the old rule.

---

### H7 — closing re-check
**Effort: ~8 h.**

Full six-family re-measure, RULE 18 and RULE 16 §16.7 acceptance checklist,
mutation re-run, and a closing report. Explicitly re-check the claims this
round *disproved*, so the next round does not inherit them.

## Ordering

H1 → H2 → H3 → H4 → H5 → H6 → H7. H1 first because it is the worst file and
the one most likely to be misdiagnosed again. H6 late because it needs the
hand-measurements from H1–H5 as its test cases.
