# F5: Parameter Objects for Wide-Parameter Functions

**Date:** 2026-09-13
**Status:** Complete to the floor the frozen contracts allow — 19 of 70 migrated, metric 70 → **51**
**Design Reference:** ROUND_F_DESIGN_2026-09-12.md §6 (step F5), RULE 19 §19.4
**Outcome record:** ROUND_F_DESIGN_2026-09-12.md §10 (first pass) and §11 (completion)
**Continued in:** [`G4_PARAM_OBJECTS_DESIGN_2026-09-13.md`](../2026-09-13-round-g-write-gate/G4_PARAM_OBJECTS_DESIGN_2026-09-13.md) — Round G step 4 took the remaining-51 table this doc leaves behind down to its 18-entry floor (11 documented constraints + 7 deferred `stores/` offenders)

## Overview

F5 addresses the functions that take more than 4 parameters (§16.1's fail line).
The remedy §19.4 prescribes is a parameter object: related arguments become
fields of one typed request, the way `PersonPageRequest` carries the six options
`HistoryQuery.list_persons` used to take positionally.

Baseline, measured 2026-09-13: **70 functions over 4 params, worst 20**
(`actions/scroll_parse.py::__init__`). After the first pass: **68**. After the
second pass (§11): **51, worst 20** — the worst is unchanged because it is
outside `stores/` and §6 never assigned it to F5.

## What actually happened, and the correction that matters

This plan arrived from branch `arena/01a09a61-chat-v-bot` describing nine
dataclasses and an `append_v2()` demonstration. Re-measured here, none of it was
wired: eight of the nine dataclasses had exactly **one** reference in the whole
tree — their own definition — `append_v2()` was never called, and the target
metric read 70 before and 70 after. Unused code that moves no metric is the
`foo_part1` / `foo_part2` shape §16.1.1 forbids, so the eight were dropped and
`append_v2()` with them.

**The pattern below was the root cause, and it is corrected here.** The original
text prescribed adding `operation_v2()` beside `operation()`, then marked
"Update Call Sites" as *optional* and "Remove Old Method" as *future*. Following
that literally produces a second API nobody calls and a metric that never moves.
§19.4's own model does the opposite — `list_persons(self, req)` has no `_v2`
twin anywhere in `backend/history_query.py`. So:

### The pattern this repo follows

1. **Create the parameter object** in `stores/history_requests.py`, fields in the
   order the old signature had them, defaults preserved exactly.
2. **Change the signature in place.** No `_v2`, no parallel API, no deprecation
   window — one function, one way to call it.
3. **Update every call site in the same commit.** This is not optional; a
   parameter object with unmigrated callers is dead code.
4. **Measure the metric afterwards** and record the before/after count. If it did
   not move, the step did not happen.

Pick functions whose call sites are all inside one family first. `_after_write`
was chosen because all five of its call sites are in `stores/`, so nothing
outside the family — and no frozen contract — had to move.

## Done — 19 functions across two passes

First pass (§10.4), `WriteContext` alone:

| Function | Was | Now | Call sites updated |
|---|---|---|---|
| `stores/history_repo_lifecycle.py::PersonLifecycle._after_write` | 8 params | `ctx: WriteContext` | 5 (2 in `history_repo_append.py`, 1 in `_touch_cursor`, the facade, and its delegation) |
| `stores/history_repo.py::HistoryRepo._after_write` (facade) | 8 params | `ctx: WriteContext` | — |

The implementation went 41 → 40 LOC, so the legacy function improved rather than
worsened (§16.0), and `history_repo.py` lost two over-long lines (54 → 52
`line-too-long`).

Second pass (§11.2), the remaining 17 — one object written per real consumer, in
the order the migration reached them:

| Object | Functions migrated (params before → after) |
|---|---|
| `WriteContext` | `_touch_cursor` in lifecycle **and** facade 6→1; `_report_unchanged` 7→2 |
| `PaneSignature` | `_same_conversation` 6→2; `ConversationIdentity.rename_if_same_conversation` 8→4 |
| `PlacedRecord` | `_ui_record` in identity **and** facade 5→1; `_collect` 6→2; `_insert_message` 8→4 |
| `SlotSearch` | `_take_empty_slot` in append **and** facade 5→3 |
| `AlignSpec` | `_align` 5→1 |
| `RowBatch` | `_write_rows` 8→2 |
| `PrependRequest` | `_prepend` in append **and** facade 11→1 |
| `MediaRecoveryRequest` | `MediaRecovery.recover_media` 6→1; `_RecoveryPass.__init__` 8→4 |

`history_requests.py` now holds eight dataclasses at **191 lines**, inside
§18.2's band; `stores/` is 38 files, the one it gained in the first pass, still
justified in `tests/unit/stores/test_stores_structure.py`. Wide functions in
`stores/` went **24 → 7**.

## Remaining — 51 functions

**Do not** recreate the dropped dataclasses speculatively. Add one when its
function is migrated, in the same commit. Every object in
`history_requests.py` is consumed by at least one production signature; that was
checked by grep at word boundaries outside the module, because the abandoned
version of this step wrote 230 lines nothing imported.

`AppendRequest` in particular cannot be wired yet: `HistoryRepo.append` (13
params) and `AppendPlanner.append` (13) have production callers in
`backend/chat_sync.py`, which the AREA D snapshot freezes. Migrating them is a
coordinated change needing the §7 option (a) decision first — the same reasoning
§9.6 applied to `list_persons`.

### `stores/` — 7 left, every one blocked by a named contract

Nothing in `stores/` is unmigrated for want of trying. Measured after the second
pass:

| Function | Params | What blocks it |
|---|---|---|
| `history_repo_append.py::AppendPlanner.append` | 13 | AREA D snapshot frozen — production callers in `backend/chat_sync.py` cannot be rewritten |
| `history_repo.py::HistoryRepo.append` | 13 | same, plus `api_baseline.json` freezes the public signature |
| `history_repo.py::rename_if_same_conversation` | 8 | `api_baseline.json` — public. It *does* build a `PaneSignature` internally; the 8 parameters are the frozen contract, not an oversight |
| `history_repo.py::recover_media` | 6 | `api_baseline.json` — public. Delegates to the migrated `MediaRecovery.recover_media` |
| `media_store.py::MediaStore.__init__` | 6 | `api_baseline.json` records the signature |
| `history_models.py::fingerprint` | 6 | module is FROZEN — "any change at all" fails AREA B |
| `history_models.py::dedupe_key` | 5 | module is FROZEN |

Five of the seven are public API in a golden file whose purpose is proving the
public surface did not move, and two are in a module frozen for that reason.
Spending either guarantee is the owner's call (§7's reasoning for AREA D, applied
to AREA B in §10.5), not the implementer's.

The five `_after_write`-class candidates this section once named as "the safe next
ones" — `_write_rows`, `_insert_message`, `_report_unchanged`,
`_same_conversation`, `_align` — are all migrated, along with `_prepend`,
`_collect`, `_take_empty_slot`, `_ui_record`, `_touch_cursor` and both media
functions.

### Outside `stores/` — 44 functions, parallel-safe

Measured per directory: `actions/` 15, `backend/` 13, `services/` 13, `bridge/`
2, `app/` 1. None of them shares a family with the `stores/` work, so they can be
migrated independently of it and of each other.

Worst first: `actions/scroll_parse.py::__init__` 20,
`backend/scroll_parser.py::__init__` 19 (AREA D frozen),
`backend/chat_parser.py::sync_conversation` 14, `actions/click_user.py::__init__`
13. Note that RULE 3 keeps block settings as explicit instance attributes, so an
action block's wide `__init__` may be a documented constraint rather than a
migration candidate — decide per block, do not assume.

§6 scoped F5 to the wide-parameter *tail* and named `stores/` as the family to
start with; these 44 are the continuation of the same step, not a new one, and
they were deliberately left alone here because touching `actions/` and `backend/`
means touching AREA D's frozen callers.

## Verification

```bash
# the metric, before and after any F5 commit — walker lives in
# ROUND_F_DESIGN_2026-09-12.md §10.4 and prints "wide=51 worst=..." here
# (it printed wide=70 before WriteContext was wired, wide=68 after the first pass)

# nothing dead was added: no unused import, and the repo-wide dead-code metric
# stays at its 7 findings with WriteContext absent from them
pylint stores/history_requests.py                     # expect no W0611
vulture core actions backend bridge services stores app ui main.py \
    --min-confidence 90                               # expect 7, none of them ours

# the family still behaves
python -m pytest tests/unit/stores tests/test_history_repo_conflicts.py \
    tests/test_history_repo_lifecycle.py tests/test_history_db_unit.py -q
```

Expected: the wide count falls by exactly the number of functions migrated, and
no dataclass exists that a signature does not consume.

First pass, verified 2026-09-13: `wide=68 worst=20`, no `W0611`, vulture 7
findings with `WriteContext` absent, **137 passed / 2 skipped / 709 subtests**.

Second pass, verified 2026-09-13: `wide=51 worst=20` — the fall is exactly 17,
the number of functions migrated; no `W0611`, pylint 9.82/10 with the single
`R0902` on `WriteContext` explained below; vulture still exactly **7** findings,
all pre-existing and none in `stores/history_requests.py`. Targeted suites
**383 passed / 2 skipped / 1 xfailed / 756 subtests**, **633 passed**, **66
passed**; full suite **2800 passed / 3 skipped / 1 deselected / 1 xfailed / 897
subtests**, which is the 2788 baseline plus exactly the twelve new §18.3 tests.

Two readings to get right, both of which mislead in the opposite direction:

* **Do not scan the file alone.** `vulture stores/history_requests.py
  --min-confidence 60` reports `unused class 'WriteContext'` and its fields,
  because a single-file scan cannot see the five call sites in `stores/`.
  Repo-wide at ≥90 — the confidence this repo tracks — it is clean, and the
  coverage report settles it independently at 100% line and branch.
* **`R0902` (too many instance attributes) is expected here and is not a
  finding.** The module's rating is 9.17 for it, and the sibling dataclass module
  `stores/history_models.py` carries the same code at 8.93 alongside C0116,
  R0913 and R0917. Eight fields is the shape of the signature it replaced.
  Stated plainly, because it is a real difference: `WriteContext` is *not* the
  same shape as §19.4's model — `PersonPageRequest` has 6 fields and so stays
  under pylint's 7-attribute default, `WriteContext` has 8 and does not. What
  §16.2 gates on a class is physical LOC (ideal ≤ 120, fail > 150) and method
  count (≤ 15): `WriteContext` is **20 LOC, 0 methods** and `PersonPageRequest`
  97 LOC, 7 methods, so both sit well inside. The pylint code is a linter
  default this round does not track, not a rule threshold.
