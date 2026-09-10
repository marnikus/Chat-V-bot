# Code quality rules

Companion to `AGENT_RULES.md` (RULES 1–15, which are about *behaviour*). The
rule here is about *shape*: how big a unit of code is allowed to be, and how
much a reader has to hold in their head at once.

## RULE 16 — a function must stay small enough to read in one sitting

A reviewer who cannot hold a function in their head at once cannot review it.
They skim, they approve, and the bug ships. So size is not a matter of taste:

| Limit | Applies to |
|---|---|
| 30 physical lines | a function or method (AST span, so a long docstring counts) |
| 300 lines | a class |
| 4 parameters | excluding `self` / `cls`; `*args` and `**kwargs` count as one each |
| 15 methods | a class |
| cyclomatic complexity 10 | radon counting rules |
| cognitive complexity 15 | SonarSource counting rules |
| nesting depth 4 | `elif` counts as a nested `if`; siblings do not add |

Plus, for code you add or change:

| Limit | Measured by |
|---|---|
| line coverage ≥ 80%, and must not drop | `pytest --cov` |
| branch coverage ≥ 75%, and must not drop | `pytest --cov --cov-branch` |
| mutation score ≥ 70% | `mutmut` |
| test-to-code ratio ≈ 1:1 | lines of test per line of new production code |
| zero new duplicated blocks | `pylint --enable=R0801` |
| zero dead code, zero unused imports | `vulture`, `pylint W0611/W0612` |

### The rule is about new code, not about the past

Measured across `core/ actions/ backend/ bridge/ services/ stores/ app/`:

```
functions: 1540 total, 152 already over a limit (10%)
classes  :  181 total,  27 already over a limit (15%)

worst classes by size
  504 LOC  36 methods  backend/scroll_parser.py::ScrollParser
  503 LOC  36 methods  services/collector_service.py::Collector
  486 LOC  45 methods  bridge/history_bridge.py::HistoryBridge
  444 LOC  28 methods  services/undo_service.py::UndoService
  368 LOC  18 methods  stores/history_repo_lifecycle.py::PersonLifecycle
```

Retro-fitting 179 violations in one change would produce a diff nobody could
review — which defeats the point of the rule. So:

1. **Code you add must fit.** No exceptions without an override (§ below).
2. **Code you touch must not get worse.** If a function was already 47 lines,
   your change may not make it 48. Shrinking it is always welcome.
3. **Oversized classes you did not create get a ratchet, not a rewrite.**
   Record their current size and fail the build if it grows. Splitting them is
   its own change, with its own design doc — and sometimes it is blocked by a
   stronger contract (see the worked example).

A ratchet is not a compromise; it is what stops debt compounding while nobody
is looking.

### Worked example: `docs/RULE16_SIZE_COMPLEXITY_FIT_2026-09-10.md`

The sortable-columns feature inherited a `list_persons` that was 46 lines,
6 parameters, cyclomatic 14 — all three already over. Six options the UI sends
as one JSON blob travelled as six parameters; collapsing them into one frozen
`PersonPageRequest` that owns the `WHERE` and `ORDER BY` fragments brought it
to 25 / 1 / 3.

`HistoryQuery` (340 LOC) and `HistoryBridge` (486 LOC, 45 methods) stayed over,
because splitting them is blocked by two *other* frozen contracts: the AREA D
API snapshot fails on removed `HistoryQuery` methods, and
`tests/test_bridge_router.js` pins `HistoryBridge`'s slot set. They shrank
instead, and the ratchet pins the numbers.

The same ratchet earned its place immediately: the first cut of that refactor
extracted a helper as a *method*, taking `HistoryQuery` from 14 methods to 15.
The gate failed the suite, and the helper became a module function.

### Overrides

A limit that can never be bent gets bypassed silently, which is worse than a
limit with a visible escape hatch. To exceed one, add an entry to `OVERRIDES`
in `tools/metrics/rule16_gate.py` — the same module that holds the limits and
the policy tables, so the exemption sits next to the rule it exempts:

```python
OVERRIDES = {
    ("bridge/history_bridge.py", "HistoryBridge", "userdb_page"): (
        "QWebChannel slot; the signature is fixed by the JS caller."),
}
```

Three rules make this safe, all enforced by `tests/test_rule16_new_code.py`:

* **It must name a gated function.** An override for something not in `OWNED`
  gates nothing and is reported.
* **A justification is mandatory** — the value is prose a reviewer reads, not
  a `# noqa`. Under 40 characters, or starting with `TODO`/`noqa`/`FIXME`,
  fails the build.
* **An override that stops being needed fails the build.** If the code later
  fits inside the limits, the stale entry is reported so it gets deleted.
  Otherwise the escape hatch becomes a dumping ground.

`OVERRIDES` is empty today: nothing this feature owns needs one.

### Enforcement

The gate is a test, not a document:

```bash
pytest tests/test_rule16_new_code.py          # the limits, executable
python3 tools/metrics/rule16_gate.py          # human-readable report
mutmut run --max-children 8                   # mutation score (setup.cfg)
```

`tools/metrics/rule16_gate.py` is the single implementation the pre-commit hook
calls. Dev dependencies: `pip install -r requirements-dev.txt`. The gate
**skips loudly** when a tool is missing rather than pretending to pass.

**Enforcement status — one of the three layers is not live.** A CI workflow is
written at `tools/ci/quality-gate.yml` but could not be installed: the push was
refused because a GitHub App token cannot author files under
`.github/workflows/` without `workflows` permission. Someone with that
permission must `cp tools/ci/quality-gate.yml .github/workflows/quality-gate.yml`
to activate it. Until then the hook is the only layer, and `git commit
--no-verify` bypasses it. The PR bot comment and merge block from the proposal
need repo/org settings for the same reason. Full account in
`docs/RULE16_SIZE_COMPLEXITY_FIT_2026-09-10.md` §9.4.

### What the tools cannot see — do not over-trust a green gate

* **`mutmut` 3.7.0 does not mutate `@dataclass` methods.** In the worked
  example, `PersonPageRequest` — 97 lines, the bulk of the new logic — produced
  *zero* mutants. A 100% mutation score there covered the two plain functions
  only. Verify with `mutmut results --all True` that your new code actually
  generated mutants before citing the number.
* **Coverage says a line ran, not that anything checked it.** In the same
  change, `_person_item` had 100% line coverage and survived 52 of 65 mutants:
  renaming a payload key the UI renders broke no test. Mutation testing found
  it; coverage never could.
* **Narrowing a mutation suite cannot inflate the score** — mutants no test can
  reach are reported `no tests` and excluded, so a narrow suite only shrinks
  what is measured. But it does mean the number applies to less than the file.
