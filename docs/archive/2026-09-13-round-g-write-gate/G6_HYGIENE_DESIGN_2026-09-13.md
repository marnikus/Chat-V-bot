# G6 — Hygiene: notes, imports, the cognitive pair, the rules paydown, the doc map

Date: 2026-09-13. Round G step 6 (ROUND_G_DESIGN_2026-09-13.md §1f). The step
that pays every remaining non-structural debt: stale comments, dead imports,
the two cognitive-17 offenders, the standing test warning, the `AGENT_RULES.md`
line budget, and the two doc indexes. One commit per family.

## 1. Stale `ideal-size:` notes — measured, three corrected

Round F §12.8 found five notes whose numbers lagged their files; G2/G3 dissolved
four of them with the splits. A fresh `wc -l` over every remaining note:

| File | Note says | Actual | Verdict |
|---|---|---|---|
| `backend/config_manager.py` | 509 | 507 | stale → correct to 507 |
| `backend/dom_highlight.py` | 534 | 514 | stale → correct to 514 (G4 shrank it) |
| `backend/history_query.py` | 603 | 601 | stale → correct to 601 |
| `bridge/history_bridge.py` | 544 | 544 | accurate — untouched |
| `services/run/progress.py` | 314 | 314 | accurate — untouched |
| `services/window_preset_service.py` | 326 | 326 | accurate — untouched |

Comment-only edits: no snapshot, metric, or gate can move.

## 2. Unused imports — the four pylint W0611 findings

`pylint --disable=all --enable=W0611` names exactly four, matching the ROUND_G
inventory: `core/events.py` (`field`), `backend/criteria_engine.py` (`field`,
`Optional`), `services/undo_support.py` (`copy`). Removed; the same pylint
invocation must come back empty. No name in any removed import is referenced
anywhere in its file (that is what W0611 measures), so no grep-surprise class
applies.

## 3. The cognitive-17 pair — REDUCED, both, per RULE 19

`current_audit.py` lists exactly two functions over the cognitive fail line:
`bridge/router.py::_build_router_class` (17) and `stores/settings_store.py::get`
(17). Both are reduced rather than exempted, because both are the §19.5 shape —
*long and flat* — where step 4 (extract by concept) is the tool, and both have
concept names already present in the code:

* **`_build_router_class`** is four numbered registration phases around one
  `Meta("Router", …)` call. Phases 1–3 become module-level
  `_register_signals(ns)`, `_register_slots(ns)`, `_register_legacy_attrs(ns)`
  — the names the numbered comments already used; the comments become the
  docstrings. The duplicate-name guards move *with* their phases, so
  `test_router_contract.py`'s two monkeypatched `ValueError("defined by both")`
  tests still exercise them through `_build_router_class()` (the phase functions
  read `BRIDGE_CLASSES`/`BRIDGE_SPECS` as module globals at call time, exactly
  as the loops did). Phase 4 is two lines and stays inline. The local
  `from services.undo_service import _values_equal` moves inside
  `_register_legacy_attrs` — same import-time semantics (call time, not module
  load), same circular-import avoidance. Expected: build ≈ 0, each phase ≤ 6.
  The file grows ~9 scaffolding lines (471 → ~480); `bridge/router.py` carries
  no ideal-size note and no gate baseline entry — the growth is the decomposition
  RULE 19 mandates, recorded here per §16.5's spirit (an offender's *metrics*
  may not worsen; cognitive 17 → ≤6 is the point of the edit).
* **`SettingsStore.get`** walks `self._data` and, on a missing key, restarts the
  same walk on `SETTINGS_DEFAULTS`. The nested restart is the cognitive cost.
  Extract it as `_from_defaults(keys, default)` — a staticmethod; the class goes
  6 → 7 methods (cap 15) and 84 → ~95 LOC (cap 150). Semantics preserved
  exactly, including the two asymmetries: a *dead-end* node (non-dict mid-walk)
  returns `default` **directly** (no defaults walk), while a *missing* key
  restarts the walk **from the root of the defaults tree for all keys**, with
  the caller's `default` as the sentinel and the `node is default` early return.
  `get_copy`/`section` delegate to `get` and are untouched.

Both files keep every public name; no AREA-D payload changes (no signature or
ownership moves — `dump_public_api.py` must stay byte-identical).

## 4. The standing warning — `coroutine 'Collector.handle_push' was never awaited`

`tests/integration/services/test_services_history.py::test_push_binding_ignores_other_bindings`
calls `self.service._on_binding({"name": "__cvbPush", "payload": "[]"})` and
discards the result — which is `Collector.handle_push(...)`'s coroutine object
(`services/history/runtime.py` legitimately *returns* it: in production the CDP
event dispatcher owns the awaitable). The test is already `async`; the fix is to
`await` the call. The assertion stays `assertIsNotNone` (the awaited value is
the handled-push count, `0` for an empty payload — not None, so the pin holds
with unchanged strength). The warning must vanish from the suite's stderr.

## 5. `AGENT_RULES.md` 763 → ≤730 — extract first (§18.4), never cut norms

§18.4's own text prescribes the mechanism and the precedent (RULE 1's worked
examples live in `docs/archive/2026-09-11-rules-appendices/`). The extraction
target is RULE 19: its 22-line ASCII ladder and the repo case studies inside
19.1–19.4 are *worked detail*, while the norms are the order itself, the
fail-line/ideal-line distinction, "never delete a real decision", the
long-and-flat exception, and the verify-after-every-step rule. The ladder +
case studies move to a new appendix
`docs/archive/2026-09-13-rules-appendices/RULE19_REMEDIATION_LADDER.md`
(new dated group, same convention as the 2026-09-11 one); RULE 19 keeps a
condensed normative form of every step plus the two-line pointer in RULE 1's
exact style. Two stale self-references are corrected while the section is open:
§18.4's "It is at that budget now" (it was at 763) becomes the post-paydown
truth, and its hard-coded "78 are archived" count is replaced by a pointer to
`docs/archive/README.md`, which owns the count — a number in a rules file is a
number that goes stale.

## 6. The doc map — `docs/README.md` and `docs/archive/README.md`

* `docs/archive/README.md`: 90 → 92 documents, 18 → 19 groups (the new
  rules-appendices group; the G6 doc itself), with the round-g group row and
  section updated.
* `docs/README.md`: the two "86 archived" counts corrected to the post-G6
  number; the tree gains the new group folder and the round-g annotation
  updated to G1–G6; the "Current vs. historical" table gains the Rounds F/G row
  the ROUND_G inventory flagged (size/parameter rounds: the three round folders
  as the historical column); the `tests/` counts re-measured rather than copied
  (165 + 26 predates three rounds of new test files).

## 7. Verification battery (per family and at step end)

* C1/C2 (comments+imports): pylint W0611 empty; `rule16_gate.py` PASS; targeted
  imports of the three edited modules.
* C3 (production): `tests/unit/bridge_safety/test_router_contract.py`,
  `tests/test_bridge_router.py`, `tests/unit/bridge/test_file_bridge.py`, the
  stores suite, `dump_public_api.py` diff = ∅ against both goldens,
  `current_audit.py` → zero functions with cognitive > 15, `rule16_gate.py` PASS.
* C4 (test): the edited file green and the suite's warning gone.
* C5/C6 (docs): `wc -l docs/current/AGENT_RULES.md` ≤ 730; archive README
  counts match `find docs/archive -name '*.md' | wc -l` minus the READMEs.
* Step end: full suite with the WebEngine deselect + coverage over the 8 roots
  — floors 91.3028 line / 87.4271 branch (the G5 result) must hold.

## 8. OUTCOMES (filled 2026-09-13 after execution)

* OUTCOME_NOTES: three notes corrected (config_manager 509→507, dom_highlight
  534→514, history_query 603→601); the other three measured accurate and left
  untouched. Commit G6.1.
* OUTCOME_IMPORTS: all four removed; `pylint --enable=W0611` on the three files
  reports 0 findings; the modules import clean. Commit G6.2.
* OUTCOME_COGNITIVE: both offenders reduced as designed —
  `_build_router_class` 17 → 0 (phases: `_register_slots` 9 is the new max in
  the file), `SettingsStore.get` 17 → under the fail line; `current_audit.py`
  now lists **zero** functions with cognitive > 15 tree-wide. The router
  contract tests (including both monkeypatched duplicate-name ValueError pins)
  and the stores suite: 178 passed / 709 subtests. `dump_public_api.py`:
  "no removed or changed symbols" — both goldens untouched. Commit G6.3.
* OUTCOME_WARNING: awaited; the file passes under `-W error::RuntimeWarning`
  (32 passed) and the full suite's stderr contains zero "never awaited"
  occurrences. Commit G6.4.
* OUTCOME_RULES: `wc -l docs/current/AGENT_RULES.md` = **728** (budget ~730);
  appendix created; both stale §18.4 self-references corrected. Commit G6.5.
* OUTCOME_DOCS: `docs/archive/README.md` 92 documents / 19 groups (the claimed
  count equals `find docs/archive -name '*.md'` minus READMEs = 92);
  `docs/README.md` counts corrected (86→92 archived, 165+26 → 173+28 test
  files, tree gained the new group and the G1–G6 annotation, the Rounds F/G row
  added to "Current vs. historical"). Commit G6.6.
* OUTCOME_SUITE: **2 828 passed, 2 skipped, 1 deselected, 1 xfailed, 898
  subtests, 476.8 s, exit 0** — the same count as after G5, as expected for a
  behaviour-preserving step.
* OUTCOME_COV: line 91.3028 → **91.3059**, branch 87.4271 → **87.4271** — both
  G5 floors held (the tiny line gain is the new `_from_defaults`/phase
  functions being fully covered).
* OUTCOME_GATES: `rule16_gate.py` PASS ("All owned functions fit. Ratchet
  intact. No stale overrides."); `tests/test_rule16_new_code.py` 23 tests OK;
  vulture `--min-confidence 90` exactly 7 findings; stores import-count
  baseline 41 unaffected (no imports added or removed at module scope).
