# Round G step 2 — `chat_sync.py` split + `ScrollParser` decomposition

Date: 2026-09-13 · Branch: `arena/01a09b73-chat-v-bot` · Parent plan:
[`ROUND_G_DESIGN_2026-09-13.md`](ROUND_G_DESIGN_2026-09-13.md) §4 (step G2)

This is the §16.5 landmine design doc for `ScrollParser`, and the F0(a)
execution doc for `backend/chat_sync.py`. Both files were parked in Round F
because the AREA D public-API snapshot forbade moving their symbols. The owner
has since lifted every freeze (Round G design §1c, ruling of 2026-09-13:
*"remove any restriction to all frozen solutions; redesign any code as
needed"*), and re-confirmed it for this step. The snapshot refresh this step
performs is the sanctioned, deliberate kind: `--write` inside the step, diff
reviewed symbol-by-symbol in §5, no assertion weakened.

## 1. Measured starting point (this tree, radon 6.0.1 / AST)

| File / class | LOC | Detail |
|---|---:|---|
| `backend/chat_sync.py` | 807 | MI **11.35** — worst in the repo; 7 public phase classes + `run_sync` + a dead `_MAX_QUIET_RETRIES` constant (defined line 60, zero uses anywhere — removed in this step) |
| `chat_sync.SyncSession` | ~250 | 26 members — the second god class in the file |
| `backend/scroll_parser.py` | 706 | MI 28.58 |
| `scroll_parser.ScrollParser` | 531 | **39 methods**, LCOM\* 0.88 — the largest god class left, named §16.5 landmine |

Both files carry the same stale `ideal-size:` note claiming the frozen AREA D
snapshot forbids the split. That reason dies with the ruling; the notes die
with the split.

Behaviour locks that exist **before** the cut (§16.5 "touch a hotspot only
with tests that lock current behaviour first"): 826-line
`tests/unit/backend/test_chat_sync_phases.py`, `test_chat_sync_plan.py`,
`test_scroll_parser_options.py` (SP#1–11), `test_scroll_parse_pipeline.py`,
`test_scroll_only_seek.py`, `test_collect_visual_and_live_refresh.py`,
`test_filter_purge.py`, plus the golden `test_backend_api_snapshot.py`.
Baseline for the whole effort: **2 808 passed / 0 failed**, coverage line
90.91 % / branch 87.01 % (Round G step 1, `/tmp/coverage_g1_final.json`).

## 2. What may NOT change, even with the freezes lifted

The ruling lifts *code contracts*, not *product contracts*:

1. **Behaviour.** This is a pure structural step. No phase order, no wording
   of a log line, no retry count, no outcome dict changes. The suite is the
   spec and must pass unmodified except for the three forced accommodations
   named in §4.
2. **Public names and signatures stay reachable.** `backend.chat_parser`'s
   re-export seam (`SLICE_RETRIES, SyncOptions, merge_live, run_sync`),
   `actions/scroll_parse.py` (`CollectResult, ScrollOptions, ScrollParser`),
   `services/run/coordinator.py` (TYPE_CHECKING `ScrollParser`), and every
   test import keep working through the two facade modules, whose names and
   paths do not move.
3. **`ScrollParser.__init__`'s 19-knob legacy signature stays.** Not because
   a snapshot says so, but because
   `test_scroll_parser_options.py::test_defaults_are_the_constructor_defaults`
   pins constructor↔`ScrollOptions` default parity knob-by-knob, and
   `from_options` is the modern entry new code already uses
   (`ScrollParse.build_parser`). The signature is a tested compatibility
   surface, not neglect; it is 28 LOC and inside the function gate.
4. **`SyncSession`'s dataclass field set and public method set stay** — the
   phases and `test_chat_sync_phases.py` read them as attributes
   (`session.person_id`, `session.state`, …), and the golden file pins the
   fields.
5. **The JS payloads stay single literals** (§16.1.5): `_EXTRACT_JS` moves
   verbatim into the DOM module.

## 3. Design

### 3.1 `chat_sync` → a prefix family (the F1 `db_deletion_*` pattern)

```
backend/chat_sync.py           seam: family map, re-exports, run_sync   (~95)
backend/chat_sync_options.py   SyncOptions — the eleven knobs           (~115)
backend/chat_sync_plan.py      MODE_* constants, ReadPlan, SyncPlanner  (~155)
backend/chat_sync_persist.py   merge_live, SyncPersister — every write  (~175)
backend/chat_sync_read.py      SLICE_RETRIES, ChunkReader, DeltaAligner (~135)
backend/chat_sync_session.py   SyncViewport, SyncSession                (~290)
```

Import direction is one-way: the seam imports the five siblings; `session`
imports `options`/`plan`/`persist`; `read` and `persist` import no sibling;
nothing imports the seam, so no cycle can close. The existing deferred import
inside `_pass_gate` (`from backend.chat_parser import verify_private`, the
documented chat_parser↔chat_sync cycle break) moves verbatim with the method.

`run_sync` stays **owned by the seam**: it is the entry point the module
docstring's phase tree describes, and keeping it there means the golden file's
`backend.chat_sync.functions.run_sync` entry does not move.

`SyncSession` decomposition (26 → 17 members, ~250 → ~160 LOC): the seven
viewport/backfill methods (`_prepare_viewport`, `_fetch_settled_state`,
`_settled_ok`, `_recover_emptied_pane`, `_settle_at_top`, `restore_viewport`,
`_window_end`) become a `SyncViewport` collaborator holding the session —
exactly the `SyncPersister(session)` pattern already in the file. Fields stay
on the session dataclass (pinned); the collaborator reads/writes them through
its reference. `SyncSession.restore_viewport` (public, pinned) keeps its
signature and delegates. The session lands at 17 members / ~160 LOC: still
over the new-code class gate (15/150) but **improved on both axes**, which is
what §16.0/§16.5 require of a legacy offender; the remaining mass is the
22-field dataclass header plus the opening/closing phase methods that pin
tests call by name.

`SyncPersister` (134 LOC / 12 members), `ChunkReader` (~72/5), `DeltaAligner`
(~32/2), `SyncPlanner` (~87/7), `SyncOptions` (~74/7), `ReadPlan` (~38/5),
`SyncViewport` (~95/8) all fit the new-code gates outright.

### 3.2 `scroll_parser` → facade + model + three collaborators

```
backend/scroll_parser.py        ScrollParser facade (14 members, ~135 LOC)
backend/scroll_parser_model.py  STOPPED, CollectResult, ScrollOptions, PassState (~195)
backend/scroll_parser_dom.py    _EXTRACT_JS, _to_record, _to_dict, ScrollDom (~190)
backend/scroll_parser_judge.py  PersonJudge — per-person decisions (~155)
backend/scroll_parser_loop.py   ScrollLoop — open/advance/settle/finish (~180)
```

`ScrollParser` (531/39) becomes a facade inside the new-code gates:
constructor, `from_options`, the `max_scrolls` property, the three
callback property+setter pairs (kept verbatim — `tests/test_filter_purge.py`
reads `parser._on_reject` to prove a disabled purge detached the hook),
`set_log_cb`, `_say`, `_stop_requested`, `collect`, `parse`, `known_nicks`
(read by two tests). 14 members ≈ 135 LOC.

The 25 moved private methods cluster by what they touch, not by size:

* **ScrollDom** (8 methods): the `_EXTRACT_JS` probe, `snapshot`,
  `confirm_person` (highlight), `do_scroll`, `settle` + its three helpers.
  The pure conversions `_to_record`/`_to_dict` become module-level privates
  in the same file (they convert probe output; judge imports them).
* **PersonJudge** (9 methods): `consume_batch`, `seek_hit`, `judge`,
  `reject_one`, `collect_one`, `hold_confirmation`, `notify_collected`,
  `notify_rejected`.
* **ScrollLoop** (9 methods, built per `collect()` call — it holds run
  lifetime state): `open_pass` (ex `_open`), `first_snapshot`, `scroll_loop`,
  `advance`, `target_reached`, `list_is_over`, `scroll_and_settle`, `finish`.

Collaborators hold the facade (`self.p`) and read `p.options` / `p._cdp` /
`p._log_cb` **live** — never cached — because the callback setters replace
the frozen `options` object via `dataclasses.replace`. This is the same
live-reference rule `SyncPersister` follows.

`_Pass` is renamed `PassState`: it crosses module boundaries inside the
family now, and an underscore name imported by siblings reads as a contract
violation. It is a new public symbol of the model module — additive, which
the snapshot has always allowed.

The facade re-exports `CollectResult`, `ScrollOptions`, `STOPPED`,
`PassState` so every existing import site (`actions/scroll_parse.py`, four
test files) is untouched.

### 3.3 Both facades keep their module paths

Neither `backend/chat_sync.py` nor `backend/scroll_parser.py` becomes a
package: `dump_public_api.module_names` skips packages outright, so a package
would silently drop the whole family out of the golden file — coverage shrink
disguised as a refactor (§16.2 anti-gaming). Prefix families keep every
symbol measurable, which is also why the F1 `db_deletion_*` split chose them.

## 4. Forced accommodations (the ONLY test edits in this step)

1. `tests/test_collect_visual_and_live_refresh.py` lines 140–151 patch
   `sp.asyncio.sleep` via `import backend.scroll_parser as sp`. `sp.asyncio`
   **is** the stdlib `asyncio` module object, so the patch is global for the
   `try:` window regardless of which module calls it. After the split the
   sleeps live in the dom/judge/loop siblings, and an unused `import asyncio`
   on the facade would be a dead import (pylint W0611). The test switches to
   `import asyncio; asyncio.sleep = spy` — same object, same semantics, same
   restore in `finally`; the spy still observes the 250 ms hold because the
   patch is process-wide either way.
2. `tests/unit/backend/backend_api_snapshot.json` (+ its `blocks` twin) is
   refreshed with `tools/metrics/dump_public_api.py --write`. The blocks half
   must come out **byte-identical** (no action block is touched); any change
   there aborts the step.
3. `tests/unit/stores/test_stores_public_api.py::
   test_stores_imports_outside_the_package_are_untouched` counts `from
   stores…` lines outside stores/ and pins the total (was 40). Found only by
   the full suite — the walk spans all five areas, so no targeted run covers
   it. The split distributes the *same* names over the files that use them:
   seam (`SyncResult`, the pinned `run_sync` annotation),
   `chat_sync_persist` (`MAX_LIVE_ITEMS, SyncResult`), `chat_sync_read`
   (`align_batch`), `chat_sync_session` (`SyncResult`) — two lines more than
   the monolith's two; the scroll_parser family is net-zero (`UserRecord`
   moved facade → `scroll_parser_dom`). Baseline bumped 40 → 42 with a
   provenance comment, which is the mechanism the test's own comment block
   prescribes ("bump … only when another area legitimately grows the
   surface … recorded here rather than silently"). The stores/ surface is
   unchanged and no stores consumer edited an import; routing the seam's
   `SyncResult` through a sibling just to keep the counter at 40 would be
   §16.2 metric-gaming, so the honest bump is the compliant move. Owner
   ruling F0 (freeze lift, deliberate in-step refresh with justification)
   covers this edit; the assertion keeps its exact form — only the recorded
   baseline moves.

No other test, and no production caller, changes.

## 5. Snapshot-refresh diff (the sanctioned spend)

Expected golden diff, enumerated before the run so the actual diff can be
checked against it — anything beyond this list aborts the step:

* `backend.chat_sync`: keeps `functions.run_sync`; its seven `classes`
  entries and the `MODE_*` / `SLICE_RETRIES` value entries move out.
  (`_MAX_QUIET_RETRIES` was never recorded — private.)
* New modules `backend.chat_sync_options|plan|persist|read|session` gain
  exactly those symbols, signatures unchanged (moved verbatim).
* `backend.scroll_parser`: keeps `classes.ScrollParser` — bases, every
  public method signature (`__init__`, `collect`, `parse`, `from_options`,
  `set_log_cb`, `max_scrolls` property) unchanged; its class `attrs`/`fields`
  unchanged. `CollectResult`, `ScrollOptions` move to
  `backend.scroll_parser_model` with identical fields; `PassState` appears
  there as an addition.
* Nothing is removed from the API as a whole: every symbol recorded in the
  old golden exists in the new one, under its family name. Checked by script,
  not by eye (§6).

**Actual outcome.** The real diff matched this list exactly, and the blocks
twin came out byte-identical. The refresh additionally absorbed pre-existing
additive staleness that predates this step (golden not re-dumped since those
commits landed): the `actions.cancellation` module entry,
`FindClickBlock.click_runner`, and an `inherited` key inside four click-block
payloads — additions only, no removal or signature change anywhere (§16.2
discipline: verified by the conservation script, recorded here).

## 6. Verification plan (and outcome)

| Check | Command / source | Result |
|---|---|---|
| Golden-symbol conservation | script: old vs new `public_api`, every `(qualname→symbol)` present somewhere with identical payload | **PASS** — 10 ownership moves, 0 losses, payloads identical |
| Blocks golden byte-identical | `git diff --stat tests/unit/actions/block_wire_snapshot.json` | **PASS** — empty diff (byte-identical) |
| Behaviour suites | chat_sync + scroll_parser test files listed in §1 | **PASS** — 202 passed (family files) + 59 passed (snapshot/public-API/stores) |
| Full suite | `pytest tests` + the standing sandbox deselect `--deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine` (Qt WebEngine cannot start in this sandbox; every recorded run since the baseline uses it — reported honestly as "1 deselected", never as passed) | **PASS** — 2808 passed, 0 failed, 2 skipped, 1 xfailed, 898 subtests passed, 1 deselected (the sandbox WebEngine test above), 477 s |
| Coverage vs step-1 baseline | same pytest run, `--cov` on the eight production roots, `--cov-branch`, vs `/tmp/coverage_g1_final.json` (90.91 / 87.01) | **PASS** — line 90.94 % (G1 90.91, +0.03 pp), branch 87.01 % (±0.00); every family file individually 91.0–100 %; +62 statements, no file dropped out of the report |
| RULE 16 gate | `rule16_gate.py --with-clones` | **PASS** — exit 0; "All owned functions fit. Ratchet intact. No stale overrides."; clone scan 0 new groups, 0 stale baseline entries |
| New-code sizes | gate-metric AST walk of all eleven family files (sloc = non-blank non-comment, same metric the gate uses) | **PASS** — files 73–247 sloc; worst function `chat_sync_persist.repair_tail` 27 (≤30); worst class `SyncSession` 149 sloc / 17 methods (≤150; method count carried unchanged from the monolith, ratcheted); radon MI grade A on every file (40.5–77.0); no-worsen diff vs HEAD: no regressed function — only the two sanctioned structural +1s (`collect` 19, `__post_init__` 7) |
| Hygiene | pylint W0611/E-level delta, vulture ≥90 on new files | **PASS** — pylint clean (seam re-exports covered by `__all__` per the `db_deletion.py` precedent + inline disables with reasons); vulture at min-confidence 90 clean (60 flags only public seam re-exports — known false positives) |

## 7. Risks and rejected alternatives

* **Naive re-export shim without refresh** — fails the golden's removed-symbol
  check (Round F lesson). Rejected; refresh is now sanctioned.
* **Promoting either file to a package** — drops the family out of the golden
  (§3.3). Rejected.
* **Redesigning `ScrollParser.__init__` to `(cdp, options, criteria)`** —
  legal post-ruling, but breaks the constructor↔options default-parity test,
  which is a genuine drift alarm between the two configuration surfaces. The
  parity test outlives the freeze. Rejected for this step.
* **Moving `SyncSession` fields into the viewport collaborator** — fields are
  golden-pinned and read directly by phase tests; moving them is churn with
  no quality gain. Rejected.
* **Clone risk** — six new sibling files with similar import headers. The
  scanner needs ≥6 consecutive identical statements; the headers differ from
  statement 3–5 (different sibling imports). Verified with `--with-clones`;
  any group that does appear gets the F1-style baseline entry with a
  justification, never a cosmetic reorder (§18.5).
* **Coverage dip from seams** — the delegation lines (`restore_viewport`,
  `collect`) are executed by the existing phase/pipeline tests; a moved line
  stays a covered line. The dead `_MAX_QUIET_RETRIES` removal shrinks the
  uncovered set by one.
