# Design: Code quality rules and auto-enforcement

Date: 2026-09-10  
Status: **design** (rules frozen for agents in `docs/AGENT_RULES_CODE_QUALITY.md`;
CI wiring still to build)  
Problem: quality numbers exist as reports but nothing blocks a PR.

## 1. Problem

New code can land on the session branch with oversized functions, CC > 10,
no tests, and duplicated logic. Humans and agents treat
`reports/CODE_QUALITY_METRICS_*.md` as optional reading.

This design does **not** claim the 2026-09-10 snapshot is fully green
against every threshold (64 functions still exceed CC 10). Enforcement is
**diff-based for new symbols** plus **no-regression** for coverage and
legacy hotspots.

## 2. Frozen thresholds

Upper bounds used as fail lines (prefer the lower bound when writing):

| Gate | Fail |
|---|---|
| Function LOC | > 30 |
| Class LOC | > 150 |
| Params (no self/cls) | > 4 |
| Methods / class | > 15 |
| Radon CC | > 10 |
| Cognitive complexity | > 15 |
| Nesting | > 4 |
| Line coverage | < 80% **or** drop vs baseline |
| Branch coverage | < 75% **or** drop vs baseline |
| Mutation (when job exists) | < 70% on selected modules |
| New duplication / new vulture unused import | any |

Counting rules match `reports/CODE_QUALITY_METRICS_2026-09-10.md` so
future audits are comparable. Embedded-JS builders are exempt from the
LOC cap only for the string literal (RULE 16 §1.5).

## 3. Architecture of the gate

```
pre-commit (staged .py)
    → size + radon CC + nesting
CI quality-gate job
    → full radon / cognitive / nesting on production packages
    → pytest --cov --branch vs baseline JSON
    → vulture ≥90%
    → duplication (new groups only)
    → parse quality-override comments
    → post PR comment table
Branch protection
    → require quality-gate
```

Baseline file (to add when implementing CI):
`reports/quality/baseline.json` generated from the audit script, committed
or uploaded as a workflow artifact from `main`.

## 4. Override grammar

```
# quality-override: cc=12 reason=Chrome tab scoring table is 11 independent signals
```

Parser: regex on the `def`/`class` line or the immediately preceding
comment. Reason ≥ 20 chars. Unknown metric tokens fail CI (typo).

## 5. Agent contract

Any agent session that edits production Python must follow
`docs/AGENT_RULES_CODE_QUALITY.md` even if CI is not merged yet.
Self-check: run `radon cc -s` on touched files before claiming done.

## 6. Out of scope for the first CI PR

- Dashboard UI (append-only markdown/JSON is enough).
- Full-tree mutmut.
- Automatic god-class / feature-envy machine (warn + human).
- Adding radon to `requirements.txt`.

## 7. Acceptance (product)

Matches the feature brief:

- CI blocks new functions > 30 LOC, CC > 10, cognitive > 15, nesting > 4
- CI blocks coverage decrease
- Uncovered new functions listed on the PR
- Smell report as PR comment
- Override with justification
- Pre-commit catches size + complexity before push
- Metrics history file for trends

## 8. Implementation order

1. Land RULE 16 docs (this change).
2. Custom checker script under `tools/metrics/` using existing audit
   definitions.
3. Pre-commit hook config.
4. GitHub Actions `quality-gate` + PR comment.
5. Baseline JSON + `--cov-fail-under` / branch check.
6. Optional mutmut job on `stores/label_state` / `backend/tab_matcher`.
