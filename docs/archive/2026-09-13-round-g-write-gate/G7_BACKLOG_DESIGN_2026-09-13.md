# G7 — The backlog step: JS instrumentation, the stores wide-param seven, the cohesion passes

Date: 2026-09-13. Round G step 7 (ROUND_G_DESIGN_2026-09-13.md §2 line G7):
the items every earlier step deferred or scheduled here. Four families, one
commit each:

1. **JS coverage instrumentation** (§1 below) — the §1e item "23 frontend JS
   files / 9 237 LOC plus embedded JS payloads sit outside every denominator".
2. **The 7 deferred `stores/` wide-parameter offenders** (§2) — G4's scope
   ruling: `history_repo_append.append` 13, `history_repo.append` 13,
   `history_repo.rename_if_same_conversation` 8, `history_repo.recover_media` 6,
   `media_store.__init__` 6, `history_models.fingerprint` 6,
   `history_models.dedupe_key` 5. "Golden-pinned store API … deserves its own
   design pass. This is a scope ruling, not a freeze."
3. **`HistoryExportService` 21-method pass** (§3) — over the 15-method cap.
4. **`StackBridge` / `ScrollParse` cohesion passes** (§4) — 308/31 LCOM\* 0.89
   and 306/14 LCOM\* 0.92, the §1d "genuine candidates".

## 1. JS coverage instrumentation — EXECUTED

### 1.1 The attribution problem and its solution

The 28 Node tests (`tests/test_*.js`, all green standalone) load the frontend
sources with `fs.readFileSync` + `new Function`/`vm` — so V8's
`NODE_V8_COVERAGE` output attributes nothing to them: eval'd scripts are
skipped unless they carry a `//# sourceURL=` pragma, verified empirically on
this Node (v22.22.3) before any tooling was written. The fix does not touch a
single repo test: `tools/metrics/js_coverage.py` mirrors the tree into a temp
directory, **appends** `//# sourceURL=cvb://<relpath>` to every attributed
file (`ui/**/*.js`, `backend/js/*.js` — appending keeps every original byte
offset valid), runs the 28 tests against the mirror under coverage, and maps
the `cvb://` URLs back. V8 offsets are UTF-16 code units; the mapper expands
non-BMP characters (the UI files are full of emoji) before converting offsets
to lines. Merging is the union of covered lines across runs; "executable" is
the union of lines touched by any V8 range.

### 1.2 First measurement — the numbers

Full table, method and interpretation:
[`reports/JS_COVERAGE_BASELINE_2026-09-13.md`](../../../reports/JS_COVERAGE_BASELINE_2026-09-13.md).
Headlines: **24 attributed files, 10 109 lines, 8 889 executable, 7 127
covered — 80.2%** with 28/28 Node tests green under the mirror. The audit's
"23 files / 9 237 LOC" undercounts today's tree by one file
(`backend/js/chat_agent.js`, 803 LOC, 95.4% covered) and ~870 lines of growth.
**Six files are never loaded by any test** — `app.js`, `composer.js`,
`criteria-editor.js`, `log-console.js`, `stack-drag.js`, `url-toolbar.js`
(1 220 LOC, the JS analogue of an uncovered Python module); weakest loaded
files are `presets-ui.js` 47.3%, `sash-grid.js` 64.2%, `user-table.js` 66.1%,
`stack-dnd.js` 66.5%.

### 1.3 Embedded payloads — inventory, not coverage

The AST inventory finds **12 static JS payloads / 420 lines** inside Python
constants (`dom_highlight.py` ×5, `dom_probe.py`, `media_handler.py`, the
three `message_injector_*` files, `scroll_parser_dom.py`, `click_user.py`) and
**zero dynamic (f-string) payloads**. They are sent over CDP as evaluate-text,
so V8 in Node can never see them; the baseline lists them by file and span and
leaves harnessing them (dom_stub-driven runs with per-payload attribution) as
a named Round H candidate. Docstrings mentioning JS are excluded from the
inventory (a first run surfaced that false positive; the exclusion is in the
tool, not the report).

### 1.4 Ruling: measurement, not a gate

This step creates the **denominator**, not a floor. No JS coverage gate is
added to `rule16_gate.py` or the pre-commit path: a floor needs a ratchet
policy and an owner decision on what the never-loaded six mean (harness them
vs. declare them WebEngine-only surfaces verified by the Python-side contract
tests). Both are recorded as Round H candidates; the baseline file is the
comparison point either way. The tool itself obeys the same size norms as its
`tools/metrics/` siblings (no function over 30 LOC, params ≤ 4).

## 2. The seven deferred `stores/` wide-parameter offenders — EXECUTED

### 2.1 Adjudication: migrate all seven

G4's scope ruling deferred them; this step adjudicated each one. None of the
seven is *signature*-pinned: the goldens and JS pins freeze **behaviour and
outputs** (fingerprint strings, dedupe keys, SQL effects), not call shapes —
verified before touching anything (no `call_args`-style assertions on
`repo.append`, and the one variadic `append` that looked like a call site was
a test page-double, §2.4.1). With the AREA-B freeze lifted by owner ruling
2026-09-13 ("remove any restriction to all frozen solutions, redesign any
code as needed" — ROUND_G_DESIGN §1c), all seven migrate to parameter
objects / value classes, each keeping **every field and every default**.

### 2.2 The four waves and the conservation table

| # | Offender (old params) | New shape | Value carrier |
|---|---|---|---|
| W1 | `fingerprint(line, occurrences, prev_line, next_line, prev_prev_line, next_next_line)` — 6 | `fingerprint(line, occ=0)` — 2 | `LineIdentity` frozen dataclass (`line, prev_line, prev_prev_line, next_line, next_next_line, occurrences=0`) with `fingerprint()` / `dedupe_key()` methods; the SEP-joined output is **byte-identical**, so every JS/golden pin is conserved |
| W1 | `dedupe_key(direction, from_nick, ts_display, kind, payload)` — 5 | `dedupe_key(line)` — 1 | same carrier |
| W2 | `AppendPlanner.append` + `HistoryRepo.append` — 13 | `append(req)` — 1 | `AppendRequest` (13 fields; defaults reproduce the old signature exactly, so `**cursor_kwargs()` expansion keeps working — its five keys are fields) |
| W3 | `HistoryRepo.rename_if_same_conversation` — 8 | `(old_nick, new_nick, pane, pane_same=False)` — 4 | `PaneSignature` gained the facade's old defaults (`head_any=""`, `tail_any=""`, `dom_count=-1`) — a widening; the inner `ConversationIdentity` already took it since F5 |
| W3 | `HistoryRepo.recover_media` — 6 | `recover_media(req)` — 1 | `MediaRecoveryRequest` (already existed; the facade now takes what the collaborator takes) |
| W4 | `MediaStore.__init__` — 6 | `(db, cdp=None, options=None)` — 3 | `MediaOptions` (`cache_dir`, `max_file_mb`, `max_cache_mb`, `enabled`; defaults identical). `db`/`cdp` stay constructor arguments — collaborators, not configuration |

Call sites migrated: W1 shim + 16 test files; W2 94 sites (2 production —
`services/collector_push.py`, `backend/chat_sync_persist.py` — + 15 test
files); W3 6 rename sites (1 production: `services/collector_tick.py`) + 14
recover sites (1 production: `chat_sync_persist.py`); W4 18 sites
(1 production: `services/history/__init__.py`). `backend/media_store.py`
shim re-exports `MediaOptions`.

Official walker result: **wide=18 → wide=11, worst=20** — the documented
RULE-3 floor; not one `stores/` offender remains.

### 2.3 The deliberate in-step surface refresh (F0 mechanics)

* `tests/unit/stores/api_baseline.json` regenerated with
  `tools/metrics/stores_api.py --write` **inside this step**, per the F0
  ruling. The diff vs. the old baseline: **zero removals**; changed
  signatures = exactly the six MIGRATED names below; new symbols =
  `LineIdentity`, `AppendRequest`, `MediaOptions`, widened `PaneSignature`
  defaults. Nineteen post-F8 leaf modules became baseline-tracked for the
  first time (the old file predated the splits — a strengthening of the
  pin, not a surface change).
* `tools/metrics/stores_api.py`: `diff()`/`compatible()` gained a
  `migrated=()` exemption. It is deliberately **not** folded into `WIDENED`
  — widened names must keep every old parameter; migrated ones reshape the
  signature on purpose and are only admissible with this design section as
  their justification.
* `test_stores_public_api.py`: new `MIGRATED` frozenset (the six names:
  `fingerprint`, `dedupe_key`, `HistoryRepo.append`,
  `rename_if_same_conversation`, `recover_media`, `MediaStore.__init__`),
  passed to the pre-B1 diff. The frozen-three test now pins the post-G7
  surface: its message records that history_models moved **here**, with the
  baseline refreshed in the same step — undocumented moves still fail.
* Import-count budget pin **41 → 44**, ledgered in the test: +1
  `collector_push.py` (AppendRequest), +1 `chat_sync_persist.py` (one
  `stores.history_requests` line shared by AppendRequest and
  MediaRecoveryRequest), +1 `collector_tick.py` (PaneSignature);
  `services/history/__init__.py` reuses its existing import line (+0). The
  invariant itself holds: no area had to edit an import to keep *working* —
  these three lines are the new call shape, adopted on purpose.

### 2.4 §16.2 test adaptations — compensated, never shrunk

1. **`test_chat_parser_delta.py` (wave false positive):** the mechanical
   wrapper folded a `FakePage.append(raw, raw)` call into an
   `AppendRequest`. `FakePage.append(*records)` is a variadic page-mutation
   double, not the repo facade — unwrapped, unused import dropped. No
   assertion changed; the real guard is the receiver audit now run after
   every wave.
2. **`test_chat_sync_phases.py`:** `FakeRepo.append`/`recover_media` take
   the request objects and `_note` records **all** fields — a dataclass
   cannot distinguish "passed" from "defaulted". One assertion adapted:
   `assertFalse(writes[1].get("align"))` ("a prepend is positional, not
   aligned") could no longer observe *absence*. The invariant moved to where
   the behaviour lives: `test_history_repo_conflicts.py` prepends with the
   default `align=True` and asserts the older prefix lands **above** the
   stored tail instead of being aligned away. The sibling `prepend=True`
   assertion at the adapted site stays. Compensating pin, documented — not
   silent shrinkage.
3. **`test_history_models.py`:** three straggler constructions hand-wrapped
   into `LineIdentity` (W1).

### 2.5 Verification

Per-wave batteries green; `test_stores_public_api.py` 7 passed;
`rule16_gate.py` PASS; walker wide=11 worst=20; **full suite after all four
waves: 2828 passed / 2 skipped / 1 deselected / 1 xfailed / 898 subtests,
exit 0** — the identical pass count to the G6 final battery, so not one test
was lost to the migration.

## 3. `HistoryExportService` — the 21-method pass — EXECUTED

The facade (`services/history/export.py`, 174 LOC) was over the 15-method cap
with **21**: five lazy per-part properties, two real lifecycle methods
(`init`/`close`) and fourteen one-line delegates. Two findings from the
caller audit shaped the pass:

1. **No caller ever touched the five properties** — they are private, and
   every consumer (including the whole test suite) calls the named delegates.
   They collapsed into one `_parts` bundle property (`_Parts.__init__` keeps
   the lazy-import discipline inside the constructor, so the module-level
   cycle stays broken, and all five collaborators are trivial `host`-holders,
   so building them together costs nothing). **−4 methods.**
2. **Three delegates were dead**: `_rebind_db`, `_flush_labels` and
   `_load_world_state` exist as `WorldSwitcher`'s *own* methods, and every
   runtime.py caller invokes `self.*` — the facade copies had zero callers
   (production and tests, verified by grep before deletion). **−3 methods.**

Result: **21 → 14 methods** (audit-confirmed), file 174 → 166 LOC, every
public and test-pinned name unchanged (`init`, `close`, `start`,
`detach_db`, `switch_db`, `migrate_install`, `export_chat` and the six
push/collector delegates the contract tests call directly). The frozen
import-header clone group is untouched — no import line changed.

Batteries: `tests/integration/services` + `tests/unit/services` **498
passed / 117 subtests**; `rule16_gate.py` PASS; vulture clean on the file.

## 4. `StackBridge` / `ScrollParse` — the cohesion passes

### 4.1 `StackBridge` — EXECUTED (330/31, LCOM\* 0.89 → 122/23, 0.667)

The wire surface is sacred: QML calls the twenty-one `@Slot`s by name and
listens to the eight `Signal`s on this exact QObject. Neither can move, so
the pass keeps `bridge/stack_bridge.py` as **the wire** — every Signal,
every Slot, every name and signature unchanged — and moves all thirty-one
method bodies into `bridge/stack_bridge_parts.py`: five domain parts
(`RunControl` 64/7, `Composer` 23/5, `StackPresets` 78/6,
`TemplatePresets` 42/5, `CustomBlocks` 44/4) plus the `StackBridgeParts`
bundle and the `_Part` plumbing base. Parts emit Qt signals **through the
host QObject**, so signal identity survives; the two static helpers stay
reachable under the bridge name as `staticmethod` aliases because tests
pin them there (`StackBridge._schedule`, `bridge._clean_blocks`).

LCOM\* mechanics: the old class scored 0.89 because each of 31 methods
owned a private slice of state; now every delegate touches the one
`_parts` field (bundle pattern, same shape as G7 §3) and the domain state
lives in small cohesive classes. The 23 remaining bridge methods are the
wire itself — 21 slots plus `__init__` and `_log` — which is the §1d
"facade is the house shape" ruling applied to a QObject: the count is
immovable without breaking QML, and the audit shows why it is honest now
(122 LOC, no logic, one shared field).

§16.2 adaptation (one, strengthened): `test_merge_undo_enabled.py::
test_bridge_no_longer_builds_a_scroll_parser` inspects
`getsource(StackBridge.run_stack)` for `engine.execute()` — the body moved,
so the pin now inspects `RunControl.run_stack` (the real implementation,
which was always the test's stated intent) **and additionally** asserts the
bridge delegate forwards to it. The pin got strictly stronger.

Batteries: bridge suites **191 passed**; `rule16_gate.py` PASS (clone scan:
0 new groups); `dump_public_api.py` "no removed or changed symbols"; audit
table above.

### 4.2 `ScrollParse` — EXECUTED (300/14, LCOM\* 0.92 → 150/7 0.778 + `ScrollRunPart` 197/12 0.545)

`ScrollParse` is the most-pinned class in the repo: RULE 3 block wire
(`__init__` params=20 under a §16.4 quality-override, blocks are built by
`cls(**data)`), the `_KNOB_CASTS` insertion order is wire-visible through
`to_dict` (a `vars()` walk that skips `_`-prefixed keys), `config_schema`
is a pinned METHOD, and `tests/unit/actions/block_wire_snapshot.json` pins
the serialised block byte-for-byte. The G3 note stands: init/schema/to_dict
behaviour stays identical.

The pass therefore splits **wire from run**: the block keeps the knob
table, `__init__`, `config_schema`, `execute` and one-line delegates for
`build_filter`/`to_scroll_options`/`build_parser`/`run_pipeline`; the eight
pipeline/builder methods move to `ScrollRunPart`
(`actions/scroll_parse_run.py`), which reads the knobs through
`self._block`. No test ever called the eight privates (verified by grep),
so **zero test adaptations** were needed and every public name/signature
stays.

The one design decision worth recording: a first draft moved
`PipelineRun`/`ScrollCallbacks` into the new module and re-exported them —
the AREA-D dumper then reported **5 drift entries** (the dumper records the
*owning* `__module__`, and three delegate annotations quote the dotted
path in their signature strings). Since F0 permits a refresh but never
*requires* one, the zero-drift shape won: the two dataclasses stay defined
in `scroll_parse.py`, the part imports them from there, and the block
imports `ScrollRunPart` lazily inside `__init__` (the house cycle-breaker,
same shape as G7 §3). Result: `dump_public_api.py` reports **no removed or
changed symbols** — both goldens untouched.

Details: `_run` is `_`-prefixed, so the `to_dict` vars-walk never sees it
and the block golden is byte-identical; `__init__` stays at exactly the
30-LOC cap (a comment line was compressed to make room for the lazy
import); `last_result` remains an attribute of the block (the part writes
it through `self._block`).

Batteries: `tests/unit/actions` + the four scroll suites + run_safety
**300 passed / 24 subtests**; `rule16_gate.py` PASS (clone scan 0/0);
vulture: only the pre-existing wire param (`execute(user_nick)`, allowed
by AGENT_RULES §Dead-code row); audit table above.

## 5. Verification battery

* Per family: targeted suites; `rule16_gate.py`; `dump_public_api.py` against
  both goldens whenever a public surface moves; stores import-count baseline
  41 (→ **44** after §2, ledgered in `test_stores_public_api.py`).
* Step end: full suite with the WebEngine deselect + coverage over the 8 roots
  — floors 91.3059 line / 87.4271 branch (the G6 result).

## 6. OUTCOMES (filled during/after execution)

* OUTCOME_JS: tool + baseline committed; 80.2% measured; ruling §1.4.
* OUTCOME_STORES: **all seven migrated** (commit G7.2) — LineIdentity
  (fingerprint 6→2, dedupe_key 5→1, SEP-join byte-identical), AppendRequest
  (13→1, 94 call sites), rename 8→4 via widened PaneSignature, recover_media
  6→1, MediaOptions (6→3). Walker **wide=18 → 11, worst=20 = the documented
  RULE-3 floor**. Baseline refreshed in-step (zero removals; 19 leaf modules
  newly pinned); `migrated=` exemption added to stores_api.diff; MIGRATED
  frozenset; import budget 41→44 ledgered. §16.2 adaptations: 2, both
  compensated (§2.4).
* OUTCOME_EXPORT: **21 → 14 methods** (commit G7.3) — five lazy properties
  collapsed into one `_parts` bundle (zero external callers), three private
  world delegates deleted as dead (WorldSwitcher owns the names; every
  runtime.py caller calls its own). File 174→166 LOC; every public/tested
  facade name unchanged.
* OUTCOME_COHESION: **StackBridge 330/31 LCOM\* 0.89 → 122/23 0.667** +
  five parts (commit G7.4; wire facade: 8 Signals + 21 @Slots unchanged;
  one strengthened §16.2 source-inspection adaptation). **ScrollParse
  300/14 0.92 → 150/7 0.778 + ScrollRunPart 197/12 0.545** (commit G7.5;
  RULE 3 wire untouched, ZERO golden drift — dataclasses stay owned by
  scroll_parse, lazy part import; zero test adaptations).
* OUTCOME_SUITE: **2828 passed, 2 skipped, 1 deselected (sandbox WebEngine),
  1 xfailed, 898 subtests** — the identical count to the G6 final battery:
  not one test lost across the whole step.
* OUTCOME_COV: **line 91.3804 % (floor 91.3059, +0.07 pp), branch 87.5066 %
  (floor 87.4271, +0.08 pp)** — both above; scope identical (eight roots,
  `--cov=main`); 15956 → 16065 statements; every new file individually
  85–100 % line. Floor file for the next step: `/tmp/coverage_g7.json`.
* OUTCOME_GATES: `rule16_gate.py` PASS incl. `--with-clones` (0 new groups,
  0 stale); `dump_public_api.py` against both goldens: "no removed or
  changed symbols"; `test_stores_public_api.py` 7 passed (refreshed
  baseline, budget pin 44); vulture: only pre-existing wire params;
  ScrollParse `__init__` at exactly the 30-LOC cap with its §16.4
  override intact.
