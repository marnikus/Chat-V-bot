# Area B rebuild — the backend/bridge spine, rebuilt test-first after the first attempt was lost

2026-09-14 · branch `arena/01a0a1d3-chat-v-bot` · base `81f8aaf` (Round H Area C + Round I)
Steps executed: **H-B6**, **H-B1**, and the **search half of H-B2**.
Design of record: [`AREA_B_BACKEND_BRIDGE_DESIGN_2026-09-14.md`](AREA_B_BACKEND_BRIDGE_DESIGN_2026-09-14.md) — the file that produced these steps.

## 1. Why this is a rebuild and not a continuation

Area B *was* implemented once before — in an Arena session whose work was never
committed. Before rebuilding anything, that claim was checked five ways, all
negative:

* `git ls-remote --heads origin` lists 21 heads; for every one of them,
  `git cat-file -e <ref>:backend/cdp_client_transport.py` fails — no branch
  contains the new modules;
* `git log --all --diff-filter=A -- backend/cdp_client_transport.py
  backend/cdp_client_events.py backend/history_query_search.py
  bridge/history_bridge_read.py` prints nothing — no commit ever added them;
* a scan of **every blob object** in the local clone for `CdpEvents`,
  `cdp_client_transport` and `history_bridge_read` finds no production copy;
* GitHub has three pull requests (#1–#3) and none of them is this work;
* nothing on disk, and the session's captured `coding.patch` contains Round H
  Area C + Round I only (the commit `81f8aaf`), which is exactly the base this
  branch already had.

Conclusion: the work lived only in that session's working tree, on top of
`81f8aaf`. It is not recoverable. What survived is the session's file-change
view — the new modules' contents plus the modified files' old and new lines
interleaved without `+`/`−` markers — which is enough to state the design and
prove what was intended, but not enough to replay the diff (for example
`CdpLease.acquire` appears there in both its pre- and post-split form).

So the area was rebuilt from the design document, **test-first** as its §3
requires ("Touch a hotspot only with tests that lock current behaviour first",
RULE 16 §16.5), and re-measured. Line-for-line identity with the lost tree is
not claimed and not possible; what is claimed is that the same two test files
exist, the same splits exist, and the gates are green.

## 2. What was rebuilt

| Step | File | Before | After |
|---|---|---|---|
| **H-B6** | `backend/cdp_client.py` | 331 LOC · MI 36.7 · coverage 65.2% | **226 · MI 60.4** |
| | `backend/cdp_client_transport.py` | — | 239 · MI 55.9 |
| | `backend/cdp_client_events.py` | — | 64 · MI 80.1 |
| **H-B1** | `bridge/history_bridge.py` | 544 · **MI 24.9** (the tree's floor) · 66.4% covered | **241 · MI 52.3** |
| | `bridge/history_bridge_read.py` | — | 92 · MI 68.7 |
| | `bridge/history_bridge_delete.py` | — | 145 · MI 62.5 |
| | `bridge/history_bridge_media.py` | — | 123 · MI 65.4 |
| | `bridge/history_bridge_settings.py` | — | 44 · MI 88.1 |
| **H-B2a** | `backend/history_query.py` | 601 · MI 35.3 | **531 · MI 42.0** |
| | `backend/history_query_search.py` | — | 105 · MI 67.2 |

### H-B6 — the CDP client split by *who it talks to*

`backend/cdp_client_transport.py` owns the wire (connect/disconnect, id-stamped
framing, the receive loop, tab discovery, every command helper);
`backend/cdp_client_events.py` owns the listener table and the isolation rule
(a raising listener, or an async one with no loop, must never stop the others);
the facade keeps the `CDPClient` QObject the rest of the application imports
(`from backend.cdp_client import CDPClient` appears in 25 production modules).

The contract that made the split safe, and the reason it is testable at all:

* the mutability stays on the facade (`_ws`, `_cmd_id`, `_pending`,
  `_connected`, `_receive_task` are plain instance attributes), and every part
  function takes the client as its first argument — so the long-standing test
  seam (shadow `cdp.send` with a fake, assign `cdp._ws` / `cdp._connected`)
  works unchanged;
* `_dispatch_event` and `_receive_loop` remain on the facade as delegates:
  `tests/test_cdp_events.py` calls the first directly, and the new transport
  tests drive the second (it is the only caller that can feed it frames);
* `CdpLease`, `_LeaseCtx`, `TabInfo` and `HIGH`/`LOW` stay in the facade — the
  API snapshot pins them to `backend.cdp_client`, including the return type
  `backend.cdp_client._LeaseCtx`. The facade therefore deliberately has **no**
  `from __future__ import annotations`: adding it would quote every annotation
  and fail the snapshot as a "changed signature".

New tests first: `tests/unit/backend/test_cdp_client_transport.py` (**29
tests**, seven classes: `TestSend`, `TestConnectDisconnect`, `TestFetchTabs`,
`TestCommands`, `TestCookies`, `TestCdpLeaseHandOver`,
`TestReceiveLoopRobustness) — the connect/disconnect lifecycle and the four
enabled domains, the pending table, tab discovery (page-only filter, non-200,
transport error), every command helper through the `cdp.send` seam, the lease
hand-over edges (cancel after hand-over releases; cancel while waiting does
not; releases skip futures that already won), and the receive loop's robustness
against unknown ids and malformed frames. It swaps `websockets.connect` and
`aiohttp.ClientSession` on the modules they were imported into (direct
assignment, restored in a `finally`), so the pins stayed green *during* the
move.

### H-B1 — the archive bridge becomes a wire facade

The seven signals and the twenty-one `@Slot`s stay on `HistoryBridge` (the
QWebChannel wire surface the frontend calls by name); each slot is now a
synchronous guard plus `_ask` (error when the archive is missing) or
`_run_if_archive` (silent refusal), delegating to a part function.

* `history_bridge_read.py` — open/page/search/stats/userdb;
* `history_bridge_delete.py` — person/message delete, clear, purge, restore,
  merge, and the `people` before/after snapshot the undo ticket carries;
* `history_bridge_media.py` — media paths, folder, and the clipboard helpers;
* `history_bridge_settings.py` — history settings and `detect_my_nick`.

Two contracts had to be preserved exactly, and both are gates rather than
comments: the **frozen seven-line import window** is a clone-baseline pair with
`bridge/db_bridge.py` (pinned by `tests/test_rule16_new_code.py`), so the header
stays verbatim; and `_run_async(scope, coro)` stays on the facade because
`bridge/router.py` uses it to schedule label-store work.

New tests first: `tests/unit/bridge/test_history_bridge_delete.py` (36 tests) —
every undo ticket's shape, the people snapshots, the bus announcements and
`userdb_changed` payloads, the refusal paths, the media/clipboard slots and
the settings fallbacks, driven directly against a stubbed `BridgeContext`.

#### The latent bug this step fixed

Before the split, `HistoryBridge.history_delete_person` called
`self.ctx.label_store.forget(clean)` — **without the call parentheses** every
other bridge uses (`bridge/router.py`, `layout_bridge.py`, `db_bridge.py` all
write `ctx.label_store()`). `label_store` is a method, so the hard-delete path
raised `AttributeError: 'function' object has no attribute 'forget'` *after* the
rows were erased: the person was gone from the database, the UI never received
`userdb_changed`, and `services/world_events.py` logged it as a WARNING
("archive history_delete_person failed: …") that no test looked at.

The fix is `label_store().forget(clean)`, and the test was verified in both
directions: with the missing parentheses restored temporarily,
`TestDeletePerson::test_hard_delete_erases_forgets_labels_and_announces` fails
with `the bridge never answered` plus the captured
`'function' object has no attribute 'forget'` warning; with the fix it passes.

### H-B2, first half — the search back-end

`backend/history_query_search.py` now owns `search(db, person_id, query, limit,
offset)` and the request-text-to-SQL guards `_fts_query` / `_like_escape` /
`_snippet` (+ `SNIPPET_RADIUS`). `HistoryQuery._search` delegates to it;
`PersonPageRequest.where()` / `order()` import the LIKE escape from its new
home, and `tests/test_history_query_edges.py` imports the two guards from there
too — the private helpers moved, so their own test moved with them.

The **row-projection half of H-B2 is not done** (`_person_item`,
`_apply_specs`, `_item_media`, `_stat_int`, `_day_bounds` →
`history_query_rows.py`), which is why `backend/history_query.py` is still 531
lines and MI 42.0 rather than inside the round's MI ≥ 45 floor.

## 3. Ratchets and gates — tightened in the same change

* **`tools/metrics/rule16_gate.py` RATCHET re-frozen**, re-measured with the
  gate's own `classes()`: `HistoryBridge` **467/44 → 180/27**, `HistoryQuery`
  **362/14 → 266/14**. Both classes may still shrink; neither may grow back.
* **API snapshot regenerated** — and a trap found by the snapshot test itself:
  `tools/metrics/dump_public_api.py --write` must run with the headless Qt
  environment (`QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs`), or
  `backend.bridge` is recorded as `{"import_error": "libGL.so.1 …"}` and its
  entire public surface is erased from the golden file. Run from a bare shell,
  `--write` silently writes that damage and the test then fails with
  `KeyError: 'classes'`. The regenerated snapshot is purely additive (+76
  lines, three new modules pinned, nothing changed or removed).
* **RULE 16 / I-1.3 sleep ratchet enforced on this rebuild's own tests.** The
  rebuilt test file first waited for the bridge's scheduled work with
  `asyncio.sleep(0.05)` — exactly the pattern the Round I ratchet exists to
  stop — which took the suite total from 64 to 67 and failed both ratchet
  tests. Converted to bounded yield points (`await asyncio.sleep(0)` loops:
  `wait_for` / `settle`), which are deterministic rather than load-dependent;
  the total is back at the 64 ceiling and the file's 36 tests went from 3.3 s
  to 0.12 s.
* `rule16_gate.py --with-clones`: **green, 0 new groups, 0 stale baseline
  entries** — the four new bridge parts do not join any clone group, and the
  `db_bridge`/`history_bridge` import pair survives the split.
* `tools/metrics/stores_modules.py`: in band (untouched by this area).

## 4. Measured result

**Suite, plain** (`pytest tests`, headless Qt, 2026-09-14):
**3,257 passed, 2 skipped, 1 deselected, 1 xfailed, 931 subtests, 370.81 s,
exit 0.**

**Suite under `coverage run --branch`** (same selection): **3,257 passed, 2
skipped, 1 deselected, 1 xfailed, 931 subtests, 509.66 s, exit 0.** The same
run produced the first recorded line/branch pair for this tree:

| Metric | This change | Recorded baseline (2026-09-14 audit) | RULE 16 §16.3 floor |
|---|---:|---:|---:|
| Line coverage | **93.83%** (16,136 / 17,197) | 92.64% | ≥ 80%, never below baseline |
| Branch coverage | **89.49%** (3,549 / 3,966) | 88.03% | ≥ 75% |
| Combined line+branch | 93.02% | — | informational only (not the gate) |

Both gated metrics rose; no *new* function has zero hits (the §16.3 "uncovered
new functions: 0" check, run over the coverage JSON with an AST walk of the ten
new/changed modules).

Per-file coverage for the two modules the design called out as *reached worst*
(combined line+branch, `--branch`), plus the leaves they were split into:

| File | Coverage | File | Coverage |
|---|---:|---|---:|
| `backend/cdp_client.py` | **99.2%** (was 65.2%) | `bridge/history_bridge.py` | **92.5%** (was 66.4%) |
| `backend/cdp_client_transport.py` | 96.2% | `bridge/history_bridge_read.py` | 91.8% |
| `backend/cdp_client_events.py` | 88.6% | `bridge/history_bridge_delete.py` | 95.7% |
| `backend/history_query.py` | 97.7% | `bridge/history_bridge_media.py` | 95.7% |
| `backend/history_query_search.py` | 93.4% | `bridge/history_bridge_settings.py` | 100% |

**Audit** (`tools/metrics/current_audit.py`): **237 production files, median 124
LOC** (the tool counts 238 files including `main.py`; §18.2 quotes the 237
modules), mean MI **69.58**, **13 files over 300 lines** (was 15), **31
functions over 30 LOC** (was 35), exact clone groups 3 (unchanged);
tests 192 files / 42,736 non-comment lines vs production 27,201.

**Gates**: `rule16_gate.py --with-clones` green — `HistoryBridge` 180/27 and
`HistoryQuery` 266/14 inside the re-frozen ratchet, `_person_request` and
`HistoryBridge.userdb_page` still inside the owned-function limits, clone scan
**0 new groups / 0 stale baseline entries** (the `db_bridge` ↔ `history_bridge`
import pair survives the split); `stores_modules.py` in band (15 of 15
effective modules); `tests/test_rule16_new_code.py` **23 passed**; API-snapshot
tests **9 passed** on a +76/−0 additive snapshot (71 modules, 0 import errors).

**The MI floor moved**: the tree's worst file was `bridge/history_bridge.py` at
**MI 24.9** (and had been for two rounds); it is now **MI 52.3**, and the floor
is `services/run/hooks.py` at **32.2**. 17 production files remain below the
round's MI ≥ 45 goal, none of them touched by this area.

**Files over 500 lines: 3** — `backend/history_query.py` (531),
`backend/dom_highlight.py` (514), `backend/config_manager.py` (511).

Design targets met vs missed, stated plainly:

| Step | Target | Measured | Verdict |
|---|---|---|---:|
| H-B1 | parts ≤ 200 lines each | 44–145 | met |
| H-B1 | file ≤ 200 lines | **241** | **missed** — the seven signals + twenty-one `@Slot`s + the frozen 7-line import window are irreducible while JS calls them by name |
| H-B1 | MI ≥ 45 (from 24.9) | 52.34 | met |
| H-B1 | coverage ≥ 90% (from 66.4%) | 92.5% | met |
| H-B6 | coverage ≥ 85% (from 65.2%) | 99.2% | met |
| H-B6 | `CDPClient` ≤ 15 methods | **20** | **missed** — every CDP command name is called from `services/` and `actions/` (25 modules import the client); the split moved the bodies to `cdp_client_transport.py`, and the facade keeps twenty delegating methods, one per command name. `CdpLease` has 8 |
| H-B2 | facade ≤ 350 / `HistoryQuery` ≤ 10 methods / MI ≥ 50 | 531 / 14 / 42.0 | **missed** — the row-projection half is unbuilt (§5) |

## 5. Not done — carried forward

* **H-B2's second half** (row projection → `history_query_rows.py`), the only
  reason `history_query.py` is still over 500 lines and outside MI 45; the
  `_my_nicks` mutant-7 test is part of it;
* **H-B3** (`config_manager.py` 511), **H-B4** (`dom_highlight.py` 514, payload
  module), **H-B5** (`router.py` 486, `media_handler.py` 474,
  `chat_parser.py` 426);
* the area MI floor: 17 production files below MI 45;
* `services/db_registry.py` coverage (70.7%) and Round I's I-1.2 (the remaining
  64 sleep conversions), I-5 (Round H's new leaves);
* area A (the whole JavaScript frontend) and area D (verification platform) —
  both untouched, as the round's design says;
* the line/branch pair above moved both gated metrics past the recorded
  baseline for the first time since the Round H audit; the next round should
  ratchet it (the numbers live here for now, because `reports/` holds dated
  snapshots rather than a movable floor).

## 6. Reproduction (every number above)

```bash
cd /home/user/Chat-V-bot
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python -m pytest tests -q -p no:randomly \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine

QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs COVERAGE_FILE=/tmp/.coverage_ab \
  .venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q -p no:randomly \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
COVERAGE_FILE=/tmp/.coverage_ab .venv/bin/python -m coverage json -o /tmp/coverage_ab.json

.venv/bin/python tools/metrics/current_audit.py > /tmp/audit_ab.json
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
.venv/bin/python tools/metrics/stores_modules.py
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python tools/metrics/dump_public_api.py --diff   # --write only with the same env
```

Evidence for the lost attempt's unrecoverability: `git ls-remote --heads origin`,
`git log --all --diff-filter=A -- backend/cdp_client_transport.py
backend/cdp_client_events.py backend/history_query_search.py
bridge/history_bridge_read.py`, and a blob-object scan for `CdpEvents`.
