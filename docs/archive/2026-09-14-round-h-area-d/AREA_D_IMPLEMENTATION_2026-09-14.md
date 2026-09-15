# Area D implementation — verification and measurement debt

Date 2026-09-14 · branch `arena/01a0a172-chat-v-bot` · implements
[`AREA_D_VERIFICATION_DESIGN_2026-09-14.md`](../2026-09-14-round-h/AREA_D_VERIFICATION_DESIGN_2026-09-14.md)

Status: **implemented** — no production file changed, only tools/tests/docs/reports/setup.cfg

## What landed

### H-D1 — mutation platform (from 1 module to a platform)

* `setup.cfg` widened: `pytest_add_cli_args_test_selection` now includes
  `tests/test_history_query_edges.py`. Measured: reachable set 159 → **1,141 of
  1,141** mutants (all reachable now, vs 910 in original design doc), runtime
  ~25s → ~2 min. The convention is explicit in the report: unreachable = "no tests"
  in selected suite, never counted as killed. Score drops 99.37% (158/159) → **49.34%**
  (563/1141) because more mutants become reachable but not killed — honest and expected.
* Second job: `tools/metrics/mutation_platform.py` JOB2 over pure bot family
  (`services/bot_variables.py`, `bot_reactions.py`, `bot_providers.py`,
  `bot_prompts.py`, `bot_transcript.py`, `bot_connections.py`, `bot_presets.py`,
  `bot_chat.py`, `bot_grok.py`) — no Qt in import path, 93–100% covered,
  never mutation-measured before. Runner now aggregates per-file (multi-file
  source_paths fix) — each file mutated separately, totals summed. Measured:
  **1,588 total, 1,499 killed, 89 survived, 94.4%** reachable score.
  Runner swaps `setup.cfg` temporarily, runs `mutmut`, restores, deletes `mutants/`
  (not gitignored). Also_copy now includes `ui/` to avoid `ui/index.html` FileNotFoundError.
* Report: `reports/MUTATION_REPORT_2026-09-14.md` with both scores and
  reachable-set arithmetic stated explicitly.

Owner decision D2: widening accepted, second job added. Runtime cost is
documented; second job is ~1–2 min.

### H-D2 — RULE 8 double audit (mechanism that hid dead label store)

* Tool: `tools/metrics/double_audit.py` — inventories every `Fake*`/`Stub*`/`Dummy*`
  plus `__getattr__` catch-all doubles, lists per double production class it
  imitates and attributes/methods it provides.
* Parity check: for each double whose production class is importable without
  Qt/CDP, assert double does not offer attribute real lacks (`hasattr(real, name)`),
  and that every member code under test uses exists on real. `FakeArchive.labels`
  would fail this immediately — pinned by test.
* Tests: `tests/test_double_audit.py` — inventory not empty, FakeArchive present,
  no invented interface in current tree (after P1 fix), catch-all flagged,
  known map honest.
* Landing rule: "a double may not invent an interface" is now executable, not a norm.

Measured: 84 files contain Fake*, 50+ fake classes, 2+ __getattr__ catch-alls
(in `test_history_service_contract.py`, `test_services_history.py`).

### H-D3 — per-file coverage floor

* Tool: `tools/metrics/file_coverage_floor.py` — every prod module with ≥30
  statements must hold ≥80% line coverage, with ratchet table for files below
  today that may only rise. Wired from `coverage.json` (RULE 16 §16.3's measurement).
* Ratchet: initially 15 files below 80% (measured 2026-09-14, line 91.77%, branch 88.03%):
  `message_injector_send.py` 21.1%, `lifecycle.py` 59.7%, `history_bridge.py` 62.3%,
  `cdp_client.py` 63.1%, `layout_bridge.py` 67.3%, `chat_text.py` 70.1%,
  `db_deletion_flow_remove.py` 70.1%, `db_registry.py` 70.5%, `collector_bridge.py`
  72.1%, `db_deletion_scan.py` 73.5%, `cancellation.py` 73.5%, `people_bridge.py`
  76.1%, `label_bridge.py` 78.0%, `media_fetch.py` 78.7%, `db_deletion_flow_detach.py`
  78.8%. Two are Area B's (history_bridge, cdp_client) — this owns floor/ratchet,
  Area B owns files.
* Coverage lift: `tests/test_area_d_coverage_lift.py` lifts 4 Area-D-owned files
  below floor with pure tests + FakeCDP for click_send paths (found/clicked,
  fallback icon, probe errors). Measured post-lift: `chat_text.py` 70.1%→**100%**,
  `message_injector_send.py` 21.1%→**100%**, `lifecycle.py` 59.7%→**87%**,
  `cancellation.py` 73.5%→**87%**. Overall line 92.64%→**93.16%** (15,833/16,995),
  branch 88.03%→**88.85%**. Ratchet now **11 files** (the 4 lifted removed).
* Test: `tests/test_file_coverage_floor.py` — no regression below ratchet,
  no new below-floor file without ratchet, ratchet sorted/honest, floor 80%.
* Gate: `file_coverage_floor.py --gate` exits 1 on regression.

### H-D4 — baseline and documentation currency

* `docs/current/AGENT_RULES.md` §16.3 re-quoted from 2026-09-10 floors
  (90.44/84.38) to **92.64/88.03** (snapshot `CODE_QUALITY_METRICS_2026-09-14.md`),
  then post-D lift to **93.16% line (15,833/16,995), 88.85% branch (3,547/3,992)**
  from `coverage.json` after `test_area_d_coverage_lift.py`. Doc notes both.
* §18.2 corrected: 186 → **208 files**, median 134, 4 over 500 with correct sizes
  (config_manager 507 → **511**), Round H splits noted.
* `docs/README.md` map updated: Round H plan + Area D implementation.
* `docs/archive/README.md` index updated: 105 → 106 docs, 22 → 23 groups,
  new group `2026-09-14-round-h-area-d`.
* Tool table: JS gate not added (D1 decision pending Area A), but mutation
  platform and file floor added via this area's tools.
* `setup.cfg` also_copy now includes `ui/` (was missing, caused mutmut FileNotFoundError
  for `ui/index.html` test).

### H-D5 — smell ratchet

* Tool: `tools/metrics/smell_inventory.py` — inventories 7 vulture findings,
  13 clone groups (all import headers, baselined, 0 new/0 stale), 4 boundary
  crossings (inspection), 11 wide-param functions (9 RULE 3, 2 non-block).
* Disposition per finding:
  - `actions/registry.py:18 Iterator` — delete (dead import)
  - `backend/cdp_client.py:35 exc_type, tb` — protocol (context manager __aexit__)
  - `services/run/coordinator.py:62 scroll_parser` — delete (unused param, no caller)
  - `services/run/hooks.py:68/71/74 coordinator` — protocol (base hook, subclasses use)
* Boundary crossings: `router.py:471 ctx.undo._history_entry`, `undo_bridge.py:178
  _clean_history`, `db_service.py:160/163 _remember/_prune_remembered`,
  `history/query.py:97/132/139 _dirs/_nick/_last_sync_reason` — either public
  name or recorded decision, `self.p._x` inside part classes excluded as
  documented part pattern.
* Wide params: 9 RULE 3 overrides documented, 2 non-block queued for options object:
  `bridge/router.py::__init__` (8 params, Area B H-B5), `backend/chat_sync.py::run_sync`
  (5 params, follow-up B).

No production file edited for smells — inventory + disposition handed to Area B/C
per "no production edits" rule, with owner areas noted.

## Verification battery

```bash
# floors this area manages
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/python -m coverage run \
  --branch --source=core,actions,backend,bridge,services,stores,app,main -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
COVERAGE_FILE=.coverage .venv/bin/python -m coverage json -o coverage.json

# per-file floor
.venv/bin/python tools/metrics/file_coverage_floor.py --gate

# double audit
.venv/bin/python tools/metrics/double_audit.py --gate

# smell inventory
.venv/bin/python tools/metrics/smell_inventory.py
.venv/bin/vulture --min-confidence 90 core actions backend bridge services stores app

# mutation (both jobs)
.venv/bin/python tools/metrics/mutation_platform.py --run-all
# or single
.venv/bin/python tools/metrics/mutation_platform.py --run-job1
.venv/bin/python tools/metrics/mutation_platform.py --run-job2

# gates
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
.venv/bin/python tools/metrics/clone_scan.py .
```

## Cross-area notes

* File-floor ratchet written so Areas B/C can lower their own rows in own commits,
  same protocol `rule16_gate.py`'s RATCHET table uses.
* H-D1 widening sequenced after B's H-B2 in design, but implemented now — numbers
  measured against moving code if B touches file again, so report notes date.
* This area owns `tests/**` existing files; new test files written by Areas A/B/C
  stay with those areas.
* No production-code edits — smell dispositions handed to B/C as notes.

## Files

* `tools/metrics/file_coverage_floor.py` (208 lines) + `tests/test_file_coverage_floor.py`
* `tools/metrics/double_audit.py` (283) + `tests/test_double_audit.py`
* `tools/metrics/mutation_platform.py` (294) + `reports/MUTATION_REPORT_2026-09-14.md`
* `tools/metrics/smell_inventory.py` (222) + `tests/test_smell_inventory.py` (new)
* `setup.cfg` widened
* `docs/current/AGENT_RULES.md` floors re-quoted, §18.2 corrected
* `docs/README.md` + `docs/archive/README.md` registered

All tools respect RULE 18 ideal sizes (150–300 lines, function 4–20 lines) and
RULE 16 gates (no new function >30 LOC, no class >150 LOC, no params >4, CC≤10).
