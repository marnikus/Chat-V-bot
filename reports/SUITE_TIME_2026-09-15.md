# Suite time — closure report 2026-09-15

Final measurements and acceptance status of the test-time-reduction program
(`docs/archive/2026-09-15-test-time-reduction/TEST_TIME_REDUCTION_PLAN_2026-09-15.md`;
day-one baseline numbers: `SUITE_BASELINE_2026-09-15.md` in the same folder).
Every number here was measured on this machine (2 cores usable), same protocol
as the baseline; group trees changed shape twice (W1 markers, W4.4 moves) —
the per-stage table states the tree each number belongs to.

## Headline closure

| Lane | Baseline (day one) | Final (this commit) |
|---|---:|---:|
| Full suite serial | 525 s* | **230.1 s** (3202 p, 902 subtests) |
| Full suite `-n 2 --dist loadfile` | 367 s (no xdist yet; serial) | **110.4 s** |
| Coverage gate (floors 90.44/84.38) | 519 s serial coverage run | **208.3 s** on the parallel path (91.77 % line / 88.05 % branch) |
| `tests/unit` group | 55.2 s (old tree) | 62.3 s (**larger** tree — see W2 row below) |
| JS harness suites | manual ritual, 29 files | inside pytest: 29 items, ≈2.7 s worst |

*525 s was the local serial run measured the same morning the baseline was
written; the archived appendix quotes it per group.

## Per-step acceptance (measured, §9 protocol)

| Step | What landed | Evidence | Status |
|---|---|---|---|
| W1 parallel + lanes | xdist, markers, path hook, `-m "not webengine"` policy | serial → parallel 162.8 s measured mid-program | ✅ |
| W2 wait tax (hot files) | `tests/unit/services/test_world_events.py` 15.4 → 1.1 s; collector/bridge/engine dials | group tables archived | ✅ |
| W2 remainder | run-safety fixed waits → event-driven | cleanup contract 3.1 → 0.13 s | ✅ |
| W3.1 template-world | **replaced by the wait-tax fix** (`_fast_clock.py` settle dials): write-gate 41.5 → 7.6 s, exceeding the ≤15 s exit with no fixture machinery | 8 tick families, ≈94 s removed | ✅ (different mechanism) |
| W3.2 node batching | `js_harness.js` accepts `{payloads: [...]}` (fresh DOM/effects per payload, isolation pinned by a test); the 3 node-spawning pytest files register payloads and run ONE spawn per file: spawns 36 → 3, trio 10.18 → 1.86 s | exit was "≈7 spawns" | ✅ |
| W3.3 e2e knobs | **withdrawn with evidence**: e2e pair 6.53 s; the only knob candidate pays ≈1 s and would change the contract under test (25-row-per-pass drain limit) | `--durations` tail listed | ⛔ (documented) |
| W4.1 JS into pytest | `tests/test_node_harness_suites.py`, `node` marker, skipif-guarded | 29/29 in 10.3 s serial | ✅ |
| W4.2 parallel coverage | adopted after verify (91.77/88.05 ≥ serial 91.77/88.03) | AGENT_RULES §16.3 command updated | ✅ |
| W4.3 CI lanes | fast + slow lanes with `--durations=25` (owner activation still pending) | `tools/ci/quality-gate.yml` | ✅ (config) |
| W4.4 classification | 82 root files: 47 → `tests/unit/`, 33 → `tests/integration/`; pyramid now 61.8 % unit | collect counts unchanged (3205 items) | ✅ |
| W4.5 hygiene | `tests/repro_bug2.py` → `tools/`; rig verified end-to-end | exit 0 run | ✅ |

## Durations tail (final serial run, top non-metrics)

`test_rule16_new_code.py::...clone baseline` 22.9 s is the metrics lane by
design. The next peaks: `test_chat_parser_delta` scroll-retry 4.3 s (real
wall-clock contract), `test_db_manager` undo-step 3.4 s, node wrapper
`history_agent_js` 2.7 s, `test_world_write_gate` refused-undo 2.0 s — all
real work, no idle waits found by the census.

## Budgets from §9.4 — informational status

- Fast lane ≤ 90 s on 2 cores: **110.4 s** today; the 4-core CI runner
  projection (plan §6) is 60–90 s — visible once CI is activated.
- `tests/unit` ≤ 20 s: the criterion predates W4.4 — the group absorbed 47
  root files (1945 vs 705 tests); the W2-era tree it measured is a subset and
  is itself ≤12 s (inner loop preserved).
- No new `slow`-free test may add >50 ms of real sleeps: policy text lives in
  `requirements-dev.txt` (W2.1); enforcement ratchet left informational —
  grep-level guard not yet built (noted, not shipped).

## Remaining tails (honest)

- `test_rule16_new_code.py` ≈ 26 s when the toolchain is present (metrics lane,
  excluded from the fast lane); clone scan dominates.
- `tests/test_node_harness_suites.py` runs 29 node processes (~8–10 s worst
  case serial; parallelised by xdist) — batching these further is possible but
  the suites double as the per-file attribution layer, so this is deliberate.
- One transient failure observed once during W4 verification
  (`test_services_people` queue-fallback assertion): unreproducible in six
  subsequent attempts incl. two clean full serials; watch, don't hide.
