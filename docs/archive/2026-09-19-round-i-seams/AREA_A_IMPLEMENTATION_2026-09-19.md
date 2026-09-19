# Round I / Area A — first transport slice

Date: 2026-09-19 · parent checkout `f8f1d880` · session branch
`arena/01a0bac1-chat-v-bot`.

Plan: `docs/archive/2026-09-19-round-i-seams/ROUND_I_DESIGN_2026-09-19.md`.
**Status: partial Area A implementation; no Areas B–F implemented.**

## Landed

- `backend/cdp_ports.py`: structural `CdpTransport` acquisition/discovery and
  `CdpConnection` send/close/async-frame-stream contracts, with no Qt/network
  imports. Separating acquisition from the established socket protocol avoids
  a redundant send/receive wrapper.
- `backend/cdp_client_transport.py`: `BrowserTransport` retains the original
  WebSocket options (50 MiB frames, 10-second open, 5-second close), HTTP
  session lifecycle, `/json/list` route, 5-second discovery timeout and
  non-200 empty result. Client open/discovery now use the injected adapter.
- `backend/cdp_client.py`: default adapter plus additive
  `client_with_transport(browser, host, port, parent)` construction seam.
  The frozen constructor is unchanged. This is construction-time injection
  through a helper, deliberately not an extra constructor argument that would
  break the snapshot. No network activity occurs during construction.
- `tests/unit/backend/test_cdp_injected_transport.py`: nine tests using a
  scripted fake with real lifecycle/framing/dispatch/evaluate/filtering code.
  Covers default binding, domain order and request payloads, reconnect/close,
  discovery endpoint/filtering, connection failure, events, malformed JSON,
  EOF, and send without connection. No network-module patching in these tests.

The existing patch-based adapter tests remain useful for real adapter options
and HTTP behavior. No API snapshots, selectors, private-gate semantics,
compatibility shims, UI files or dependencies changed. No production bug fix
is smuggled into the lifecycle extraction: pending-request timeout and task
cancellation behavior are deliberately unchanged.

## Validation and reproducibility

Environment: Python 3.11 venv, Node v22.22.3; headless Qt with the repository's
`tools/build_stubs.py .venv /tmp/stublibs` and:

```bash
export QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs
.venv/bin/python -m pytest tests/unit/backend tests/test_cdp_events.py -q
.venv/bin/python tests/test_rule16_new_code.py
.venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
.venv/bin/python -m coverage json -o /tmp/round-i-coverage.json
for f in tests/test_*.js; do node "$f"; done
```

| Check | Result |
|---|---|
| Pre-edit CDP lifecycle/events/API snapshot selection | 53 passed after building Qt stubs; initial import attempt lacked libGL |
| Post-edit backend + CDP events | **284 passed, 1 xfailed, 55 subtests passed** |
| New injected-transport suite + frozen API snapshot, final rerun | **18 passed** (9 new + 9 snapshot checks) |
| Full Python suite | **3275 passed, 72 failed, 2 skipped, 1 deselected, 1 xfailed, 973 subtests passed** |
| Baseline comparison | Restoring the two edited production files to HEAD and excluding only the new test file produced **3266 passed and the identical 72 failure identifiers**. Restored working changes afterwards. No claim of an all-green checkout. |
| RULE 16 executable | 23 checks run, 2 failures reproduced on baseline: stale `PersonPageRequest` location expectations (`history_query.py` vs `history_query_request.py`). Not fixed under Area A. |
| Aggregate observed coverage | **92.85% statements, 88.38% branches** (16495/17766 statements; 3514/3976 branches). Test run has failures; not promoted to the official ratchet baseline. |
| CDP facade coverage | 100% statements, 87.5% branches |
| CDP transport coverage | 97.10% statements, 92.31% branches |
| Node harness | 21/35 files pass, 14 fail; unchanged JS/harness files have missing helper globals such as `UIHelpers`, `SashGridDrag`, `HistoryStoreCore`. Not repaired under A. |
| Diff whitespace | `git diff --check` clean |

New concrete functions were measured separately because the existing owned-
function gate does not automatically select this new seam:

| Function | Physical LOC | Parameters (excluding self) | Radon CC | Cognitive |
|---|---:|---:|---:|---:|
| `client_with_transport` | 11 | 4 | 1 | 0 |
| `BrowserTransport.connect` | 3 | 1 | 1 | 0 |
| `BrowserTransport.discover` | 5 | 1 | 2 | 1 |
| Edited `open_client` | 16 | 2 | 3 | 2 |
| Edited `_fetch_tab_list` | 3 | 1 | 1 | 0 |

Protocol declarations have one-line bodies and ≤1 argument excluding self;
new classes remain below 150 LOC / 15 methods; new nesting stays below 4.
Mutation testing for this slice was **not run**. Meeting the audit's mutation
exit criteria and the remaining RULE 16 verification obligations is not
claimed. Existing coverage percentages do not establish mutant-killing power.

## Remaining Area A work / release gates

Typed probe adapters; private-gate truth-table expansion; selector inventory,
canonical fixed-selector registry and doc parity; sanitized captured DOM/frame
corpus and agent approvals; shim importer inventory; scoped mutation baseline
and ratchet; final review after baseline gate failures are resolved separately.
No live Chrome endpoint or authorized user-session capture was available.
Synthetic protocol tests are not labeled captured evidence. A frozen-DOM test
will not on its own detect a future site change.

This slice makes acquisition fakeable without changing existing contracts;
it does **not** mean every browser-facing component now has a port, every
legacy monkeypatch is gone, or all of Area A has met its exit gates.
