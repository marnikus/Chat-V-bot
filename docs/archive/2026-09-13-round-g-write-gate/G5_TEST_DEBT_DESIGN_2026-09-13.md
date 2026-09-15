# G5 — the test-debt batch: design and executed record

**Date:** 2026-09-13 (Round G, step 5)
**Plan reference:** ROUND_G_DESIGN_2026-09-13.md §1e (test-quality tail) and §3 (row G5)
**Baseline:** G4 tip (suite 2808 passed; coverage floor line 91.0949 / branch 87.0557,
`/tmp/coverage_g4_final.json`)

## 1. Targets, with the measured evidence

Uncovered lines re-measured from the G4 coverage JSON (not quoted from Round F):

| module | pct | missing lines | what they are |
|---|---|---|---|
| `services/undo_history.py` | 85.71 | 54–58 | `_migrated_entry` — **the whole body**; §8.12.5: the seq-preserving rebuild whose bug pushed every app entry ahead of the world entries and issued duplicate seqs |
| `services/undo_world.py` | 84.52 | 66–68, 72–73, 79–80, 98, 113 | `restart_world`'s three failure paths (queue switch warning, undo-sync warning, the emit `except: pass`); `_schedule_world_undo_save`'s body; `sync_world_state`'s malformed-entry skip |
| `services/undo_apply.py` | 92.39 | 40–41, 60, 81, 151, 153, 167, 244 | the eight attributed lines: `_values_equal`'s json fallback, `_position_of`'s equality (non-identity) match, `_apply_labels_command`'s refusal, the archive command's two refusals, `rewind_after_failure`'s non-dict guard, `redo`'s cannot-re-apply `Err` |
| `services/undo_service.py` | 93.25 | 113, 115, 133, 159–160, 184, 238 | bonus, same family: `attach`'s dbs/memory slots, `_clean_history`'s non-list `[]`, the two delegate bodies, and 159–160 — see §5 |

## 2. Remedy — one gaps file in the established convention

`tests/integration/services/test_undo_history_world_gaps.py`, in the convention of
`test_services_undo_gaps.py` (which covers the `undo_db` seams): module docstring naming
the seams, unittest classes, standalone-runnable. Every test asserts **behavior**, not
line execution (§16.2 — coverage is the by-product, never the assertion):

* `_migrated_entry` — through a real `UndoService` (covering the `undo_service.py:184`
  delegate in the same stroke): a positive int `seq` is preserved verbatim; a missing,
  non-int, or non-positive `seq` is NOT carried over; the rebuilt entry otherwise equals
  `_history_entry(kind, value)`.
* `restart_world` failure paths — with `RestartDeps` fakes: a raising `switch_db` logs a
  warning and the restart STILL announces the world live; a raising `sync_world_state`
  same; a raising `archive.my_nick` is swallowed by the `except: pass` and the final
  `log.info` still runs. Each asserts both the warning channel and the continuation.
* `_schedule_world_undo_save` — `WorldSync` with a recording `_world_store` (line 98) and
  the `undo_service.py:238` delegate through a real service with a patched `_world_store`.
* `sync_world_state` malformed skip (line 113) — raw list containing a non-dict and a
  dict without a string `kind`: both dropped, the valid entry survives into the commit.
* `undo_apply`'s eight: `_values_equal` with json-hostile values falls back to `==`;
  `_position_of` finds an equal-but-not-identical entry; `_apply_labels_command` refuses a
  non-dict snapshot; `_apply_archive_command` refuses an unknown op and, with archive and
  people both unwired, a known op; `rewind_after_failure(None, …)` returns quietly;
  `redo` on a command entry whose `apply_command` fails returns
  `Err("nothing_to_redo", "cannot re-apply …")` and moves no pointer.
* Bonus: `attach(UndoDeps(dbs=…, memory=…))` fills exactly those two slots and leaves the
  rest; `_clean_history("not a list") == []`.

## 3. F6b — module-wide mutation measurement of `history_query.py`

Method (F6 §9.6 defined the shape; this step pays the runtime it declined to quote):

1. temporarily widen `setup.cfg`'s `pytest_add_cli_args_test_selection` with
   `tests/test_history_query_edges.py` — the file F6 measured at 910 reachable of 1 141
   mutants when added to the four pinned suites;
2. `.venv/bin/mutmut run --max-children 8` (QT offscreen + stublibs in the environment;
   `--noconftest` stays load-bearing exactly as the setup.cfg note records);
3. record killed / survived / reachable in §7; investigate every survivor one mutant at a
   time (F6's method — a survivor here means "no SELECTED suite kills it");
4. revert `setup.cfg` — the committed pre-commit job stays the narrow ~25-second one; F6
   rejected widening it and this step does not re-litigate that. `mutants/` is gitignored.

## 4. The `dbconn` rewind asymmetry — decision recorded, implementation NOT taken

§8.13.3 named it: a refused `dbconn` op does not `rewind_after_failure` the way `archive`
does. The plan row gates implementation on an owner ruling ("decision + implementation if
the owner rules"), and the ruling has not been made. The decision material, so the owner
can rule in one reading:

* **What rewind would do:** on a failed dbconn undo/redo, put the pointer back ON (undo) /
  IN FRONT OF (redo) the entry, so the next Ctrl+Z retries the same command — the archive
  semantics, `undo_apply.rewind_after_failure`'s documented contract.
* **Why it was parked:** the retryability question is about LEGACY delete entries. A
  retried `dbconn` delete-undo restores a deleted world from its backup; D4
  (SYSTEM_OF_RECORD) says a deleted world stays deleted for NEW entries, and
  `test_services_undo_gaps.py` locks today's ordering ("the timeline moves at once",
  `_announce` built from the DbManager's own result). Making failures retryable does not
  contradict D4 on the success path, but it changes user-visible pointer behavior that
  existing tests pin as-is — a product decision, exactly the class this test-debt step
  must not smuggle (the same rule that locked D4's tension instead of fixing it).
* **Recommendation:** mirror the archive rewind on the spawned work's failure branches
  (`result is None` / not ok) inside `_apply_db_command`, with the two locked tests
  rewritten in the same commit and a negative check that a SUCCESSFUL op still moves the
  pointer once. One hour of work the moment the owner rules.

## 5. Finding — `undo_service.py` 159–160 is unreachable, recorded not covered

Inside `push`'s same-value branch: the redo-tail truncation above it
(`if index < len(history) - 1: history = history[:index + 1]`) guarantees
`index == len(history) - 1` whenever the branch runs, so the inner
`if index < len(history) - 1:` can never be true. F6's rule for the provably-equivalent
mutant applies: recorded, not killed, not removed (removal is a production change this
test-only step does not carry; G6/G7 may take it with its own battery).

## 6. Verification battery

* the new gaps file green standalone and under pytest;
* full suite with the WebEngine deselect — passed count ≥ 2808, no new failures;
* coverage vs the G4 floor: line ≥ 91.0949, branch ≥ 87.0557, and the four undo modules'
  missing-line lists shrink to exactly {159, 160} for `undo_service.py` and ∅ for the
  other three targets;
* `rule16_gate.py --with-clones` EXIT=0; vulture inventory unchanged (7);
* F6b score recorded in §7.

## 7. OUTCOMES (filled 2026-09-13 after execution)

* OUTCOME_TESTS: 20/20 green, under pytest and standalone. `undo_history.py`,
  `undo_world.py`, `undo_apply.py` reach 100% line and branch; the
  `undo_service.py` gap reduces to {159, 160} — the §5 dead branch.
* OUTCOME_F6B: widened-selection full run on this 2-core machine
  (`--max-children 2`, ~2 min at 9 mutants/s): **1 141 mutants — 563 killed,
  578 survived (49.3%), 0 timeouts, 0 "no tests"**. The zero 🫥 is a mutmut-3
  artifact: it maps tests per mutated *chunk*, so every mutant gets at least the
  tests that touched its function, even when they never execute the mutated line.
  Survivor triage (cluster + representative `mutmut show` per cluster):
  * **Class A — selected suites never execute the mutated line** (dominant):
    `around` 100 (its real-person path is tested only in
    `tests/test_history_query.py`, outside the selection; edges' sole around test
    is the missing-person early return, and chunk mapping assigns all 100 to it —
    `person = None` mutants "survive" only because that test never reaches them);
    deep branches of `person_stats`/`page`/`db_stats`/`search_global`/
    `search_person`/`_item_media`/`_snippet`/`day_bounds` whose states the edges
    fixtures do not seed.
  * **Class B — executed, weakly asserted**: `_fts_query` 6 (regex/quote variants
    indistinguishable on the seeded FTS fixtures — e.g. wrapping the split
    pattern in `XX` still phrase-matches the seeded row), `around`'s default
    `radius=25→26`, `stat_int` 3.
  * **Class C — equivalent-under-test**: a minority inside Class B.
  * Regression check: **zero survivors in F6's narrow target functions**
    (request/window/sort mutants do not appear in `mutmut results` at all) — the
    widened selection still kills everything the narrow 159-mutant job killed.
  * Interpretation: 49.3% is the mutation score **of the pre-commit selection**,
    not of the CI suite over the module — the full suite exercises the Class A
    paths. A full-suite mutation run is another (much slower) widening that
    F6 §9.6's method rules out here; recorded as a Round H candidate together
    with an edges-file strengthening pass (never silently merged into this step:
    F6 kept the committed job narrow on purpose and this step does not
    re-litigate that).
* OUTCOME_SUITE: `pytest tests -q` with the WebEngine deselect: **2 828 passed,
  2 skipped, 1 deselected, 1 xfailed, 898 subtests, 481.7 s, exit 0**
  (2 808 before this step + the 20 new).
* OUTCOME_COV: line 91.0949 → **91.3028**, branch 87.0557 → **87.4271** — both
  above the G4 floors. Per-file: the three undo targets have `missing_lines`
  `[]`; `undo_service.py` keeps exactly [159, 160].
* OUTCOME_GATES: `rule16_gate.py` PASS (no production code changed in this
  step); vulture `--min-confidence 90` still exactly 7 findings;
  `test_undo_structure.py` pins green; both AREA-D goldens untouched;
  `setup.cfg` reverted to the committed narrow selection.
