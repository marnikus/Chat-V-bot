# Round G — plan only, no implementation

**Date:** 2026-09-13 · **Snapshot:** `37d43b4` · **Branch:** `arena/01a09b51-chat-v-bot`
**Status:** **PLAN. Nothing below has been implemented.** No production file was
changed in the session that produced this document.
**Measurements it is built on:** `reports/CODE_QUALITY_METRICS_2026-09-13.md`
**Predecessors:** `docs/archive/2026-09-12-round-f-size-tail/ROUND_F_DESIGN_2026-09-12.md`,
`docs/archive/2026-09-13-round-f/F5_PARAMETER_OBJECTS.md`

Every step is sized at **8–16 hours** and is written as the four phases RULE 16
§16.6 requires: **(1) understand → (2) research & design → (3) implement →
(4) verify**. Each step states its exit metric so "done" is a number, not an
opinion.

---

## 0. Where the debt actually is

Round F closed what it could reach. The numbers it moved and the numbers it did
not tell you exactly what is left:

| Category | State | Verdict |
|---|---|---|
| Cyclomatic complexity | 0 / 2,058 above 10 | **closed** |
| Nesting | 0 above 4 | **closed** |
| Coverage / branch / tests | 90.87% / 86.94% / 2,800 green | **healthy** |
| Mutation (1 file) | 99.37%, 1 equivalent survivor | **F6 complete** |
| Coupling shape | 4 most-used modules have Ce 0 | **healthy** |
| Wide params | 70 → 51 | **partly done, blocked** |
| Cohesion | LCOM 0.97 on a 40-method class | **open** |
| File mass | 7 over 500; **5 of them frozen** | **blocked on a decision** |
| Maintainability | 19 files < MI 40; worst 11.4 | **open** |

Two structural facts decide the ordering, and neither is about effort:

**Fact 1 — the AREA D snapshot freezes `backend/` and `actions/`.**
`tools/metrics/dump_public_api.py` skips packages (`if info.ispkg: continue`)
and counts a symbol only when `obj.__module__ == qualname`. Therefore, inside
`backend/**` and `actions/**`:
* turning `chat_sync.py` into `backend/chat_sync/` **deletes** the module from the
  snapshot → `test_no_module_disappeared_or_failed_to_import` fails;
* moving `SyncSession` to a sibling and re-exporting it reads as **removed**.

The prefix-family recipe that fixed `stores/history_repo*` and
`services/db_deletion*` is unavailable exactly where the five worst files live.

**Fact 2 — size and cohesion disagree, and cohesion is right.**
`SchemaMigrator` is 406 LOC at LCOM **0.12**; `Collector` is 239 LOC at LCOM
**0.97**. A line-count sort puts the wrong one first. Round G ranks by
`LOC × LCOM × Ce`, which is why a 239-line class outranks a 406-line one.

Consequence: **G0 is a decision, not code, and it gates G1.** Everything from G2
down is deliberately chosen to be executable *without* that decision, so the
round is never blocked waiting on it.

---

## 1. Step map

| # | Step | Exit metric | Est. | Depends on |
|---|---|---|---:|---|
| **G0** | AREA D snapshot decision + contract change | a written, tested decision either way | 8–12 h | — |
| **G1** | `backend/chat_sync.py` 807 / MI 11.4 | ≤ 300 lines per successor, MI ≥ 45 each | 14–16 h | G0 = "refresh" |
| **G2** | `Collector` 40 methods / LCOM 0.97 / Ce 12 | ≤ 15 methods, LCOM ≤ 0.6, Ce ≤ 8 | 14–16 h | — |
| **G3** | `UndoService` 28 methods / LCOM 0.95 / Ce 13 | ≤ 15 methods, LCOM ≤ 0.6 | 10–12 h | G2's pattern |
| **G4** | Wide-parameter tail 51 → ≤ 35 | 51 → ≤ 35, worst outside `actions/` ≤ 8 | 12–14 h | — |
| **G5** | Widen mutation scope, 1 file → 6 | honest repo-level score, ≥ 70% | 10–12 h | — |
| **G6** | CC-10 frontier + 2 cognitive-17 | max cognitive ≤ 15; ≤ 5 functions at CC 10 | 12–14 h | — |
| **G7** | 2 real clone groups | clone baseline 12 → 10 groups | 8–10 h | — |
| **G8** | Density pass, 5 small low-MI files | each ≥ MI 45, no file grows > 10% | 10–12 h | — |

**Recommended execution order: G2 → G0 → (G1 if unblocked) → G6 → G4 → G8 → G5 → G7.**
G2 goes first because it is the largest unfrozen win and needs no decision; G0
runs in parallel as a review task because it needs a human.

---

## G0 — Decide the AREA D snapshot question

**8–12 h · blocks G1 · produces a decision + a test, not a refactor**

### 1. Understand
`tests/unit/backend/test_backend_api_snapshot.py` enforces
`backend_api_snapshot.json` over `backend/**` and `actions/**`. Its purpose is
"no public API moved without someone noticing". Its *mechanism* additionally
forbids packages and re-exports — which is a side effect of how it enumerates,
not an intended contract. The test's own docstring sanctions a refresh when the
change is "intentional and coordinated". This step is that coordination.

### 2. Research & design
Produce a decision doc comparing exactly three options, each with the test diff
it implies:

* **A — refresh the snapshot on demand.** Cheapest; weakens the golden file's
  stated guarantee every time it is used.
* **B — teach the dumper package-awareness.** Walk into packages, and treat a
  symbol as owned when its `__module__` is the qualname **or any submodule of
  it**. The snapshot then survives a package split *and still fails* on a real
  removal — the guarantee is preserved, the false constraint is not.
  **This is the recommended option** and the design doc should argue it.
* **C — leave frozen.** Accept `chat_sync.py` at MI 11.4 permanently and record
  it as permanent debt in RULE 18.2 rather than as a pending step.

Deliverable: `docs/archive/2026-09-13-round-g/AREA_D_DECISION_2026-09-13.md`.

### 3. Implement (if B)
Change `module_names()` to descend into packages; change `dump_module()`'s
ownership test to prefix matching. Regenerate the snapshot and **diff it by
hand** — the correct diff for a no-op tree is *empty*. A non-empty diff before
any refactor means the dumper changed meaning and the change is wrong.

### 4. Verify
Empty snapshot diff on the unchanged tree; a deliberately deleted public symbol
still fails the test (prove the guarantee survives); full suite green.

**Exit:** decision recorded and, if B, snapshot semantics changed with a proven
empty diff. **Do not start G1 before this closes.**

---

## G1 — `backend/chat_sync.py`: 807 lines, MI 11.4

**14–16 h · needs G0 = A or B · the single worst file in the repository**

### 1. Understand
807 lines, SLOC 536, MI 11.4 — half the next-worst file, a sixth of the project
mean. Contains `SyncSession` (250 LOC, 23 methods, LCOM 0.89). It is also
RULE 15's home turf: the two-step private-chat gate and the archive write path
run through here, so behaviour preservation is a **data-integrity** requirement,
not a nicety. Read RULE 14, RULE 15 and `SYSTEM_OF_RECORD.md`'s archive rows
before touching a line.

### 2. Research & design
Find the seams by responsibility, not by line number. The expected four:
session lifecycle · the RULE 15 verification gate · message/media persistence ·
CDP transport and heartbeat. Write the target file list with a predicted MI for
each *before* moving code, and record which seam each current method belongs to.
Any method that will not classify is the real finding and gets discussed, not
forced.

### 3. Implement
Under G0-B: `backend/chat_sync/` package with the four modules, `__init__.py`
re-exporting the current public names unchanged. Under G0-A: a `chat_sync_*`
prefix family plus a refreshed snapshot. Move code in **one commit per seam**,
running the suite between each — a 536-SLOC move done in one commit is
unreviewable.

### 4. Verify
Each successor ≤ 300 lines and MI ≥ 45; suite unchanged at 2,800 passed;
coverage not below 90.87% line / 86.94% branch; snapshot diff explained
symbol-by-symbol; RULE 15's gate tests specifically re-run and named in the
commit message.

**Exit:** no file in `backend/` above 500 lines except `scroll_parser.py` and
`history_query.py` (their own later steps). Mean MI ≥ 68.

---

## G2 — `Collector`: 40 methods, LCOM 0.97, Ce 12

**14–16 h · no dependencies · start Round G here**

### 1. Understand
`services/collector_service.py::Collector` — 239 LOC, **40 methods**, LCOM
**0.97**, Ce **12**, Ca 3. LCOM 0.97 over 40 methods means almost no two methods
share state: this is not a class, it is a namespace. It is a §16.5 landmine and
it is a `QObject` with signals, so the Qt object identity must survive. A
partial family already exists (`collector_tick.py` 425 LOC/MI 32.9,
`collector_partner.py`, `collector_report.py`) — the split direction is
established, it was just never finished.

### 2. Research & design
Cluster the 40 methods by the attributes they touch (the LCOM matrix *is* the
design input — compute it, print it, cluster it, put the table in the doc). Expect
4–5 collaborators: queue/backlog · tick scheduling · partner resolution ·
reporting · Qt signal surface. `Collector` stays a `QObject` façade owning the
signals and delegating; collaborators are plain classes with **no Qt import**,
which is what drops Ce from 12 to ≤ 8.

Record the rejected shape explicitly: moving 25 methods out and leaving 25
one-line forwarders is the `foo_part1` pattern §16.1.1 forbids. A forwarder is
only justified when it is a Qt slot the channel pins.

### 3. Implement
One collaborator per commit, tests first (RULE 8) locking current behaviour:
collection under filter, `on_collect`/`on_reject` symmetry (RULE 6), the backlog
guard's fail-open behaviour (RULE 9), stop honoured mid-tick (RULE 7).

### 4. Verify
`Collector` ≤ 15 methods, LCOM ≤ 0.6, Ce ≤ 8; every collaborator ≤ 150 LOC and
≤ 10 methods; `collector_tick.py` MI 32.9 → ≥ 45; coverage held; the ratchet in
`rule16_gate.py` updated *downward* (a ratchet you raise is not a ratchet).

---

## G3 — `UndoService`: 28 methods, LCOM 0.95, Ce 13

**10–12 h · reuses G2's pattern**

### 1. Understand
179 LOC, 28 methods, LCOM 0.95, **Ce 13** — the highest efferent coupling of any
non-root module in the tree. It is the owner of RULE 12's single global timeline
across six entry kinds (`stack`, `grid`, `people`, `labels`, `archive`, `dbconn`),
and `undo_timeline.py` / `undo_support.py` / `undo_world.py` already exist. The
Ce 13 is the tell: it imports one collaborator per kind and dispatches.

### 2. Research & design
The six kinds are the seam and RULE 12 already names them. Design a per-kind
handler protocol (`validate` / `apply_before` / `apply_after`) with a registry;
`UndoService` keeps only push, dedup, truncate-on-branch, the cap, and dispatch.
Guard against the anti-gaming clause: a registry of **lambdas** that only hides
an `if`-chain is forbidden; a registry of **named handler classes that each own
real per-kind logic** is the domain concept RULE 16 §16.2 permits. State that
distinction in the doc so review can check it.

### 3. Implement
Handlers first, with per-kind tests; then flip dispatch; then delete the chain.
RULE 12's invariant — one `Ctrl+Z` reverses the most recent edit regardless of
panel, and a `people` entry undoes in **one** step — is the equivalence gate.

### 4. Verify
≤ 15 methods, LCOM ≤ 0.6, Ce ≤ 8; each handler ≤ 100 LOC; the cross-kind undo
ordering tests pass untouched (if they needed editing, behaviour changed).

---

## G4 — Wide-parameter tail: 51 → ≤ 35

**12–14 h · no dependencies · continues F5**

### 1. Understand
F5 took 70 → 51 and stopped at a real boundary, not from fatigue. The remaining
51 are **two different problems**:

* **~15 in `actions/`** — block `__init__`s (worst: `scroll_parse.__init__` at
  **20**, `click_user.__init__` 13, `custom_find.__init__` 11). These are pinned
  by RULE 3 (settings are plain instance attributes), by `config_schema()`, by
  the `BUILTIN_BLOCKS` mirror in `ui/js/stack-dnd.js`, and by the AREA D
  snapshot which captures `config_schema()` output. §16.1.1 explicitly forbids
  hiding them behind `**kwargs`. **Treat as frozen; do not touch in G4.**
* **~36 elsewhere** — ordinary functions where §19.4's parameter object applies:
  `backend/chat_parser.py::sync_conversation` (14),
  `backend/visual_click.py::find_and_click` (12),
  `backend/media_handler.py::attach_image` (10), `bridge/context.py::__init__` (10),
  `backend/dom_highlight.py::build_find_probe` (9),
  `services/db_deletion_policy.py::plan_deletion` (9), plus the `services/` and
  `stores/` remainder.

### 2. Research & design
Per target: does a **named domain concept** group the arguments? `find_and_click`
has an obvious one (a *click request*: selector, phase colours, pause, highlight
flag). `plan_deletion` has one (a *deletion policy input*). Where no concept
exists, **leave the function alone and record why** — F5's own lesson was that
eight unused dataclasses moved the metric by zero and had to be deleted.

### 3. Implement
F5's five-step pattern exactly, from `F5_PARAMETER_OBJECTS.md`: create the object
→ migrate the signature → update **all** call sites → delete the old signature →
re-measure. **No `_v2` twin**, ever — that was F5's documented root cause.

### 4. Verify
Wide functions ≤ 35; worst non-`actions/` signature ≤ 8; no new dataclass with
fewer than 2 call sites (grep-checked); suite green with no test edits, since
these are internal signatures.

---

## G5 — Make the mutation score honest

**10–12 h · no dependencies**

### 1. Understand
99.37% is a true number about **one file**. `setup.cfg` scopes mutmut to
`backend/history_query.py`; 982 of 1,141 mutants are unreachable by the selected
suites and excluded from the score. Two traps are already documented and must be
preserved: `--noconftest` is load-bearing (without it a conftest import failure
records **every** mutant as killed — a silent false 100%), and narrowing suites
excludes rather than inflates.

### 2. Research & design
Pick five more **pure** modules — no Qt, no I/O, deterministic — as the widened
scope. Candidates: `backend/person_filter.py`, `backend/chat_text.py`,
`services/undo_support.py`, `stores/history_models.py`, `core/result.py`. Estimate
runtime first: at the measured **15 mutations/second**, keep the whole run under
~10 minutes or it stops being run at all. Decide up front that the headline
number **will drop** and that a drop is the step succeeding.

### 3. Implement
Widen `source_paths`, widen the suite selection per module, run, triage every
survivor into *equivalent* (recorded with the argument, as `_my_nicks` mutant 7
already is) or *real gap* (write the test). Add a `tools/ci` entry so it is
reproducible.

### 4. Verify
≥ 70% on every module in scope (RULE 16 §16.3's floor), every survivor either
killed or recorded with a written equivalence argument, total runtime documented.

---

## G6 — The complexity frontier

**12–14 h · no dependencies · RULE 19 order says this precedes size work on the same functions**

### 1. Understand
Ten functions sit at **exactly CC 10** — one new `if` in any of them is a hard
gate failure, so the codebase is one commit away from reopening a closed
category. Four are also near the cognitive ceiling: `type_message.execute`
(10/15), `person_filter.check` (10/14), `scroll_parser._consume_batch` (10/15),
`cancellation.sleep_with_stop` (10/11).

Separately, the two cognitive-17 functions **are not the ones the 2026-09-12
report named**. `dom_probe.build_probe` now measures cognitive 8; today's
outliers are `bridge/router.py::_build_router_class` (17, 51 LOC) and
`stores/settings_store.py::get` (17). Both are ordinary Python — neither is
covered by the §16.1.5 embedded-JS exemption. Correct the record as part of this
step.

### 2. Research & design
Apply RULE 19's order per function: nesting first (already 0 above 4), then CC,
then cognitive, then size. For `_build_router_class`, the cognitive cost is the
class-factory loop over the slot table — the question is whether the table can be
declarative data with a flat builder. For `settings_store.get`, it is typed-getter
dispatch — a per-type coercion map of **named functions** (not lambdas) is the
legitimate form.

Hard constraint, quoted so review can apply it: "four independent binary outcomes
cannot cost less than CC 5. Do not lower CC by deleting a real decision."

### 3. Implement
One function per commit with a before/after `radon cc -s` line in each message.

### 4. Verify
Max cognitive ≤ 15 (category finally closed); at most 5 functions remaining at
CC 10; no function's CC reduced by deleting a branch that had behaviour; the two
corrected exemption records updated in `reports/` and in RULE 16's exemption list.

---

## G7 — The two real clone groups

**8–10 h · cheapest honest win in the report**

### 1. Understand
12 clone groups / 89 lines, **0 new** against the baseline — the gate is green.
Nine groups are 6–9-line import headers in sibling family modules, an artefact of
the family splits RULE 18.2 asked for; correctly baselined, leave them. Two are
real:
* **span 15** — `actions/click_back.py:20` vs `actions/click_main_tab.py:19`, the
  largest clone in the tree: two RULE 1 find-and-click blocks sharing a body;
* **span 7** — `backend/media_handler.py:118` vs `backend/message_injector.py:98`.

### 2. Research & design
The `actions/` pair belongs in `actions/base.py::FindClickBlock`, which already
exists (62 LOC, 5 methods) and is the named owner of exactly this concept — so
this is §16.4's "extract a named helper in the owning layer", not a new
abstraction. Check the other RULE 1 blocks (`CUSTOM_FIND`, `CLICK_USER`,
`CLICK_SEND`) for the same body before extracting, so the helper is written once
against all consumers. Note the AREA D constraint: adding a method to
`FindClickBlock` changes `actions/` public API — confirm the snapshot's treatment
before, not after.

### 3. Implement
Extract into `FindClickBlock`; delete both copies; re-baseline `clone_scan` with
the two entries **removed**, not re-added.

### 4. Verify
Clone groups 12 → 10; both blocks' behaviour tests unchanged; two-phase
FIND/CLICK logging and overlay colours byte-identical (RULE 1's whole point is
that the log is predictable); `rule16_gate.py --with-clones` green.

---

## G8 — Density pass on the small low-MI files

**10–12 h · the work no size-based sort will ever find**

### 1. Understand
Five files are **inside** RULE 18.2's size band yet below MI 40:

| MI | Lines | File |
|---:|---:|---|
| 28.7 | 299 | `services/window_preset_service.py` |
| 31.8 | 258 | `services/run/progress.py` |
| 32.2 | 151 | `services/run/hooks.py` |
| **33.7** | **128** | `app/window.py` |
| 36.9 | 174 | `services/history/query.py` |

`app/window.py` — MI 33.7 in 128 lines — is the sharpest case in the repo.
Low MI at low line count means low comment ratio and high complexity per line:
these files are **dense**, not big. Splitting them would push them below 150
lines and make things worse.

### 2. Research & design
For each file decide which of three applies and say so in the doc: (a) missing
explanation — MI rewards comment ratio and these files have none; (b) a genuine
local simplification; (c) MI artefact, accept and record. Do **not** pad comments
to move a number — that is metric gaming, and if (a) is the answer the comment
must be a module docstring that says what the file owns and which direction its
imports go, which RULE 18.2 requires anyway and which these five are missing.

### 3. Implement
One file per commit, MI before/after in each message.

### 4. Verify
Each of the five ≥ MI 45; no file grew by more than 10% of its line count;
coverage unchanged; the added docstrings actually name the ownership and import
direction (reviewable by reading, not by a tool).

---

## 2. Rejected approaches, recorded

| Rejected | Why |
|---|---|
| Sort by line count and start with `chat_sync.py` immediately | Frozen by AREA D. Starting there stalls the round on day one. G0 first, G2 in parallel. |
| Split `SchemaMigrator` (406 LOC) because it is big | LCOM **0.12** — it is one cohesive job. A split would raise coupling to lower a line count. Explicitly out of scope. |
| Finish the `actions/` wide constructors in G4 | Pinned by RULE 3 + `config_schema()` + the JS `BUILTIN_BLOCKS` mirror + the AREA D snapshot. Needs its own step after G0, not a line item. |
| Add `operation_v2()` beside `operation()` | F5's documented root cause: a second API nobody calls and a metric that never moves. |
| Report churn and bug density as numbers | One reachable commit; no defect attribution. False precision. Tooling task, appendix below. |
| Re-merge the family files to kill the 9 import-header clone groups | Undoes the RULE 18.2 splits that created them; lands outside the 150–300 band. Baselined is correct. |
| Raise the `rule16_gate.py` ratchet to accommodate a refactor | A ratchet that moves up is not a ratchet. |

## 3. Appendix — the three unmeasurable metrics

To report technical debt ratio, churn and bug density honestly, three things are
needed and none is an analysis task:

1. **Full git history** (this checkout has 1 reachable commit) → churn per file,
   churn × complexity risk ranking.
2. **A bug-fix commit convention** (`fix:` prefix or an issue link) → bug density
   per KLOC and defect-prone module ranking.
3. **A remediation-cost model** (SonarQube-style, or a local rule: N minutes per
   gate violation by type) → technical debt ratio.

Recommendation: adopt (2) now since it costs nothing going forward, and revisit
(1) and (3) once the repository is cloned with depth.

## 4. Definition of done for Round G

```text
[ ] G0 decided and written down, either way
[ ] no production file over 500 lines except those G0 froze by decision
[ ] no class over 15 methods except those the ratchet records with a reason
[ ] max cognitive complexity <= 15 (category closed)
[ ] functions over 4 params <= 35
[ ] mutation measured on >= 6 modules, every module >= 70%
[ ] mean MI >= 70, no file below MI 45
[ ] line coverage >= 90.87% and branch >= 86.94% (this round's baseline, never down)
[ ] 2,800+ tests green, 26/26 JS entrypoints green
[ ] rule16_gate.py --with-clones green; ratchet moved down, never up
[ ] SYSTEM_OF_RECORD.md and docs/README.md updated for anything that moved
[ ] every step's design doc in docs/archive/2026-09-13-round-g/ records the
    rejected dishonest reduction, per RULE 16 §16.6 step 2
```
