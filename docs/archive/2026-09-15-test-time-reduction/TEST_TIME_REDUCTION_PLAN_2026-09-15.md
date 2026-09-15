# Test-time reduction plan — redesign of the testing process

**Status: plan only. No production code, test code, config or workflow was
changed to produce this document.** Written 2026-09-15.

Every number quoted as *measured* was produced on that date in a clean sandbox
(2 cores, Python 3.11.2, PySide6 6.11.2, GL stubs from `tools/build_stubs.py`)
running the tree at this commit. Raw run logs, commands and per-file tables:
`docs/archive/2026-09-15-test-time-reduction/SUITE_BASELINE_2026-09-15.md`.

The structure follows the inspiration report (pyramid, fixtures,
parallelisation, CI lanes) but is re-derived from what this repository
actually is today — several inspiration phases are **already done here** and
are listed in §3 so nobody redoes them.

---

## 0. Summary

| What | Measured today | Projection after plan |
|---|---:|---:|
| Full suite, serial (`pytest tests -q`, WebEngine deselected) | **367 s (6:07)** | 130–170 s |
| Same, 2 workers (`-n 2 --dist loadfile`, **zero changes needed**) | **181.5 s (3:01)** | 60–100 s |
| Coverage-gate command (RULE 16 §16.3, serial + branch) | **519 s (8:39)** | ≤ ~240 s |
| `tests/unit` group alone | 55.2 s (CPU only 8.2 s) | ≤ ~15 s |
| CI fast lane (does not exist yet — CI is inactive) | — | ≤ 90 s on 2-core runner |
| Node harness (29 suites, all green, **not wired into pytest/CI**) | 7.7 s | gated in CI |

Three facts drive the whole plan:

1. **The suite is wait-bound, not CPU-bound.** Wall time is ≈ 2.7× CPU time
   overall and ≈ 6× on `tests/unit`. There are 127 `asyncio.sleep` sites in
   tests, plus poll loops that run real multi-second timeouts.
2. **The suite is already parallel-safe.** `pytest -n 2` passes 3,168/3,168
   with no failures today (tmp_path discipline, in-memory DBs, no fixed
   ports). Parallelisation is a config change, not a refactor.
3. **A long tail dominates.** Ten files ≈ 40% of serial time; the single
   slowest item (22.5 s, 6% of the suite) is the RULE 16 clone scan running
   *inside pytest* — work the pre-commit hook and the CI gate job already do.

---

## 1. Baseline (measured 2026-09-15)

| Invocation | Tests | Wall | User CPU | Wall/CPU |
|---|---:|---:|---:|---:|
| Full suite serial, `--deselect tests/test_sash_webengine.py` | 3,168 (+902 subtests) | 367.4 s | 115.6 s | 2.7× |
| — `tests/unit` | 1,049 | 55.2 s | 8.2 s | **6.7×** |
| — `tests/integration` | 603 | 46.5 s | 20.5 s | 2.3× |
| — root-level `tests/test_*.py` | 1,516 | 261.7 s | 85.3 s | 3.1× |
| Coverage-gate command (§16.3 verbatim, serial) | 3,168 | 519.2 s | 266.3 s | 1.9× |
| 29 Node harness suites, sequential spawn | 29 files | 7.7 s | — | — |
| Collection + conftest startup (fixed cost per process) | — | ~0.7–3.3 s | — | — |

Long tail (standalone file timings, serial):

| File | Wall | What makes it slow |
|---|---:|---|
| `tests/test_world_write_gate.py` | 41.5 s | 43 tests × per-test world-file create + migrate + real trash writes |
| `tests/test_rule16_new_code.py` | 23.9 s | one test re-runs the whole-tree AST clone scan (22.5 s) inside pytest |
| `tests/test_recollect_after_clear.py` | 21.0 s | collector ticks + DB lifecycle, real intervals |
| `tests/test_db_manager.py` | 17.7 s | per-test world lifecycle |
| `tests/unit/services/test_world_events.py` | 15.4 s | real-clock poll loops (`wait_for_world_open` with real timeouts up to 15 s) |
| `tests/test_history_bridge.py` | 11.4 s | bridge round-trips over a real world file |
| `tests/test_userdb_sort_bridge.py` | 8.6 s | same pattern |
| `tests/unit/actions/test_block_actions_coverage.py` | 6.4 s | action waits with real durations |
| `tests/test_media_recovery_e2e.py` | 5.5 s | idle-tick drains with real intervals |
| `tests/test_db_switch_e2e.py` | 2.1 s | true end-to-end |

Sleep census: 127 `asyncio.sleep` occurrences across ~35 files (densest:
`test_wait_page_cancellation`, `test_find_click_blocks`, `test_speed_multiplier`,
`test_world_write_gate`, `test_services_run`, `test_stop_contract`,
`test_cleanup_contract`), 7 `time.sleep` (all in the deselected WebEngine
file). Full census: appendix §6.

---

## 2. Where the time goes — the three taxes

1. **Wait tax (largest).** Tests poll and sleep against real clocks: fixed
   `asyncio.sleep(...)` waits that run their full duration, and production
   poll loops driven at production timeouts (a "world that never opens" is
   verified by actually waiting 15 s). This is why wall ≈ 2.7–6.7× CPU and
   why parallelisation alone cannot get below ~100 s on this box.
2. **Lifecycle tax.** World-bound tests create + migrate a real SQLite world
   file per test (~0.5–1.0 s in the write-gate family), and seven pytest
   files spawn a fresh `node tests/js_harness.js` subprocess per probe
   payload (~30–80 ms each).
3. **Duplication tax (smallest, fully fixable by config).** The RULE 16 gate
   is executed up to three times per change: pre-commit hook, the pytest
   suite itself (22.5 s clone scan), and the CI gate job. The docs quote the
   WebEngine deselect in three places. The 29 JS harness suites are run by
   hand only — a *coverage of testing* gap more than a time gap, fixed in W4.

---

## 3. What is already true — do not rebuild

The inspiration report spends phases on things this repository already has.
Skim this table before starting any workstream:

| Inspiration phase | Status here | Evidence |
|---|---|---|
| JS logic tested in Node, not a browser | **Done** | RULE 8 harness: `tests/js_harness.js` + `tests/dom_stub.js`, 29 suites, ~8 s total |
| Reduce WebEngine tests to smoke-only | **Done** | exactly one WebEngine test remains, deselected locally, in CI, and by the §16.3 coverage command |
| Separate transport from logic / fake adapters | **Done** | RULE 8-mandated fake CDP client that behaves like the real page (`tests/unit/*`, `tests/integration/services/test_services_cdp.py`) |
| Dependency-injection seams | **Done** | `core/` container + `tests/unit/core/test_di.py` |
| Worker-safe resources for xdist | **Done (unintentionally)** | 254 `tmp_path` uses, in-memory DB fixtures, no fixed ports — `-n 2` passed 3,168/3,168 measured |
| Scope mutation testing narrowly | **Done** | `setup.cfg` mutmut job ~1 min, reachable-mutant arithmetic in its comments |
| unit/ vs integration/ taxonomy | **Partial** | dirs exist and hold 1,652 tests, but 82 files (1,516 tests, 48%) still sit unclassified at root |
| Markers / lanes / parallelism config | **Gap** | no markers registered, `--strict-markers` is on, no xdist dependency |
| Wait/lifecycle/duplication taxes | **Gap** | §2 |
| CI pipeline | **Gap** | `tools/ci/quality-gate.yml` exists but is **not active** (GitHub refused the `workflows` scope; activation is a manual copy, noted inside the file) |

Consequence: no testability refactor of production code is needed for the big
win. This plan is speed plumbing plus two small production knobs (W2.3, W3.3).

---

## 4. Workstreams

Order is by measured gain per unit of risk. W1–W2 are test-side only;
W2.3/W3.3 touch production minimally (new optional kwargs) and follow the
RULE 16 §16.6 workflow with tests first; W4 wires everything into gates.

### W1 — Parallel execution and marker lanes (S, measured −50 %)

**Changes**

1. `requirements-dev.txt`: add `pytest-xdist` (pin, like the other tools).
2. `pytest.ini`:
   * register markers (required by `--strict-markers`): `unit`,
     `integration`, `e2e`, `slow`, `metrics`, `node`, `webengine`;
   * document the parallel invocations in a comment *above* `addopts`
     (do not bake `-n auto` into `addopts` — keep serial the default for
     debugging; CI and the documented commands opt in).
3. `tests/conftest.py`: add `pytest_collection_modifyitems` that auto-marks
   by path — `tests/unit/`→`unit`, `tests/integration/`→`integration`,
   `test_sash_webengine.py`→`webengine`+`slow`, `*_e2e*`→`e2e`+`slow`,
   `test_rule16_new_code.py`→`metrics`, node-harness wrapper (W4.1)→`node`.
   Manual `@pytest.mark.slow` is then allowed for opt-in cases (W2.1).
4. Replace the three hard-coded `--deselect=tests/test_sash_webengine.py…`
   copies (SYSTEM_OF_RECORD.md §7, AGENT_RULES.md §16.3 command,
   `tools/ci/quality-gate.yml`) with `-m "not webengine"` — one policy.
5. Write down the worker-safety invariants that already hold and must keep
   holding (they are why `-n 2` is green today): per-test state only via
   `tmp_path`; in-memory or `tmp_path` SQLite; no fixed ports; nothing
   written relative to CWD (`logs/`, `saved_media/`) in tests.

**Exit criteria:** `pytest -n auto --dist loadfile -q -m "not webengine"`
green; wall ≤ 3:10 on a 2-core box (measured today: 3:01);
`pytest --markers -q` lists the seven markers; serial invocation unchanged.

**Constraint:** `--dist loadfile`, not `load` — keep per-file module state
coherent and durations attributable; revisit only if a skewed file appears.

### W2 — Kill the wait tax (M, biggest projected gain after W1)

**Policy (new, written in the same change that enforces it):** a test may
spend ≤ 50 ms in real sleeps unless marked `slow` with a one-line
`# wait-budget:` reason. This is a ratchet on *new* tests first.

**Changes**

1. Add one shared condition-poll helper in `tests/` (RULE 8-honest: it runs
   the *real* loop and wakes when the predicate fires, instead of sleeping a
   fixed duration). Replace the fixed-wait sites from the census, densest
   files first (appendix §6). Expected to recover most of the unit group's
   47 idle seconds.
2. Timeout injection, using the pattern the suite already trusts
   (`wait_for_world_open(store, timeout=0.1, step=0.01)` in
   `tests/unit/services/test_world_events.py`): pass short explicit
   timeouts/steps in every test of a timeout/poll path.
3. **Production mini-knobs** where a default is baked in and unreachable
   (e.g. the run-when-world-open grace, media drain tick): add a narrow
   optional kwarg with the production default; no behaviour change. Each such
   change: tests first, radon no worse, RULE 19 order (nesting → CC →
   cognitive → size) if the touched function is a §16.5 landmine.
4. Reuse the existing global speed-multiplier mechanism
   (`docs/archive/2026-09-13-speed-multiplier/`) in test setup for any block
   test still paying real user-facing waits — it already scales exactly those.

**Exit criteria:** `tests/unit` wall ≤ ~20 s and `tests/integration` ≤ ~30 s
serial; zero grep hits for bare `asyncio.sleep(` outside an allow-listed
`slow` test; the 15.4 s `test_world_events` file ≤ ~2 s.

**Forbidden:** mocking the pollers away or asserting on internal call counts
instead of outcomes — the wait behaviour itself is under test (RULE 8). We
shorten *time*, not behaviour.

### W3 — Lifecycle tax: fixtures and subprocesses (M)

**Changes**

1. **Template-world fixture** for the world-bound families (write-gate,
   db_manager, recollect, history bridges): create + migrate *one* world file
   per worker (session scope), then per test `shutil.copy` it into the
   test's `tmp_path` (~ms vs ~0.5–1.0 s create+migrate). Copies keep real
   files on the real code path — RULE 8 and the RULE 14 file model are
   preserved. Per-family rollout, write-gate family first.
2. **Batch the Node harness:** extend `tests/js_harness.js` to also accept a
   JSON list of payloads and return a list of results; the seven pytest files
   that spawn `node` per probe then make one spawn per file. (JS change in
   test tooling, no production Python.)
3. **e2e tick knobs** (with W2.3): idle-drain/tick intervals in the two e2e
   files become injectable; tests use short intervals.

**Exit criteria:** `test_world_write_gate.py` ≤ ~15 s serial (from 41.5);
node subprocess count per pytest run of those files ≈ 7 (from dozens);
e2e pair ≤ ~3 s.

### W4 — Wiring, lanes and guardrails (M)

1. **JS harness into pytest:** one wrapper file (e.g.
   `tests/test_node_harness_suites.py`) that runs each `tests/test_*.js`
   suite as a separate parametrized item via `node`, marked `node`, skipping
   with the existing "node harness unavailable" pattern when `node` is
   absent. Serial cost ≈ 8 s, parallelised by W1. This makes the JS suites a
   *gate* instead of a manual ritual, and unblocks the JS-coverage follow-up
   already planned in `docs/archive/2026-09-14-round-h/AREA_D_VERIFICATION_DESIGN_2026-09-14.md`.
2. **Coverage gate on the parallel path:** switch the §16.3 invocation to
   `pytest -n auto --cov --cov-branch --cov-report=json` (pytest-cov combines
   worker coverage). Verification step, gate it: combined totals must be ≥
   recorded floors (line 90.44 % / branch 84.38 %; measured today
   91.77 / 88.03) and ≥ the serial run of the same commit — if they drift,
   keep the coverage pass serial and only parallelise the non-coverage lanes.
   Then update the §16.3 copy-paste command and snapshot the new baseline in
   `reports/` per convention.
3. **Activate CI and split lanes** (owner action first: copy
   `tools/ci/quality-gate.yml` → `.github/workflows/` — the repo header in
   that file explains the `workflows`-permission refusal). Proposed lanes:
   * Lane 0 (static): RULE 16 gate job, unchanged (~1 min, no Qt needed).
   * Lane 1 (fast, every push): `pytest -n auto -m "not slow and not e2e and not webengine and not metrics"` + `node` suites, target ≤ 90 s on a 2-core runner.
   * Lane 2 (slow, every push but after Lane 1; or scheduled if too hot):
     `-m "slow or e2e or metrics"` serial. WebEngine stays local/hardware-only.
   * Always run with `--durations=25` in CI so the tail stays visible.
4. **Classify the root 82 files** into `unit/` vs `integration/` (most are
   integration by behaviour). Pure location change, batched `git mv`, markers
   follow via the W1.3 path hook. **Same-commit updates:** `setup.cfg`
   `[mutmut]` `pytest_add_cli_args_test_selection` (pins four nodeids) and any
   remaining path references. Target pyramid of Python tests: unit ≥ 60 %,
   integration ~35 %, e2e ≤ 5 % — reclassification is labelling, not
   rewriting, because RULE 8 already forces behaviour-level tests.
5. **Hygiene:** `tests/repro_bug2.py` is not collected (name) and not a test —
   move it under `tools/` next to the other diagnostics.

**Exit criteria:** CI green with two lanes; a JS harness failure fails CI;
`pytest -m unit -q` runs only unit-marked items; mutmut job still green.

---

## 5. Effort vs. impact

| Step | Effort | Wall-time impact | Type | Risk |
|---|---|---|---|---|
| W1 parallel + markers + lanes config | 0.5–1 day | **−50.6 % measured** (367→181.5 s on 2 cores) | measured | low |
| W2.2+W2.3 hot files (top of census) | 1–2 days | −20–30 % projected | projection | low |
| W4.3 CI activation + lanes | 0.5 day + owner click | dev-feedback from 6 min → ≤ 90 s | projection | external (workflows permission) |
| W3.1 template-world fixtures | 1 day | −25 s on write-gate family | measured family | medium (shared-fixture hygiene) |
| W2 remainder (full census) | 2–3 days | −10–15 % projected | projection | low |
| W3.2 node batching | 0.5 day | −1–3 s | estimate | low |
| W4.1 JS harness into pytest/CI | 0.5–1 day | ~0 s; closes a *coverage* hole | — | low |
| W4.2 coverage on parallel path | 0.5 day | −40–55 % of 519 s coverage run | projection, verify-then-adopt | medium (floor drift) |
| W4.4 root classification | 1–2 days | ~0 s; enables precise lanes | — | low (two files pin nodeids) |
| W4.5 hygiene | 0.2 day | ~0 | — | low |

## 6. Expected outcome

| Stage | Full suite (2 cores) | Coverage gate | Inner loop (`tests/unit -q`) |
|---|---:|---:|---:|
| Today (measured) | 367 s | 519 s | 55.2 s |
| After W1 (measured) | 181.5 s | 519 s | ~28 s (n=2) |
| + W2 hot files, W4.3 | ~130–150 s | 519 s | ~12–15 s |
| + W3, W2 remainder | ~100–130 s | 519 s | ≤ ~12 s |
| + W4.2 (if floor check passes) | ~100–130 s | **≤ ~240 s** | ≤ ~12 s |

A 4-core CI runner should land the fast lane near 60–90 s. Numbers above are
projections except rows explicitly marked measured; the protocol in §9 is how
each becomes measured.

## 7. Rejected ideas (and why)

| Idea | Why rejected |
|---|---|
| Replace DB/bridge tests with mocks or in-memory doubles | RULE 8 — tests execute the real thing; the fake-CDP discipline is a *strength* of this suite, and RULE 14's world is a real file (trash/attach paths need it). Speed must come from cheaper real fixtures and shorter real waits |
| Run the whole suite on `:memory:` SQLite | the world model is a file (RULE 14); several flows `ATTACH`/copy/restore the file; template-copy (W3.1) keeps the real thing at 1 % of the cost |
| Drop branch coverage or lower the §16.3 floors "for speed" | floors are the RULE 16 contract; W4.2 proves parallelism keeps them |
| Delete slow tests | the suite is the executable spec; SOR §7 names frozen contracts pinned by exactly these files |
| `pytest-testmon` / diff-based selection | extra machinery, and frozen-contract suites must always run; reconsider only if the suite is still over budget after W1–W4 |
| Bake `-n auto` into `pytest.ini addopts` | serial debugging must stay one command away; lanes opt in explicitly |
| Migrate async tests to `pytest-asyncio` | all async tests already run via `unittest.IsolatedAsyncioTestCase`; the plugin is present but unused; zero speed gain, pure churn |
| Run the WebEngine test in CI via GL stubs | it needs a real GPU/GL context by design; stays a local/manual smoke gate (already deselected in three places, unified by W1.4) |

## 8. RULE-compliance checklist for the implementation

| Rule | How this plan honours it |
|---|---|
| RULE 8 — tests execute the real thing | every technique shortens *time*, not behaviour: real loops woken by condition, real DB files copied from a template, real timeouts set short. No behaviour-less doubles introduced |
| RULE 16 — quality gates | docs-only change now. Implementation steps that touch production (W2.3, W3.3 knobs) follow §16.6: tests first, `radon cc -s` before/after, gate run; §16.3 floors re-verified per step; new baselines land in `reports/` with today's date; §16.0 keeps test/tooling edits out of LOC gates |
| RULE 17 — one current doc, dated archive | this plan lives in a dated archive folder; READMEs updated in the same change; when a workstream lands, SYSTEM_OF_RECORD.md §7 (commands/counts) is updated in that same change |
| RULE 18 — ideal sizes | plan is split into main doc + measurement appendix so each fits one read; new test helpers target 4–20-line functions / 150–300-line files; `ideal-size:` reasons required for deviations |
| RULE 19 — remediation order | any production function touched for a knob is fixed in ladder order (nesting → CC → cognitive → size); §16.5 landmines get the design note they demand before edits |
| Frozen contracts (SOR §7) | classification (W4.4) moves files only; the AREA D API snapshot, router wire contract, deletion result dict and collector status strings are untouchable side effects — their pinning tests must stay green byte-for-byte |

## 9. Re-measurement protocol (definition of "done" per step)

1. Reproduce the baseline exactly as the appendix documents (env vars, stub
   libs, same machine class).
2. After each workstream, record: serial full suite, `-n 2` full suite,
   group timings, `--durations=25`, and the §16.3 coverage pass; paste into a
   new dated `reports/SUITE_TIME_<date>.md` (the reports/ convention already
   used by the RULE 16 / RULE 18 baselines).
3. A step is accepted only if: suite green serial *and* parallel; coverage
   floors held; its exit criteria from §4 are met; SOR §7 updated.
4. Budgets to ratchet thereafter (CI-enforced, informational first):
   fast lane ≤ 90 s; `tests/unit` ≤ 20 s serial; no new `slow`-free test may
   add > 50 ms of real sleeps (W2.1 policy).

---

*Appendix with all raw measurements:
`docs/archive/2026-09-15-test-time-reduction/SUITE_BASELINE_2026-09-15.md`*
