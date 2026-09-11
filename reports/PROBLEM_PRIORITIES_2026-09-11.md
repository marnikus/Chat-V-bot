# Prioritised problem list — what should be fixed next

Date 2026-09-11. Read alongside `CODE_QUALITY_METRICS_2026-09-11_round4.md`;
this document changes nothing, it only ranks what the tree actually contains.

Every number below was measured on this commit (`3b34421`) with the tools in
`tools/metrics/` plus one ad-hoc AST pass over the exception handlers. The inputs
are `/home/user/analysis/audit_round4.json` and `coverage_round4.json`.

Ranking rule, same as the CC pass: **safety consequence first, then silent
regression risk, then measured gate debt, then size.** Effort is in "one PR"
units, and risk means the chance the fix breaks something.

---

## P0 — the safety path fails silently

**1. 147 of 269 blind `except Exception` handlers leave no trace at all.**
Measured as: `except Exception` / `except BaseException` handler whose body
contains no `log.*`, no `report(`, no `*emit(`, no `warning/debug/error(`, and no
`raise`. Distribution of the silent ones:

```
21 of 21  services/db_deletion.py          8 of  9  services/db_deletion_scan.py
19 of 22  services/db_deletion_flow.py     8 of  8  stores/media_fetch.py
13 of 13  backend/message_injector.py      7 of  9  bridge/stack_bridge.py
                                           6 of  6  backend/media_handler.py
                                           6 of  7  services/db_registry.py
```

Sampled by hand, and the honest reading matters: these are mostly
**fail-closed by intent**. `db_deletion.is_within()` — the predicate that decides
whether a path is inside the world directory — returns `False` on any unexpected
error, i.e. "not allowed, do not delete" ✓ correct. `message_injector`'s
readers return `None`/`False` for the same reason. The problem is not that they
are wrong; it is that **nothing in the file distinguishes "silent because it is
safe" from "silent because nobody finished it"**, and the project's own rule says
each one must carry the reason:

> `docs/AGENT_RULES_CODE_QUALITY.md` §2 — "A function that needs a `noqa` must
> say why in the comment; otherwise it is a review comment, not an override."

**200 of 202 `# noqa: BLE001` markers have nothing after them on the line.**
So this is an auditability debt sitting on the deletion path, not (yet) a bug.

*Fix*: one PR per file, smallest first (`db_deletion_scan` 8, `media_fetch` 8,
`stack_bridge` 7, `db_registry` 6, `message_injector` 13, `db_deletion_flow` 19,
`db_deletion` 21): for each handler either add the one-line reason, or add
`log.debug("…: %s", exc)` so a field problem is at least findable in the run
file. Effort 5 small PRs. Risk: ~zero (no behaviour change).
*Why first*: it is the only item on this list where the failure mode is "a user
loses data or a deletion silently does nothing, and the log has nothing to
say".

**2. `app/lifecycle.py` — startup/teardown at 35.8 % line, 0.0 % branch coverage.**
The worst-covered production file, and it is the one that decides whether the
database handles and the delete lock are released on exit (RULE 18 §3:
"unlock/delete temp files on exit, even on crash"). Its branches are *entirely*
unexercised: the crash paths are the ones that matter.
*Fix*: 3–4 tests driving the lifecycle with an injected failure (close raises,
lock held, DB already gone). Effort 1 PR. Risk: none (tests only).
*Why here*: an untested teardown on a tool that deletes files is the difference
between a corrupt world and a recoverable one.

## P1 — the gates are not enforced by anything that runs

**3. There is no CI.** `.github/` does not exist. Every rule in
`docs/AGENT_RULES_CODE_QUALITY.md` is checked by hand, which is how a project
gets a "159 → 138" number only in the rounds where someone felt like measuring.
The tools exist and are fast (`gate_check` over the whole tree: ~20 s;
`current_audit`: ~4 s; `clone_scan`: seconds) — a workflow running them plus
`pytest -q` plus the 24 JS harnesses would make the rules real.

**4. The rule-checking tests silently no-op without dev tools.**
`requirements-dev.txt` documents it in its own header: "The gate
(`tests/test_rule16_new_code.py`) **skips** the complexity and smell checks when
they are absent rather than pretending to pass." Honest — but the effect is that
a fresh clone without the five extra packages passes with zero quality checks.
*Fix for 3+4 together*: one workflow file + make `test_rule16_new_code.py` fail
(rather than skip) when the tools are missing on a CI run. Effort 1 PR each.
Risk: none. **Highest leverage per line changed on this list.**

**5. 22 JS suites are run by hand.** `tests/test_*.js` (22 files: grid
persistence, panel boot, lazy paging, sash resize, the user-memory sort…) are
standalone scripts you invoke with `node tests/test_grid_persistence.js`. Six
Python tests do shell out to `node` — but only to `tests/js_harness.js`, the
DOM-stub probe runner, not to those 22 suites. So the front-end behaviour the
JS files pin has no automated trigger, and nothing fails when one rots. The two
`tests/*.js` helpers (`js_harness.js`, `dom_stub.js`) are the exception: they are
inputs, not suites.
*Fix*: one `tests/test_js_suites.py` that globs `tests/test_*.js`, runs each with
`node`, asserts exit 0 — exactly the shape of the six node-calling tests that
already work.
Effort: small. Risk: it will fail on day one for whatever has rotted (that is the
point); budget one follow-up to green it.

**6. Mutation testing covers one file.** `setup.cfg` scopes mutmut to
`backend/history_query.py`: 1 of 141 production files, while RULE 16 §2 asks for
"≥ 70 % mutation score". Round 4's number (94.34 % of executed, 150 killed / 9
survived) is real but tiny in scope, and 964 of 1,123 mutants have "no tests" —
which is the same fact stated differently. *Fix*: widen `source_paths` one
package at a time (start with `stores/`, whose suites are fast), and re-report
killed/survived/**no-tests** as three numbers, never folding no-tests into
survived. Effort 1 PR + patience for runtime. Risk: none to the app.

**7. `HistoryBridge` has 7 lines and 0 methods of headroom.** The ratchet in
`tests/test_rule16_new_code.py` pins `493 LOC / 45 methods`; the file is
**486 / 45**. The next person who adds a bridge method — or six lines — gets a
red test they did not cause. The pin is correct (splitting is the job), but a
pin that trips during an unrelated feature is a bad day waiting to happen.
*Fix*: schedule the split (it is P3-12), or annotate the ratchet with a pointer
to the design doc so the failure tells the developer what to do. Also fix the
comment/code drift: the docstring in that test says "490 LOC" where the pin dict
says 493.

## P2 — measured gate debt, ranked by what a reader has to hold

The 138 over-gate functions decompose like this (this is the shape of the
remaining work, and it is *not* mostly CC any more):

```
54  params > 4 only          28  LOC > 30 only
17  CC > 10 only             12  LOC + CC
 6  LOC + CC + cognitive      3  LOC + params + CC
 2  nesting only              1  cognitive only   (+ a few other pairs)
```

**8. Params is now the biggest category: 54 functions over 4.**
Concentrated in the repo family and the bridges:
`stores/history_repo_append.py::append` (13 params, CC 11, 54 LOC),
`stores/history_repo_lifecycle.py::_after_write` (8),
`backend/chat_parser.py::verify_private` / `settle_after_top` (5 each, both also
over LOC and CC), `actions/click_user.py::_verify_new_tab` (5),
`stores/history_repo_identity.py::_ui_record` (5) and `_same_conversation` (6).
This is the item the last round deliberately left alone, and it is why some of
the others are stuck: RULE 16 §6.2 forbids adding a parameter to a function that
already breaks the gate, so several CC fixes *cannot* be done cleanly until a
parameter object exists.
*Fix*: design the parameter objects first (one PR for the repo family —
`AppendRequest` / `AfterWriteFacts` style value classes — one for the two
`chat_parser` entry points), then the CC fixes come cheap. Effort: 2–3 PRs, but
they touch call sites across `stores/` and `backend/`. Risk: medium — these are
write-path entry points, and the harness protocol (differential vs
`git show <base>`) is mandatory here.

**9. CC > 10: 42 by the audit (46 by the gate tool, which also counts nested
defs).** 41 open + 1 frozen. Highest priority within it — by branch count ×
cognitive × thin coverage:

| prio | function | CC | cog | LOC | cov | why it is where it is |
|---|---|---|---|---|---|---|
| 7 | `backend/dom_probe.py::interpret` | 14 | 22 | 38 | 98 % | the probe-answer decoder; every block reads its verdict through this |
| 7 | `backend/message_injector.py::click_send` | 14 | 14 | 46 | **70 %** | the send click, and the file is the second-worst covered in `backend/` |
| 7 | `services/undo_service.py::work` | 14 | 19 | 41 | 83 % | inside the undo apply path (see P0) |
| 7 | `stores/user_memory.py::replace_all` | 14 | 18 | 39 | 99 % | queue-wide rewrite; high blast radius |
| 6 | `backend/cdp_client.py::get_cookies` | 13 | 16 | 27 | **64 %** | auth-sensitive, poorly covered |
| 6 | `backend/history_query.py::person_stats` | 15 | 11 | 31 | 97 % | last size+CC offender in the file round 4 rewrote |
| 6 | `services/collector_service.py::handle_push` | 15 | 13 | 39 | 89 % | also owns the one runtime warning the suite reports (unawaited coroutine) |
| 6 | `stores/history_repo_identity.py::_ui_record` | 15 | 14 | 26 | 97 % | blocked by its 5 params (item 8) |
| 5 | `backend/chat_sync.py::plan` / `::_settle_at_top` | 15 | 14/15 | 26/30 | 96 % | the file with the worst MI in the repo (11.9) |
| 5 | `stores/history_models.py::from_dict` | 15 | 9 | 20 | 100 % | pure mapper → trivial table-driven fix, good first pick |

*Fix*: one file per PR on the round-4 protocol (gate_check → differential
harness → targeted tests). The frozen `stores/migration.py::migrate_legacy_config`
(CC 19, 79 LOC) is **not** on this list — see P4-19.

**10. Two functions whose only crime is nesting are the two hardest to read:**
`backend/cdp_client.py::fetch_tabs` (nesting 5, 64 % covered) and
`bridge/collector_bridge.py::collector_command` (nesting 6, 65 %). RULE 18 says
four frames is what a reader holds; six is not reviewable. Cheap to fix, and the
coverage of those two files is where it is precisely because nobody can follow
the flow. Do them with item 9's `get_cookies` (same file).

**11. A measurement blind spot worth a rule amendment.**
`services/undo_service.py::_apply_db_command` reads **CC 5** because radon
attributes a nested closure's branches to that closure — while the same body
measured whole is **cognitive 31**, the highest in the file. All three tools in
`tools/metrics/` inherit radon here, so "CC ≤ 10" cannot by itself clear a
function that hides its branches inside `async def work(): …`. Round 4 worked
around it by using LOC + cognitive as tie-breakers; the durable fix is to make
`gate_check`'s whole-body cognitive number the gate for functions containing a
nested `def`, and to say so in §1 of the rules file (one line). Until then,
`undo_service` and `services/run/hooks.py` (which has three nested hooks) are
under-measured.

## P3 — size and architecture

**12. 38 classes over the 150 LOC / 15 method gate; 11 over 300.** The five
that block the most work, with their file's coverage:

```
504 LOC / 36 m  backend/scroll_parser.py::ScrollParser        (file 94 % cov)
503 LOC / 36 m  services/collector_service.py::Collector      (89 %)
486 LOC / 45 m  bridge/history_bridge.py::HistoryBridge       (65 %)  ← P1-7
444 LOC / 26 m  services/undo_service.py::UndoService         (83 %)
368 LOC / 18 m  stores/history_repo_lifecycle.py::PersonLifecycle (95 %)
```

`ScrollParser` and `Collector` are the two where the *next* feature will land and
the file will tip further. `HistoryBridge` is the one with a pin on it.
*Fix*: each needs a design doc before code (round 4's report §7 phase 4 says the
same and I agree — starting them without one is how a 500-LOC class becomes two
300-LOC classes that still don't fit).

**13. Ten import cycles, all through `backend`.** The cheapest cut is already
known: retiring the two back-assignment shims
(`backend/bridge.py:9-10`, `backend/action_engine.py:3`) removes four of the ten
and takes four `# noqa: F401` re-export markers with them (the production tree
carries 48 of those in total, most of them legitimate seams like
`backend/chat_parser.py:31`). Low risk, low effort, and it makes item 8's parameter objects
easier to place. No complexity benefit — do it as a housekeeping PR.

**14. Duplication: 12 exact-AST clone groups / 90 physical lines (flat since
round 3).** The largest is a 15-line pair —
`actions/click_back.py:20` vs `actions/click_main_tab.py:19` — the
`FIELDS = (BlockField(selector…), BlockField(child_selector…), …)` block-schema
declaration. A shared `_SELECTOR_FIELDS` tuple (or a base-class default) kills the
biggest group outright. The rest are `BaseAction.__init__` boilerplate pairs;
pylint R0801 still reports 1 group.

**15. Worst maintainability (radon MI): `backend/chat_sync.py` 11.9,
`services/db_deletion.py` 20.5, `services/undo_service.py` 21.4,
`bridge/history_bridge.py` 23.7.** Three of the four are the deletion/undo path,
which is why P0 and P2-9's `undo_service` rows matter more than the CC numbers
elsewhere. Note `chat_sync.py`'s MI is driven by size (its 2 CC-15 functions are
*inside* the gate) — a split, not a branch fix.

## P4 — hygiene, and debts this report owns

**16. Four files lost per-file coverage in round 4** because the new helpers'
defensive arms are proven only by throwaway harnesses:
`stores/label_state.py` 94.5 → 93.3, `services/history/mutate.py` 95.3 → 94.2,
`services/history/runtime.py` 89.0 → 88.5, `services/run/error_recovery.py`
96.4 → 96.3 (ten files rose, including `actions/cancellation.py` 76.3 → 82.9).
*Fix*: lift the nine `/tmp/diffh/diff_*.py` harness scenarios into `tests/` as
property-ish unit tests (they already know how to build the fixtures). That
also closes the "every new function has a test" half of RULE 16 §5 properly
instead of by argument. Effort: 1–2 PRs, no production change.

**17. `tests/test_rule16_new_code.py` counts nested `def`s as methods.** A
consequence worth recording: extracting a nested helper into a *method* counts
twice against a class ceiling, which is why round 4 pushed helpers to module
level instead. The file already relies on this; if the counting ever changes,
the ratchet moves. One sentence in the test's docstring is enough.

**18. Metric definitions that must not be compared across rounds** (round 3 and 4
say this too, but it belongs in one list):
- Round 3's branch coverage **88.99 %** used `(num_branches − partial) /
  num_branches`, which counts wholly-uncovered branches as covered. Under
  coverage.py's own definition round 3 is **84.38 %** and round 4 is **84.53 %**.
  Do not compare a new branch number with any figure ≥ 88 % in rounds 1–3.
- Round 3's TDR (7.8 % / 10.9 %) used 27 in the oversized-class term where the
  same audit reports 35–38; round 4 restated both sides (8.2 → 6.9 structural,
  11.3 → 10.1 with test debt). Rounds 1–2 TDR figures are unusable.
- `deep.py`-style nesting numbers from round 1 are wrong (the corrected
  definition lives in `current_audit.py`).
- Churn and bug density remain **unavailable**: the checkout has one commit of
  history and no defect ledger. Anything that claims a trend in those two is
  invented.

**19. `stores/migration.py` is the one file that cannot comply.** Its
`migrate_legacy_config` (CC 19, 79 LOC, the largest function in the repo after
the exempt `dom_probe.build_probe`) is pinned byte-for-byte by
`tests/unit/stores/test_stores_public_api.py`. The freeze is *right* — it is the
importer for old user files — but the repo has no way to record "exempt on
purpose", so the number will be re-litigated every round.
*Fix (a decision, not a refactor)*: add an explicit exemption list to
`gate_check.py` + one line in the rules doc, or lift the freeze. Five minutes
either way, and it makes "max CC = 19, and that is intentional" a fact the tools
print instead of a paragraph someone writes.

**20. The GUI has no automated execution.** `test_sash_webengine.py::test_grid_in_real_webengine`
is deselected in every documented run because it aborts the interpreter without
real GL; the grid, panels and paging are covered only by the 22 hand-run JS
suites plus DOM stubs. Combined with item 5 that is the real gap: not
"coverage is 90 %" but "nothing machine-runs the front end". Fixing 5 (a pytest
wrapper over `tests/*.js`) gets most of the way there without needing a GPU.

**21. `requirements.txt` is unpinned** (5 runtime deps, all `>=`), while
`requirements-dev.txt` is fully pinned. A fresh install can drift into a
PySide6/aiohttp minor version that changes Qt or CDP behaviour. One PR: pin with
`==` or add a lockfile note; it is also what makes a CI runner reproducible
(items 3–5).

---

## Suggested order of work

```
1  item 5   pytest wrapper for the 22 JS suites            1 PR    no risk
2  item 4  + 3   fail-not-skip gate + a CI workflow         1 PR    no risk
3  item 19   gate_check exemption list for migration.py    1 PR    no risk
4  item 1    noqa reasons / debug logs, deletion path first 5 PRs   ~no risk
5  item 2    lifecycle teardown tests                       1 PR    no risk
6  item 16   harnesses → repo tests                         2 PRs   no risk
7  item 9  + 10   CC tail, one file per PR                  ~12 PRs low (protocol exists)
8  item 8    parameter objects                              3 PRs   medium
9  item 11   measure whole-body cognitive for nested defs   1 PR    low
10 item 13 / 14 / 21   cycles, biggest clone, pins          3 PRs   low
11 item 12   the two god classes, docs first                design  high
```

Items 1–6 are what stop quality from sliding back; 7–10 keep shrinking the
measured tail; 11 is the one that needs thinking before typing. If only two
things get done, do **1** (nothing runs the front end) and **4** (the gate
currently passes when the tools are missing).
