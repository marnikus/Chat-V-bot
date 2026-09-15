# Code Quality Metrics — 2026-09-16 (after the JS-split fixes on `main`)

Measured on `origin/main` (`f8f1d88 "upd"`, 2026-09-15 13:35 +0200) via a
detached worktree — this captures the user's latest fixes (the Round-H Area A
JS splits: `ui/js/` 27 → 85 files, `sash-grid`/`stack-dnd`/`user-table`/
`window-presets`/`bot-*`/`labels-*` decomposed). This workspace branch
(`arena/01a0a4de-chat-v-bot`, tip `49d4ec9`) is reported separately where
named, because the two streams diverged (see §8).

Environment: venv from `requirements-dev.txt`, Qt stubs via
`tools/build_stubs.py` (`LD_LIBRARY_PATH=/tmp/stublibs`) — the same technique
main's own `tools/metrics/run_tiers.py` uses. The suite was run by tier per
that runner's taxonomy (`pure`, `db`, `qt`, gates): a flat `-n 4` run hangs on
Qt fork-unsafety on this tree.

## §0 Headline

> **The fixes go in the right structural direction, but they shipped
> unverified.** The suite is RED: **73 failing tests** (22 pure/db +
> 45 qt + 6 gates/misc) plus a flaky Qt SIGABRT; the **JS gate FAILs with
> 86 violations**; **JS coverage collapsed 82.52% → 69.49%**; Python coverage
> measured 90.37% — under main's own §16.3 recorded baseline of **93.16%**
> (never-decrease breach). Meanwhile the shape metrics genuinely improved
> (see §2). The debt is *verification*, not *structure*.

## §1 Complexity metrics

| Metric | Threshold | Measured on main | Verdict |
|---|---:|---|---|
| Cyclomatic (radon, 8 pkgs) | ≤ 10 | **0 functions over 10** | ✅ |
| Cognitive / nesting (RULE 16) | ≤ 15 / ≤ 4 | rule16 gate exit 0 ("all owned functions fit") | ✅ |
| JS functions > 30 LOC (js_gate) | ≤ 30 (new code) | **37 over** (49 at the 2026-09-14 baseline — improving, still violating) | ❌ |
| Worst JS function | — | `backend/js/chat_agent.js::(anonymous)` **782 LOC**; `ui/js/sash-core.js::(anonymous)` **661 LOC** (grew 619→661 since baseline) | ❌ |
| Largest JS object | ≤ 150 LOC | `sash-grid-drag-core.js` **194**, `sash-grid-drag-spec.js` **159** | ❌ |
| JS methods per object | ≤ 15 | `bot-settings-core.js` object **21** | ❌ |

## §2 Size & volume — the direction is right here

| Metric | main | Baseline (2026-09-14) | Note |
|---|---|---|---|
| JS files | 85 | 42 | the splits |
| JS total lines | **11,182** | 12,229 | **−1,047** — real deduplication |
| JS functions | 1,149 | — | |
| Python size gate | exit 0 | exit 0 | func LOC ≤ 30, class ≤ 150, params ≤ 4 — clean |
| Own gate self-test | **2 failed** | — | `test_rule16_new_code.py`: a request object is over its own size gate |
| File-count ratchets | **3 failed** | — | stores package file count + module-family counts |

## §3 Coupling & cohesion (package import graph, counted as distinct package deps)

| Package | Ca | Ce | Instability I |
|---|---:|---:|---:|
| core | 4 | 0 | 0.00 (stable root ✓) |
| stores | 4 | 2 | 0.33 |
| actions | 2 | 1 | 0.33 |
| backend | 5 | 4 | 0.44 |
| services | 3 | 4 | 0.57 |
| bridge | 1 | 4 | 0.80 |
| app | 0 | 4 | 1.00 (unstable leaf ✓) |

Layering reads healthy (core is depended on, app depends, nothing leaks
upward). LCOM is not measured by any tool in-tree; cohesion is enforced as
the stores module-family ratchet — currently **FAILING (2 tests)** because
the fixes added undeclared stores modules.

## §4 Test quality

| Metric | Target | Measured on main | Verdict |
|---|---:|---|---|
| Suite status | green | **3263 passed, 73 FAILED**, 5 skipped, 1 xfailed, 973 subtests (3340 items) | ❌ |
| Line coverage | ≥ 80%, never < baseline | **90.37%** — below the §16.3 recorded **93.16%** | ❌ breach |
| Branch coverage | ≥ 75% | **85.56%** | ✅ floor, ⚠ below last measurement |
| JS line coverage | ratchet ≥ 82.52 | **69.49%** (5,365/7,721) | ❌ −13 pts |
| Test-to-code ratio | ~1:1 | 43,376 / 26,873 ≈ **1.6 : 1** | ✅ |
| Mutation score | ≥ 70% (soft) | last measured 2026-09-14 (`reports/MUTATION_REPORT_2026-09-14.md`); not re-run today | — |
| JS suites via Node | green | **14+ failing** (userdb_refresh, userdb_sort, window_preset(s), …) | ❌ |
| Phased timing | — | pure 57 s · db-tier 105 s · qt-only 117 s · residual 22 s (+ gates) | flaky Qt abort in mixed qt runs (−6) |

### The 73 RED, by family (full names reproduced in the Round plan)

| Family | Count | Hint |
|---|---:|---|
| JS-split DOM/bridge contract regressions | ~9 | `test_archive_delete_undo` (4), `test_person_labels` (2), `test_live_status_and_order` (1), `test_people_undo` (1), window-presets export (1) |
| Legacy bridge/router compat surface (`TestLegacyCompatSurface`, file bridge) | ~7+ | helpers removed while contracts still pin them |
| Defensive backend reads | 2 | `test_history_query_gaps` |
| Media network-watch behaviour | 3 | `test_media_network_watch` |
| Stores frozen surface / counts / file families | 5+2 | API-drift vs contract vs ratchet |
| Gate self-tests (rule16 request object, js_gate baselines, clone baseline) | 3+1+1 | the gates' own baselines drifted |
| qt-only tier residuals | ~35 more | same families above plus `test_sash_webengine` (needs real GL — environment-bound on any runner) |

## §5 Code smells

| Smell | Detector | Measured |
|---|---|---|
| Dead code | vulture ≥ 90 | **3 findings** — `services/run/hooks.py:21/24/27` unused `coordinator` (100%) |
| Duplication | clone_scan | baseline **mismatch** (`test_smell_inventory` FAIL — count drifted from baseline; spans still present, e.g. `undo_world.py` ↔ `preset_store.py`) |
| Long methods / god classes | js_gate | §1 table (37 new >30, two >150 objects, one 21-method object) |
| Untested new code | js_gate | ~20 NEW split files **never loaded by any Node test** |
| Feature envy | manual | not measured (review-level smell) |

## §6 Maintainability

| Metric | Value |
|---|---|
| radon MI (280 production files) | min 40.21 · p25 56.4 · median 65.8 · mean ~70.0 |
| Technical debt (counted) | 73 red tests + 86 JS-gate violations + 3 vulture + 1 clone-drift |
| Code churn | **not measurable** — `main` is a single-commit import (`f8f1d88`); keep history on future pushes |
| Bug density | no tracker import — proxy: 73 failing contracts / 26.9k prod LOC |

## §7 What this says (priorities → see the Round plan)

1. **RED first.** 73 failing contracts is the cheapest, highest-value work in
   the repo right now: each is either a real regression (fix the code,
   RULE 8) or legitimate drift (re-baseline the contract and name it).
2. **The JS verification floor fell through the floor.** 82.52 → 69.49%,
   ~20 never-loaded files, 14+ red suites. The splits need harnesses, not
   more splits.
3. **Split leftovers are now the size head.** 37 NEW >30-LOC functions and
   two >150-LOC objects in files that were just created — fix in RULE 19
   order before they fossilize into "legacy".
4. **Gate integrity.** Gates that exit 0 while printing FAIL (js_gate),
   self-test breaches (request object), and ratchets tripped by undeclared
   modules hole the whole enforcement story.

## §8 Session-branch comparison (this workspace, `49d4ec9`, measured 2026-09-15)

Suite 3206 passed / 3340-vs-3209 collect scale; parallel `-n 4` in 73.8 s;
coverage 91.77 / 88.05; JS coverage 82.79 with a live pytest ratchet
(global floor 82.7, 30 per-file pins); wait-budget ratchet (≤ 50 ms sleeps);
RULE 8 integration doctrine in the rules file. The two streams each shipped
what the other lacks: `main` has the Area A JS splits + tier runner +
JS/size/mutation tooling; this branch has the test-time lanes, ratchets and
the doctrine. **Reconciliation is step R0 of the Round plan.**

## Reproduction

```bash
# tiers (main's own runner taxonomy)
python tools/metrics/run_tiers.py --with-qt           # pure+db+qt
python -m pytest -m "db or pure" -q -n auto --tb=no -rf
python -m pytest -m "qt and not db and not pure" -q -n 0 --tb=no -rf
python -m pytest -m "not pure and not db and not qt" -q -n 2 --tb=no -rf
# coverage (canonical tier scope, 2-stage because qt needs -n 0)
python -m pytest -m "db or pure" -q -n auto --cov=<8 pkgs> --cov-branch --cov-report=
python -m pytest -m "qt and not db and not pure" -q -n 0 --cov=<8 pkgs> --cov-branch --cov-append --cov-report=json:coverage.json
# gates and smells
python tools/metrics/rule16_gate.py && python tools/metrics/js_gate.py
python tools/metrics/js_coverage.py && python tools/metrics/clone_scan.py --cache /tmp/cc.json
python -m vulture --min-confidence 90 backend bridge services stores actions core app
```
