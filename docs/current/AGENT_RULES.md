# Agent rules — the only rules file for this repository

What an AI agent (or a human) **MUST** follow when adding or changing code
here. This file replaces the former `AGENT_RULES.md` +
`AGENT_RULES_CODE_QUALITY.md` pair (both preserved in
[`docs/archive/2026-09-10-agent-rules-v1/`](../archive/2026-09-10-agent-rules-v1/)).

* Current behaviour, invariants and flows: [`SYSTEM_OF_RECORD.md`](SYSTEM_OF_RECORD.md)
* Doc map (what is current vs historical): [`docs/README.md`](../README.md)
* Rule numbers are **stable** — production code cites them (`RULE 1` … `RULE 17`).
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

### Correct

```python
from backend.visual_click import find_and_click

class MyBlock(BaseAction):
    async def execute(self, user_nick, cdp, engine=None):
        await self.pre_delay()
        return await find_and_click(
            cdp,
            selector=self.selector,
            label_selector=self.label_selector,
            match_text=self.match_text,
            click_selector=self.click_selector,
            highlight_enabled=self.highlight_enabled,
            confirm_pause_ms=self.confirm_pause_ms,
            label=f"my thing “{self.match_text}”",
            engine=engine,
        )
```

### Incorrect — do not do this

```python
raw = await cdp.evaluate("document.querySelector('.x').click()")   # ✗ no logging
raw = await cdp.evaluate(build_probe(..., click=True))             # ✗ no overlays
```

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
   and rules 1–15. Then the matching archived design (§16.7 tells you where).
2. **Research and design the structure in a doc first** when the change moves
   complexity across files (new class, extraction from a hotspot). Record
   current radon numbers, target numbers, and the dishonest reductions you
   rejected. Put it in `docs/archive/<YYYY-MM-DD>-<topic>/` (RULE 17).
3. **Tests first** for behaviour changes (RULE 8). Refactors claiming
   behaviour-preservation run the existing suite as the equivalence gate.
4. **Measure**: `radon cc -s path/to/file.py`. Any new function at `C` or worse
   (CC ≥ 11) → stop and redesign.
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
