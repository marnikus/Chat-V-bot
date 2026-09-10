# INTEGRATION-01 — Post-merge integration fixes (cleanup PR, first slice)

**Date:** 2026-09-10 · **Branch base:** `arena/01a08b4d-chat-v-bot` (`a49dd2a`,
"integrate correct AREA B with A+C+D")
**Parent plan:** `docs/REFACTOR_2026-09-09_FOUR_AREA_PLAN.md` §8.3 (gates) +
§9 (deferred cleanup PR), plus the cross-area requests of AREA B §3.5,
AREA C §9 and AREA D §8.
**Status:** design → tests → implementation (this document is written first;
no production code changes with it).

---

## 0. Scope and ground rules

The four AREA branches are merged and the suite is green
(`2129 passed, 0 failed`). What remains is exactly what the plan deferred:
work that **spans two or more areas** and therefore could not land inside any
single one (§8.4 forbids cross-area edits). This document is the **first
cleanup slice** — the mechanical, behaviour-preserving part of §9.

In scope (each item names the areas it spans):

| id | fix | spans | kind |
|---|---|---|---|
| I1 | retire the 11 test-only `backend/*.py` shims; codemod the 50 test files that import them | B + C + D | deletion + test-only codemod |
| I2 | repoint the last `services.run_service` importer; delete the alias package (AREA C request §9.1) | A + C | deletion + 1 test edit |
| I3 | move the zero-dependency leaf `backend/chat_agent_js.py` → `core/chat_agent_js.py`, killing the last `stores → backend` edge (plan §3.5) | B + D | move, no signature change |
| I4 | delete the 7 vulture `--min-confidence 90` findings incl. the `RunHooks` dead params (AREA C request §9.2) and the dead `execute(scroll_parser=)` arg | A + C + D | deletion / rename |
| I5 | split the last two functions over CC 25 (`_execute_cycle` 31, `_normalized` 28) so Gate 7 holds | B + C | internal extraction, frozen façades |
| I6 | await the push-binding coroutine in `test_push_binding_ignores_other_bindings` (kills the suite's only `RuntimeWarning`) | C | test hygiene, no production change |
| I7 | move the `ActionResult` leaf `actions/base.py` → `core/action_result.py`, breaking the genuine `backend.visual_click` ⇄ `actions/__init__.scan()` import cycle that I1 unmasked (found during implementation, F8) | D | move, re-exports keep every path alive |
| P1–P3 | pin the result with integration tests (layering edges, removal set, dead-code/CC gates) so it cannot rot | all | new tests |

Ground rules:

1. **Behaviour is frozen.** Every production edit is a move, a deletion of
   dead code, or an internal extraction behind an unchanged signature —
   except the three *intentional, documented* signature changes of I4, which
   the plan explicitly assigns to the cleanup PR (§8.3 Gate 6: *"the one
   exception to 'no removals' is the cleanup PR"*).
2. **The Gate 6 removal set is exactly 13 module paths + 1 moved class + 3
   signatures**, pinned by test (`TestShimsAreRetired`,
   `TestRunServiceAliasIsRetired`, `TestChatAgentJsLivesInCore`,
   `TestActionResultLivesInCore`, `TestDeadCodeGates`): the 11 shims, the
   `run_service` alias, the `backend.chat_agent_js` module path (re-added as
   `core.chat_agent_js`), the `ActionResult` class (re-homed to
   `core.action_result`, re-exported by both `actions` paths with identical
   identity), `RunCoordinator.execute(scroll_parser)`,
   `RunHooks.*(coordinator)` → `(_coordinator)`, `_LeaseCtx.__aexit__` arg
   renames. Anything else that disappears fails the suite.
3. **Process:** design (this doc) → new tests red → implementation → existing
   tests/snapshots updated with documented arithmetic → full suite green.
4. Out of scope (documented as follow-ups in §8): `bridge/*` + `app/*`
   coverage, JS duplication, the `services → backend` re-layering,
   `docs/ARCHITECTURE.md` refresh, CI gates.

---

## 1. Problem — what the post-merge measurement says

Re-measured on `a49dd2a` (same tools as the plan: `tools/metrics/metrics.py`,
`deep.py`, `coverage run --branch`, `vulture`, full pytest with
`QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs`):

| metric | plan baseline (pre-A) | post-merge (now) |
|---|---|---|
| suite | 377 failed / 983 passed / 14 collection errors | **2129 passed, 0 failed**, 3 skipped, 1 xfailed, 771 subtests |
| collection errors | 14 | 0 |
| coverage (TOTAL, branch) | 80.0 % line / 69.7 % branch | **87 %** (12 109 stmts / 2 976 branches) |
| production files / LOC / SLOC | 108 / 18 251 / 15 322 | **133 / 22 373 / 18 499** |
| classes / methods / functions | 119 / 866 / 160 | 178 / 1 307 / 192 |
| worst CC | 130 (`sync_conversation`) | **31** (`_execute_cycle`) then **28** (`_normalized`) |
| functions over CC 10 / over CC 25 | 75 (7.3 %) / 7 | **67** / **2** |
| mean / median CC | 4.2 / 2 | 3.3 / 2 |
| god classes (≥ 15 mth) | 15 listed | 26 (facades kept their method count by design) |
| vulture `--min-confidence 90` | 5+ (plan §12.1) | **7 findings** |
| test-only `backend/` shims | 11 | 11 (0 production importers) |
| `services/run_service` alias | present | present (1 importer) |
| `stores → backend` edges | 1 | 1 (`media_fetch → chat_agent_js`) |
| suite warnings | — | 1 (`handle_push was never awaited`) |

Per-package coverage now: `core` 99 % · `actions` 94 % · `stores` 92 % ·
`services` 90 % · `backend` 88 % · `app`+`main` 80 % · `bridge` 64 %
(excluded by the task's ground rule, unchanged).

**Gates 0–7 on the merged tree** (plan §8.3):

| gate | verdict | note |
|---|---|---|
| 0 collection | ✅ 0 errors | |
| 1 no Qt poisoning | ✅ | conftest teardown check green |
| 2 P0 runtime bugs | ✅ | `load_stack` + runtime `UserRecord` |
| 3 app boots | ✅ | `import main` headless |
| 4 full suite | ✅ | 2129 / 0 |
| 5 frozen files | ✅ | areas touched only their own files |
| 6 API parity | ✅ for A–D | the cleanup removals below are the documented exception |
| 7 metrics | ❌ | **2 fns > CC 25, 7 vulture-90 findings** (coverage 87 % ✅) |

So the integration backlog is: **Gate 7 red + §9 items I1–I3 + I6**.
Findings F1–F7 detail them; §4 turns each into a fix.

---

## 2. Findings (evidence)

### F1 — 11 `backend/*.py` shims are test-only (plan §9 row 1)

```
backend/{action_engine,collector,db_manager,history_db,history_models,
         history_repo,history_service,label_store,media_store,
         preset_store,user_memory}.py
```

* 0 production importers (grep over `core actions backend bridge services
  stores app main.py`, shim files themselves excluded).
* 50 test files import them (126 import statements at plan time).
* `backend/bridge.py` is **live** (`app/bootstrap.py:9`) and stays.

### F2 — `services/run_service/` alias survives (AREA C §8 + §9.1)

`services/history_service/` is already deleted; `services/run_service/`
remains with exactly one importer,
`tests/integration/services/test_run_service_paths.py:19` (A-owned at the
time, now freely editable on the merged branch).

### F3 — one `stores → backend` edge left (plan §3.5, AREA B §3.5)

`stores/media_fetch.py:28: from backend import chat_agent_js`, pinned by
`ALLOWED_UPWARD_EDGES = {"media_fetch.py": "backend.chat_agent_js"}` in
`tests/unit/stores/test_stores_structure.py`.

Why a move, not DI: the module imports **only stdlib** (`json`, `os`) — a
pure leaf — and is imported from three packages (`backend/chat_parser`,
`services/collector_service`, `stores/media_fetch`) plus 2 test files.
`core/` is documented as *"the bottom, zero-dependency"* (`core/__init__.py`)
and every package already depends on it, so `core/chat_agent_js.py` is
downward for all three importers. The alternative (a DI seam through
`MediaStore.__init__`) would change a frozen `stores/` signature and leave
direct `MediaStore(...)` constructions in tests with no default.

One coupling to carry over: the module loads `backend/js/chat_agent.js`
**relative to its own `__file__`** (`AGENT_PATH`), and the JS asset must stay
where it is — `tests/test_history_agent_js.js` (Node) reads
`backend/js/chat_agent.js` by path. The moved module therefore resolves the
asset repo-root-relative (pure path math, no `backend` import — `core` must
stay dependency-free).

### F4 — 7 vulture `--min-confidence 90` findings (Gate 7)

| # | finding | safe fix |
|---|---|---|
| 1 | `actions/registry.py:18` unused import `Iterator` | delete from the `typing` import (`Optional`, `Type` stay — both used) |
| 2–3 | `backend/cdp_client.py:35` unused `exc_type`, `tb` in `_LeaseCtx.__aexit__` | rename to `_exc_type`, `_exc`, `_tb` (dunder, positional-only in practice; no subclass overrides) |
| 4 | `services/run/coordinator.py:54` unused `scroll_parser` arg of `execute()` | **remove the parameter** — the sole production caller (`bridge/stack_bridge.py:91`) and every test call `execute()` with no args; drop the now-unused `TYPE_CHECKING` import of `ScrollParser` |
| 5–7 | `services/run/hooks.py:68,71,74` unused `coordinator` params | rename to `_coordinator` (all callers positional; test subclass overrides keep their own names; arity unchanged) |

Verified: `_`-prefixed names silence vulture (scratch check); no kwargs
callers of any of the three hook methods; no signature introspection of
`execute()` in tests.

### F5 — two functions still over CC 25 (Gate 7: `radon cc -nc`)

* `services/run/coordinator.py:90 _execute_cycle` — CC **31**, 37 LOC.
  The run-engine core; covered by `test_services_run.py` + the run-state
  contract suite.
* `stores/label_state.py:74 _normalized` — CC **28**, 50 LOC. Pure
  normalisation; covered by the label suites.

Both are decomposable into named phases without changing any emit/tracer
order (spec in §4.5).

### F6 — `handle_push was never awaited` (suite's only warning)

`PushBindings.on_binding` is **sync by contract**: it returns the
`handle_push(...)` coroutine and the CDP dispatcher schedules it
(`backend/cdp_client.py:142-146`: `isawaitable → create_task`). Production
is correct — the AREA C contract test already pins this
(`test_history_service_contract.py:146-150`: *"the binding handler hands its
result back for the CDP layer to schedule"*). Only the older
`test_services_history.py:422` drops the coroutine. Fix = await it there
(test hygiene, zero production change).

### F8 — genuine import cycle `backend.visual_click` ⇄ `actions` (found during implementation)

Deleting the shims changed the dump tool's import order and exposed that
`backend/visual_click.py:28` (`from actions.base_action import ActionResult`)
is a real cycle: importing `backend.visual_click` **first** in a fresh
interpreter dies, because `actions/__init__.py` runs `ActionRegistry.scan()`,
which imports `actions/find_click_runner.py`, which re-imports the still
partially-initialised `backend.visual_click` (`CLICK_PAUSE_MS`). Production
and the suite were only safe by import-order luck (conftest/`main` always
touch `actions` first). The codebase itself documents the edge
(`actions/base.py:_click_runner` docstring). Fix = I7: the three-constant
`ActionResult` leaf moves to `core/action_result.py`; `actions/base.py` and
`actions/base_action.py` re-export the same object, so every import path —
and every `is` comparison — is unchanged. After I7, `backend → actions` is
zero and every first-import order works (pinned by subprocess test).

Snapshot consequence: `ActionResult` leaves the `actions.base` snapshot
section (`__module__`-based recorder) — an intentional, identity-pinned move
(see P2), not a removal.

### F7 — `services → backend` edges (accepted, pinned — NOT fixed here)

`services/collector_service.py` → `backend.{chat_parser,history_query}`
(+ `chat_agent_js`, which I3 re-homes to `core`) and
`services/history/__init__.py` → `backend.{chat_parser,history_query}`.
These sit inside the business-logic layer (`ARCHITECTURE.md` §4.1 puts CDP
parsers and services in one layer); re-homing `HistoryQuery`/`ChatParser`
below `services/` is a real re-architecture with bridge/test blast radius,
so this slice **pins the exact edge set** (runtime vs `TYPE_CHECKING`
classified) and defers the re-layering to a follow-up with its own design.

---

## 3. Target structure

```
backend/
  chat_agent_js.py            ✂ MOVED → core/chat_agent_js.py (AGENT_PATH now
                                repo-root-relative to backend/js/chat_agent.js,
                                which STAYS for the Node suite)
  {action_engine,collector,db_manager,history_db,history_models,
   history_repo,history_service,label_store,media_store,
   preset_store,user_memory}.py  ✂ DELETED (I1; 0 production importers)
  bridge.py                   … kept (live: app/bootstrap.py)
  cdp_client.py               … _LeaseCtx.__aexit__ args underscore-prefixed (I4)
  chat_parser.py              … `from backend import chat_agent_js` → core (I3)
core/
  chat_agent_js.py            ★ NEW HOME (byte-identical logic + AGENT_PATH fix)
services/
  run_service/                ✂ DELETED (I2)
  run/coordinator.py          … execute() loses dead arg; _execute_cycle → 4
                                helpers (I4+I5)
  run/hooks.py                … coordinator → _coordinator (I4)
stores/
  label_state.py              … _normalized → 4 helpers (I5)
  media_fetch.py              … `from backend import chat_agent_js` → core (I3)
services/collector_service.py … `from backend import chat_agent_js` → core (I3)
tests/
  integration/test_post_merge_contract.py   ★ NEW (P1–P3 + behaviour pins)
  <50 files>                   … shim imports → canonical homes (I1 codemod)
  integration/services/test_run_service_paths.py … → services.run (I2)
  integration/services/test_services_history.py  … await push result (I6)
  unit/stores/test_stores_structure.py       … ALLOWED_UPWARD_EDGES → {} (I3)
  unit/stores/test_stores_public_api.py      … 37 → 29 (I1 arithmetic, §6)
  unit/backend/test_backend_api_snapshot.py  … module floor 45 → 38 (I1+I3)
  unit/backend/backend_api_snapshot.json     … regenerated (I1+I3)
```

Net: 133 → **122** production files (−11 shims, −1 alias package,
+1 `core/action_result.py`; the `chat_agent_js` move is −1/+1).

---

## 4. Implementation spec

### 4.1 I1 — shim retirement + codemod

Delete the 11 files of F1. Codemod every test import by this table
(single-home mappings; verified: no test line mixes homes except the
`get_action_class` row):

| from | to |
|---|---|
| `backend.action_engine` | `services.run` — **except** `get_action_class` → `actions.base_action` (only `tests/test_repeat_loop.py:31`; `services.run` does not re-export it) |
| `backend.collector` | `services.collector_service` |
| `backend.db_manager` | `services.db_service` |
| `backend.history_db` | `stores.history_db` |
| `backend.history_models` | `stores.history_models` |
| `backend.history_repo` | `stores.history_repo` |
| `backend.history_service` | `services.history` |
| `backend.label_store` | `stores.label_store` |
| `backend.media_store` | `stores.media_store` |
| `backend.preset_store` | `stores.preset_store` |
| `backend.user_memory` | `stores.user_memory` |

Multi-line imports keep their shape; only the module path changes (plus the
one split import in `test_repeat_loop.py`).

### 4.2 I2 — `run_service` retirement

`tests/integration/services/test_run_service_paths.py:18-22` becomes one
import from `services.run` (every name it takes — `STANDALONE_NICK`,
`USER_SCOPED_BLOCKS`, `RETIRED_BLOCK_KEYS`, `RunCoordinator`, `RunTracer`,
`norm_level`, `normalize_blocks`, `RunProgress` — is exported there);
delete `services/run_service/__init__.py` (+ package dir).

### 4.3 I3 — `chat_agent_js` → `core/`

1. `git mv backend/chat_agent_js.py core/chat_agent_js.py`.
2. Path fix (the only logic touch):
   ```python
   AGENT_PATH = os.path.join(os.path.dirname(os.path.dirname(
       os.path.abspath(__file__))), "backend", "js", "chat_agent.js")
   ```
   with a comment explaining why the asset stays in `backend/js/`
   (Node suite path pin).
3. Docstring: new home + "asset lives in `backend/js/`"; fix the stale
   `see backend/collector.py` pointer to `services.collector_service`.
4. Repoint 3 production + 2 test importers (`from core import chat_agent_js`,
   usages untouched):
   `backend/chat_parser.py`, `services/collector_service.py`,
   `stores/media_fetch.py`, `tests/test_chat_parser_delta.py`,
   `tests/test_private_gate.py`.

### 4.4 I4 — dead code (7 findings → 0)

Exactly the four edits of the F4 table. No other renames.

### 4.5 I5 — CC splits (both façades keep name + signature)

**`_execute_cycle` (31 → ≤ 6; helpers ≤ 12).** Extract three private methods
on `RunCoordinator`, moving code verbatim (same order of awaits, emits and
tracer notes); thread state through a private `_CyclePlan` dataclass:

* `_plan_cycle() -> _CyclePlan` — scroll lookup → collect phase → label
  filter → order → take phase → `has_skip`/`mem_click`/`needs_user`/
  `take_present` resolution (today's lines 90–96).
* `_announce_cycle_mode(plan) -> str` — the `queue / empty_stack / needs_user
  / standalone` emit cascade; returns `"queue"`, `"standalone"`, `"empty"`
  or `"empty_stack"`; performs the `progress.extend_total` calls exactly
  where they are today.
* `_drive_user_queue(plan, queue, standalone, has_skip) -> str` — the
  per-user loop incl. stop/pause/`mark_messaged`/emits (today's tail).
* `_execute_cycle` becomes: plan → `mem_click` early-return (unchanged) →
  take-miss early-return (unchanged) → announce → drive.

**`_normalized` (28 → ≤ 4; helpers ≤ 9).** Extract three pure helpers on
`LabelState`:

* `_normalize_defs(raw) -> (defs, seen_ids)` — the defs loop incl. the
  id/name dedup rules.
* `_normalize_assign(raw, seen_ids) -> assign` — the nick→ids loop.
* `_normalize_filter(raw, seen_ids) -> (include, exclude)` — incl. the
  *"exclusion wins"* rule, verbatim.
* `_normalized` orchestrates + builds the payload dict (unchanged shape).

### 4.6b I7 — `ActionResult` → `core/`

1. New leaf `core/action_result.py` (the class, verbatim, + home docstring).
2. `actions/base.py`: replace the definition with
   `from core.action_result import ActionResult  # re-export`; refresh the
   `_click_runner` docstring premise.
3. `backend/visual_click.py`: import from `core.action_result`.
4. No other importer changes (`actions.*` and the lazy
   `services/run/error_recovery.py:146` import keep resolving the same
   object through the re-exports).
5. Pins: identity across all three paths + zero `backend → actions` AST
   edges + fresh-interpreter first-import matrix
   (`visual_click`, `find_click_runner`, `actions`, `collector_service`,
   `chat_parser`, `app.bootstrap`, `main`).

### 4.6 I6 — push-binding test hygiene

```python
result = self.service._on_binding({"name": "__cvbPush", "payload": "[]"})
self.assertTrue(inspect.isawaitable(result))
self.assertEqual(await result, 0)
```

(`0`: real collector, empty payload → no items. Test method is already
`async`.)

### 4.7 P1–P3 — integration pins (new tests, §5)

* P1 layering: zero `stores → backend` AST edges; exact
  `services → backend` runtime set
  (`collector_service → {chat_parser, history_query}`,
  `history/__init__ → {chat_parser, history_query}`) and exact
  `TYPE_CHECKING`/function-local set — any new edge fails.
* P2 removal set: the 12 module paths gone, `core.chat_agent_js` present
  with `AGENT_VERSION`/`agent_source()`, every name the shims re-exported
  importable from its canonical home (spot-check per shim).
* P3 gates-as-tests: repo-wide max CC ≤ 25 (plan's own `cc_of`, copied
  verbatim); targeted dead-code pins (no `Iterator` import, `execute(self)`
  arity, `_coordinator`/`_exc_*` names).

---

## 5. Test-first plan (process step 2, executed before §4)

New file `tests/integration/test_post_merge_contract.py`:

| class | pins | red before? |
|---|---|---|
| `TestShimsAreRetired` | P2 (12× `assertRaises(ImportError)` + canonical-home spot imports) | ✅ red (shims exist) |
| `TestRunServiceAliasIsRetired` | `services.run_service` unimportable; `services.run` exports the 8 names | ✅ red (alias exists) |
| `TestChatAgentJsLivesInCore` | `core.chat_agent_js` API + `AGENT_PATH` resolves to the shipped JS; `backend.chat_agent_js` gone | ✅ red (lives in backend) |
| `TestActionResultLivesInCore` + `TestImportOrderIsCycleFree` | I7 identity, zero `backend → actions` edges, first-import matrix | ✅ red pre-I7 (cycle; added with the fix) |
| `TestStoresHasNoUpwardEdge` | P1 zero-edge assertion | ✅ red (1 edge) |
| `TestServicesBackendEdgesArePinned` | P1 exact-set assertion | ✅ red (chat_agent_js edge present) |
| `TestDeadCodeGates` | P3 targeted pins | ✅ red (7 findings) |
| `TestComplexityGate` | P3 max-CC ≤ 25 | ✅ red (31, 28) |
| `TestPushBindingContract` | `on_binding` None-vs-awaitable; dispatcher schedules awaitables | 🟢 green (already true — regression pin) |
| `TestExecuteCycleOutcomes` | empty_stack/empty/standalone/stop behaviour matrix through fakes | 🟢 green (pre-refactor pin for I5) |
| `TestLabelNormalizationMatrix` | dup ids/names, unknown ids, include∩exclude, non-dict rows | 🟢 green (pre-refactor pin for I5) |

Red-before is verified by running the new file **before** implementing §4.

---

## 6. Existing-test updates (integration-phase, all arithmetic documented)

| id | file | change | why |
|---|---|---|---|
| U1 | `unit/stores/test_stores_structure.py` | `ALLOWED_UPWARD_EDGES → {}` + docstring ("zero — I3 removed the last one") | the gate's purpose was to keep it at one; now it keeps it at zero |
| U2 | `unit/stores/test_stores_public_api.py` | `37 → 29` + comment | the 8 `from stores…` lines inside the deleted shims (`history_db` 1, `history_models` 2, `history_repo` 1, `label_store` 1, `media_store` 1, `preset_store` 1, `user_memory` 1 — recounted, not assumed) |
| U3 | `unit/backend/test_backend_api_snapshot.py` | module floor `45 → 38` + comment | 50 − 11 shims − `chat_agent_js` = 38 |
| U4 | `unit/backend/backend_api_snapshot.json` | regenerate via `dump_public_api.py --write` | intentional removals; P2 pins the set so the refresh cannot hide drift |
| U5 | `integration/services/test_run_service_paths.py` | single `services.run` import (I2) | |
| U6 | `integration/services/test_services_history.py` | await push result (I6) | |
| U7 | 50 test files | I1 codemod table | |
| U8 | `tests/repro_bug2.py` (not collected) | same codemod, consistency | |
| U9 | `tests/test_merge_undo_enabled.py` | source-grep retarget: `_run_collect_phase` now lives in `_collect_cycle_queue`, one delegation below `_execute_cycle` (I5 keeps the ownership contract) | |
| U10 | 11 test files, 54× `engine.execute(None)` / `eng.execute(None)` → `engine.execute()` | the removed dead arg was passed `None` positionally by tests (`test_action_engine_sequence`, `test_click_user_memory`, `test_click_user_order`, `test_engine_standalone_run`, `test_live_status_and_order`, `test_mark_person_messaged`, `test_nick_placeholder`, `test_repeat_loop`, `test_run_engine_p0_pins`, `test_search_users`, `test_take_person`); production already called it bare | |

No `WIDENED`/baseline change in `stores/`: I5 adds only private helpers
(`stores_api.surface()` skips `_`-names) and I3 changes an import, not a
signature.

---

## 7. Exit criteria

1. New contract file: red before §4, green after.
2. Full suite: `2129+ passed, 0 failed`, 0 warnings (the `handle_push`
   warning gone), still deselecting only the pre-existing
   `test_grid_in_real_webengine` (needs real GL — plan §1 caveat 1).
3. Gate 7 green: repo-wide max CC ≤ 25 (same counter), vulture-90 clean,
   coverage TOTAL ≥ 80 % (must not regress below today's 87 %).
4. Gates 0–6 stay green; P2 removal set exact.
5. Node JS agent test still passes (`node tests/test_history_agent_js.js` —
   asset untouched, sanity check).
6. Metrics report `reports/INTEGRATION_METRICS_2026-09-10.md` with the
   before/after tables of §1 refreshed post-fix.

---

## 8. Risks, non-goals, follow-ups

| risk | mitigation |
|---|---|
| `_execute_cycle` split reorders an emit/tracer note | verbatim move + pre-refactor outcome matrix (green before/after) + the existing 30+ engine tests |
| codemod misses a name (`get_action_class`!) | per-symbol table (§4.1) + full suite + P2 canonical-home imports |
| snapshot regen hides drift | P2 pins the exact removal set independently of the golden file |
| `AGENT_PATH` breaks headless/zip usage | same `__file__`-relative technique, one level up; pinned by `TestChatAgentJsLivesInCore` |

Non-goals / follow-ups (own designs, own slices): `services → backend`
re-layering (F7); `bridge/*` + `app/lifecycle.py` coverage (excluded by task
rule); JS duplication (~350 lines, plan §9); `docs/ARCHITECTURE.md` refresh
(wholesale stale, incl. pre-existing rows); CI gates (`radon`, `vulture`,
`coverage --fail-under` in CI).
