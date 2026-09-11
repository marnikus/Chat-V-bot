# Code quality, round 5 — what was left, what is biggest, what got fixed

Date: 2026-09-11 (UTC). Branch `arena/01a08dc3-chat-v-bot`, base `53ba5fb`.

Scope of this round (the ask): take the leftover problems from
`reports/PROBLEM_PRIORITIES_2026-09-11.md` and the round-4 report, rank them by
what can be measured, fix the biggest ones, and close with an explicit
RULE 16 / RULE 18 recheck.

Every number comes from a tool inside this repository, run on this tree, and is
compared only against the same tool on the round-4 tree. Where a number is not
comparable to an older figure, that is said next to it.

Two provenance notes that matter for reading the tables:

* `git log` on this branch ends at the base commit `53ba5fb` — rounds 1–4 were
  written into the working tree but never committed (the branch's history
  reverted to the base at some point, and pushing is blocked by the sandbox's
  GitHub auth). So "round 4" below means *this tree minus this round's edits*,
  not a revision you can check out by name.
* For `services/db_deletion.py`, `_flow.py` and `_scan.py` that tree *is*
  `53ba5fb`: rounds 1–4 left those three files alone, which is what makes their
  before/after figures exact (`git show HEAD:<file>` reproduces the "before").

```bash
# complexity / sizes / coupling / duplication
.venv/bin/python tools/metrics/current_audit.py > /home/user/analysis/audit_r5.json
# RULE 16 gates, with the §5 split this round added
.venv/bin/python tools/metrics/gate_check.py main.py core actions backend bridge services stores app --quiet --classes
# the full suite, exactly as the repo's own runbook (docs in CODE_QUALITY_METRICS_2026-09-10.md §reproduce)
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/python -m pytest -q \
  --cov --cov-branch --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
```

The two environment variables and the single deselect are not optional here: without
`QT_QPA_PLATFORM=offscreen` the run aborts (`Fatal Python error: Aborted`, exit 134)
at the real-WebEngine test around 63 %, which looks exactly like a broken tree and
is not one.

---

## 1. The leftover problems, ranked by measured consequence

Ranking input was not opinion: each candidate was measured first (AST pass over
`except Exception` handlers, gate_check over the whole production tree, a scan of
what any runner executes, and the pinned sizes in `tests/test_rule16_new_code.py`).

| # | problem | measurement | cost of leaving it | done here |
|---|---|---|---|---|
| 1 | **RULE 16 §5 (the override mechanism) does not exist.** The rulebook says CI parses `# quality-override: metric=value reason=…`; `grep -rn quality-override --include=*.py` returned **0 hits** and there is no CI at all (`.github/` absent from the index) | 248 gate violations across the production tree, **0 of them** carrying an accepted reason | the only sanctioned way to record "this size is deliberate" is fiction, so every future round re-litigates the same 20 symbols and the honest answer to "why is `build_probe` 122 lines?" lives in a report nobody runs against the code | **yes** |
| 2 | **No runner executes the browser half of the app.** `tests/test_*.js` = 22 self-contained suites; nothing in the repo invokes them (no CI, and no pytest file spawns them — only 6 files shell out to `tests/js_harness.js`, a different thing) | all 22 exit 0 today; `bridge/` is the least-covered package at 85.52 % line / 72.67 % branch | a UI/bridge contract can break silently; RULE 8 says JS behaviour is *proven*, and right now it is proven by hand or not at all | **yes** |
| 3 | **The tool that deletes files answers doubt silently.** In `services/db_deletion*.py`: 36 of the production tree's silent `except Exception` handlers, one of them (`_resolve_folder_policy`) dropping another world's media folder from the *protection set* while both of its neighbours in the same file refuse | the module's own docstring promises "any unverifiable world or unplannable target raises `_PhaseRefusal`"; the ladder's guards `_other_folder_reason` / `_shared_reference_reason` fell through toward `"remove"`, while `_symlink_reason`, `_outside_root_reason` and `_non_file_reason` fail the other way | media belonging to a world that was momentarily unreadable gets unlinked, with no log line to explain it | **yes** |
| 4 | `bridge/history_bridge.py::HistoryBridge` god-class | measured 486 LOC / 45 methods against a test pin of ≤493/45 → **7 lines and 0 methods of headroom** | a reader must scroll ~10 screens; but any split *must* be paired with the pin, or the ratchet fails for the right reason | no — see §6 |
| 5 | `app/lifecycle.py` | 35.85 % line / 0.0 % branch (8 branches, teardown: lock release + DB handles) | the shutdown path nobody tests | no — see §6 |
| 6 | 138 functions / 38 classes still over a gate | 54 params-only, 28 LOC-only, 17 CC-only, 12 LOC+CC, 2 nesting-only, 1 cognitive-only | readability debt, no measured defect | no — the §5 split in this round is what makes each one a decision instead of noise |
| 7 | mutation scope = 1 module, no CI, `# noqa: BLE001` markers 16/202 with a reason | round-3/4 tables | latent defects go unfound | no — listed in §6 with the numbers |

### 1.1 The negative result, kept in

Ranking candidate 3 meant reading it, and reading it disproved the headline I
started with. `canonical()` cannot raise (its own `except` falls back to
`abspath`, then to the raw string) and `DbRegistry.active_path()` cannot raise
either (it returns `"history.db"`), so the ladder's fall-throughs are **not
reachable through an OS error today**, and the "another world's files get deleted
quietly" story is not a live defect. What is true, and what this round fixed:

* `_resolve_folder_policy` calls a method that genuinely can fail
  (`registry.media_dir` → `ConfigManager.get` on a config that will not parse),
  and on failure it **skipped that world** — verified on the round-4 tree:
  `(set(), False)` returned with no log, no refusal, and the protection set empty.
* the guards' direction was **inconsistent with their own siblings**, which is how
  a "safe" fallback becomes unsafe in the next edit;
* nothing in the tool said which way a handler fell, so no reviewer could tell the
  two apart without reading 675 lines.

So this is a consistency-and-contract fix plus a pin, not a bug-fix-with-a-CVE.
Claiming more would be the kind of number a metric cannot see.

---

## 2. What changed

### 2.1 §5 overrides: the marker is parsed, validated and pinned

`tools/metrics/gate_check.py` now reads `# quality-override:` comments on a
`def`/`class` line (or anywhere in the signature header, which multi-line
signatures need) and splits every violation into two numbers:

```
violations: 248 (accepted with reason: 7, unexplained: 241)
```

The parser is strict in the ways §5 is strict — a metric token from the allowed
list, a numeric accepted value, a reason of ≥ 20 characters, one token per
metric — and it refuses to be a hiding place:

* measured **worse** than accepted → `override params: measured 6 > accepted 5`,
  and the violation **stays open** (drift cannot be grandfathered);
* measured **better** than accepted → `override loc: gate is not broken, override
  can go` (a marker must be deleted when its reason goes away);
* unparseable → the violation stays open and the reason for rejection is printed.

`tests/test_quality_override_format.py` enforces the same thing over the whole
production tree: every marker parses, every marker covers a real violation, and
`OPEN_DEBT = 241` may only shrink. It also tests the parser against the
rulebook's own example line, so the documentation and the code cannot drift apart.

Three markers were added — the sites where the constraint is a fact outside the
file, not a preference:

```python
class HistoryBridge(QObject):  # quality-override: class-loc=486 methods=45 reason=each method is a JS-callable bridge RPC, the surface ui/js names
def build_probe(  # quality-override: loc=122 params=8 reason=the body is one generated JS template, kept whole for CDP
                     prepend: bool = False) -> AppendResult:  # quality-override: loc=54 params=13 cc=11 reason=signature mirrors HistoryRepo.append, the store keyword API
```

`build_probe` is the rulebook's own example of a size not to fix
(`AGENT_RULES_CODE_QUALITY.md` §2: "Do not refactor that builder to meet 30
LOC"); the other two name the external surface that pins them. Each marker records
**today's measured value**, so growth trips the gate — the override is a
photograph, not a licence.

The rest of the 241 were deliberately left unexplained. `stores/migration.py`,
`stores/jsonio.py` and `stores/history_models.py` are frozen byte-for-byte by
`tests/unit/stores/test_stores_public_api.py`, so they *cannot* carry a marker,
and their violations stay counted as debt: a freeze is a decision, not a clean
bill of health. Sites whose only reason is "old" (e.g. `sleep_with_stop`,
`_ui_record`, `StepExecutionMixin` at 148 LOC) got nothing either — §5 asks for a
constraint, and "faster to ship" is not one.

### 2.2 The browser suites run in the test command

`tests/test_js_browser_suites.py` parametrises over `tests/test_*.js`, spawns each
with `node` from the repository root (the cwd a few of them read fixtures
against), skips the file when node is not installed, and fails with the suite's
own last 25 lines. `test_js_suites_are_discovered()` pins a floor of 22 so a bad
glob cannot turn this into a test that runs nothing.

Proof it is a test and not a decoration: a failing suite was injected
(`process.exit(1)` appended to `tests/test_sash_core.js`) and the runner reported
`sash_core: 31 passed, 0 failed / EXPECTED FAILURE / assert 1 == 0`. All 22 were
also checked to exit non-zero on failure — 15 call `process.exit(1)`, the other 7
use `process.exitCode = 1` or `process.exit(failed ? 1 : 0)`, so an exit code is a
real contract here, not a convention.

### 2.3 The delete pipeline's guards all fail the same way now

| site | before | after |
|---|---|---|
| `db_deletion_scan._resolve_folder_policy` | a world whose `media_dir()` raised was skipped: its folder vanished from `other_folders`, i.e. from the set that keeps *its* files out of the removal list | split into `_other_world_folders` (14 LOC, CC 3) which calls `_refuse_unreadable_world` → `raise_refusal(st, "scan", "cannot resolve the media folder of X; deletion refused to keep that world's files out of reach", _Fail(extra={"unverifiable_worlds": […]}))` — the message shape its neighbour `_scan_other_worlds` already used; `_folder_exclusive` / `_victim_folder_is_shared` (9 and 10 LOC) keep the two "unprovable ⇒ assume shared" branches, which were already correct |
| `db_deletion._other_folder_reason` | outer `except Exception: pass` → fell through the rest of the ladder, ending in `"remove"` | a guard that cannot resolve a path returns `retain:other_world_folder`; one `try` per fallible step instead of try-in-loop-in-try (24 LOC, CC 8, nesting 3) |
| `db_deletion._shared_reference_reason` | same fall-through | `retain:shared` on an unreadable reference |
| `db_deletion_flow._validate` | `except Exception: st.was_active = False` → the "switch away from the active world" phase is skipped, so the DB the app is using can be unlinked | refuses: `_PhaseRefusal(phase="validate", "cannot tell whether that database is the active one: …", was_active=True)` — the answer every other unreadable precondition in this file already gives |
| 14 handlers in the trio | `# noqa: BLE001` with no explanation | `# noqa: BLE001 -- realpath unavailable: abspath is next`, `-- unknown = not inside, which retains`, `-- outside_root already retained it`, … |

`classify_candidate`'s docstring now states the invariant the ladder kept by
accident: "Every predicate fails closed: when a lookup raises, the candidate is
retained, never removed."

**Three existing assertions were updated, and that is the part to review.**
`tests/integration/safety_deletion/test_deletion_defensive.py::TestClassifyDefensive`
pinned the old direction (`assertEqual(v, "remove")`, comments reading "root check
swallowed → falls through to remove"). Its file docstring is "Defensive-branch
coverage", i.e. characterization tests written to cover branches, not to argue for
them — the same class already asserts the opposite direction for the neighbours it
touched (`test_islink_raises_retains`, `test_canonical_raises_outside`). They now
assert the retained verdict, with the decision written at the site. Behaviour
direction, stated plainly: **a candidate the tool cannot judge survives**; the worst
case this creates is an orphaned file that is still on disk, instead of one that is
gone.

`tests/integration/safety_deletion/test_unverifiable_world.py` (8 tests) is new:
the refusal, the "readable worlds are all still collected" counterpart (so the fix
cannot turn into over-refusal), the three ladder fall-throughs, "a broken resolver
retains even a plain removal", the happy path still removing, and both `_validate`
cases. Each behavioural assertion was run against the round-4 source and
**failed there** (2 ladder tests + 1 validate test), which is how the change is
shown to be real rather than a rephrasing.

`tests/test_silent_except_deletion.py` pins what is left per file
(`db_deletion.py` 9, `db_deletion_flow.py` 11, `db_deletion_scan.py` 0) with the
ratchet direction that matters: a new silent `except Exception` in the tool that
unlinks files fails the suite. Same script, same tree before and after:
**21 → 9, 12 → 11, 3 → 0**.

---

## 3. Sizes and complexity: round 4 → round 5

Same tools, same frozen counting (`tools/metrics/current_audit.py`), so every line
below is comparable.

| measure | round 4 | round 5 |
|---|---|---|
| production functions | 1,743 | **1,747** (the four helpers the deletion split added; the round-4 figure is this round's count minus those four, because no other file gained or lost a function) |
| mean CC / max CC | 3.18 / 19 | **3.18 / 19** (max is the frozen `stores/migration.py::migrate_legacy_config`) |
| functions with CC > 10 | 42 | **42** |
| mean cognitive / max / > 15 | (not in round 4's tables) | **2.28 / 22 / 10** — max 22 is `backend/chat_sync.py`, untouched |
| mean function LOC / > 30 LOC | 10.06 / 61 | **10.06 / 61** |
| functions over ≥ 1 gate / ≥ 3 gates | 138 / 10 | **138 / 10** |
| classes / > 150 LOC / > 300 / max methods | 199 / 35 / 11 / 44 | **199 / 35 / 11 / 44** |
| mean class LOC | 80.14 | **80.14** |
| gate metric violations, functions + classes | first measured this round: **248** (its function half is round 4's 138 over-gate functions) | **248 = 7 accepted with a reason + 241 open, and `OPEN_DEBT = 241` pinned in a test** |
| broad-catch markers with a reason | 2 of 202 | **16 of 202** |
| silent handlers in the deletion trio | 36 of 52 | **20 of 52** |
| `db_deletion_scan.py` CC of `_resolve_folder_policy` | 13 (25 LOC) | **1** (4 LOC) + four helpers named after their decision |

Round 5 was not a complexity round — it was a "make the rule real, make the
browser tests run, make the destructive tool consistent" round, and the tables
show nothing moved in either direction. What did move is where a reader looks:
the file that decides deletions has no unexplained fallback left in its scan half.

### 3.1 Coverage (production scope only — `tests/` and `tools/` are excluded, and coverage.py's `percent_covered` is the combined line+branch figure, never report it as line coverage)

| measure | round 4 | round 5 |
|---|---|---|
| line | 90.59 % | **90.66 %** (12,436 / 13,717) |
| branch | 84.53 % | **84.56 %** (2,804 / 3,316) |
| files at 100 % line | 64 | **64** |
| `services/db_deletion_scan.py` | 70.9 % line | **75.40 % line / 86.67 % branch** (left the under-75 % list) |
| `services/db_deletion.py` | 96 % | **99.76 % line / 100.00 % branch** |
| full suite | 2,569 passed | **2,617 passed, 3 skipped, 1 deselected, 1 xfailed, 779 subtests, 0 failures, 337 s** |

The +48 tests are exactly the new ones: 23 browser suites + floor, 16 override
rules, 1 silent-handler ceiling, 8 delete-tool guard tests. The three updated
assertions in `test_deletion_defensive.py` changed verdicts, not counts.
`app/lifecycle.py` is still the least-covered production file at 35.85 % line /
0.0 % branch — unchanged, and still first on the §6 list.

---

## 4. RULE 16 recheck (docs/AGENT_RULES_CODE_QUALITY.md §1–§9)

| § | requirement | how it was checked | verdict |
|---|---|---|---|
| 1 | new/rewritten production symbols inside every gate | `gate_check.py` on the 3 changed production files, per symbol: `_other_folder_reason` 24 LOC/CC 8/cog 11/nest 3, `_shared_reference_reason` 18/7/8/3, `_other_world_folders` 14/3/3/2, `_folder_exclusive` 9/3/2/1, `_victim_folder_is_shared` 10/4/4/3, `_refuse_unreadable_world` 9/2/1/0 (3 params), `_resolve_folder_policy` 4/1/0/0, `_validate` 25/7/5/1; plus the tool and the 4 new test files (`violations: 0`) | **pass** — no override used on new code |
| 2 | frozen counting definitions | gate_check reuses the same AST span / params / radon / ancestry rules it was verified against in rounds 3–4; nothing in this round redefined a metric | **pass** |
| 3 | sizes of what a reader opens | every new unit ≤ 25 lines, every new file under 130 lines, one decision per name | **pass** |
| 4 | coverage must not drop | 90.66 % ≥ 90.59 %, 84.56 % ≥ 84.53 %, 64 files at 100 % unchanged | **pass** |
| 5 | override mechanism | **implemented** (it did not exist), format-tested against the rulebook's example, and pinned: 7 accepted, 241 open, `OPEN_DEBT` may only shrink | **pass, and now enforceable** |
| 6 | match the surrounding idiom; siblings the same shape | the fix *is* this rule: the ladder's guards now all answer doubt the way `_symlink_reason`/`_non_file_reason` already did, and the new refusal reuses `_scan_other_worlds`' message and `unverifiable_worlds` payload; 14 `# noqa: BLE001 -- reason` markers follow the 2 existing ones | **pass** |
| 7 | no dead code | `vulture --min-confidence 80` on the tool: nothing; `functions_in`/`violations`, which the rewrite left uncalled, were deleted from `gate_check.py` | **pass** |
| 8 | duplication | the new helpers share one refusal message between the scan's two "cannot read another world" sites instead of a second copy. Measured now: `pylint --disable=all --enable=R0801 backend/ bridge/` reports nothing, and `tools/metrics/clone_scan.py`: 12 groups / 90 unique physical lines — identical to the round-3 series it is comparable to | **pass, no new clones** |
| 9 | every change has a test that could have failed | the 8 new deletion tests were run against the round-4 source and failed there (2 ladder + 1 validate); the browser runner was proven by injecting a failing suite; the override rules are tested both ways (accepted / drift / stale / malformed) | **pass** |

RULE 16's test-coverage companion: `test_rule16_new_code.py` still passes
unmodified — its class ratchets (`HistoryQuery` ≤ 362, `HistoryBridge` ≤ 493/45)
and its vulture/duplication checks were re-run as part of the full suite.

## 5. RULE 18 recheck — the reader's context budget

RULE 18 asks what one person can hold on screen, so it is measured as "how much do
you scroll to understand one unit", not as a violation count.

| what a reader must hold | round 4 | round 5 |
|---|---|---|
| longest production function | 122 LOC `backend/dom_probe.py::build_probe`, exempt *by prose in a report* | 122 LOC, **exempt by a parsed marker in the code** (§2 of the rulebook and the code now agree) |
| most branches in one function | 19 (frozen) / 15 elsewhere | 19 (frozen) / 15 elsewhere |
| deepest indentation in a function I touched | 4 | **3** (the ladder's guards each became one flat "resolve, or retain" step) |
| a function needing more than one screen | 61 | 61 |
| classes over four screens | 35 | 35 |
| mean function / mean class | 10.06 / 80.14 | 10.06 / 80.14 |

The three questions, for this round's units:

1. **Can you read it in one screen?** Yes. The function that decides whether
   another world's files are reachable is 14 lines and ends in a refusal;
   `_resolve_folder_policy` is 4 lines that read as "gather folders, judge
   exclusivity" instead of 25 lines of nested tries.
2. **Does the name say what it does?** `_other_world_folders`,
   `_victim_folder_is_shared`, `_refuse_unreadable_world`, `_folder_exclusive` —
   each is named after the decision it makes, and the two `_…_reason` guards say
   in the code what they return when they cannot tell.
3. **Is the reader's context the same or smaller?** Smaller for the function, and
   now smaller for the *file*: `classify_candidate`'s docstring states the
   fail-closed rule that previously took reading all seven guards to infer, and 14
   handlers say which way they fall instead of leaving the reader to decide
   whether "pass" was safe.

## 6. Leftover, ranked for round 6

1. `app/lifecycle.py` — 35.85 % line / 0.0 % branch, and the branch total is only
   8, so a test for "lock file removed on teardown", "DB handles closed twice" and
   "second start while a lock exists" moves it a long way. Cheapest real coverage
   win left in the repo.
2. Split `HistoryBridge` (486 LOC / 45 methods) by *surface*: history browsing vs
   mutation vs media, three classes, one registry entry each. Budget the pin
   edit in the same change — `tests/test_rule16_new_code.py` allows 493/45 and the
   file's own new marker pins 486, so the marker must move with the class or
   `test_quality_override_format.py` fails on "gate is not broken".
3. 54 params-only violations: the ones worth doing are the four-argument
   functions that were 5 by accident (fold the extra into an existing dataclass);
   the keyword-only safety ladders (`classify_candidate` at 7) are the ones to
   *mark* with a real constraint rather than reshape.
4. 17 CC-only violations between 11 and 15 (max outside frozen files: 15 at
   `stores/history_repo_identity.py::_ui_record`, `stores/history_models.py::from_dict`,
   `services/collector_service.py::handle_push`, `backend/history_query.py::person_stats`,
   `backend/chat_sync.py::plan`).
5. `# noqa: BLE001` reasons on the remaining 186 silent handlers, in the order the
   blind-handler count falls: `backend/message_injector.py` 13,
   `stores/media_fetch.py` 8, `bridge/stack_bridge.py` 7, `backend/media_handler.py` 6,
   `services/db_registry.py` 6 — with `tests/test_silent_except_deletion.py` as the
   template for a per-package pin.
6. Wire the JS suites into coverage: they report to nothing today; the harness
   already accepts a `?cov` style instrumentation, so an instrumented run would
   turn "the JS ran" into "the JS ran *and* this branch was taken".
7. Mutation scope (`setup.cfg` covers one module today, 94.34 % of the mutants it
   executed). Widening to `services/` is the next real defect detector, at the cost
   of a long run.
8. Retire the two shims `backend/bridge.py:9-10` and `backend/action_engine.py:3`,
   which removes 4 of the 10 package import cycles; then break the `backend` hub
   cycle.
9. Consider CI (there is none). `gate_check.py --strict` and the two new test files
   are already the check's content; the missing piece is a runner.

## 7. Files this round touched

* `tools/metrics/gate_check.py` — §5 marker parsing, accepted/unexplained split,
  self-measured 0 violations.
* `tests/test_quality_override_format.py` (new, 17 tests) — format, staleness,
  `OPEN_DEBT = 241`.
* `tests/test_js_browser_suites.py` (new, 23 tests) — the 22 browser suites + floor.
* `tests/test_silent_except_deletion.py` (new, 1 test) — per-file silent-handler
  ceiling for the delete tool.
* `tests/integration/safety_deletion/test_unverifiable_world.py` (new, 8 tests).
* `tests/integration/safety_deletion/test_deletion_defensive.py` — 3 characterization
  assertions moved to the fail-closed verdict, with the reason at the site.
* `services/db_deletion.py`, `services/db_deletion_flow.py`,
  `services/db_deletion_scan.py` — the guard changes above (verified by AST diff
  against `53ba5fb`: only `_other_folder_reason`, `_shared_reference_reason`,
  `_validate` and `_resolve_folder_policy` differ, plus the four new helpers —
  no other body in those three files changed).
* `bridge/history_bridge.py`, `backend/dom_probe.py`,
  `stores/history_repo_append.py` — one marker line each, no statement changed.
