# Area A design — the frontend: measure it, gate it, then take apart the two god objects

Round H · 2026-09-14 · branch scope `ui/**`, `backend/js/**`, JS test/tool files
Part of [`ROUND_H_DESIGN_2026-09-14.md`](ROUND_H_DESIGN_2026-09-14.md).
Source of numbers: [`reports/CODE_QUALITY_METRICS_2026-09-14.md`](../../../reports/CODE_QUALITY_METRICS_2026-09-14.md)
and `/tmp/js_cov_h.json`. **Plan only — nothing implemented.**

## 1. Why this area is first

RULE 16 enforces size and complexity on Python only (`§16.0`: *"New production
function/class in `core/`, `actions/`, `backend/`, `bridge/`, `services/`,
`stores/`, `app/`, `main.py`"*). Everything under `ui/` is therefore outside
every size limit the repository owns. The consequence is measurable:

| | Python (gated) | JavaScript (ungated) |
|---|---:|---:|
| Files | 208 | 30 |
| Lines | 26,333 nonblank/noncomment | 11,865 physical |
| Largest file | 601 | **1,361** |
| Largest class/object | 467 LOC / 31 methods | **1,331 LOC / 69 methods** |
| Longest real function | 54 | **205** |
| Functions over 30 LOC | 39 / 2,268 = 1.7% | 50 / 546 = **9.2%** |

Four rounds of Python refactoring (F, G, and the bot-chat defect round) took the
Python tail down. Nothing has ever touched this one, because nothing measures it.

## 2. Measured state at `5197ce0`

### 2a. Files, largest first (all 30; `ui/js/**` + `backend/js/**`)

| Lines | Coverage | File |
|---:|---:|---|
| 1,361 | 64.2% | `ui/js/sash-grid.js` |
| 1,341 | 67.8% | `ui/js/stack-dnd.js` |
| 803 | 95.4% | `backend/js/chat_agent.js` |
| 779 | 95.9% | `ui/js/labels.js` |
| 642 | 95.5% | `ui/js/sash-core.js` |
| 510 | **0.0%** | `ui/js/app.js` |
| 474 | **47.3%** | `ui/js/presets-ui.js` |
| 458 | 70.7% | `ui/js/history-store.js` |
| 448 | 66.1% | `ui/js/user-table.js` |
| 448 | 92.2% | `ui/js/history-db.js` |
| 412 | 91.3% | `ui/js/history-model.js` |
| 397 | 97.5% | `ui/js/bot-chat.js` |
| 395 | 94.9% | `ui/js/bot-settings.js` |
| 376 | 73.1% | `ui/js/window-presets.js` |
| 356 | **0.0%** | `ui/js/stack-drag.js` |
| 355 | 95.2% | `ui/js/bot-prompt.js` |
| 354 | 98.6% | `ui/js/db-panel.js` |
| 345 | 93.6% | `ui/js/history-view.js` |
| 303 | 95.4% | `ui/js/collector-panel.js` |
| 238 | 99.6% | `ui/js/bot-connection-view.js` |
| 229 | 100.0% | `ui/js/color-picker.js` |
| 195 | 99.0% | `ui/js/dark-select.js` |
| 168 | **0.0%** | `ui/js/url-toolbar.js` |
| 85 | **0.0%** | `ui/js/criteria-editor.js` |
| 83 | 100.0% | `ui/js/core/ui-helpers.js` |
| 81 | **0.0%** | `ui/js/composer.js` |
| 76 | 82.9% | `ui/js/bot-messages.js` |
| 74 | 98.7% | `ui/js/core/bridge-ready.js` |
| 70 | 94.3% | `ui/js/core/dialog.js` |
| 39 | **0.0%** | `ui/js/log-console.js` |

### 2b. The two god objects (this audit's scanner; no repo tool measures them)

**`ui/js/sash-grid.js` — `SashGrid` 1,331 LOC / 69 methods.** Largest members:
`_renderWindowsMenu` 59, `_showSpec` 59, `_ensureWindowControls` 51,
`_setupWindowsMenu` 48, `_renderDock` 43, `validatePortablePreset` 36,
`_computeSpec` 35, `_setupLayoutMenu` 35, `_syncEmptySplits` 34.
Its header names five separate concerns itself: tree rendering, window states
(open/minimized/closed + dock), drag & sash resize, the layout menu and the
windows menu, and portable preset export/import.

**`ui/js/stack-dnd.js` — `StackDnD` 1,168 LOC / 58 methods.** Largest:
**`_showConfig` 180, `_setupButtons` 78, `_renderStack` 75, `_summary` 41,
`pushHistory` 38, `_renderMenu` 36**, `_setupConfigPin` 31,
`_setupKeyboardReorder` 29, `removeBlock` 29.
`_showConfig` is a single HTML-string builder with per-block special cases
(`SPEED_MULTIPLIER` stepped input + quick presets + live preview, `TYPE_MESSAGE`,
`CUSTOM_FIND` constructor rows, …). It is the second-longest function in the
repository (`app.js::setupBridgeListeners`, 205, is the longest) and 3.3× the
longest Python function that is not an embedded JS payload (`stores/history_db.py::init`,
54).

### 2c. Functions over the RULE 16 fail line (30 LOC), top ten

| LOC | Function | File |
|---:|---|---|
| 205 | `setupBridgeListeners` | `ui/js/app.js` |
| 180 | `_showConfig` | `ui/js/stack-dnd.js` |
| 78 | `_setupButtons` | `ui/js/stack-dnd.js` |
| 75 | `_renderStack` | `ui/js/stack-dnd.js` |
| 75 | `init` | `ui/js/user-table.js` |
| 74 | `open` | `ui/js/color-picker.js` |
| 67 | `restoreSession` | `ui/js/app.js` |
| 64 | `renderActive` | `ui/js/labels.js` |
| 61 | `init` | `ui/js/composer.js` |
| 61 | `init` | `ui/js/history-db.js` |

50 functions in total exceed 30 lines; 10 exceed 60; 2 exceed 100.

### 2d. Never loaded by any test (1,239 LOC)

`app.js` (510), `stack-drag.js` (356), `url-toolbar.js` (168),
`criteria-editor.js` (85), `composer.js` (81), `log-console.js` (39).
All six are shipped: every one of them has a `<script>` tag in
`ui/index.html` (lines 711–739). `app.js` is the application entry point — the
file that wires every window's bridge listeners.

## 3. Steps

### H-A1 — measure it (`tools/metrics/js_size.py`)

The JS analogue of the AST walker RULE 18 §18.6 points at. Parses by brace
matching (as the audit did) and reports, per file: total lines, object literals
with LOC + method count, and every function/method with its inclusive LOC span —
the counting rule §16.1 already defines (first line of `def`/`function` through
the last line of the body, decorators/attributes excluded).

* Output: table to stdout, `--json PATH` for the machine-readable form.
* Baseline written to `reports/JS_SIZE_BASELINE_2026-09-14.md` so later rounds
  compare like-for-like.
* Acceptance: the numbers in §2b/§2c of this document are reproduced by
  `python tools/metrics/js_size.py` (the audit's `/tmp/jsfn.js` was the
  prototype; this makes it a repo artefact).

### H-A2 — gate it (`tools/metrics/js_gate.py`, `tests/test_js_gate.py`) — **owner decision D1**

Mirror RULE 16 §16.1/§16.2 on JS:

| Check | Fail if | Counting |
|---|---:|---|
| Function/method LOC | **> 30** | inclusive span, same rule as §16.1 |
| Object literal LOC | **> 150** | §16.1's class rule |
| Methods per object | **> 15** | direct members only |
| File LOC | **> 500** | with a ratchet table for `sash-grid.js` and `stack-dnd.js` that may shrink, never grow |
| Per-file coverage | **decreases** | from `tools/metrics/js_coverage.py --json`; the six never-loaded files ratchet from 0 upward |

Coverage is measured by an existing tool; the gate only compares against the
recorded baseline. The gate is a *separate script*, not a new table in
`rule16_gate.py`, so it cannot collide with Area B/C/D edits to that file.

### H-A3 — split `ui/js/sash-grid.js` (1,361 → facade + parts)

Split along the seams the file's own header already names:

| New file | Owns | Rough size |
|---|---|---:|
| `ui/js/sash-grid.js` | facade: public entry points (`init`, `render`, `applyPreset`, `openWindow`, …) delegating to parts; constants | ≤ 300 |
| `ui/js/sash-grid-tree.js` | split-tree → DOM render, `.sash-split/.sash-window/.sash`, empty-split sync | ~250 |
| `ui/js/sash-grid-windows.js` | windows menu, open/close/minimize/restore, dock strip | ~300 |
| `ui/js/sash-grid-presets.js` | `_computeSpec` / `_showSpec` / `validatePortablePreset` / export-import | ~250 |
| `ui/js/sash-grid-drag.js` | drag by title bar, sash resize, double-click reset, Escape cancel | ~200 |

Target: `SashGrid` ≤ 15 methods, every file ≤ 300 lines, no function > 30 LOC,
coverage of the four parts ≥ 85% (they are the 64.2% file's untested half).

### H-A4 — split `ui/js/stack-dnd.js` and dissolve `_showConfig`

Same pattern (facade + `stack-dnd-render.js`, `stack-dnd-config.js`,
`stack-dnd-history.js`, `stack-dnd-menu.js`), plus the part that matters most:

`_showConfig` (180 LOC) becomes **a table of row builders + one generic
renderer** — RULE 19 §19.2's "lookup tables instead of if/elif chains — tables
are data, not branches":

```js
const ROW_BUILDERS = {
  SPEED_MULTIPLIER: speedMultiplierRow,   // number input + quick presets + preview
  TYPE_MESSAGE:     typeMessageRow,
  ...                                     // default: genericRow
};
```

Each builder 4–20 lines (RULE 18.1), one per block type, individually testable —
which is exactly what the 67.8% coverage is missing today.

### H-A5 — load the six, then split `app.js`

First the harness, then the split (you cannot safely restructure 205 lines that
no test has ever executed):

1. Add Node suites that load `composer.js`, `criteria-editor.js`,
   `log-console.js`, `stack-drag.js`, `url-toolbar.js`, `app.js` against the
   existing DOM-stub pattern (`tests/test_stack_dnd_migration.js` is the model:
   `readFileSync` the real shipped file, eval it against a stub, exercise it).
2. Split `app.js::setupBridgeListeners` (205 LOC) into one registration function
   per window (`_wireStack`, `_wireHistory`, `_wireLabels`, `_wireBot`, …), each
   ≤ 20 lines, called from a short `setupBridgeListeners`.
3. `url-toolbar.js` (168) and `stack-drag.js` (356) are already inside the file
   ideal; they need tests, not splits.

Target: all 30 files loaded by ≥ 1 Node suite; `app.js` ≤ 300 lines.

### H-A6 — lift the weak coverage

| File | Now | Target |
|---|---:|---:|
| `presets-ui.js` | 47.3% | ≥ 80% |
| `sash-grid.js` (+ new parts) | 64.2% | ≥ 85% |
| `user-table.js` | 66.1% | ≥ 85% |
| `stack-dnd.js` (+ new parts) | 67.8% | ≥ 85% |
| `history-store.js` | 70.7% | ≥ 85% |
| `window-presets.js` | 73.1% | ≥ 85% |
| total | 82.8% | **≥ 90%** |

## 4. Constraints this area must respect

* **No build step, no modules.** The app loads plain scripts by `<script src>`
  order in `ui/index.html` (lines 711–739) and the Node suites `readFileSync`
  the same files. A split therefore requires, in the same commit: the new
  `<script>` tags in `ui/index.html` **and** the load order in every affected
  test. Load order is a real dependency (each file expects the previous one's
  globals) — parts must be loaded before the facade that delegates to them.
* **RULE 8.** Tests execute the real shipped file; no re-declaring the module
  inside a test fixture.
* **The DOM stub is the contract.** `tests/dom_stub.js` + the per-test stubs are
  how "the real thing" runs headless; a split that needs a new global must add
  it to the stub rather than special-casing in the module.

## 5. Rejected alternatives

| Rejected | Why |
|---|---|
| Convert to ES modules / add a bundler | Changes the shipping model for every window and every test to satisfy a size rule; RULE 18 asks for readable files, not a toolchain. |
| Split `sash-grid.js` purely by line count (three ~450-line chunks) | §16.1.1: a split must be named by responsibility. The five seams above come from the file's own header. |
| Move `_showConfig`'s HTML templates into a template file | The problem is the *branching per block type*, not the strings; a table of builders removes branches, a template file would relocate them. |
| Leave the six never-loaded files alone | They are 1,239 shipped lines with zero verification, and `app.js` is the wiring of the entire UI. |

## 6. Verification battery (every step)

```bash
node --check ui/js/<changed>.js
for f in tests/test_*.js; do node "$f"; done          # 29 today + the new suites
.venv/bin/python tools/metrics/js_coverage.py --json /tmp/js_cov.json
.venv/bin/python tools/metrics/js_size.py             # after H-A1
.venv/bin/python tools/metrics/js_gate.py             # after H-A2
.venv/bin/python tools/metrics/rule16_gate.py         # unchanged Python gate stays green
```

Plus: `ui/index.html` tag order reviewed by eye against the load-order contract
in §4; no JS file added without a matching test load.

## 7. Cross-area notes

* `ui/**`, `backend/js/**`, `tests/*.js` and `tools/metrics/js_*.py` are owned by
  this area alone. No other area edits them; this area edits no Python
  production module.
* `backend/js/chat_agent.js` is read at runtime by `backend/chat_agent_js.py`
  (a real file on disk, `AGENT_VERSION` 11, so Node can test it). Changing it
  changes Python behaviour — keep it a refactor-with-tests or leave it alone;
  it is the best-covered JS file (95.4%) and is *not* a round-H target.
* `ui/index.html` and `ui/css/**` are not owned by any other area.
