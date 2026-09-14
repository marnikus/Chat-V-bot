# JS size baseline — 2026-09-14 (Round H, step H-A1)

First measurement of the JavaScript side of this repository by a tool that
lives in the repo. The 2026-09-14 audit measured the same 30 files with a
throwaway prototype (`/tmp/jsfn.js`) — this makes the measurement a repo
artefact: `tools/metrics/js_size.py`, with the machine-readable snapshot in
`reports/js_size_baseline.json` (the gate `tools/metrics/js_gate.py` ratchets
against it).

**Re-run:**

```bash
.venv/bin/python tools/metrics/js_size.py            # table to stdout
.venv/bin/python tools/metrics/js_size.py --json P   # machine-readable
```

## Counting rule (frozen)

* **Physical lines** per file: number of newlines + 1 — the same convention
  as `js_coverage.py`, so the two tools agree on a file's size.
* **Function / method span** (the §16.1 rule): first line of the signature
  through the last line of the body, blanks included. `function`
  declarations and expressions, object-literal method definitions
  (including `get`/`set`), and arrow functions with a block body (or a name)
  all count, at every nesting depth — nested functions counted separately.
  Comment lines are not part of a function.
* **Object literal**: reported with its inclusive span and its method count
  (function members only — data keys are not methods). "Gated" objects have
  ≥ 1 method; data-only literals (icon maps, `BUILTIN_BLOCKS` entries) are
  reported but never gated.

## Measured (2026-09-14, pre-split tree of `arena/01a0a11b-chat-v-bot`)

30 files · 11,895 physical lines · 1,075 functions · 73 over 30 LOC ·
13 over 60 · 7 over 100.

| File | Lines | Funcs | Max obj LOC | Max obj methods | >30 |
|---|---:|---:|---:|---:|---:|
| `backend/js/chat_agent.js` | 803 | 61 | 23 | 1 | 6 |
| `ui/js/app.js` | 510 | 43 | 164 | 10 | 4 |
| `ui/js/sash-grid.js` | 1,361 | 127 | **1,331** | **69** | 14 |
| `ui/js/stack-dnd.js` | 1,341 | 104 | **1,168** | **58** | 7 |
| `ui/js/labels.js` | 779 | 63 | 756 | 39 | 7 |
| `ui/js/sash-core.js` | 642 | 45 | 14 | 0 | 3 |
| (the other 24 files — full table in the JSON) | | | | | |

Longest functions: `setupBridgeListeners` 204 · `_showConfig` 179 ·
`_setupButtons` 77 · `_renderStack` 74 · `init` (user-table) 74 · `open`
(color-picker) 73 · `restoreSession` 66 · `renderActive` (labels) 63 ·
`init` (composer) 60 · `init` (history-db) 60.

## Reconciliation with the 2026-09-14 audit prototype

* The two god objects reproduce **exactly**: `SashGrid` 1,331 LOC / 69
  methods, `StackDnD` 1,168 LOC / 58 methods.
* Every named function in the audit's §2c top-ten reproduces within **one
  line** — the prototype included a directly-preceding section-comment line
  in the span (e.g. `setupBridgeListeners` 205 here 204, `restoreSession`
  67 here 66). This baseline follows the documented §16.1 rule (signature
  line through last body line, comments excluded), so those spans are one
  line shorter than the audit's headline numbers.
* The audit's "546 functions / 50 over 30 / 2 over 100" undercounted,
  because the prototype did not descend into the UMD factory wrappers of
  `sash-core.js` / `history-model.js` / `history-view.js` /
  `chat_agent.js`. This tool counts at every depth: that adds the four
  factory functions themselves (327–782 LOC each) and `history-model.js::
  create` (238 LOC — the longest *named* function in the repo, which the
  audit's "largest function is 205" claim missed). The gate ratchets against
  this baseline, so the discrepancy cannot move either way silently.

## What the gate does with this file

`tools/metrics/js_gate.py` re-measures the tree and compares:

| Check | Fail if |
|---|---:|
| File LOC | a file exceeds `max(500, baseline)` — the two god files ratchet only down |
| Function LOC | a **new** function > 30; a baseline function grows |
| Object literal LOC | a file's largest gated object exceeds `max(150, baseline max)` |
| Methods per object | a file's max exceeds `max(15, baseline max)` |
| Per-file coverage | drops below the baseline (`reports/js_coverage_baseline.json`) |
