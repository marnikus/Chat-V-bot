# Test-integration principles redesign — design + plan (2026-09-15)

Triggered by the instruction: *redesign the documented principles of how tests
should be integrated, on top of the new test architecture the 2026-09-15
test-time program landed.* Method, in order: research → this plan → implement.

## 1. Research findings — the architecture that exists today (verified 2026-09-15)

| Mechanism | Where it lives | Contract it enforces |
|---|---|---|
| Marker lanes | `pytest.ini` (`markers`, `addopts`) | fast lane = `not slow and not e2e and not metrics`; webengine opt-in only |
| Auto-marking at collection | `tests/conftest.py` `pytest_itemcollected` | `unit/` + `integration/` by directory; `*_e2e.py` → `e2e`+`slow`; the RULE 16 gate → `metrics` |
| Wait budget | `tests/test_wait_budget.py` + `tests/wait_budget_baseline.txt` (25 pins) | ≤ 50 ms real sleep per test, else `slow` + a `# wait-budget:` reason; **no NEW** over-budget sleep may be pinned |
| JS coverage ratchet | `tests/test_js_coverage.py` + `tests/js_coverage_baseline.json` (30 per-file pins, global 82.7), tool `tools/metrics/js_coverage.py` | per-file floors and the global floor may only improve; JS suite failures surface |
| Fast-settle dial | `tests/_fast_clock.py` | patches `backend.chat_sync_session.SettleSpec` at the construction site — the real `SettleSpec` and the real settle loop still run |
| Node suites as pytest items | `tests/test_node_harness_suites.py` (glob `tests/test_*.js`, 29 suites, `node` mark) | a JS suite fails inside pytest, parallelised by xdist; no manual registration |
| Coverage floors | RULE 16 §16.3, measured at `-n 4`: line 91.77 / branch 88.05 | ≥ 80% / ≥ 75% overall and never below the recorded baseline |
| Pre-commit | `.pre-commit-config.yaml` (`rule16_gate.py`, `stores_modules.py`) | the size/complexity/smell gate runs before a commit lands |
| CI (inactive) | `tools/ci/quality-gate.yml` (fast lane job + slow/e2e/metrics job + RULE 16 job) | owner-blocked: GitHub App token lacks `workflows` permission (refused twice, dated in the file header) |

Measured envelope (closure: `reports/SUITE_TIME_2026-09-15.md`): serial
3206 p / 227.7 s; parallel `-n 4 --dist loadfile` 3206 p / 73.8 s (fast-lane
target ≤ 90 s MET); coverage gate 131.7 s at `-n 4`.

## 2. Diagnosis — where the doctrine is stale

1. **RULE 8 is five lines** written for the 2026-09-09 harness era. It states
   the root principle (real thing, deletion test) but nothing a contributor can
   act on about *where a new test lands*, its *time budget*, or the *ratchets*
   it must not lower.
2. **SOR §7 leads with the serial command**; lanes live in one comment line.
   The baselines, the fast-settle dial and the node wrapper have no row.
3. **SOR §8 contradicts its own header** on coverage (91.83/87.02 vs 91.77/88.05).
4. `tests/conftest.py`'s auto-marking comment still speaks of the W4.4
   classification as future work — it shipped (491fae2).
5. `pytest.ini`'s parallel-lane comment says `-n auto`; the adopted, measured
   form is `-n 4` (§16.3 coverage command, closure report).
6. Five live files point at `docs/AGENT_RULES_CODE_QUALITY.md` — archived since
   2026-09-10; the live doc is `docs/current/AGENT_RULES.md`.
7. Both doc indices call `2026-09-15-test-time-reduction/` "plan only" — it
   was executed and measured.

## 3. The redesigned principles (the normative text that will land)

- **P1 (unchanged root).** Tests execute the real thing; a test that would
  pass with the feature deleted is not a test.
- **P2 Lane by location and name.** Per-module contract → `tests/unit/`;
  cross-module contract → `tests/integration/`; real DB lifecycle →
  `tests/*_e2e.py`; executable gates (size, budgets, floors) carry `metrics`
  and stay out of the fast lane. Location and filename are the registration —
  nothing else to edit.
- **P3 Time budget.** ≤ 50 ms of real sleep per test. Beyond is a contract,
  not convenience: `slow` mark + `# wait-budget:` reason. The ratchet fails
  on any NEW over-budget sleep.
- **P4 Speed comes from dials, not mocks.** Shorten a real settle loop via
  `tests/_fast_clock.py` (dials `SettleSpec` at its construction site; the
  loop still runs). Mocking the loop away is not a dial — it deletes the test.
- **P5 Ratchet baselines only improve.** `wait_budget_baseline.txt` and
  `js_coverage_baseline.json` regenerate only after the drift is reviewed and
  named in the commit. Pinning a regression is withdrawn work.
- **P6 A new JS suite needs no registration.** Drop `tests/test_*.js` — the
  node wrapper collects it; refresh the JS-coverage pins in the same change.
  A UI file with no suite stays pinned at 0.0 until it gets one.
- **P7 Coverage floors stay RULE 16 §16.3** (≥ 80/75, never below baseline);
  the measured form is the parallel `-n 4` command.

## 4. Implementation plan — edits and the line ledger

RULE 18 §18.4: `AGENT_RULES.md` (730 lines) and `SYSTEM_OF_RECORD.md` (343)
are at their ceiling — every addition here is paid by an extraction in the
same change. RULE 17: no new current doc; the norm lives in RULE 8 + SOR §7,
this doc carries the inventory and reasoning.

| File | Edit | Ledger |
|---|---|---|
| `docs/current/AGENT_RULES.md` | Extend RULE 8 with the P1–P6 doctrine (lane placement, 50 ms budget, dials-not-mocks, ratchets-only-improve, JS auto-collection) | +24 |
| same | Fold §16.0's JS-string-builder table row into §16.1.5 (the block that owns the exception) | −3 |
| same | §16.5: drop the re-stated audit counts (owned by the linked baseline snapshot) | −2 |
| same | §16.8: compress the "not required of one session" list | −2 |
| same | §16.0 post-table: fold the sentence duplicating RULE 8's root line | −1 |
| same | §16.3: drop the js_harness clause (moved into RULE 8), tighten the branch-% note and the stubs note | −3 |
| same | §16.7: two two-line checklist items to one line each | −2 |
| same | §16.1.1/§16.4/§16.6 wrap-tightening (no norm change) | −3 |
| same | balancing knob: RULE 8's own bullet wraps (prose expand/shrink) | rest |
| `docs/current/SYSTEM_OF_RECORD.md` | §7 rewrite: lane commands (parallel + fast + tail + node + webengine), baselines and dials named, stubs note kept | 0 internal |
| same | §8 coverage row → 91.77/88.05 (match header) | 0 |
| same | §9 add this design as newest row; pay by merging the two overlapping `tests/unit/` table rows in §7 | 0 |
| `pytest.ini` | parallel comment: `-n auto` → `-n 4` (two spots) | 0 |
| `tests/conftest.py` | auto-marking comment: W4.4-future → lane-machinery truth | 0 |
| `.pre-commit-config.yaml`, `tools/ci/quality-gate.yml`, `tools/metrics/rule16_gate.py`, `tests/test_rule16_new_code.py` | pointer `docs/AGENT_RULES_CODE_QUALITY.md` → `docs/current/AGENT_RULES.md` (RULE 16; origin archived) | comment-only |
| `docs/README.md` | archived count +1, new folder bullet, "plan only" → executed | +1 |
| `docs/archive/README.md` | index row + section for this folder; fix the "plan only" row | +6 |

## 5. Verification (§16.6 gates)

`wc -l` invariants (730 / 343); `tools/metrics/rule16_gate.py` exit 0; full
collection still 3209/3210 with no errors; the metrics lane itself green;
`grep` shows no stale pointer outside `docs/archive/` and caches. Then one
commit for doctrine + map + pointers, pushed.

## 6. Rejected alternatives

- **New RULE 20.** Rule numbers are referenced across tests, docs and CI;
  a tail-rule costs the same lines as extending RULE 8 but fragments the one
  place a reader looks for "how do I add a test".
- **New current doc (e.g. `TESTING.md`).** RULE 17 forbids it, and RULE 18
  §18.4 keeps `docs/current/` at three files deliberately.
- **Editing the archived plan docs** to restate the doctrine. RULE 17: dated
  history is the record of what was believed then; the map is updated instead.
