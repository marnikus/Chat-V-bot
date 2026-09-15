# Suite time — closure report 2026-09-15 (refreshed end of day)

Final measurements and acceptance status of the test-time-reduction program
(`docs/archive/2026-09-15-test-time-reduction/TEST_TIME_REDUCTION_PLAN_2026-09-15.md`;
day-one baseline: `SUITE_BASELINE_2026-09-15.md`, same folder). Every number
measured on this machine (2 cores usable), same protocol as the baseline.
This document was refreshed after the last wave of the day (W3.3 retry,
ratchets, `-n 4` lanes) so nothing below is stale at merge time.

## Headline closure

| Lane | Baseline (day one) | Final (this commit) |
|---|---:|---:|
| Full suite serial | 525 s* | **214.6 s** |
| Full suite parallel | 367 s (serial then; no xdist) | **73.8 s** (`-n 4 --dist loadfile`) |
| Coverage gate (floors 90.44/84.38) | 519 s serial coverage run | **131.7 s** on the parallel path (91.77 % line / 88.05 % branch) |
| `tests/unit` group | 55.2 s (old tree) | 62.3 s (**larger** tree — see W4.4 row) |
| JS harness suites | manual ritual, 29 files | inside pytest: 29 items (~2.7 s each worst) + coverage-gated |
| Suite total | 3,168 tests | 3,206 tests + 903 subtests, 2 skipped, 1 xfailed |

*525 s was the local serial run measured the same morning the baseline was
written; the archived appendix quotes it per group.

## Per-step acceptance (measured, §9 protocol)

| Step | What landed | Evidence | Status |
|---|---|---|---|
| W1 parallel + lanes | xdist, markers, path hook, `-m "not webengine"` policy | serial → parallel 162.8 s measured mid-program | ✅ |
| W2 wait tax (hot files) | `tests/unit/services/test_world_events.py` 15.4 → 1.1 s; collector/bridge/engine dials | group tables archived | ✅ |
| W2 remainder | run-safety fixed waits → event-driven | cleanup contract 3.1 → 0.13 s | ✅ |
| W3.1 template-world | **replaced by the wait-tax fix** (`_fast_clock.py` settle dials): write-gate 41.5 → 7.6 s, exceeding the ≤15 s exit with no fixture machinery | 8 tick families, ≈94 s removed | ✅ (different mechanism) |
| W3.2 node batching | `js_harness.js` `{payloads: [...]}` mode (fresh DOM/effects per payload, isolation pinned); 3 pytest files register payloads once per module: spawns 36 → 3, trio 10.18 → 1.86 s | exit was "≈7 spawns" | ✅ |
| W3.3 e2e knobs | **retried & landed test-side**: profiler attribution showed 2.7 s of settle polls reaching `chat_sync_session` via `prepare_backfill`; adopting `fast_settle()` in the two `*_e2e` case classes took the pair 6.53 → 4.81 s; the rest is genuine end-to-end work | sleep-trace before/after | ✅ (dial, not production knob) |
| W4.1 JS into pytest | `tests/test_node_harness_suites.py`, `node` marker, skipif-guarded | 29/29 | ✅ |
| W4.2 parallel coverage | adopted after verify (91.77/88.05 ≥ serial 91.77/88.03) | AGENT_RULES §16.3 command updated | ✅ |
| W4.3 CI lanes | fast + slow lanes with `--durations=25` (owner activation still pending) | `tools/ci/quality-gate.yml` | ✅ (config) |
| W4.4 classification | 82 root files: 47 → `tests/unit/`, 33 → `tests/integration/`; pyramid 61.8 % unit | collect counts unchanged | ✅ |
| W4.5 hygiene | `tests/repro_bug2.py` → `tools/`; rig verified end-to-end | exit 0 run | ✅ |
| Post-closure | `tests/test_wait_budget.py` + baseline (25 pins) — the W2.1 50 ms policy now enforced; `tests/test_js_coverage.py` + per-file pins (30 floors, global 82.7) — the AREA D JS-coverage follow-up as a metrics-lane ratchet; `-n 4` adopted everywhere (74 s all-green on 2 cores, coverage-identical; `worksteal` tried: 73.7 s, tie — `loadfile` kept for attributable durations); `test_services_people` transient pinned by intent assertion | this table | ✅ |

## Durations tail (final serial run, top non-metrics)

`test_rule16_new_code.py::...clone baseline` ~23 s is the metrics lane by
design. The next peaks: `test_chat_parser_delta` scroll-retry ~4.3 s,
`db_manager` undo-step ~3.4 s, node wrapper `history_agent_js` ~2.7 s,
`world_write_gate` refused-undo ~2.0 s — all real work, no idle waits found.

## Budgets from §9.4 — informational status

- Fast lane ≤ 90 s on 2 cores: **MET — 73.8 s** (`-n 4 --dist loadfile`).
- `tests/unit` ≤ 20 s: the criterion predates W4.4 — the group absorbed 47
  root files (1945 vs 705 tests); the W2-era tree inside it still measures
  ≤ 12 s.
- No new `slow`-free test may add >50 ms of real sleeps: **enforced** by
  `tests/test_wait_budget.py` (metrics lane) — new violations fail, stale
  pins fail, `# wait-budget:` reasons exempt.

## Remaining tails (honest)

- `test_rule16_new_code.py` ≈ 23–26 s with the toolchain present (metrics
  lane, excluded from the fast lane); clone scan dominates.
- The node wrapper runs 29 node processes (~8–10 s worst-case serial) —
  kept: the suites double as the per-file attribution layer (deliberate).
- `test_services_people` one-time transient: unreproduced in nine total
  attempts; the test now pins its stated rank contract, so a recurrence
  will name the exact mechanism it broke.
- e2e pair sits at 4.81 s of real lifecycle work (below it is only the
  wall-clock contracts RULE 8 protects).
