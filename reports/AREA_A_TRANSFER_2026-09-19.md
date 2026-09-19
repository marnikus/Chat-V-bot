# Area A transfer — local verification, 2026-09-19

Base: `7aeafd4`, branch `arena/01a0bac1-chat-v-bot`. Scope: supplied Area A
implementation merged with the existing Round I transport seam.
Design: `docs/archive/2026-09-19-area-a-integration/AREA_A_TRANSFER_2026-09-19.md`.

## Test and quality results

| Check | Observed result |
|---|---|
| Pre-transfer backend/private-gate/delta/CDP selection | 352 passed, 1 xfailed, 55 subtests passed |
| Same selection after transfer, including new backend tests | **424 passed, 1 xfailed, 1,637 subtests passed** |
| Full Python suite (real WebEngine test deselected) | **3,347 passed, 72 failed, 2 skipped, 1 deselected, 1 xfailed, 2,555 subtests passed** |
| Baseline failure comparison | Exact same 72 failure identifiers as Round I's run, previously reproduced with original production code; zero new or resolved failures |
| Frozen backend API / block snapshot | All nine tests pass; snapshot files unchanged |
| Node harness | 22 of 36 files pass; the same 14 UI harness failures as before (missing helper globals). New golden test passes |
| Real agent checks | Golden 8/8; existing history-agent 43/43 and private-scope 15/15 |
| Valid gate differential | 5,760 old/new judgments, zero differences in all result fields |
| Malformed list sample | 12 intentional changes to explicit refusal, including four old exceptions; not advertised as behavior-preserving for malformed input |
| RULE 16 measuring command, including clone scan | **No breaches, no missing tools**, with all new functions registered |
| RULE 16 test wrapper | 21 pass, 2 pre-existing stale PersonPageRequest-location assertions fail (not changed in Area A) |

Commands (headless Qt stubs built via the repository's builder):

```bash
export QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs
.venv/bin/python -m pytest tests/unit/backend tests/test_private_gate.py \
  tests/test_chat_parser_delta.py tests/test_cdp_events.py -q
.venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
.venv/bin/python -m coverage json -o /tmp/area-a-coverage.json
.venv/bin/python tools/metrics/rule16_gate.py --with-clones --json
.venv/bin/python tests/test_rule16_new_code.py
for f in tests/test_*.js; do node "$f"; done
```

## Coverage (failed full run, not a promoted baseline)

Overall: **16,698/17,967 statements = 92.94%**;
**3,535/3,996 branches = 88.46%**. This improves the previous local checkout
observation (92.85% / 88.38%), but remains below the different historical
RULE 16 baseline (93.16% / 88.85%). Do not claim global acceptance or lower
those floors. The pre-existing suite failures remain release-gate work.

| Added implementation | Statement | Branch |
|---|---:|---:|
| cdp_transport | 47/47 (100%) | 2/2 (100%) |
| private_gate | 98/99 (98.99%) | 27/28 (96.43%) |
| probe_results | 70/70 (100%) | 10/10 (100%) |
| selectors | 25/25 (100%) | 2/2 (100%) |
| legacy_shims | 10/10 (100%) | 4/4 (100%) |
| cdp_ports compatibility adapter | 10/10 (100%) | no branches |

Protocol ellipsis bodies are excluded by coverage's normal protocol handling;
every new concrete function is executed. Runtime adapter policy is tested with
library doubles **at** the network boundary; higher layers use injected wires.

## Size/complexity

Existing RULE 16 walker + Radon 6.0.1 / cognitive-complexity 1.3.0.
No thresholds or existing overrides changed. New leaves intentionally remain
below the preferred 150-line band when they have one small responsibility.

| Added file | Lines | Max function LOC | Max CC (Radon) | Max cognitive |
|---|---:|---:|---:|---:|
| cdp_transport.py | 101 | 7 | 3 | 1 |
| probe_results.py | 138 | 19 | 6 | 2 |
| private_gate.py | 203 | 28 | 10 | 4 |
| selectors.py | 70 | 9 | 3 | 2 |
| legacy_shims.py | 35 | 9 | 3 | 2 |

New functions have ≤4 non-self/cls parameters; new classes fit ≤150 LOC and
≤15 methods; nesting passes the existing gate. Legacy `mouse_wheel` and
`settle_after_top` are not worsened. Exact-AST clone scan reports no new groups.

## Scoped mutation baseline

Mutmut **3.7.0**, four workers, one source module per independent run in a
scratch copy (the repository's `setup.cfg` and old jobs were not overwritten).
Clean tests and mutmut's forced-fail validation both completed before scoring.
No timeouts, invalid/error, suspicious, skipped or unreachable mutants were
reported in either run. Killed/(killed+survived) is the score here; no survivor
is dismissed as equivalent, and this is not a score for all of Area A.

| Module | Generated/reachable | Killed | Survived | Score |
|---|---:|---:|---:|---:|
| backend/private_gate.py | 200 | 183 | 17 | **91.50%** |
| backend/probe_results.py | 153 | 148 | 5 | **96.73%** |

To reproduce, copy the source packages and tests to a scratch directory, use
the same virtualenv, and create this `setup.cfg` there (run each source alone,
removing only that scratch directory's `mutants/` between runs):

```ini
[mutmut]
source_paths=backend/private_gate.py
also_copy=
    backend
    stores
    core
    actions
    services
    bridge
    app
    tools
    ui
    main.py
pytest_add_cli_args=
    --noconftest
pytest_add_cli_args_test_selection=
    tests/unit/backend/test_private_gate_truth_table.py
    tests/unit/backend/test_probe_results.py
    tests/test_private_gate.py::TestVerifyPrivate
```

Use `python -m mutmut run --max-children 4` then
`python -m mutmut results --all True`. Repeat with
`source_paths=backend/probe_results.py`. `--noconftest` avoids unrelated Qt
fixture initialization; all selected tests still execute real production code.
Mutation of selectors, transport/commands, remaining parser families and a
continuous mutation ratchet remain follow-ups, not implied by these scores.

### Survivors (retained work queue, not counted as killed)

**private_gate**

```text
backend.private_gate.x__is_self_chat__mutmut_9: survived
backend.private_gate.x__split_authors__mutmut_7: survived
backend.private_gate.x__split_authors__mutmut_8: survived
backend.private_gate.x__split_authors__mutmut_9: survived
backend.private_gate.x__foreign_authors__mutmut_7: survived
backend.private_gate.x__foreign_authors__mutmut_13: survived
backend.private_gate.x__foreign_authors__mutmut_15: survived
backend.private_gate.x__foreign_authors__mutmut_16: survived
backend.private_gate.x__foreign_authors__mutmut_18: survived
backend.private_gate.x__foreign_authors__mutmut_19: survived
backend.private_gate.x__foreign_authors__mutmut_20: survived
backend.private_gate.x__foreign_authors__mutmut_21: survived
backend.private_gate.x_judge_private__mutmut_1: survived
backend.private_gate.x__strangers_verdict__mutmut_25: survived
backend.private_gate.x__strangers_verdict__mutmut_36: survived
backend.private_gate.x__strangers_verdict__mutmut_42: survived
backend.private_gate.x__strangers_verdict__mutmut_43: survived
```

**probe_results**

```text
backend.probe_results.x_decode_tab_state__mutmut_27: survived
backend.probe_results.x_decode_tab_state__mutmut_75: survived
backend.probe_results.x_decode_tab_state__mutmut_76: survived
backend.probe_results.x_decode_tab_state__mutmut_77: survived
backend.probe_results.x_decode_tab_state__mutmut_78: survived
```

## Infrastructure and scope limits

`tools/ci/quality-gate.yml` includes a dedicated registry/decoder/golden canary
job. This repository's workflow file is a **staged template**, not active under
`.github/workflows`; activation remains an owner/permissions follow-up.
No live Chrome validation, fresh site captures or Qt WebEngine run is claimed.
Shim exports remain; only deprecation and importer prevention are implemented.
