# RULE 16 — Code quality gates (mandatory for every agent change)

Rules an AI agent MUST follow when adding or changing production Python
in this repository. This document is the **source of truth** for size,
complexity, coverage, smells, overrides, and CI. It is more specific than
the generic “keep code clean” request: numbers, scopes, tools, and
exceptions are frozen here.

Companion: `docs/archive/2026-09-10-agent-rules-v1/AGENT_RULES.md` (behavioral product rules 1–15).
Baseline snapshot: `reports/CODE_QUALITY_METRICS_2026-09-10.md`.

---

## 0. When this rule applies

| Situation | Gate |
|---|---|
| New production function/class in `core/`, `actions/`, `backend/`, `bridge/`, `services/`, `stores/`, `app/`, `main.py` | **Hard fail** if any threshold in §1–§3 is exceeded |
| Edit of an existing function that already violates a threshold (legacy) | Must not **worsen** the metric; prefer reduce. See §6 |
| Tests, `tools/`, docs, HTML dumps, generated caches | **Out of scope** for size/CC (tests still must exist for new production paths) |
| Embedded JavaScript inside Python string builders (`dom_probe`, highlight probes) | Length limit **does not** force a split of the JS payload. CC of the Python wrapper still applies. See §1.5 |
| Compatibility facades / `__init__` that only re-export | Method-count / class-LOC may be waived with an override comment (§5) |

If a change would pass with the feature deleted, it is not a test
(`docs/archive/2026-09-10-agent-rules-v1/AGENT_RULES.md` RULE 8). Coverage that only executes lines without
asserting behavior does **not** satisfy §3.

---

## 1. Size and volume — hard limits on **new** code

Use the **upper** end of each range as the CI fail line. Prefer the lower
end when writing new helpers.

| Check | Prefer | **CI fail if** | How counted |
|---|---:|---:|---|
| Function / method physical LOC | ≤ 20 | **> 30** | Inclusive AST source span: first `def`/`async def` line through last line of body. Includes blanks and docstring. Excludes decorator lines. Nested functions counted separately. Lambdas ignored. |
| Class physical LOC | ≤ 120 | **> 150** | Inclusive AST span of the `class` body. Nested classes counted separately. |
| Parameters per function | ≤ 3 | **> 4** | Exclude leading `self` / `cls`. Count keyword-only args. Count `*args` and `**kwargs` as **one each**. |
| Direct methods per class | ≤ 10 | **> 15** | Methods defined on the class body only (not inherited). Include `__init__`, properties’ fget/fset if defined as `def` on the class. |

### 1.1 What an agent must do when approaching a limit

1. **Do not** split a function into `foo_part1` / `foo_part2` solely to
   game LOC. Extraction is allowed only when the helper has a name that
   states a real responsibility (`_announce_stopped`, `_try_prepare_cycle_queue`).
2. **Do not** hide parameters behind a catch-all `**kwargs` to dodge the
   param cap. Block settings stay as explicit instance attributes
   (RULE 3). Wide `__init__` on action blocks is **legacy**; new blocks
   must take ≤ 4 constructor params besides `self` and fold extras into a
   typed config object or `config_schema` fields set after construction.
3. New classes that would exceed 15 methods must be designed as
   collaborating types *before* writing the 16th method.

### 1.2 Pre-commit vs CI

- Pre-commit: size limits on **staged production files only**.
- CI: same limits on the PR diff’s new functions, plus a report of
  remaining legacy violators (warn, do not fail — §6).

### 1.5 Embedded JS exception (explicit)

`backend/dom_probe.py` `build_probe` is 122 LOC because it embeds a JS
probe. **Do not refactor that builder to meet 30 LOC.** New probe builders
may exceed 30 LOC **only** when the excess is a single JS/HTML string
literal. The Python control flow around that literal must still be
CC ≤ 10 and nesting ≤ 4.

---

## 2. Complexity — block merge if exceeded on new code

| Check | Tool | **CI fail if** | Counting rules (frozen) |
|---|---|---:|---|
| Cyclomatic complexity (CC) | `radon cc -s` (Radon 6.x) | **> 10** | Radon: base 1; +1 per `if`/`elif`/`except`/`for`/`while`/`assert`/`with` (if extra); +1 per `and`/`or`; +1 per comprehension `if`; +1 per ternary. `try` itself and `in` tests cost 0. |
| Cognitive complexity | `cognitive-complexity` 1.3.x (or flake8 plugin wrapping the same lib) | **> 15** | Library default. Nested functions scored separately. |
| Nesting depth | custom AST walker (same definition as `reports/CODE_QUALITY_METRICS_2026-09-10.md`) | **> 4** | Maximum ancestry of `if` / loops / `with` / `try` / `match`. `elif` is nested AST `if`. Sibling blocks do **not** add. |

### 2.1 Anti-gaming (non-negotiable)

Copied from the AREA C design and now a standing rule:

> Do not scatter conditions into meaningless one-line helpers to satisfy
> a metric.

Forbidden:

- `if x: return _helper_true(); return _helper_false()` where helpers
  contain the original body with no new name meaning.
- Dispatch tables of lambdas whose only purpose is to hide `if` count.
- Inferring control flow from a flag to drop a real exception branch
  (see rejected D3 in `docs/archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_C_CC_DESIGN_2026-09-10.md`).

Allowed:

- Delete **dead** branches (`except ImportError` for a module that always
  exists).
- Extract a helper that already exists as a named concept in the domain
  (`check_stopped`, `_try_prepare_cycle_queue`).
- Replace `except Exception` + `isinstance` scaffolding with a narrow
  `except RunStopped`.

### 2.2 Override

A single function may exceed CC/cognitive/nesting **only** with a
justification comment on the `def` line (see §5). CI still **posts** the
violation; merge is allowed only if the comment is present **and** a
human (or the PR template checkbox) acknowledges it.

---

## 3. Test coverage — new code must be tested

Global floors (must not go down; current baseline 2026-09-10:
line **88.44%**, branch **81.32%**):

| Metric | Target | Tool | Fail rule |
|---|---:|---|---|
| Line / statement coverage | **≥ 80%** overall; **never decrease** vs the last `main` / recorded report | `pytest --cov --branch` with `--source=core,actions,backend,bridge,services,stores,app,main` | CI fail if overall line **or** branch % is lower than the stored baseline file |
| Branch coverage | **≥ 75%** overall | same | same |
| Uncovered **new** functions | **0** without an override | coverage XML/JSON diff vs base SHA | PR comment lists every new function with 0 hits |
| Mutation score | **≥ 70%** on touched *pure* modules when a mutmut job is configured | `mutmut` | Soft-fail (comment) until the job is wired; then hard-fail for those modules |
| Test-to-code ratio | **~1:1** (nonblank non-comment Python LOC, tests vs production) | audit script | Warn if PR drops the ratio below 1:1; do not fail solely on ratio |
| Combined line+branch % from coverage.py | informational only (was 87.03%) | — | **Do not** use this number as the gate |

### 3.1 What “tested” means for an agent

For every new production function:

1. At least one test that would **fail if the function were deleted**
   or if its boolean were inverted.
2. Empty vs broken distinguished (RULE 4).
3. Stop / cancel paths honoured if the function loops (RULE 7).
4. JS probes go through `tests/js_harness.js`, not string matching
   (RULE 8).

### 3.2 Coverage command (copy-paste)

```bash
QT_QPA_PLATFORM=offscreen \
python -m pytest tests -q \
  --cov=core --cov=actions --cov=backend --cov=bridge \
  --cov=services --cov=stores --cov=app --cov=main \
  --cov-branch \
  --cov-fail-under=80 \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
```

Branch 75% is checked from `coverage.json` (`totals.covered_branches / totals.num_branches`),
not from `--cov-fail-under` (that flag is line-only).

Do **not** add application deps for test tools. Analysis packages live in
the CI / `.venv` used for metrics, not in `requirements.txt`.

---

## 4. Code smell detection — flag, then fix or justify

| Smell | Detector | Agent action | CI |
|---|---|---|---|
| Duplicated logic (DRY) | `jscpd` and/or pylint `R0801`; repo also uses exact-AST clones ≥ 6 lines | Extract a named helper **in the owning layer**; do not copy-paste probes, report strings, or SQL | Fail on **new** clone groups vs base SHA |
| Dead code | `vulture --min-confidence 90` on production packages | Remove unused imports. Unused args on protocol/callback signatures may stay if the signature is required | Fail on **new** findings at ≥90% that are unused imports or unused variables (not unused args on interface methods) |
| Long method | size rule §1 | Split by responsibility, not by line quota | Same as §1 |
| God class | class LOC > 150 or methods > 15 | Decompose before adding a 16th method / more lines | Fail on **new** classes; warn on legacy growth |
| Feature envy | review (no reliable automated graph yet) | If a method mostly uses another type’s data, move it | Manual PR comment; no hard fail until a detector exists |

Smells are **zero new** on the PR diff. Pre-existing smells are inventory,
not a license to add more.

---

## 5. Override mechanism (required justification)

Place a comment on the function or class that CI will parse:

```python
def wide_legacy_adapter(self, a, b, c, d, e):  # quality-override: params=5 reason=CDP wire matches Chrome DevTools payload; do not invent a wrapper type this PR
    ...
```

Format (strict):

```
quality-override: <metric>=<value> reason=<one line, ≥ 20 characters>
```

Allowed `<metric>` tokens: `loc`, `class-loc`, `params`, `methods`, `cc`,
`cognitive`, `nesting`, `coverage`, `vulture`, `dup`.

Rules:

- Reason must name a **constraint** (wire format, generated JS, Qt slot
  signature), not “faster to ship”.
- One override per metric per symbol.
- Overrides on **new** files are exceptional; CI still comments.
- Never use override to skip tests for a new behavior path.

---

## 6. Legacy code (already over the line)

From the 2026-09-10 audit: 64/1532 functions CC>10, 73 functions LOC>30,
11 classes LOC>300 under the old cap (new cap is **150** — more classes are
legacy offenders). Agents **must**:

1. Not increase CC, cognitive, nesting, LOC, params, or method count of a
   legacy offender.
2. Not add new methods to a class already over 15 methods unless the PR
   also extracts enough methods to net ≤ the old count.
3. Prefer touching a hotspot only with tests that lock current behavior
   first (red-green only if behavior changes).

Hotspots to treat as landmines (do not “quickly fix CC” without a design
doc): `ScrollParser`, `Collector`, `HistoryBridge`, `UndoService`,
`services/run/coordinator.py`, `stores/label_state.py`,
`backend/history_query.py`, `services/db_lifecycle.py`,
`backend/tab_matcher.py`, `actions/wait_page.py`.

---

## 7. Enforcement pipeline (what the agent must assume exists or add)

If these files are missing, the agent’s **first** quality task is to add
them — not to invent a one-off script in `/tmp`.

| Stage | What runs | Fail? |
|---|---|---|
| Pre-commit | size + radon CC + nesting on staged production `.py` | Yes (local); overridable with `git commit --no-verify` **only** together with a `quality-override` in the diff |
| CI (every PR) | full radon, cognitive, nesting, coverage vs baseline, vulture, duplication | Yes for new-code violations and coverage regression |
| PR comment bot | Markdown table: symbol, metric, value, threshold, override? | Always post if any violation or smell |
| Merge | Branch protection: required check `quality-gate` | Block |
| Dashboard | Append a row to `reports/CODE_QUALITY_METRICS_*.md` or a JSON history under `reports/quality/` | Not a merge blocker |

### 7.1 Tool versions (pin in CI, not in app requirements)

| Check | Tool | Threshold |
|---|---|---|
| CC | `radon cc -s` 6.0.x | ≤ 10 |
| Cognitive | `cognitive-complexity` 1.3.x | ≤ 15 |
| Coverage | pytest-cov + coverage.py 7.x | ≥ 80% line / ≥ 75% branch; no drop |
| Mutation | `mutmut` (optional job) | ≥ 70% |
| Smells | pylint + custom | zero **new** |
| Dead code | vulture 2.16+ `--min-confidence 90` | zero **new** unused imports/vars |
| Duplication | jscpd and/or AST clone scan ≥ 6 lines | zero **new** groups |
| Size | custom linter / wemake-python-styleguide `TooLong*` | function ≤ 30 LOC |

Production packages scanned: `core`, `actions`, `backend`, `bridge`,
`services`, `stores`, `app`, `main.py`. Exclude `tests`, `tools`,
`ui` JS (JS has its own harness; no Python size gate).

---

## 8. Agent workflow (implementation process)

Before writing production code:

1. **Understand the problem.** Read the matching `docs/*_DESIGN_*.md` and
   RULES 1–15. If none exists, write the design **first**.
2. **Design structure in a doc** when the change will move complexity
   across files (new class, extract from a hotspot). Include: current
   radon numbers, target numbers, rejected dishonest reductions.
3. **Tests first** for behavior changes (RULE 8). Refactors that claim
   behavior-preservation must run the existing suite as the equivalence
   gate — do not add tests that only snapshot internals.
4. **Measure.** After the change, run radon on the touched files:

   ```bash
   radon cc -s path/to/file.py
   ```

   If any new function is `C` or worse (CC ≥ 11), stop and redesign.
5. **Do not** lower CC by deleting a real decision. Floor examples:
   four independent binary outcomes cannot cost less than CC 5
   (1 base + 4 branches).

---

## 9. Acceptance checklist (agent self-review before claiming done)

Copy into the PR / session summary:

```text
[ ] No new function > 30 physical LOC (except documented JS-literal builders)
[ ] No new class > 150 LOC or > 15 methods
[ ] No new function with > 4 params (excluding self/cls)
[ ] radon CC ≤ 10 on every new / edited function (or quality-override)
[ ] cognitive complexity ≤ 15 on those functions
[ ] nesting depth ≤ 4
[ ] overall line coverage ≥ 80% and not below last baseline
[ ] overall branch coverage ≥ 75% and not below last baseline
[ ] every new function has a test that would fail if deleted
[ ] no new vulture unused-import findings
[ ] no new duplication groups
[ ] quality-override comments used only with a real constraint
[ ] did not game metrics with dummy helpers
```

---

## 10. What this rule does **not** require of an agent in one session

- A live metrics dashboard UI.
- Mutation testing of the entire tree (start with pure modules:
  normalization, filters, tab scoring).
- Refactoring every legacy hotspot to green.
- Putting radon/vulture in `requirements.txt`.

Those remain “build” items in the product plan. The agent **does**
enforce §1–§6 on the code it writes **now**.
