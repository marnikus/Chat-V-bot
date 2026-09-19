# Area A quality follow-up — prioritized results

2026-09-19 · base `c74e14b` · branch `arena/01a0bac1-chat-v-bot`.
Follows [the transfer baseline](AREA_A_TRANSFER_2026-09-19.md); that historical
report is not rewritten. Design and decisions:
[`AREA_A_QUALITY_2026-09-19.md`](../docs/archive/2026-09-19-area-a-quality/AREA_A_QUALITY_2026-09-19.md).

## Completed, highest priority first

1. **Safety contracts:** added 12 tests for unknown/renamed own-nicks, flat
   author evidence, strict defaults, refusal details/order, and non-default
   pending/scroll/tab decoding. Covered the previously unexecuted gate path.
2. **Simpler gate:** normalized comparison identities once instead of inside
   every author iteration, used a set for accepted outbound identities, and
   removed redundant equality from non-empty substring matching. Public
   signatures, original display names, ordering and refusal strings remain.
   A 3,402-judgment differential against the parent gate found no differences.
3. **Reliable quality check:** corrected two stale PersonPageRequest source
   paths to `backend/history_query_request.py`. Kept existence/size assertions
   and all thresholds; no skipped tests or widened ratchets.

## Measured before → after

| Metric | Transfer baseline | This follow-up |
|---|---:|---:|
| Private gate maximum Radon CC | 10 | **8** |
| Private gate line / branch coverage | 98.99% / 96.43% | **100% / 100%** (102 statements, 28 branches) |
| Decoder line / branch coverage | 100% / 100% | **100% / 100%** (70 statements, 10 branches) |
| Gate mutation | 183/200 = 91.50%; 17 survivors | **191/195 = 97.95%; 4 survivors** |
| Decoder mutation | 148/153 = 96.73%; 5 survivors | **153/153 = 100%; 0 survivors** |
| RULE 16 wrapper | 21 pass, 2 fail | **23 pass** |
| Full Python suite | 3,347 pass, 72 fail | **3,361 pass, 70 fail** |
| Overall line / branch coverage | 92.937% / 88.463% | **92.944% / 88.488%** |

Targeted backend/private-gate/delta/CDP suite: **436 passed**, 1 xfailed,
1,641 subtests passed. Full run additionally reports 2 skipped, 1 deselected,
1 xfailed, 2,559 subtests passed. The only removed failure identifiers are the
two repaired RULE 16 assertions; **zero new failures**. Frozen API checks pass.
Existing measuring command with clone scan: zero breaches, zero skipped tools.
Real agent: golden 8/8, history-agent 43/43, private-scope 15/15.

### Verification commands

```bash
export QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs
.venv/bin/python -m pytest tests/unit/backend tests/test_private_gate.py \
  tests/test_chat_parser_delta.py tests/test_cdp_events.py -q
.venv/bin/python tests/test_rule16_new_code.py
.venv/bin/python tools/metrics/rule16_gate.py --with-clones --json
.venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
.venv/bin/python -m coverage json -o /tmp/area-a-quality-coverage.json
node tests/test_chat_agent_golden.js
node tests/test_history_agent_js.js
node tests/test_private_scope_js.js
```

Mutation uses the **same three test selections and scratch-copy configuration**
as the transfer report, with the expanded test files, mutmut 3.7.0 and four
workers. Both clean-test and forced-fail checks completed. Both commands exited
0. All generated mutants were reachable; no timeouts, invalid/error, suspicious,
skipped or unreachable outcomes reported. The gate's denominator changed
because its code changed, not because survivors were excluded. Class-level
configuration/symbol metadata is not necessarily mutated by the tool; scores
are scoped evidence, not proof of correctness or whole-project scores.

## Remaining findings, sorted by priority

| Priority | Finding | Next action |
|---|---|---|
| **P1 — release confidence** | 70 existing Python failures remain, including bridge/store contracts and stale structural expectations; no new ones from this pass | Triage by root cause before repairs; do not simply refresh frozen snapshots |
| **P1 — release confidence** | Observed global coverage remains below the historical 93.16% / 88.85% floor | Recover missing coverage and resolve baseline/suite drift; keep floors unchanged |
| **P2 — safety evidence** | Four private-gate mutants survive | Inspect and pin distinguishing domain inputs, or document proof of equivalence; keep all four in the denominator meanwhile |
| **P2 — execution infrastructure** | Canary workflow is still an inactive template; prior run had 14 failing UI harness files | Activate with appropriate workflow permissions and fix harness loading separately; this pass reran only the three relevant agent suites |
| **P3 — remaining audit scope** | Typed sync/scroll consumers, live DOM/CDP capture, other Area A mutation scopes and shim retirement remain | Continue the reviewed Area A roadmap without changing unrelated areas or removing compatibility prematurely |

Current mutation survivor queue (IDs belong to **this** source revision):

```text
backend.private_gate.x__split_authors__mutmut_5
backend.private_gate.x__foreign_authors__mutmut_15
backend.private_gate.x_judge_private__mutmut_1
backend.private_gate.x__strangers_verdict__mutmut_25
```

No live Chrome, real WebEngine, active CI or all-green repository claim is made.
