# Round I — steps I1–I3

Branch `arena/01a09b51-chat-v-bot`. Three commits, one per step, each
self-contained and fully verified before the next began.

| Step | Commit | Subject |
|---|---|---|
| I1 | `47dfa93` | Hygiene, and the guard that would have caught F2 |
| I2 | `0ec3126` | Single-source the two real logic duplications (F4) |
| I3 | `36a81fa` | Extract `PresetApplier` from `file_bridge` |

## Baseline correction before any work

The audit was taken at `c0e18a2` on a different branch, on a tree WITHOUT the
AI-feature port. Every figure was re-measured here first
(`tools/metrics/current_audit.py`). All I1–I3 targets reproduced exactly —
`dom_highlight.py` 360/MI 56.4, `file_bridge.py` 332/37.5, `stack_bridge.py`
330/39.4 — with one difference: **19** files at 300–399, not 18, because the
port added one. Round I's SLOC baseline is therefore **26,569**, not the
audit's number.

## I1 — hygiene and the missing guard

The headline was not the duplicate deletion but that **nothing could have
found it**: `ElementMatch` and `Overlay` were each defined twice in
`backend/dom_highlight.py`, the second shadowing the first. Vulture sees the
survivor as used, the clone scanner is cross-file, and coverage marks both
`class` statements executed.

Deletion was proved safe, not assumed: pairs located by AST → proved
byte-identical → the shadowed FIRST copies removed → survivors proved
byte-identical to the copies that had been live → top-level name set unchanged
(16→14 defs, same set). 360 → 309 lines.

`tests/unit/test_no_duplicate_definitions.py` closes the gap and is proved
non-vacuous twice, including by reintroducing the actual bug.

Other items, with two corrections to the audit:

- The `import os` in `export.py` justified itself with a claim that hoisting
  it would break a frozen clone group. **The claim was false** — with the
  import hoisted, the clone scan reports 0 new groups. No baseline entry was
  needed.
- F5 understated the problem: **three** `# ideal-size` headers were stale, not
  two (`bot_chat.py` 292→307 was missed because the port landed after the
  audit). Each re-derived from a fresh radon/AST run, and the counts resynced
  after the comment edits changed them.
- `coordinator.py::execute(scroll_parser=None)` was **removed**, not
  documented: unused in the body, no production caller passed it, 35 test call
  sites migrated.
- `test_grid_in_real_webengine` needed no new marker — the existing subprocess
  renderer probe already skips it cleanly (verified with `-rs`).
- Vulture 7 → 5, the survivors inventoried per-finding in
  `reports/VULTURE_INVENTORY_2026-09-14.md`. All are protocol-fixed signatures.

## I2 — the two logic duplications

R0801 in the audited scope (`backend/ bridge/`): **2 → 0**. Tree-wide
(8 packages): **10 → 8**, measured with the same command before and after; the
8 survivors live in a scope the gate has never scanned and are inventory, not
regressions.

- **The JS label idiom** became `CANDIDATE_LABEL_JS`, one definition and two
  callers. `build_probe`'s literal was NOT split to chase LOC — the fragment
  drops into a `%(...)s` slot the function already had. Behaviour pinned by
  measurement: all **8** distinct call shapes byte-identical before/after
  (19,620 chars), the highlight builders likewise, and the probe JS re-run in
  a real DOM through the three Python drivers of `js_harness.js`.
- **The stop/callback guard** now defers to `actions/cancellation.py`, the
  owner of the protocol (RULE 7). `is_stop_requested` was verified equivalent
  at all seven boundaries before reuse — the non-callable case mattered, since
  one site guarded with `callable()` and the other with `is None`. New
  `call_guarded` swallows `Exception` but **not** `BaseException`, so
  `CancelledError` still propagates (asserted). Docstrings were moved, and
  each site kept the fact local to it.

The imports are function-local because `actions/__init__` runs a registry scan
that imports backend back — a top-level import is an observed circular-import
error, not a stylistic choice.

## I3 — `PresetApplier`

Guard first. `test_file_stack_bridge_wire_contract.py` extends H1's
metaobject comparison to FileBridge (7 entries) and StackBridge (29) — 36 wire
entries that had no protection. Proved non-vacuous against real absences: a
deleted `Signal`, and separately a deleted `@Slot` **decorator**, which is the
case that matters because the Python attribute survives it.

8 module-level functions took `bridge` only to reach `ctx` and `_log`; that
pair became `PresetApplier`'s state. `export`/`preview` return `(result, emit)`
so the applier needs no reference to the signals, and the save dialog stays in
the bridge — the applier imports no Qt at all.

| File | LOC | MI |
|---|---|---|
| `file_bridge.py` before | 332 | 37.50 |
| `file_bridge.py` after | 195 | 50.33 |
| `preset_applier.py` | 206 | 57.65 |

RULE 19 checked in order first: max CC was 9, so size genuinely was the
driver. No function's complexity rose. Slot names/signatures unchanged, router
diff **empty**, `dump_public_api.py --diff` clean.

### A real bug surfaced by the new tests

`test_patch_lands_in_the_worlds_app_settings` began failing in full-suite runs
while passing alone. Removing just the new test file made it green, so the new
tests only shifted timing — but the underlying cause is a genuine defect and
was fixed rather than slept around: `_persist_app_settings` called
`create_task()` without holding a reference, and **asyncio keeps only a weak
one**, so the GC may collect the task mid-write and a setting silently never
lands. Tasks are now retained in `pending_writes()` until they settle, and the
test awaits the write instead of guessing 0.05 s.

## Round-wide budget

| | SLOC | vs baseline |
|---|---|---|
| I0 baseline | 26,569 | — |
| after I1 | 26,524 | −45 |
| after I2 | 26,539 | −30 |
| after I3 | 26,610 | **+41 (0.15%)** |

Largest single step +71 (0.27%), inside the 0.5% per-step cap; the round is at
0.15% of its 2% allowance. Mean MI 69.38 → 69.42.

## Verification at each step

Full suite green every time (3,085 passed / 7 skipped / 1 xfailed / 903
subtests at I3, up from 3,077 by the 8 new wire guards), 28/28 Node harnesses
green by exit code, `rule16_gate.py --with-clones` green with vulture and
pylint actually installed, public-API diff clean.

**Not done — steps I4–I14 remain**, including `stack_bridge.py` (330/MI 39.4),
the H-product coverage gaps (F6: `send_button.py` 21.1%, `history_media.py`
37.6%), the F1 rewrite of Round H's closing table, and the 8 tree-wide R0801
pairs inventoried in I2.
