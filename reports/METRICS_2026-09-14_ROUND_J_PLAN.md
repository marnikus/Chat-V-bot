# Metrics measurement + Round J plan — 2026-09-14

Measured at commit `0ece364` (SPEED_MULTIPLIER port), working tree clean.
Every number below was produced by a command in §7, not copied from a
previous round. Where a metric contradicts an earlier report, the earlier
report is corrected here rather than quietly replaced.

---

## 1. The six metric families, measured

### 1.1 Complexity — Python: **clean**. JavaScript: **65 violations**

| Metric | Threshold | Python | JavaScript |
|---|---|---:|---:|
| Cyclomatic complexity | ≤ 10 / function | **0 over** (max 10, mean 2.95) | **65 over** (max 35, mean 3.41) |
| Cognitive complexity | ≤ 15 / function | **0 over** | **19 over** (max 56) |
| Nesting depth | ≤ 3–4 | **0 over** | **4 over** (max 6) |

2 273 Python functions, 1 339 JavaScript functions (module IIFE wrappers
excluded — see §6.1).

### 1.2 Size & volume

| Metric | Threshold | Python | JavaScript |
|---|---|---:|---:|
| Function LOC | ≤ 20–30 | 35 over 30 (mean 9.34) | 69 over 30 (mean 10.80) |
| Class LOC | ≤ 200–300 | 23 over 200, **1 over 300** (`SchemaMigrator` 406) | n/a (no classes) |
| Parameters | ≤ 3–4 | 52 over 4 (raw), max 20 | 4 over 4 |
| Methods / class | ≤ 10–15 | 26 over 15, max 44 (`HistoryRepo`) | n/a |

Files over 300 physical lines: **8 Python**, **28 JavaScript**. The two
largest files in the repository are both JS: `sash-grid.js` (1 361) and
`stack-dnd.js` (1 341).

### 1.3 Coupling & cohesion (Python only — no JS tooling exists)

| Metric | Goal | Result |
|---|---|---|
| Afferent coupling (Ca) | low | max 31 (`core.events`) — a stable hub at I=0.0, correct |
| Efferent coupling (Ce) | low | max 20 (`bridge.router`), then `services.run.coordinator` 15 |
| Instability | balance | **1 module** in the painful zone (Ca≥5 **and** I>0.6): `services.collector_service` (Ca 5, Ce 13, I 0.72) |
| LCOM* | → 0 | 16 classes at >0.90 with ≥10 methods; worst real offender `Collector` 0.97 / 40 methods |

`lcom4_net > 1` fires on 93 classes, but most are dataclasses and protocols
where it is meaningless (`core/result.py::Err`, `PresetStoreProto`). The
honest signal is LCOM* combined with method count.

### 1.4 Test quality

| Metric | Target | Measured |
|---|---|---|
| Line coverage (Python, 8 packages, `--branch`) | ≥ 80% | **92.22%** (15 680/16 841) |
| Branch coverage (Python) | ≥ 75% | **88.43%** (3 502/3 960) |
| Test-to-code ratio (Python) | ~1:1 | **1.56:1** (41 730 : 26 805) |
| Mutation score (Python) | ≥ 70% | 99.37% on the one module last measured (`history_query`); not re-run tree-wide |
| **Line/branch coverage (JavaScript)** | ≥ 80 / 75% | **not measured — no instrumentation exists** |
| Test-to-code ratio (JavaScript) | ~1:1 | 0.91:1 by line count (10 787 : 11 865) |

Python suite: 3 164 passed, 7 skipped, 1 xfailed, 903 subtests.
14 Python files ≥40 statements sit under 80% line coverage; worst are
`app/lifecycle.py` (53.73%) and `backend/cdp_client.py` (63.14%).

### 1.5 Code smells

| Smell | Measured |
|---|---|
| Duplication | 11 clone groups, 76 physical lines — **all are import headers**, the accepted baseline |
| Dead code | vulture ≥80% confidence: **5 findings**, all false positives (`__exit__` params, protocol stubs) |
| Long methods | 35 Python + 69 JS functions over 30 LOC |
| God classes | `HistoryRepo` 44 methods, `Collector` 40, `LabelStore` 38, `MediaStore` 33, `HistoryDB` 30 |
| Feature envy | not separately instrumented; LCOM* is the proxy |

### 1.6 Maintainability

| Metric | Measured |
|---|---|
| Mean MI (radon, `multi=True`) | **69.68**; 110 files <65, 30 files <50 |
| Technical-debt ratio | no SonarQube in this repo; the RULE 16 gate is the executable stand-in and it **passes** |
| Code churn | flat — max 7 commits/file over the last 200 (`bridge/router.py`); **no risky hotspot** |
| Bug density | not tracked as a series; no defect database exists |

**On MI:** radon's own "A" band starts at 20, so MI<65 is *not* a defect —
the formula is dominated by SLOC, so any 200-line file scores in the 40s.
The 110 figure should not be read as 110 problems. I am deliberately **not**
proposing an MI-driven round; chasing it would mean splitting files to move
a number, which §16.2 forbids as metric gaming.

---

## 2. Where the biggest problem is

Python is in good shape: zero complexity violations, coverage well over
both floors, duplication at the accepted import-header baseline, dead code
effectively nil, churn flat. Nine rounds (A–I) of remediation did that.

**Every one of those rounds measured Python only.** The audit tool reads
`ui/js` for exactly two numbers — file count and line count — and the
RULE 16 gate never opens a `.js` file at all. That blind spot now holds:

* **11 865 lines** of production JavaScript, 31% of the codebase;
* **65 functions over CC 10**, against **0** in Python;
* **19 functions over cognitive 15**, including one at **56**;
* one function at **CC 35 / cognitive 50 / 179 LOC** (`stack-dnd.js::_showConfig`);
* **zero coverage instrumentation** — the 31 harnesses assert behaviour, but
  nothing measures what fraction of the frontend they reach;
* **5 files never loaded by any harness** (`composer.js`, `criteria-editor.js`,
  `log-console.js`, `stack-drag.js` 355 lines, `url-toolbar.js`).

This is not a close call. The worst Python function in the tree is CC 10;
the worst JS function is CC 35 with six levels of nesting. Round J therefore
takes the frontend from unmeasured to governed, and fixes what that
measurement exposes.

The one Python item worth carrying along is `services.collector_service`
(Ca 5, Ce 13, I 0.72, LCOM* 0.97, 40 methods) — the only module that is both
depended-upon and unstable. It gets one step, not a round.

---

## 3. Round J — steps

Nine steps, each ~8–16 h, each a self-contained commit with the full
verification green. RULE 19 order inside every step: nesting → cyclomatic →
cognitive → size. §18.2 "LCOM wins over size" applies to JS modules too:
where splitting a file would scatter one cohesive behaviour, it stays.

### J1 — Make JavaScript measurable (tooling, no production change)
Add `tools/metrics/js_audit.py`+`js_scan.js` (acorn AST: CC, cognitive,
nesting, LOC, params per function; per-file rollup), pinned to a vendored
acorn with a committed lockfile so the measurement is reproducible offline.
Emit the same JSON shape `current_audit.py` emits so both feed one report.
Extend `current_audit.py` to call it. **No production file changes.**
Deliverable: a baseline table for all 30 JS files. This is the step that
makes every later step verifiable.

### J2 — Bring JS under the RULE 16 gate
Teach `tools/metrics/rule16_gate.py` to own `.js` functions with the same
thresholds and the same ratchet/override machinery it already applies to
Python, seeded with today's 65/19/4 as the ratchet ceiling so the gate goes
green immediately and can only descend. Document the JS thresholds in
AGENT_RULES §16. **No production change** — this makes J3–J8 enforceable.

### J3 — JS coverage instrumentation + the 5 untested files
Wire `c8`/`node:coverage` around the 31 harnesses; publish line/branch
numbers next to the Python ones. Then write harnesses for the five files no
test loads, prioritising `stack-drag.js` (355 lines, pointer-event logic).
Target: every JS file loaded by ≥1 harness, and a *measured* frontend
coverage baseline to hold subsequent steps against.

### J4 — `stack-dnd.js::_showConfig` (CC 35 / cog 50 / 179 LOC)
The single worst function in the repository. It is a dispatcher: header,
per-key field rows (with four bespoke cases — CUSTOM_FIND, TYPE_MESSAGE,
SPEED_MULTIPLIER, the On/Off bar), then wiring. Redesign as a small
row-renderer registry keyed by block/field so each bespoke case is its own
≤20-line function and the loop carries no branches. Every branch is already
observable through the existing 5 stack-dnd harnesses plus J3's coverage.

### J5 — `sash-grid.js` complexity cluster (9 CC>10, 2 cog>15, 14 LOC>30)
The largest JS file (1 361 lines) and the densest violation cluster:
`_computeSpec` (CC 34 / cog 56 / nesting 5), `_showSpec` (CC 24 / cog 45),
`validatePortablePreset` (CC 34). The first two are one responsibility —
compute a spec, then render it — so extract the spec algebra into a pure
module (`ui/js/core/grid-spec.js`) that is unit-testable without a DOM, and
leave rendering behind. `validatePortablePreset` becomes a table-driven
field validator.

### J6 — `app.js` startup path (`_applyGlobalResult` nesting 6, `setupBridgeListeners` 204 LOC)
`_applyGlobalResult` has the worst nesting in the tree (6) and cognitive 55
in 39 lines — guard-clause inversion first (RULE 19 order), then extract.
`setupBridgeListeners` is 204 lines of registration: split into per-domain
registrar functions so each bridge's listeners read as one unit.
`restoreSession` (CC 22) and `initApp` (cog 18) come with it.

### J7 — `backend/js/chat_agent.js` pane logic (7 CC>10, 4 cog>15)
The injected page agent: `selectPane` (CC 30), `visiblePane` (CC 20),
`scrollerCandidates` (CC 24), `walk` (cog 15). This is the riskiest file to
change — it runs inside the target site — so it is deliberately late, after
J3's coverage exists. The three pane functions share one scoring heuristic
that is currently re-expressed three times; unify it as a single scored
candidate list.

### J8 — the remaining JS tail (`labels.js`, `user-table.js`, `collector-panel.js`, `history-*`)
6+4+5+4 CC>10 across four files, none individually severe. Mechanical
application of RULE 19 to each, in descending order, with the J2 ratchet
tightening after each file so the improvement cannot regress.

### J9 — `services/collector_service.py` + round close
The one Python item: `Collector` (40 methods, LCOM* 0.97, Ce 13, I 0.72,
Ca 5). Split by the LCOM4 partition the audit already reports (4 components),
keeping the facade so the 5 dependents are untouched. Then the round-closing
re-measurement: regenerate every table in §1 **from the tree** (Round H's
lesson — a closing table is measured at commit time, never copied from the
plan), plus the RULE 18 / RULE 16 re-check required by the task.

---

## 4. What is deliberately *not* in Round J

* **MI-driven file splitting.** §1.6 explains why the 110 figure is an
  artefact of radon's SLOC weighting, not 110 defects.
* **Python complexity work.** There is none left to do: 0 violations.
* **The import-header clone groups.** §18.5 forbids reordering or deleting
  live imports to dodge the scanner; the baseline is argued and stands.
* **Tree-wide mutation testing.** Worth doing, but it is a round of its own —
  the one module measured sits at 99.37%, so there is no evidence of a
  test-quality problem that would justify displacing the JS work.
* **`HistoryRepo` (44 methods) and the other god classes.** Real, but Round H
  already took the worst two; at LCOM* 0.93 with a working facade they are
  less costly than a CC-35 function nobody can test.

## 5. Risks

* **J1's acorn dependency.** The repo has no `package.json` today. Vendoring
  a parser is a real addition to the tree; the mitigation is that it lands in
  `tools/`, never in `ui/`, so no shipped code gains a dependency.
* **J7 changes code that runs inside the target site.** Held until coverage
  exists, and the harnesses for it are the acceptance criterion of J3.
* **SLOC budget.** §18.2b allows ≤2% per round (the ≤0.5%/step convention I
  have been using is stricter). Extractions add lines; each step states its
  measured delta, and J9 states the round total.

## 6. Measurement caveats

1. **IIFE wrappers.** Four "functions" of 782/619/386/327 LOC are module
   closures (`(function(){...})()`), CC 1–6. They are excluded from the
   function tables; counting them would invent four fake offenders.
2. **`params_effective`.** The audit re-expands parameter objects, so its
   122 figure includes functions whose wide arity *is* the RULE 19 remedy.
   §1.2 reports raw arity (52) alongside it.
3. **JS cognitive complexity** is my implementation of the nesting-weighted
   increment, not SonarSource's certified one. It is consistent across files
   and therefore valid for ranking and for a ratchet; it is not comparable to
   a Sonar number.
4. **No JS coverage number exists yet** — §1.4 reports the ratio, which is a
   proxy, not a measurement. J3 replaces it.

## 7. Commands

```bash
# Python audit (six families)
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  python tools/metrics/current_audit.py > /tmp/j1.json

# Python coverage
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs python -m pytest tests -q \
  --cov=actions --cov=backend --cov=bridge --cov=core --cov=services \
  --cov=stores --cov=app --cov=main --cov-branch

# gates
python tools/metrics/rule16_gate.py --with-clones
python tools/metrics/dump_public_api.py --diff
python -m vulture actions backend bridge core services stores app main.py --min-confidence 80

# JS (this report; becomes tools/metrics/js_audit.py in J1)
node /tmp/jsm/scan.js ui/js/*.js ui/js/core/*.js backend/js/*.js

# churn
git log --format=format: --name-only -n 200 | grep -E '\.(py|js)$' \
  | grep -vE '^(tests|tools|docs)/' | sort | uniq -c | sort -rn | head -20
```
