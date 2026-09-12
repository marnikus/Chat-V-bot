# Agent rules — the only rules file for this repository

What an AI agent (or a human) **MUST** follow when adding or changing code
here. This file replaces the former `AGENT_RULES.md` +
`AGENT_RULES_CODE_QUALITY.md` pair (both preserved in
[`docs/archive/2026-09-10-agent-rules-v1/`](../archive/2026-09-10-agent-rules-v1/)).

* Current behaviour, invariants and flows: [`SYSTEM_OF_RECORD.md`](SYSTEM_OF_RECORD.md)
* Doc map (what is current vs historical): [`docs/README.md`](../README.md)
* Rule numbers are **stable** — production code cites them (`RULE 1` … `RULE 19`).
  Never renumber; append instead.

| # | Rule | Kind |
|---|---|---|
| 1 | All find-and-click goes through the shared visual runner | behaviour |
| 2 | Report every step through `engine.report()` | behaviour |
| 3 | Block settings are plain instance attributes | behaviour |
| 4 | Distinguish "empty" from "broken" | behaviour |
| 5 | Long-running work reports progress incrementally | behaviour |
| 6 | Filtered-out entities must not persist | data |
| 7 | Stop must be honoured by every long-running loop | behaviour |
| 8 | Tests execute the real thing | testing |
| 9 | A guard that skips work must not stall the stack | behaviour |
| 10 | One control per decision | behaviour |
| 11 | "Don't add" must still mean "do the work" | behaviour |
| 12 | One global history for every editable surface | data |
| 13 | Never persist state you cannot read back | data |
| 14 | The archive is not the queue | data |
| 15 | Nothing is archived without the two-step gate | data |
| 16 | Code-quality gates on every production change | quality |
| 17 | One current doc, dated archive | docs |
| 18 | Ideal sizes: write for the reader's context budget | quality |
| 19 | Fix complexity before size (nesting → CC → cognitive → size) | quality |

---

## RULE 1 — All find-and-click goes through the shared visual runner

> **Any action block that locates a DOM element and clicks it MUST call
> `backend.visual_click.find_and_click(...)` (or `find_and_click_exact(...)`).
> Never call `element.click()` from a hand-rolled probe inside a block.**

The runner is the single place that implements the mandatory two-phase,
visually confirmed click:

| Phase | What is logged | What is drawn |
|---|---|---|
| **FIND** | success/failure, node count, candidates, visibility | thin **RED** outline on the detected element, then a pause |
| **CLICK** | whether the target is clickable, then the click result | thin **ORANGE** outline on the click-target area, then the click |

### Why it is centralised

* every block behaves identically, so the log is predictable;
* the element found in phase 1 is stashed and reused in phase 2, so the click
  can never land on a different node than the one the user saw highlighted;
* overlays are `pointer-events:none` with a transparent background, so they can
  never intercept the click or shift layout;
* fixing or improving the confirmation UX happens in exactly one file.

Worked correct/incorrect code: [`docs/archive/2026-09-11-rules-appendices/RULE1_VISUAL_CLICK_EXAMPLES.md`](../archive/2026-09-11-rules-appendices/RULE1_VISUAL_CLICK_EXAMPLES.md)
(extracted from this file to keep it loadable in one read — RULE 18 §18.4).

### Required params on every such block

Expose these so the behaviour stays configurable and preset-storable:

```python
highlight_enabled: bool = True     # draw the outlines
confirm_pause_ms: int = 700        # pause after FIND so the user can look
```

Blocks currently compliant: `CUSTOM_FIND`, `CLICK_MAIN_TAB`, `CLICK_BACK`,
`CLICK_USER`, `CLICK_SEND`.

### Overlay colour convention

| Colour | Constant | Meaning |
|---|---|---|
| **RED** `#ff2d2d` | `COLOR_FIND` | element detected during the FIND phase |
| **ORANGE** `#ff9500` | `COLOR_CLICK` | the area about to be clicked |
| **GREEN** `#00c853` | `COLOR_COLLECT` | a person matched the filter and was collected |

For pure visual confirmation with **no** click, use
`backend.dom_highlight.build_highlight_probe(...)`. It never touches the click
stash and never calls `scrollIntoView` — moving the viewport during a parse
would corrupt the scroll position tracking.

---

## RULE 2 — Report every step through `engine.report()`

Blocks receive the running engine. Use `engine.report(message, level)`
(`info` / `success` / `warn` / `error`) for each meaningful step. These lines
reach the UI log console *and* the JSONL run trace. A block that fails silently
is a bug — always say why.

---

## RULE 3 — Block settings are plain instance attributes

`BaseAction.to_dict()` serialises every public instance attribute, which is what
makes settings round-trip through presets. So:

* store configuration as `self.foo = ...` in `__init__`, with a default value;
* accept unknown keys via `**kw` so **older presets keep loading**;
* describe each field in `config_schema()` so the UI can render it;
* mirror the defaults/labels in `ui/js/stack-dnd.js` (`BUILTIN_BLOCKS`).

Never read settings out of the global config from inside a block when they
belong to that block — the block owns its own parameters.

---

## RULE 4 — Distinguish "empty" from "broken"

An empty result must be reported distinctly from a failure. The engine follows
this rule (empty queue vs. user-dependent stack vs. standalone run); blocks must
too. Never let a no-op path end with a success-looking log line.

---

## RULE 5 — Long-running work reports progress incrementally

Anything that loops over many items (scrolling, parsing, batch actions) must
surface each result **as it happens**, not in a batch when the loop ends. The
Scroll & Parse pipeline takes an `on_collect` callback, which the engine wires
to `person_collected()` → `person_found` signal → `users_updated`, so the table
updates live.

Two matching requirements:

* a callback into the UI must never be able to kill the pipeline — wrap it in
  `try/except` and log a warning;
* support both sync and async callbacks (`asyncio.iscoroutine(...)`).

---

## RULE 6 — Filtered-out entities must not persist

When a pipeline filters items, only the items that **pass** may be written to
storage. Never persist "everything we saw" for bookkeeping convenience — that is
exactly how rejected people ended up in the users table and survived across
runs.

Symmetry is the rule: if there is an `on_collect` hook, there must be an
`on_reject` hook that *destroys* any stored record for the rejected item. A
re-run under a stricter filter must make the list **shrink**, never grow.

Invariant to preserve: *after any run, storage contains only entities that pass
the currently configured filter.*

---

## RULE 7 — Stop must be honoured by every long-running loop

A stop flag checked only in the outermost loop is not a stop. Long-running
phases must accept a `should_stop` predicate and check it:

* at the top of each iteration, **and**
* inside any inner wait/poll loop, so a stop during a multi-second timeout is
  prompt.

Distinguish "stopped" from "failed" in the return value — reusing `None` for
both produced a bogus "lost the page context" error. `asyncio.CancelledError`
always propagates untouched; only `RunStopped` maps to the `"stopped"` outcome.

## RULE 8 — Tests execute the real thing

JavaScript probes are tested by running them through `tests/js_harness.js`
against a DOM stub, not by asserting on generated strings. Pipelines are tested
against a fake CDP client that behaves like the real page, including lazy
loading. If a test would pass with the feature deleted, it is not a test.

## RULE 9 — a guard that skips work must not stall the stack

A setting that makes a phase decline to do its work is only allowed to skip
*that work*, never the phases downstream of it. When Scroll & Parse skips
collection because of the backlog guard, `_run_collect_phase()` still returns
`await self._memory.get_queue()`, so the people already waiting are worked
through. If it returned `[]` instead, ticking the checkbox would quietly stop
the entire pipeline — the exact opposite of what the user asked for.

Two corollaries:

* **Fail open.** Counting the backlog fails open to `0` at both layers
  (`ActionEngine.backlog_count()` and `ScrollParse._read_backlog()`), so a
  counting error can never silently stop collection.
* **Skipping is success.** A skipped run returns `ActionResult.OK`, not a
  failure — the guard firing is correct behaviour.

Note the asymmetry, which is intended: a *normal* collect phase returns only the
people it just collected, while a *skipped* one returns the whole waiting queue.

## RULE 10 — one control per decision

A setting must not duplicate a decision another setting already makes. The
Scroll & Parse block used to have both four tri-state filter selects *and* an
"Also apply Filter panel criteria" checkbox, so a person could be rejected by
rules that were not visible in the block being looked at — which makes "why was
this person dropped?" unanswerable from the block config. The selects are now
the only source of truth.

When a setting is retired, the constructor must accept and **discard** its key
(`kw.pop(dead, None)`), because `BaseAction.to_dict()` re-emits `self.config`
and would otherwise write the dead key back into presets forever.

## RULE 11 — "don't add" must still mean "do the work"

Scroll-only mode (`scroll_only`) scrolls the page hunting for someone already in
the list who is not yet messaged, and adds nobody. Two invariants:

* **A seek writes nothing.** No `on_collect`, no `on_reject`, no purge. A target
  that fails the filter is passed over, never destroyed — it is being judged for
  suitability right now, not for membership.
* **A seek still counts newly rendered people** for stall detection. Seek mode
  cannot short-circuit on `nick in known_nicks` (a target is by definition
  already known, so that guard would skip exactly who we are hunting), but if it
  also stopped counting new arrivals the scroll would stall out before reaching
  a target further down the list.

An empty target set falls through to normal collection, so the mode drains the
backlog and then resumes harvesting instead of becoming a permanent off-switch.

## RULE 12 — one global history for every editable surface

Every editable surface — action stack, grid layout, people list, labels, archive
deletions, DB-connection actions — records onto **ONE** chronological undo
timeline, so one `Ctrl+Z` always reverses the most recent edit regardless of
which panel produced it. There must be no separate undo/redo controls or
shortcuts. The common push logic owns deduplication, truncate-on-branch, and the
cap (`backend.config_manager.MAX_STACK_HISTORY`).

* **Kinds:** `stack`, `grid`, `people`, `labels`, `archive`, `dbconn`. Each
  entry is `{kind, value, seq}`; `services/undo_support.py` validates per kind
  and migrates legacy shapes.
* **Where it lives:** app-level entries (`stack`, `grid`) persist in
  `config/undo.json`; world-bound entries (`people`, `labels`, `archive`,
  `dbconn`) persist in the active world's `undo_history` table and die with the
  world.
* **People entries** (delete / delete-selected / clear-all / status toggle /
  reset-messaged) are reversible commands stored as
  `{kind:"people", value:{before:[…], after:[…]}}` — full-row snapshots of both
  halves. `undo()` reverses the TIP people entry with its `before` half and
  `redo()` re-applies its `after` half, so a people action is undone in ONE
  step even when stack/grid edits surround it in the timeline.
* **Automatic engine side-effects** (a run marking people messaged, filter
  purges, live collection) are NOT recorded — only explicit user actions.

Legacy per-surface history keys may be read for migration only; new edits must
never write them.

## RULE 13 — never persist state you cannot read back

The grid layout is validated (version, node shape, sizes summing to 100, and the
exact window set) and **REJECTED** when invalid, leaving the previously stored
layout untouched — `LayoutService.canonical_grid_payload()` decides,
`bridge/layout_bridge.save_grid_layout()` refuses. Storing an unreadable layout
would brick the UI on every subsequent start — a bad payload must cost the user
one failed save, not their whole layout.

Corollary for "reset to default": restoring the default tree is not enough when
a hidden panel releases its grid space. `resetToDefault()` also un-hides every
window, and any window that can be shown while empty needs an empty state
(RULE 4) so it does not look broken.

## RULE 14 — the archive is not the queue

Since *One DB = One World* both live in the **same world file**, in different
tables — the separation is a contract about *who may write what*, not about
files:

* **`users`** answers *"who should I message under the current filter"* and may
  shrink at any time — filters purge it, People-list edits delete from it, undo
  rewrites it.
* **`persons` / `messages`** answer *"what was actually said"* and are
  append-only. No filter, purge, undo or People-list edit may delete archived
  messages, and no collector may add anyone to the queue. Deleting a person in
  the Full User Database writes a tombstone (`deleted_at`) that Undelete
  reverses; only an explicit hard delete erases rows.
* The only operation that clears archive rows is an explicit **Clean DB**, which
  is an *edit*, not a deletion: the file is backed up to `db_trash/` and Ctrl+Z
  restores it (undo kind `dbconn`).
* Worlds are joined to nothing — a world is self-contained. The two table groups
  are joined **by nick at read time only**: clicking a nick in User Memory looks
  the person up in the archive; it never copies data between them.

## RULE 15 — nothing is archived without the two-step gate

A message may be written to a person's history **only** when both checks
pass, and the checks must be re-applied on every path that saves (heartbeat
tick, live `__cvbPush` batch, `COLLECT_HISTORY` block):

1. the conversation on screen contains exactly two nicks — mine and that
   person's (a third author ⇒ it is not a private chat);
2. the active tab is a private tab whose title names that same person.

The gate lives in one place, `backend/chat_parser.verify_private()`, and it
fails **closed**: an agent that cannot report who wrote what collects
nothing, and a refused check disarms the push channel until a tick verifies
the conversation again. Never "save it anyway and clean up later" — a
polluted history cannot be un-mixed.

Media follows the same ownership rule: bytes are filed under the
conversation they belong to (`saved_media/<Latin nick>/images|gifs/
YYYY-MM-DD_NNN.ext`), never in an anonymous global pile, and the UI shows
the saved file rather than the remote URL.

---

## RULE 16 — Code-quality gates on every production change

Mandatory for every change to production Python. Numbers, scopes, tools and
exceptions are frozen here. Origin and rationale:
[`docs/archive/2026-09-10-quality-gates/CODE_QUALITY_GATES_DESIGN_2026-09-10.md`](../archive/2026-09-10-quality-gates/CODE_QUALITY_GATES_DESIGN_2026-09-10.md).
Executable form: `tests/test_rule16_new_code.py` (run it; do not re-derive).
Baseline snapshot:
[`reports/CODE_QUALITY_METRICS_2026-09-10.md`](../../reports/CODE_QUALITY_METRICS_2026-09-10.md).

### 16.0 When this applies

| Situation | Gate |
|---|---|
| New production function/class in `core/`, `actions/`, `backend/`, `bridge/`, `services/`, `stores/`, `app/`, `main.py` | **Hard fail** if any threshold in §16.1–§16.2 is exceeded |
| Edit of an existing function that already violates a threshold (legacy) | Must not **worsen** the metric; prefer reduce (§16.5) |
| Tests, `tools/`, docs, HTML dumps, generated caches | **Out of scope** for size/CC (tests still must exist for new production paths) |
| Embedded JavaScript inside Python string builders (`dom_probe`, highlight probes) | Length limit **does not** force a split of the JS payload. CC of the Python wrapper still applies (§16.1.5) |
| Compatibility facades / `__init__` that only re-export | Method-count / class-LOC may be waived with an override comment (§16.4) |

If a change would pass with the feature deleted, it is not a test (RULE 8).
Coverage that only executes lines without asserting behavior does **not**
satisfy §16.3.

### 16.1 Size and volume — hard limits on **new** code

| Check | Prefer | **Fail if** | How counted |
|---|---:|---:|---|
| Function / method physical LOC | ≤ 20 | **> 30** | Inclusive AST source span: first `def`/`async def` line through last line of body. Includes blanks and docstring. Excludes decorator lines. Nested functions counted separately. Lambdas ignored. |
| Class physical LOC | ≤ 120 | **> 150** | Inclusive AST span of the `class` body. Nested classes counted separately. |
| Parameters per function | ≤ 3 | **> 4** | Exclude leading `self` / `cls`. Count keyword-only args. Count `*args` and `**kwargs` as **one each**. |
| Direct methods per class | ≤ 10 | **> 15** | Methods defined on the class body only (not inherited). Include `__init__`, properties' fget/fset if defined as `def` on the class. |

These are the **fail** lines. The sizes to *aim at* — for functions, files,
modules and context files — are RULE 18.

**16.1.1 When approaching a limit**

1. **Do not** split a function into `foo_part1` / `foo_part2` solely to game
   LOC. Extraction is allowed only when the helper's name states a real
   responsibility (`_announce_stopped`, `_try_prepare_cycle_queue`).
2. **Do not** hide parameters behind a catch-all `**kwargs` to dodge the param
   cap. Block settings stay as explicit instance attributes (RULE 3). Wide
   `__init__` on action blocks is **legacy**; new blocks take ≤ 4 constructor
   params besides `self`.
3. New classes that would exceed 15 methods must be designed as collaborating
   types *before* writing the 16th method.

**16.1.5 Embedded-JS exception (explicit)**

`backend/dom_probe.py` `build_probe` is 122 LOC because it embeds a JS probe.
**Do not refactor that builder to meet 30 LOC.** New probe builders may exceed
30 LOC **only** when the excess is a single JS/HTML string literal. The Python
control flow around that literal must still be CC ≤ 10 and nesting ≤ 4.

### 16.2 Complexity — block merge if exceeded on new code

| Check | Tool | **Fail if** | Counting rules (frozen) |
|---|---|---:|---|
| Cyclomatic complexity | `radon cc -s` (Radon 6.x) | **> 10** | Radon: base 1; +1 per `if`/`elif`/`except`/`for`/`while`/`assert`/`with` (if extra); +1 per `and`/`or`; +1 per comprehension `if`; +1 per ternary. `try` itself and `in` tests cost 0. |
| Cognitive complexity | `cognitive-complexity` 1.3.x | **> 15** | Library default. Nested functions scored separately. |
| Nesting depth | custom AST walker (same definition as the baseline report) | **> 4** | Maximum ancestry of `if` / loops / `with` / `try` / `match`. `elif` is nested AST `if`. Sibling blocks do **not** add. |

**Anti-gaming (non-negotiable).** Forbidden: one-line helpers that only re-host
the original body; dispatch tables of lambdas whose only purpose is to hide `if`
count; inferring control flow from a flag to drop a real exception branch.
Allowed: deleting **dead** branches; extracting a helper that already exists as
a named concept in the domain; replacing `except Exception` + `isinstance`
scaffolding with a narrow `except RunStopped`.

Floor example: four independent binary outcomes cannot cost less than CC 5
(1 base + 4 branches). Do not lower CC by deleting a real decision.

### 16.3 Test coverage — new code must be tested

Global floors (must not go down; measured 2026-09-10: line **90.44%**,
branch **84.38%**):

| Metric | Target | Tool | Fail rule |
|---|---:|---|---|
| Line coverage | **≥ 80%** overall; **never decrease** vs the recorded baseline | `pytest --cov --branch` with `--source=core,actions,backend,bridge,services,stores,app,main` | fail if overall line or branch % drops below the stored baseline |
| Branch coverage | **≥ 75%** overall | same | same |
| Uncovered **new** functions | **0** without an override | coverage JSON diff vs base SHA | every new function with 0 hits is listed in review |
| Mutation score | **≥ 70%** on touched *pure* modules when a mutmut job is configured | `mutmut` (configured in `setup.cfg`) | soft-fail until wired, then hard-fail for those modules |
| Test-to-code ratio | ~1:1 nonblank non-comment Python LOC | audit script | warn, do not fail |
| Combined line+branch % from coverage.py | informational only | — | **not** the gate |

Branch 75% is read from `coverage.json`
(`totals.covered_branches / totals.num_branches`), not from
`--cov-fail-under` (that flag is line-only).

**What "tested" means.** For every new production function: at least one test
that would **fail if the function were deleted** or its boolean inverted; empty
vs broken distinguished (RULE 4); stop/cancel paths honoured if it loops
(RULE 7); JS probes go through `tests/js_harness.js` (RULE 8).

**Coverage command (copy-paste):**

```bash
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
.venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
COVERAGE_FILE=.coverage .venv/bin/python -m coverage json -o coverage.json
```

(`LD_LIBRARY_PATH` is only needed on a machine without GL/X11/NSS — build the
stubs with `tools/build_stubs.py`.) Do **not** add analysis packages to
`requirements.txt`; they live in `requirements-dev.txt`.

### 16.4 Smells and the override mechanism

| Smell | Detector | Action |
|---|---|---|
| Duplicated logic | pylint `R0801` / exact-AST clones ≥ 6 lines (`tools/metrics/clone_scan.py`) | Extract a named helper **in the owning layer**; never copy-paste probes, report strings or SQL |
| Dead code | `vulture --min-confidence 90` | Remove unused imports/vars. Unused args on protocol/callback signatures may stay |
| Long method / god class | §16.1 | Split by responsibility, not by line quota |
| Feature envy | review | Move the method; no automated gate yet |

Zero **new** smells on the diff. Pre-existing smells are inventory, not a
licence to add more.

An override is a comment CI/review parses:

```python
def wide_legacy_adapter(self, a, b, c, d, e):  # quality-override: params=5 reason=CDP wire matches Chrome DevTools payload
    ...
```

Strict format: `quality-override: <metric>=<value> reason=<one line, ≥ 20 chars>`
with `<metric>` ∈ `loc, class-loc, params, methods, cc, cognitive, nesting,
coverage, vulture, dup`. The reason must name a **constraint** (wire format,
generated JS, Qt slot signature), not "faster to ship". One override per metric
per symbol; never an override to skip a test.

### 16.5 Legacy code (already over the line)

Baseline audit: 64/1532 functions CC>10, 73 functions LOC>30, 11 classes over
the old 300-LOC cap. You **must** not increase CC, cognitive, nesting, LOC,
params or method count of a legacy offender, and must not add methods to a class
already over 15 without netting down. Touch a hotspot only with tests that lock
current behaviour first.

Landmines (need a design doc before "quickly fixing CC"): `ScrollParser`,
`Collector`, `HistoryBridge`, `UndoService`, `services/run/coordinator.py`,
`stores/label_state.py`, `backend/history_query.py`, `services/db_lifecycle.py`,
`backend/tab_matcher.py`, `actions/wait_page.py`.

### 16.6 Agent workflow (implementation process)

1. **Understand the problem fully.** Read [`SYSTEM_OF_RECORD.md`](SYSTEM_OF_RECORD.md)
   and rules 1–15, plus the size ideals in RULE 18. Then the matching archived
   design — [`docs/archive/README.md`](../archive/README.md) indexes all of them.
2. **Research and design the structure in a doc first** when the change moves
   complexity across files (new class, extraction from a hotspot). Record
   current radon numbers, target numbers, and the dishonest reductions you
   rejected. Put it in `docs/archive/<YYYY-MM-DD>-<topic>/` (RULE 17).
3. **Tests first** for behaviour changes (RULE 8). Refactors claiming
   behaviour-preservation run the existing suite as the equivalence gate.
4. **Measure**: `radon cc -s path/to/file.py`. Any new function at `C` or worse
   (CC ≥ 11) → stop and redesign, in the order RULE 19 prescribes.
5. **Update the current docs** in the same change (RULE 17).

### 16.7 Acceptance checklist (self-review before claiming done)

```text
[ ] No new function > 30 physical LOC (except documented JS-literal builders)
[ ] No new class > 150 LOC or > 15 methods
[ ] No new function with > 4 params (excluding self/cls)
[ ] radon CC ≤ 10, cognitive ≤ 15, nesting ≤ 4 on every new/edited function
[ ] overall line coverage ≥ 80% and not below baseline; branch ≥ 75%
[ ] every new function has a test that would fail if deleted
[ ] no new vulture unused-import findings; no new duplication groups
[ ] quality-override comments used only with a real constraint
[ ] did not game metrics with dummy helpers
[ ] new code aims at the RULE 18 ideals (function 4-20 lines, file 150-300,
    module 5-15 files); every deviation carries an `ideal-size:` reason
[ ] any complexity/size remediation followed the RULE 19 order
    (nesting -> cyclomatic -> cognitive -> size last)
[ ] SYSTEM_OF_RECORD.md + docs/README.md updated if behaviour/docs moved
```

### 16.8 Not required of one session

A live metrics dashboard; mutation testing of the whole tree (start with pure
modules); refactoring every legacy hotspot to green; putting radon/vulture in
`requirements.txt`.

---

## RULE 17 — one current doc, dated archive

Documentation follows the same rule as code: **one source of truth, no rot.**

* [`docs/current/`](../current/) holds only what is true today —
  `SYSTEM_OF_RECORD.md` (spec, invariants, flows), this file (rules),
  `DOM_SELECTORS.md` (living selector reference). If it is not true today it
  does not belong here.
* Every design/plan/root-cause doc goes straight into
  `docs/archive/<YYYY-MM-DD>-<topic>/`, dated by the day it was written.
  Archived docs are never edited to "catch up" — they are the record of what was
  believed then. (A single correction note is allowed, e.g. marking a promised
  file that was never written.)
* **Do not add a new top-level doc for a feature.** Write the design into the
  archive, then update the rows of `SYSTEM_OF_RECORD.md` it affects
  (behaviour table, invariants, flows, "history of X" links) and the map in
  `docs/README.md`.
* Reference a doc by its **full repo-relative path on one line**
  (`docs/archive/2026-09-08-one-db-one-world/DB_CREATION_DELETION_REDESIGN_DESIGN_2026-09-08.md`)
  so it stays greppable; long lines in prose/comments are fine.
* A doc that no longer describes reality gets either (a) its content folded into
  `SYSTEM_OF_RECORD.md`, or (b) a one-line pointer to what replaced it — never
  deletion, because the reasoning is the value.

---

## RULE 18 — Ideal sizes: write for the reader's context budget

> **These are preferences, not fail lines.** The only things that *fail* a
> change are the RULE 16 thresholds. This rule states what to **aim at by
> default**, and requires a stated reason when you aim elsewhere.

Why sizes matter here: every reader of this code — a human at 2 a.m. or an AI
agent with a fixed context window — has a limited budget. A function that fits
on one screen is a function whose branches were all considered; a file that fits
in one read is a file that gets changed correctly instead of approximately; a
context file that fits in one load leaves room for the code the agent still has
to read. The numbers below are what "fits" means in this repository.

| Element | Ideal size | Sweet spot |
|---|---|---|
| **Function / method** | **4–20 physical lines** | ~8–12 lines |
| **Single file** | **150–300 lines** | ~200 lines |
| **Module** (one directory of cohesive files) | **5–15 files**, cohesive | 7–10 files |
| **Context file** (`docs/current/*`, a `CLAUDE.md` / `AGENTS.md`, a package README) | **60–200 lines** | ~120 lines |

**Preferences only — nothing in this table fails a build.** The enforced
thresholds are RULE 16's and they are unchanged; this rule tells you where to
*aim*, not where you get rejected.

"Lines" is counted exactly as in §16.1 — the inclusive physical span, docstring
included, decorator lines excluded, nested functions counted separately — so a
number in this rule and a number in RULE 16 always mean the same thing. The
reference implementation of that count is the AST walker in
`tests/test_rule16_new_code.py`.

### 18.1 Functions — 4–20 lines

* **Under 4** is fine when the name earns its place: a domain concept
  (`check_stopped`), a required hook or protocol method, or a predicate used in
  several places. It is *not* fine when the body is one call re-hosted under a
  name that means nothing — that is the metric-gaming pattern §16.2 forbids.
* **4–20** is the band where a reader holds the whole body in mind at once,
  including every `except` branch. Most new code should land here.
* **Over 20** usually means a second responsibility is hiding inside the first.
  How to get back down — and in which order — is RULE 19.
* *Measured:* 2026-09-12, after the DB-undo-restore port — **63.6%** of 1 997 functions are in band (median 7 lines, mean 9.7, p90 21). The 2026-09-11 snapshot is `reports/IDEAL_SIZE_BASELINE_2026-09-11.md` §1; today's reproduction is in the port notes.

### 18.2 Files — 150–300 lines

* One **primary responsibility** per file, and a module docstring that says what
  the file owns *and* which direction its imports go ("no Qt in `core/`", "no
  `backend.*` import from `services/`"). That sentence is what keeps a module
  split from rotting back into a monolith.
* **Under 150** is normal and good for leaves, shims and pure-data modules
  (`stores/atomic.py`, `core/result.py`). Merge two small files only when they
  always change together; otherwise the separate name is worth more than the
  saved file.
* **Over 300** — stop and look for the second responsibility before adding the
  next feature, then split by single responsibility (RULE 19 §19.4 has the
  worked pattern: `services/run/`, `stores/history_repo*`, `services/db_deletion*`).
* *Measured:* 2026-09-12, after Round F step F2 — 166 files, median **137** lines,
  **8 files still over 500**. `services/db_deletion.py` (665, MI 20.5) became the
  six-file `db_deletion_*` family, largest member 205 (step F1); then
  `services/collector_service.py` (601, MI 27.2) became the seven-module
  `collector_*` family plus a facade at **281** lines and MI **53.5**, with the
  `Collector` class down from 526 to **239** LOC and all 40 of its names still on
  the facade (step F2 — the god class itself, not just the file, was the target;
  see [`ROUND_F2_F3_GOD_CLASS_DESIGN_2026-09-12.md`](../archive/2026-09-12-round-f-size-tail/ROUND_F2_F3_GOD_CLASS_DESIGN_2026-09-12.md)).
  Five of the remaining eight
  are `backend/` files that the frozen AREA D API snapshot forbids splitting —
  the reason, and the decision it needs, are in
  [`docs/archive/2026-09-12-round-f-size-tail/ROUND_F_DESIGN_2026-09-12.md`](../archive/2026-09-12-round-f-size-tail/ROUND_F_DESIGN_2026-09-12.md)
  §2 and §7. One more sits inside the collector family and is *not* frozen:
  `services/collector_tick.py` at 425 lines, holding probe, archive and tick
  orchestration — recorded as the family's next candidate rather than given an
  `ideal-size:` note, because §18.5 wants a constraint named and only scope
  applies. Known debt (§16.5 landmines): do not grow them, extract when you next
  touch.

### 18.3 Modules — 5–15 cohesive files

* **Cohesion test:** the files in one directory should change together and share
  a vocabulary. If two files in the same directory never change in the same
  commit, they belong in different directories.
* **Past ~15 files**, split — either by sub-package (`services/run/`,
  `services/history/`) or by a prefix family (`stores/label_*`,
  `stores/media_*`, `stores/history_*`). A family is a module in everything but
  the directory separator; treat it as one when counting.
* *Measured:* 2026-09-12, after Round F step F2 — `core/` 6, `app/` 4, `bridge/` 14,
  `services/history/` 7, `services/run/` 10 in band, and the `collector_*` prefix
  family is **9**, in band and cohesive (all nine share the `CollectorState`
  vocabulary and the `host.` protocol); `services/` 33, `stores/` 37, `backend/` 30,
  `actions/` 23 over it, held by prefix families (`history_*` 9, `collector_*` 9,
  `db_deletion_*` 8, `label_*` 6, `undo_*` 4, `media_*` 4).

### 18.4 Context files — 60–200 lines

A **context file** is any doc a reader is expected to load *whole* before
working: the files in `docs/current/`, a root `CLAUDE.md` / `AGENTS.md`, a
package-level README. The test is not "is it complete?" but **"can an agent read
all of it and still have room for the code it must change?"**

* That single test is why `docs/current/` holds three files and 78 are archived
  (RULE 17): a pointer outward beats a wall of prose.
* **Over 200 lines**, move the detail into `docs/archive/<date>-<topic>/` (or a
  linked appendix) and leave the link here. A context file is a map, not the
  territory.
* *Measured:* `reports/IDEAL_SIZE_BASELINE_2026-09-11.md` §4 (re-run `wc -l docs/current/*.md` rather than trusting a
  number written here — these files move). `SYSTEM_OF_RECORD.md` and
  `DOM_SELECTORS.md` are accepted overruns: their value is that every invariant
  sits next to the module and the test that enforces it, which is lost the moment
  it is split. They are **at their ceiling** — the next edit to either moves
  detail into `docs/archive/` instead of adding lines.
* `AGENT_RULES.md` is measured against a different budget: an agent must be able
  to load *all* the rules in one read, so splitting them would defeat the
  purpose. **Budget: ~730 lines.** It is at that budget now — adding RULE 19
  (2026-09-11) pushed it past the ~700 set when RULE 18 was written, and the
  difference was paid by moving detail out, not by cutting norms: RULE 1's worked
  code went to a linked appendix, the measurement dumps went to
  `reports/IDEAL_SIZE_BASELINE_2026-09-11.md`, and the remediation prose that
  RULE 18 and RULE 19 both carried now lives once, in RULE 19. The next rule
  added here must do the same — extract first, then add.

### 18.5 When you exceed an ideal

Allowed, with a reason the next reader can see:

```python
# ideal-size: 78 lines reason=single JS payload for the probe; splitting the
# string literal would break the in-page agent contract
```

* The reason must name a **constraint** (wire format, one JS/HTML literal, a Qt
  slot signature, a frozen contract that forbids the split), not convenience.
* No tooling parses `ideal-size:` — it is for the reader, unlike the
  `quality-override:` comment in §16.4 which review does parse.
* Never satisfy an ideal by gaming it (§16.2): no `foo_part1`/`foo_part2`, no
  lambdas that only hide `if` count, no splitting a JS literal to shrink a file.

### 18.6 Measuring (copy-paste)

Copy-paste commands are in the *Reproduction* section of
`reports/IDEAL_SIZE_BASELINE_2026-09-11.md` (`wc -l` per file, `radon raw -s`,
directory counts). Function lengths come from the AST walker in
`tests/test_rule16_new_code.py` (`node.end_lineno - node.lineno + 1`) — use that
count, not a line grep.

---

## RULE 19 — Fix complexity before size (the remediation order)

> When code is over the line, fix it in this order: **nesting → cyclomatic →
> cognitive → size.** Size is a *symptom*; the other three are the cause.
> Splitting first turns one complicated function into several files that share
> one complicated decision — greener metrics, worse code (§16.2 gaming).

```
Step 1:  Fix NESTING DEPTH first (> 4 → flatten)
         ├── Guard clauses / early returns
         ├── Invert conditions
         └── Extract deeply nested blocks

Step 2:  Fix CYCLOMATIC COMPLEXITY (> 10 → simplify)
         ├── Replace conditionals with polymorphism / dispatch
         ├── Strategy pattern for branching
         └── Lookup tables instead of if/elif chains

Step 3:  Fix COGNITIVE COMPLEXITY (> 15 → clarify)
         ├── Break compound boolean expressions into named variables
         ├── Replace clever tricks with obvious code
         └── Simplify control flow

Step 4:  NOW check SIZE — it's probably already fixed
         ├── If function still > 20 LOC → extract by concept
         ├── If class still > 120 LOC → single responsibility split
         └── If params > 3 → introduce parameter object
```

Steps 1–3 quote the **fail lines** (RULE 16: nesting 4, CC 10, cognitive 15).
Step 4 quotes the **ideals** (RULE 18 / §16.1 "prefer": 20 / 120 / 3) — *not*
fail lines, which are 30 / 150 / 4. Nothing in step 4 rejects a change on its own.

Why the order works: each earlier step **deletes decisions**, and deleting
decisions is what moves every later metric. Flattening a six-deep branch usually
removes 2–4 CC; a lookup table replacing an `if/elif` chain removes the CC, the
nesting *and* most of the cognitive load; and a function whose branches are gone
is often short enough that no extraction is needed at all.

**19.1 Step 1 — nesting (> 4).** Guard clauses: refuse early and return so the
happy path is never indented — structurally, the way `services/db_deletion_flow.py`
raises `_PhaseRefusal` from a phase and catches it once in `delete_world`,
instead of 27 nested early-return blocks. Invert (`if not ok: return`, not
`if ok:` around the body). Extract the *innermost* deep block first — smallest
scope, safest move. Measured by the AST walker in `tests/test_rule16_new_code.py`.

**19.2 Step 2 — cyclomatic (> 10).** Dispatch instead of branching on a type:
the 16 blocks are a registry lookup (`actions/registry.py` `get_action_class`),
not an `if/elif` over block ids. Lookup tables are data, not branches:
`choose_cycle_mode()` returns `CycleDecision(mode, reason)` from a precedence
table; `DB_GROUP_SUFFIXES`, `MIME_EXT`, `IMAGE_EXT` are tuples/dicts. Two
interchangeable back-ends behind one call, not a branch at every call site:
archive search is FTS5 when SQLite offers it and a `text_lc LIKE` scan when it
does not (`backend/history_query.py`). Never delete a real decision to reach the
number — four independent binary outcomes cost CC 5 minimum (§16.2).

**19.3 Step 3 — cognitive (> 15).** Name the compound: `if _is_self_chat(names)`
reads, `if a and not b and c or d` does not; `StackFacts.has_mem_click` exists so
nobody re-scans the stack inside a condition. Obvious beats clever — a comment
explaining a trick is a request to delete the trick. Scored by
`cognitive-complexity` 1.3.x.

**19.4 Step 4 — size, last.** By now the function is often already inside the
ideal. If not, extract **by concept** with a name that already exists in the
domain (`_gate_before_cycle`, `_announce_stopped`, `inspect_stack`) — never
`foo_part1`. A class over the ideal gets a single-responsibility split, the way
`services/run/` and `stores/history_repo*` were split (§18.2). Too many params
get a parameter object: `PersonPageRequest` in `backend/history_query.py` is the
model — `needle` / `where` / `order` / `spec` / `columns` as properties of one
typed request instead of five arguments.

**19.5 When the ladder does not apply.** A function that is long but *flat* —
sequential phases or a fallback ladder, little nesting — is not fixed by steps
1–3. Two real cases: `DbLifecycle._delete_unlocked` was 631 LOC at CC 143
because it ran seven sequential phases, and the fix was extraction by phase
(`validate → scan → switch → detach → database → media → finalize`);
`backend/message_injector.py` `_run_type_strategies` (70 LOC) is a verified
typing ladder — value setter → Ctrl+V → `insertText` — whose length is three
real attempts plus their read-backs, so it extracts per attempt, not per branch.
In both, step 4 was the tool rather than the fallback. Read the shape before
picking a step: nested → 1, branching → 2, dense → 3, long-and-flat → 4.

**19.6 Verify after every step.** `radon cc -s <file>`, then the gate:
`.venv/bin/python tests/test_rule16_new_code.py`. A step is not finished because
the number moved — it is finished when the existing suite is still green
(§16.6 step 3), because steps 1–3 must be behaviour-preserving.
