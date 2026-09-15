# JS coverage baseline — 2026-09-13 (Round G, step G7.1)

The first measurement of the JavaScript side of this repository. Before this
the frontend sat outside every quality denominator (2026-09-12 audit §3): the
Python suite has RULE 16 §16.3 coverage floors; the 24 attributed JS
files (10,109 LOC) had no number at all.

**Re-run:** `.venv/bin/python tools/metrics/js_coverage.py [--json PATH]`
(no Qt needed; Node v22 on PATH). The tool mirrors the repo into a temp tree,
appends a `//# sourceURL=cvb://<rel>` pragma to every attributed file (V8's
`NODE_V8_COVERAGE` skips `new Function`/`vm`-eval'd scripts without one;
appending keeps every original offset valid), runs all 28 `tests/test_*.js`
under coverage, merges V8 ranges per file (UTF-16 offsets, union across runs)
and reports line coverage. Nothing is written inside the repo.

## Measured (2026-09-13, Node v22.22.3, 28/28 Node tests green)

| File | Lines | Executable | Covered | % |
|---|---|---|---|---|
| `backend/js/chat_agent.js` | 803 | 803 | 766 | 95.4% |
| `ui/js/app.js` | 491 | 0 | 0 | 0.0% |
| `ui/js/collector-panel.js` | 303 | 303 | 289 | 95.4% |
| `ui/js/color-picker.js` | 229 | 229 | 229 | 100.0% |
| `ui/js/composer.js` | 81 | 0 | 0 | 0.0% |
| `ui/js/core/bridge-ready.js` | 74 | 74 | 73 | 98.7% |
| `ui/js/core/dialog.js` | 70 | 70 | 66 | 94.3% |
| `ui/js/core/ui-helpers.js` | 83 | 83 | 83 | 100.0% |
| `ui/js/criteria-editor.js` | 85 | 0 | 0 | 0.0% |
| `ui/js/db-panel.js` | 354 | 354 | 349 | 98.6% |
| `ui/js/history-db.js` | 448 | 448 | 413 | 92.2% |
| `ui/js/history-model.js` | 412 | 412 | 371 | 90.0% |
| `ui/js/history-store.js` | 453 | 453 | 319 | 70.4% |
| `ui/js/history-view.js` | 342 | 342 | 320 | 93.6% |
| `ui/js/labels.js` | 779 | 779 | 747 | 95.9% |
| `ui/js/log-console.js` | 39 | 0 | 0 | 0.0% |
| `ui/js/presets-ui.js` | 474 | 474 | 224 | 47.3% |
| `ui/js/sash-core.js` | 633 | 633 | 604 | 95.4% |
| `ui/js/sash-grid.js` | 1360 | 1360 | 873 | 64.2% |
| `ui/js/stack-dnd.js` | 1248 | 1248 | 830 | 66.5% |
| `ui/js/stack-drag.js` | 356 | 0 | 0 | 0.0% |
| `ui/js/url-toolbar.js` | 168 | 0 | 0 | 0.0% |
| `ui/js/user-table.js` | 448 | 448 | 296 | 66.1% |
| `ui/js/window-presets.js` | 376 | 376 | 275 | 73.1% |
| **TOTAL** | **10,109** | **8,889** | **7,127** | **80.18%** |

"Executable" = lines inside at least one V8 range; "covered" = lines with a
non-zero range count in at least one of the 28 runs. The denominator counts
every line of the file (comments included) only in the Lines column — the %
is covered/executable.

### What the numbers say

* **Six files are never loaded by any Node test** (executable = 0):
  `ui/js/app.js`, `ui/js/composer.js`, `ui/js/criteria-editor.js`, `ui/js/log-console.js`, `ui/js/stack-drag.js`, `ui/js/url-toolbar.js` —
  1,220 LOC with no JS-side
  verification at all. These are the JS analogue of an uncovered Python module
  and the natural first targets for new harness tests.
* Weakest loaded files: `presets-ui.js` 47.3%, `sash-grid.js` 64.2%,
  `user-table.js` 66.1%, `stack-dnd.js` 66.5%, `history-store.js` 70.4%,
  `window-presets.js` 73.1%.
* Strongest: `color-picker.js` and `core/ui-helpers.js` 100%,
  `core/bridge-ready.js` 98.7%, `db-panel.js` 98.6%, `labels.js` 95.9%,
  `chat_agent.js` / `collector-panel.js` / `sash-core.js` 95.4%.

## Embedded JS payloads in Python (inventory, not coverage)

V8 cannot see the JS that lives inside Python string constants — it is sent
over CDP as `Runtime.evaluate`/`addScriptToEvaluateOnNewSource` text. The tool
inventories them by AST (string constants ≥ 8 lines containing ≥ 2 JS markers;
docstrings excluded; f-string payloads would be flagged dynamic — there are
none): **12 payloads, 420 lines**.

| Python file | Line | Span |
|---|---|---|
| `actions/click_user.py` | 25 | 14 |
| `backend/dom_highlight.py` | 39 | 69 |
| `backend/dom_highlight.py` | 203 | 35 |
| `backend/dom_highlight.py` | 242 | 21 |
| `backend/dom_highlight.py` | 267 | 62 |
| `backend/dom_highlight.py` | 403 | 11 |
| `backend/dom_probe.py` | 75 | 61 |
| `backend/media_handler.py` | 55 | 53 |
| `backend/message_injector_field.py` | 34 | 17 |
| `backend/message_injector_send.py` | 23 | 26 |
| `backend/message_injector_type.py` | 31 | 20 |
| `backend/scroll_parser_dom.py` | 24 | 31 |

These 420 lines stay outside the
coverage denominator by construction. Where a payload is exercised at all, it
is through the Python tests that drive it against `tests/dom_stub.js` /
`tests/js_harness.js`; giving them their own V8-measured harness runs is a
Round H candidate, not something this baseline claims.

## Status of this baseline

This file is a **measurement, not a gate**: no JS coverage floor exists yet and
this report does not create one. What it creates is the denominator — any
future JS change can be compared against these numbers, and the never-loaded
list is now visible debt rather than invisible debt. The design record for the
tool and the ruling on floors:
`docs/archive/2026-09-13-round-g-write-gate/G7_BACKLOG_DESIGN_2026-09-13.md` §1.
