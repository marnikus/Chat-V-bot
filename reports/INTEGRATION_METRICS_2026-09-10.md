# Metrics — post-merge (a49dd2a) → post-integration (INTEGRATION-01)

**Date:** 2026-09-10 · **Branch:** `arena/01a08b4d-chat-v-bot`
**Method:** the plan's own tools (`tools/metrics/metrics.py`, `deep.py`,
`area_d.py`, `coverage run --branch`, `vulture`, `radon cc`, full pytest with
`QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs`, Node for the JS
agent). Every number below was re-measured; nothing is copied from the plan
except the labelled baseline column.

---

## 1. Headline: the new metric you have now

| metric | plan baseline (pre-A) | post-merge | **post-integration (now)** |
|---|---|---|---|
| suite | 377 F / 983 P / 14 coll-err | 2129 P / 0 F | **2160 P / 0 F** (3 skip, 1 xfail, 815 subtests) |
| suite warnings | — | 1 (`handle_push` coroutine) | **0** |
| collection errors | 14 | 0 | 0 |
| coverage TOTAL (branch) | 80.0 % line / 69.7 % br | 87 % | **87 %** (12 108 stmts / 2 976 br) |
| production files / LOC / SLOC | 108 / 18 251 / 15 322 | 133 / 22 373 / 18 499 | **122 / 22 320 / 18 459** |
| classes / methods / fns | 119 / 866 / 160 | 178 / 1 307 / 192 | **178 / 1 315 / 190** |
| worst CC (plan counter) | 130 | 31 + 28 | **22** (`history_query._item`) |
| worst CC (radon) | — | — | **22** (`_item`), then 21 (`delete`) |
| functions CC > 10 / > 25 | 75 (7.3 %) / 7 | 67 / 2 | **67 / 0** ✅ |
| mean / median CC | 4.2 / 2 | 3.31 / 2 | **3.29 / 2** |
| vulture `--min-confidence 90` | 5+ | 7 | **0** ✅ |
| test-only `backend/` shims | 11 | 11 | **0** (`bridge.py` is live and stays) |
| `services/run_service` alias | present | present | **deleted** |
| `stores → backend` edges | 1 | 1 | **0** ✅ |
| `backend → actions` edges | 1 (`visual_click`) | 1 | **0** ✅ (cycle broken) |
| import-order fragility | masked | masked | **gone** (7 first-import orders pinned green) |
| JS agent suite (Node) | — | — | 43 P / 0 F |

## 2. Coverage by package (branch)

| package | post-merge | now |
|---|---|---|
| `core` | 99 % | 99 % |
| `actions` | 94 % | 94 % |
| `stores` | 92 % | 93 % |
| `services` | 90 % | 90 % |
| `backend` | 88 % | 88 % |
| `app` + `main` | 80 % | 80 % |
| `bridge` | 64 % | 64 % (excluded by task rule) |
| **TOTAL** | 87 % | **87 %** |

## 3. Gates 0–7 (plan §8.3)

| gate | post-merge | now |
|---|---|---|
| 0 collection | ✅ | ✅ |
| 1 no Qt poisoning | ✅ | ✅ |
| 2 P0 bugs | ✅ | ✅ |
| 3 app boots | ✅ | ✅ |
| 4 full suite | ✅ 2129/0 | ✅ **2160/0** |
| 5 frozen files | ✅ | ✅ (cleanup removals are the documented exception) |
| 6 API parity | ✅ | ✅ + documented removal set (12 module paths, 1 moved class, 3 signatures) |
| 7 metrics | ❌ (CC 31/28, vulture 7) | ✅ **max CC 22, vulture-90 clean, cov 87 %** |

## 4. What changed structurally

* −11 `backend/*.py` shims, −`services/run_service/`, 50 test files on
  canonical imports; `backend/bridge.py` kept (live).
* `backend/chat_agent_js.py` → `core/chat_agent_js.py` (asset stays in
  `backend/js/` for the Node suite); `stores → backend` now zero.
* `ActionResult` (`actions/base.py`) → `core/action_result.py`, re-exported
  with identical identity; `backend → actions` now zero; the
  `visual_click` ⇄ `actions.scan()` cycle is dead.
* `_execute_cycle` 31 → 7 (+5 helpers ≤ 11); `_normalized` 28 → 2
  (+3 helpers ≤ 11); dead `execute(scroll_parser=)` arg removed;
  `RunHooks`/`__aexit__` unused params marked.
* `services → backend` edge set pinned exactly (4 runtime files, 1
  TYPE_CHECKING file, 1 lazy file) — accepted intra-layer, no growth allowed.

## 5. Deliberately not done (follow-ups, own designs)

`services → backend` re-layering · `bridge/*` + `app/lifecycle.py` coverage ·
JS duplication (~350 lines) · `docs/ARCHITECTURE.md` refresh (wholesale
stale) · CI gates · god-class facades keep their method counts by design
(API stability first).
