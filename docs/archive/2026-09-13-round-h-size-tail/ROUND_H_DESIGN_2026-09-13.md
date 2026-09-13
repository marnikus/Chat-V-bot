# Round H design — the last four 500-line files, and the steps after them

Date 2026-09-13 · branch `arena/01a09c20-chat-v-bot` · base `de85230`
(G4 design doc on top of executed G1–G3). Required by RULE 16 §16.6 step 2
and RULE 17. Every number in §1 was re-measured on this tree; the audit is
`reports/CODE_QUALITY_METRICS_2026-09-13.md`.

**This document is a plan. No production code is changed in this session.**

Implementation of each step, when it happens, must use a high-capability
model (Claude Opus / GPT-5 class). The owner recorded that smaller models
did not produce working solutions on this tree.

## 1. What Round G left, re-measured

Round G executed G1 (green suite + `WriteTurn` union), G2 (`chat_sync` +
`ScrollParser` families), G3 (flow/injector families + two constructors).
G4 is an approved design that has **not** been implemented — wide-param
count is still 51, identical to the F5 handoff. G5–G7 were never started.

| Item | G start (Round G §1c) | Now | |
|---|---|---|---|
| Files > 500 | 7 | **4** | G2/G3 retired three |
| Worst file | `chat_sync.py` 807 / MI 11.35 | `history_query.py` **601** | |
| Worst MI | 11.35 | `history_bridge.py` **24.95** | floor more than doubled |
| Files < MI 20 | 1 | **0** | |
| Wide > 4 params | 51 | **51** | G4 not run |
| Functions > 30 LOC | 42 | **39** | |
| Classes > 300 LOC | 9 | **8** | `ScrollParser` gone |
| `Collector` methods | 40 | **40** | G3 shrank `__init__`, added no method |
| Cognitive > 15 | 2 (undocumented) | **2** (same two) | |
| `AGENT_RULES.md` | 763 / ~730 | **763 / ~730** | unpaid |
| Suite | 2808 / 0 (G3) | production unchanged | |

The four remaining >500 files, with the seam each one already has:

| Lines | MI | File | Already-visible seam |
|---:|---:|---|---|
| 601 | 35.27 | `backend/history_query.py` | `PersonPageRequest` is already a sibling concept inside the file; `HistoryQuery` is at the 15-method cap so helpers are already module-level; `page` (53, CC 10) and `_search` (49) are the two long methods |
| 544 | 24.95 | `bridge/history_bridge.py` | 31 direct methods + **13 nested `async def work`** that the ratchet counts as 44; comments already group read / mutate / media / settings |
| 532 | 55.73 | `backend/dom_highlight.py` | `_HELPERS_JS` / `_FIND_BODY` / `_CLICK_BODY` / `_HIGHLIGHT_BODY` vs the Python builders vs `interpret_*` |
| 507 | 40.82 | `backend/config_manager.py` | `_Owner` / `_SettingsOwner` / `_ListOwner` / `_DictOwner` / `_NamedOwner` vs `ConfigManager` |

AREA B / AREA D freezes stay lifted (owner ruling F0, Round G §1c). Snapshot
refreshes are still the sanctioned in-step kind: conservation script, no
silent assertion shrink.

## 2. The biggest problem, and why it is H1

Complexity is closed (RULE 19 steps 1–3 have nothing left above a fail
line except two cognitive-17 functions that are not in these four files).
Size is the debt. Of the size debt, **the last four files over 500 lines
are the only remaining glance-test failures** — everything else is a 301–500
band, a wide signature, or a method-count facade.

Inside those four, `history_query.py` is the biggest problem that is also
the most spendable:

* It is the **largest file in the repository** (601).
* `HistoryQuery.page` is the longest remaining *decision* function (53 LOC,
  CC 10 — at both the size and complexity ceilings). `_search` is next (49).
  RULE 19 §19.5: both are long-and-flat ladders, so step 4 (extract by
  concept) is the tool, not flattening.
* `HistoryQuery` is at the method cap (14). New behaviour cannot be added
  without a split; the next feature in this file is otherwise forced to
  grow a landmine.
* It is **not** a Qt slot contract, **not** a RULE 3 wire, **not** a JS
  payload. The public method set stays on the class; only bodies move.
  That is the G2 `ScrollParser` recipe, which already worked once.
* Round G parked it as "G7 backlog". After G2/G3 it is no longer backlog —
  it is the head of the list.

Why **not** start with G4 (wide params), even though that design is ready:

* G4 retires 33 signatures and does not take any file under 500.
* H1–H3 change some of the files G4 also touches (`dom_highlight`
  builders). Doing the file split first means G4's "must not grow
  `dom_highlight.py`" constraint applies to a file that is already in
  band, which is the cheaper place to migrate signatures.
* A ready design does not rot in three size steps; a 601-line file does
  keep attracting features.

Why **not** start with `HistoryBridge` (worst MI): the QWebChannel slot
set is a live wire contract. The nested-`work` extraction is real work
and is H2, not H1. Feasibility × impact still puts the unconstrained
read-path module first — the same ranking Round F used when it did not
start with the frozen #1 file.

## 3. Step plan — Round H (each step ≈ 8–16 h)

| # | Step | Content | Hours | Closes |
|---|---|---|---:|---|
| **H1** | **Split `history_query.py` 601 → facade + 3, and extract `page` / `_search`** | §4 | 10–14 | largest file; CC-10 `page`; method-cap class |
| **H2** | **Decompose `HistoryBridge` 544 / 467 / 44** | nested `work` → collaborators; slots stay; ratchet 44 → 31 | 10–14 | worst MI; largest class; §16.5 landmine |
| **H3** | **The two long-and-flat 500s** | `dom_highlight.py` 532 → JS payload module + Python builders; `config_manager.py` 507 → owners module + facade | 10–14 | files >500 → **0** |
| **H4** | **Wide-parameter continuation (former G4)** | execute `G4_PARAM_OBJECTS_DESIGN_2026-09-13.md` as written: 11 overrides + 33 migrations, stores/ still deferred | 12–16 | 51 → 18 (11 wire + 7 stores) |
| **H5** | **Method-count pass (not facades)** | `StackBridge` 308/31; `ScrollParse` 306/14 LCOM 0.98; `Collector` 40-method facade — which names the host protocol still needs | 10–14 | two Qt/block god classes + a recorded Collector decision |
| **H6** | **301–500 band + density** | `media_handler.py` 482, `router.py` 471 (`_build_router_class` cog 17 lives here — reduce or override), `media_fetch.py` 464, `chat_parser.py` 441; density pair `window_preset_service.py` 326/MI 30.6, `run/progress.py` 314/MI 31.1 | 12–16 | next size slice |
| **H7** | **Test-debt batch (former G5)** | `_migrated_entry`, `_schedule_world_undo_save`, `restart_world` failures, `undo_apply` eight lines, `click_send` family now visible at ~20%, F6b module-wide mutation of the *split* query family, `settings_store.get` cog 17, `dbconn` rewind decision | 10–14 | coverage ≥ G3; mutation job honest |
| **H8** | **Hygiene + RULE 18 context budget (former G6)** | stale `ideal-size:` notes (three are 2 lines off); W0611 triage (~30, not all dead); `_rep` clone; `AGENT_RULES.md` 763 → ≤ 730 by §18.4 extract-first; docs map; JS coverage instrumentation start | 8–12 | notes true, rules loadable, clone ratchet down |

After H3 the glance-test ("any file over 500?") is green. After H4 the
param fail-line for everything outside a documented constraint is green.
H5–H8 are the tail that Round F already named and never finished.

**Do not implement more than one step per session** unless the owner
explicitly continues. Each step gets its own design-outcome section (or
sibling doc, if the step moves complexity across files the way H1–H3 do)
and the §16.7 checklist before it claims done.

## 4. H1 — `history_query.py` split + the two long ladders

### 4.1 Measured starting point

| Symbol | Now | Gate |
|---|---|---|
| `backend/history_query.py` | 601 lines, MI 35.27, sloc 417 | file ≫ 300 ideal, > 500 glance-test |
| `HistoryQuery` | 310 class LOC / 14 methods / LCOM\\* 0.74 | class > 150; at the 15-method cap; ratchet 362/14 (already under loc) |
| `HistoryQuery.page` | 53 LOC, CC 10, cog 10, nest 2, 4 params | both size and CC ceilings |
| `HistoryQuery._search` | 49 LOC, CC 9, cog 8, nest 2, 4 params | size ceiling |
| `PersonPageRequest` | 97 LOC / 7 methods | inside every new-code gate; already the §19.4 model |
| Golden | `backend.history_query` owns `HistoryQuery` + `PersonPageRequest` + the SORT constants the dumper records | refresh is additive (new modules) plus any ownership move we choose to make |

### 4.2 What may NOT change

1. **Behaviour.** No SQL, no sort whitelist, no FTS-then-LIKE fallback
   order, no payload key, no default. The suite is the spec
   (`tests/test_history_query_*.py`, `tests/unit/backend/test_history_query_*.py`
   if present, the Full-User-Database bridge tests).
2. **`HistoryQuery`'s public method set and signatures stay on the class
   in `backend/history_query.py`.** Callers (`bridge/history_bridge.py`,
   `services/history/query.py`, tests) keep importing `HistoryQuery` and
   `PersonPageRequest` from `backend.history_query`. The seam re-exports
   anything that moves.
3. **`PersonPageRequest` stays in the seam file.** Moving it forces an
   OWNED-path edit in `tools/metrics/rule16_gate.py` for seven methods
   that already fit. There is no size win — the class is 97 lines and is
   the file's documented heart. Keeping it also keeps the golden class
   entry unmoved.
4. **Do not promote the file to a package.** `dump_public_api.module_names`
   skips packages; a package would drop the family out of the golden
   (G2 §3.3, same reason). Prefix family, like `chat_sync_*` / `db_deletion_*`.
5. **JS is not involved.** No §16.1.5 exception is needed or claimed.

### 4.3 Target layout

```
backend/history_query.py          seam: SORT_*, PersonPageRequest,
                                   HistoryQuery facade, re-exports     (~250)
backend/history_query_item.py     _FIELD_SPECS, _apply_specs,
                                   _item_media, HistoryQuery._item,
                                   _person_item, _stat_int             (~90)
backend/history_query_page.py     empty page, the three-way window
                                   fetch, has_more/has_newer, gaps,
                                   around                              (~160)
backend/history_query_search.py   _like_escape, _fts_query, _snippet,
                                   FTS path, LIKE path, search_person,
                                   search_global                       (~170)
backend/history_query_stats.py    list_persons, db_stats, person_stats,
                                   _day_bounds                         (~130)
```

Line budget is physical, docstring included. Every sibling lands in or
under the 150–300 ideal. The seam lands in the ideal (150–300) instead of
under 150 because `PersonPageRequest` + the sort tables + the facade
headers are one responsibility: "the archive read API".

Import direction is one-way: seam → {item, page, search, stats}; page /
search / stats → item (for `_item` / `_person_item`); nothing imports the
seam. No cycle can close. `HistoryDB` is imported by the siblings that
run SQL, not by `item.py`.

### 4.4 `HistoryQuery` becomes a facade (14 methods stay, bodies leave)

The class keeps every public name. Each long method becomes a one-call
delegate. That is what §16.5 requires of a legacy offender (must not
worsen; prefer reduce) and what the method cap requires (cannot add a
15th).

```
page            → history_query_page.fetch_page(db, nick, before, after, limit)
around          → history_query_page.fetch_around(db, nick, ord_, radius)
gaps            → history_query_page.fetch_gaps(db, person_id)     # already 7 LOC, still moves so paging stays together
search_person   → history_query_search.search_person(...)
search_global   → history_query_search.search_global(...)
_search         → history_query_search.search_rows(...)            # private, may become module-level
list_persons    → history_query_stats.list_persons(db, req)
db_stats        → history_query_stats.db_stats(db)
person_stats    → history_query_stats.person_stats(db, nick)
_item           → history_query_item.item_from_row(row)            # already 7 LOC
_clamp, _person_row, _my_nicks stay on the class (tiny, used everywhere)
```

Class LOC 310 → ~90 (docstring + 14 thin methods + three tiny helpers).
Ratchet in `rule16_gate.py` lowers 362 → the new measured loc (may
shrink, may not grow). Method count stays 14 unless a nested def
disappears — do not add any.

### 4.5 The two ladders, extracted by concept (RULE 19 §19.5)

`page` is sequential, not nested: clamp → lookup → one of three window
queries → decorate → return. Flattening will not help. Named phases:

| New name | What it is | Why that name |
|---|---|---|
| `empty_conversation(nick)` | the missing-person payload | RULE 4: empty is a value, not a branch |
| `load_window(db, pid, before, after, limit)` | the three-way `after_ord` / `before_ord` / latest query | one responsibility, one CC of ~4 |
| `decorate_page(db, person, items, total)` | has_more / has_newer / gaps / my_nicks | the return dict, once |

`page` on the facade: clamp, call the three, return. Target ≤ 20 LOC, CC
≤ 4. The three helpers are new functions and must meet RULE 16 hard
limits (≤ 30 LOC, CC ≤ 10, cog ≤ 15, nest ≤ 4, ≤ 4 params). If
`load_window` would take 5 params, it takes a tiny `WindowSpec` (before /
after / limit) — the §19.4 pattern already in this file — rather than a
`**kwargs` dodge.

`_search` is a two-backend ladder (FTS, then LIKE), which is the
documented interchange (RULE 19 §19.2 already cites it). Named phases:

| New name | What it is |
|---|---|
| `search_fts(db, where, params, match, select, limit, offset)` | the `try` path; returns `(rows, total)` or raises the same `Exception` the LIKE path currently catches |
| `search_like(db, where, params, needle, select, limit, offset)` | the fallback |
| `search_rows(...)` | pick backend, catch FTS failure, log the existing warning string **verbatim** |

If any helper would exceed 4 params, wrap `(where, params, select, limit,
offset)` as `SearchRun` — one object, used by both backends. Do not
introduce it unless a helper actually crosses 4; speculative objects are
the F5 `_v2` failure mode.

Wording, SQL, and the FTS-failure log line move **verbatim**.

### 4.6 Snapshot and gate edits (the only forced ones)

1. `tools/metrics/dump_public_api.py --write`. Expected golden diff:
   `backend.history_query` keeps `HistoryQuery` (every public method
   signature identical) and `PersonPageRequest` (every method identical);
   new modules `backend.history_query_{item,page,search,stats}` appear
   with whatever they *own* (module-level functions). **Zero removals.**
   Conservation script, same as G2 §5. Blocks golden must be
   byte-identical (this step does not touch actions).
2. `RATCHET[("backend/history_query.py", "HistoryQuery")]` loc lowers to
   the post-split measured class LOC. Methods stay 14 unless a nested def
   disappeared, in which case lower that too. Never raise a ratchet.
3. `OWNED` paths stay valid because `PersonPageRequest` and
   `list_persons` / `_person_item` remain in `history_query.py` (the
   latter two as one-line delegates — still the same function objects the
   gate finds by AST name). If `_person_item` moves to `item.py`, update
   the OWNED tuple in the same commit and keep measuring it.
4. No other test edit. If a test patches `backend.history_query.page` it
   still hits the facade. If a test patches a private helper by module
   attribute, that is a forced accommodation and is enumerated in the
   outcome section the way G2 §4 enumerated three.

### 4.7 Targets to verify after H1

| Measure | Before | Target |
|---|---|---|
| `history_query.py` lines | 601 | **150–300** (aim ~250) |
| Each sibling | — | ≤ 300, preferably 150–300 |
| `HistoryQuery` class LOC | 310 | ≤ 120 ideal if the 14 wrappers fit; fail line 150 |
| `page` LOC / CC | 53 / 10 | ≤ 20 / ≤ 5 |
| `_search` / `search_rows` LOC / CC | 49 / 9 | ≤ 25 / ≤ 6 |
| Every **new** function | — | RULE 16 hard limits; RULE 18 ideals |
| Files > 500 in the repo | 4 | **3** (`history_bridge`, `dom_highlight`, `config_manager`) |
| Full suite | 2808 / 0 (G3) | 0 failed, ≥ 2808, no test losing status |
| Line / branch coverage | 90.99 / 87.05 | **not below**; family files individually ≥ the monolith's |
| `rule16_gate.py --with-clones` | rc=0 | rc=0; ratchet lowered not raised; 0 new clone groups |
| `tests/test_rule16_new_code.py` | 23 passed | 23 passed |
| vulture ≥ 90 | 7 | 7, none new |
| JS suites | 26/26 | 26/26 (untouched) |
| Docs (RULE 17) | stale 603-line note | note **deleted** (file now in band); archive outcome filled; `AGENT_RULES.md` §18.2 measured sentence updated **without growing the file** (rewrite, do not append) |

### 4.8 Dishonest reductions rejected

* **Keeping `page` at 53 and only moving it.** That relocates the ceiling
  hit, it does not fix it. RULE 19 is extract-by-concept, not move-the-blob.
* **Splitting `page` into `page_part1` / `page_part2`.** Forbidden (§16.1.1).
* **Deleting the FTS `except` to drop CC.** That is a real backend; four
  independent outcomes have a CC floor (§16.2).
* **A package `backend/history_query/`.** Drops the family from the golden.
* **Moving `PersonPageRequest` just to shrink the seam.** No reader-gain;
  burns an OWNED-path edit for a class that already fits.
* **Touching `HistoryBridge` in the same step** because it imports
  `PersonPageRequest`. The import stays; the bridge is H2.
* **Running G4's `list_persons` mutation widening "while we are here".**
  F6b is H7. Mixing a structural split with a mutation-job redesign is
  how steps stop being 8–16 h and stop being reviewable.

### 4.9 Tests that lock behaviour before the cut (§16.5)

Existing: the history-query unit/integration files, the userdb bridge
tests that call `list_persons` / `page` / `search_*`, and
`test_backend_api_snapshot.py`. H1 does not add behaviour, so it does
not add tests except:

* one negative check that `page`'s three window paths still disagree
  (after_ord vs before_ord vs latest) — only if the current suite would
  pass with `load_window` always taking the "latest" branch. If an
  existing test already fails that mutation, do not duplicate it.
* the conservation script output, recorded in the outcome section.

A refactor claiming behaviour-preservation runs the **existing** suite as
the equivalence gate (§16.6 step 3).

## 5. H2 — `HistoryBridge`: nested `work` out, slots stay

**Problem.** Largest class (467 LOC), worst MI (24.95), ratchet 467/44.
Direct methods are 31; the extra 13 are nested `async def work` inside
the `@Slot` methods. Those closures are why the gate counts 44 and why
`history_delete_person` is 44 LOC.

**Shape (collaborators, not a second QObject):**

```
bridge/history_bridge.py            QObject, Signals, every @Slot (thin),
                                    _run_async / _schedule / _json_arg /
                                    _need_archive                       (~220)
bridge/history_bridge_read.py       page / search / stats / userdb /
                                    detect_my_nick bodies               (~150)
bridge/history_bridge_mutate.py     delete / clear / purge / restore /
                                    merge / people snapshot             (~180)
bridge/history_bridge_media.py      media_path / restore / folder /
                                    clipboard / copy_text               (~120)
```

Every `@Slot` keeps its name, signature and decorator on `HistoryBridge`.
The slot body becomes `_need_archive` + `_run_async(scope, self._read.foo(...))`
(or mutate/media). Nested `work` closures **disappear** — they become
methods on the collaborator. That is the ratchet drop 44 → 31, which is
the whole point of counting nested defs in the gate.

`history_delete_person` (44 LOC) / `history_clear_person` (38) /
`history_delete_message` (31) extract by phase (guard → token → people
snapshot → repo call → undo push → emit), not by line quota. Log wording
stays verbatim (UI tests pin it).

**Must not:** register a second QObject on the WebChannel; rename a slot;
grow `HistoryBridge` method count; raise the 467/44 ratchet. After the
cut the ratchet **lowers** to the new measured (loc, methods).

**Forced test accommodations:** only if a test patches a nested `work` by
closure (none expected — grep first). Snapshot: `HistoryBridge` public
methods unchanged; new modules additive.

**§16.7:** every new collaborator method ≤ 30 LOC, CC ≤ 10, ≤ 4 params.
File `history_bridge.py` target ≤ 300 (the slot list plus the four
helpers). If the slot list alone cannot fit 300, the leftover is an
`ideal-size:` note that names the QWebChannel contract — the note that
is already there, with a true number.

## 6. H3 — the two long-and-flat 500s

Both files are §19.5 long-and-flat. Do not "fix CC" in them; there is
almost none.

### 6.1 `dom_highlight.py` 532

The mass is JS string literals (`_HELPERS_JS`, `_FIND_BODY`, `_CLICK_BODY`,
`_HIGHLIGHT_BODY`, `_QUERY_VARS`, `_LABEL_JS`, `_MATCH_JS`). §16.1.5
says the Python wrapper's CC/nesting still apply and the JS payload must
**not** be split to game LOC.

```
backend/dom_highlight.py           COLOR_*, public builders,
                                    interpret_find / interpret_click    (~180)
backend/dom_highlight_js.py        the JS literals + `_probe` / `_splice`
                                    (the payload module)                (~350)
```

`dom_highlight_js.py` will sit over 300. That is allowed with

```
# ideal-size: N lines reason=single JS payload family for the two-phase
# visual runner; splitting a literal would break the in-page agent contract
```

The *Python* file lands in band. Builders keep their current wide
signatures in H3 (H4 wave 2 migrates them the next step). Shrinking
signatures and moving JS in one step is two reasons for one diff.

JS bytes must stay **byte-identical** — the in-page contract. A test that
hashes `build_find_probe(...)` output (or the existing interpret tests)
is the equivalence gate. `build_probe` in `dom_probe.py` is **out of
scope** (its own 122-LOC exemption, do not "while we are here").

### 6.2 `config_manager.py` 507

The `_Owner` hierarchy is already the split. It just lives in the same
file as `ConfigManager` + `DEFAULTS`.

```
backend/config_manager.py          DEFAULTS, routes, ConfigManager,
                                    json_dumps                          (~250)
backend/config_owners.py           _Owner and the four subclasses,
                                    _deep_merge, _set_nested            (~250)
```

`ConfigManager` 177 LOC / 20 methods is still over 15 methods — it is a
compatibility facade (the module docstring says so) and stays. Do not
invent a 16th. `__init__` 26 LOC is inside the fail line; leave it
unless a natural extract appears.

Tests: `test_config_manager_contract` patches owners and live-vs-copy
`get()` (ledger #4). The owners module must remain patchable at the
names those tests use, or the tests update as a forced accommodation
enumerated in the outcome.

### 6.3 H3 exit criterion

Files > 500 in production Python: **0**. If `history_bridge.py` after H2
is still > 500, H3 does not include a third rescue — H2 failed its
target and is reopened, not silently widened.

## 7. H4 — execute the G4 parameter-object design

The design is already written and approved:

`docs/archive/2026-09-13-round-g-write-gate/G4_PARAM_OBJECTS_DESIGN_2026-09-13.md`

Run it as written: 11 `quality-override:` constraints (9 RULE 3 block
`__init__`s + `run_sync` + `BridgeRouter.__init__`), 33 in-place
migrations in eight waves, stores/ 7 still deferred. Blocks golden
byte-identical. Walker 51 → 18.

Adjustments this round's H1–H3 force, to be confirmed at the start of
H4 by a fresh walker — not by this document guessing:

* `dom_highlight.build_*` may live next to a JS sibling; the signature
  migration still happens on the Python builders. `probe_requests.py`
  (G4 wave 2) is still the right home for the specs — do **not** put
  them in `dom_highlight_js.py`.
* `ScrollParser.__init__` 19-knob collapse onto `ScrollOptions` is
  unchanged (G2 already introduced `from_options`).
* `sync_conversation` 14 → `SyncRunSpec` still lives in
  `chat_parser.py` / `parser_requests.py`. H6 is what splits
  `chat_parser.py`; H4 must not.

If the walker after H1–H3 does not still read 51, stop and re-derive
the wave list before touching a signature. The F5 lesson: a parameter
object with no migrated caller is dead code.

## 8. H5 — method-count pass, excluding facades

Facades that stay (do not "fix" these): `HistoryRepo` 44, `LabelStore`
38, `MediaStore` 33, `UndoService` 28 (F3 already did this),
`HistoryQuery` after H1.

Real work:

1. **`StackBridge` 308 / 31 / LCOM 0.89.** Same recipe as H2: `@Slot`
   names stay, preset / template / custom-block / run-control bodies
   move to three collaborators. File target 150–300. Method count on
   the QObject will not drop much (slots stay); class LOC and file LOC
   will. Nested helpers, if any, leave.
2. **`ScrollParse` 306 / 14 / LCOM 0.98.** RULE 3 wire `__init__` stays
   (H4 override). `run_pipeline` / `_collect` / `to_scroll_options` /
   `build_parser` become the G4 wave 8 objects **if H4 has already
   landed**; if H5 runs first, extract bodies without changing
   signatures. Prefer H4-before-H5 so this step does not fight H4 wave 8.
3. **`Collector` 40 methods / 216 LOC.** F2 already extracted
   collaborators; G3 moved the counter block. What remains is a facade
   the `collector_structure` tripwire pins. H5's job is a **decision
   record**: list every name, mark host-protocol vs true leftover, and
   only then move leftover names off the class (netting down, §16.5 —
   no 41st method). If the tripwire forbids a net drop, record that as
   a documented constraint (`quality-override: methods=40 reason=...`)
   rather than pretending the 40 is oversight.

`HistoryExportService` 21 methods / LCOM 1.00 is 113 LOC — inside the
class-LOC gate, over the method gate. It is a bag of independent export
operations. Splitting it is a cohesion pass, not a size pass; do it here
only if (1)+(2)+(3) finish inside the hour budget. Otherwise H6/H8.

## 9. H6 — 301–500 band + density

Pick by (MI × lines), not by lines alone. The working set:

| Lines | MI | File | Likely split |
|---:|---:|---|---|
| 482 | 45.8 | `backend/media_handler.py` | attach vs list vs JS readback; `_rep` clone with injector is the H8 dedup, not this split |
| 471 | 44.9 | `bridge/router.py` | `_build_router_class` (51 LOC, cog 17, CC 10) is the density; extract the class factory from the instance |
| 464 | 31.5 | `stores/media_fetch.py` | `MediaFetcher` 306/15 is cohesive — helper module, not decomposition |
| 441 | 40.7 | `backend/chat_parser.py` | gate functions vs `ChatParser` vs `sync_conversation` (H4 already narrowed the latter) |
| 441 | 37.7 | `stores/history_repo_lifecycle.py` | cohesive 375/19 — helper module |
| 440 | 41.8 | `stores/history_schema_repair.py` | cohesive 406/25 — helper module |
| 425 | 32.9 | `services/collector_tick.py` | already three classes; file-level split by Probe / Archive |
| 326 | **30.6** | `window_preset_service.py` | density, not size — explain-and-decompose |
| 314 | **31.1** | `services/run/progress.py` | same |

One step cannot honestly finish nine files. H6 does **router
(`_build_router_class` cog 17) + media_handler (next-largest unfrozen
file) + the two density files**. The cohesive stores helpers
(`SchemaMigrator`, `PersonLifecycle`, `MediaFetcher`) are a second H6
session if the owner continues, not a silent widening.

`_build_router_class`: RULE 19 order is cognitive last among complexity,
but nesting is 3 and CC is 10 — so the order is CC (at ceiling) then
cognitive. Extract the per-bridge registration so the factory is a loop
over a table, not 51 lines of `setattr`. If four independent bridges
cannot cost less than CC 5, do not delete a bridge to make the number.

## 10. H7 — test debt

Former G5, plus what G3 made newly visible:

| Item | Why it is here |
|---|---|
| `undo_support._migrated_entry` (and the seq-preserving rebuild) | untested; this is the function that issued duplicate seqs |
| `undo_world._schedule_world_undo_save`, `restart_world` three failure paths | `undo_world.py` 84% |
| `undo_apply.py` eight attributed lines | exception fallbacks, refusal, redo `Err` |
| `click_send` family | G3 split made 20% coverage a file-level number; tests that would fail if `click_send` were deleted (RULE 8) |
| F6b module-wide mutation of the **H1 query family** | 910 reachable vs 159; own step, not smuggled into H1 |
| `stores/settings_store.py::get` cog 17 | 17 LOC, nest 4 — reduce (named predicates) or a real `quality-override:` |
| `dbconn` rewind vs `archive` | product decision; implement only if the owner rules |

Coverage must not fall below G3 (90.99 / 87.05) and not below the
2026-09-10 floors (90.44 / 84.38). Every new test would fail if the
production function were deleted.

## 11. H8 — hygiene + the rules-file budget

* **Stale `ideal-size:` notes.** After H1–H3 the three "scheduled debt,
  603/534/509" notes are gone with their files. Any leftover note whose
  number disagrees with `wc -l` is rewritten or deleted. "A note whose
  number is wrong is worse than no note" (Round F §12.8).
* **W0611 triage.** ~30 findings. Delete only names that are not
  re-export seams and not `quality-override:`-adjacent. `history_db.py`'s
  schema re-exports look unused to pylint and may be the public surface —
  grep before deleting. `find_and_click` imports on click-blocks may be
  intentional RULE 1 breadcrumbs; confirm against `FindClickBlock`.
* **`_rep` clone** (`media_handler.py` ↔ `message_injector_field.py`).
  One shared helper in a tiny module both already conceptually own, or
  one side imports the other if direction allows. Then **delete** the
  baseline pair (ratchet down).
* **`AGENT_RULES.md` 763 → ≤ 730.** §18.4: extract first, then the file
  can take a sentence. Candidates: the §18.2 measured paragraph (move
  the file table into this audit), the §16.5 landmine list (move into
  the audit — `ScrollParser` is already off, `Collector` / `HistoryBridge`
  / `UndoService` / `coordinator` / `label_state` / `history_query` /
  `db_lifecycle` / `tab_matcher` / `wait_page` need a true-today rewrite
  *in the archive*, with the rule keeping a one-line pointer). Do not
  cut norms to make a number.
* **Docs map.** `docs/README.md` still says 86 archived docs in places;
  `docs/archive/README.md` said 88 in 18 groups against 89 on disk
  before this folder. This session pays the Round H registration; H8
  re-counts from `find`.
* **JS coverage instrumentation.** Start: one tool (`c8` or `nyc`) on
  the 26 Node entrypoints, recorded as a baseline, no fail-under yet.
  9,283 frontend LOC is the rest of the iceberg and is **not** this
  step's close-out.

## 12. RULE 16 / RULE 18 / RULE 19 — the gate each step must pass

Copied so a step session does not have to re-derive it. A step that
cannot tick this list is not done, even if the metric it aimed at moved.

```
[ ] No new function > 30 physical LOC (except documented JS-literal builders)
[ ] No new class > 150 LOC or > 15 methods
[ ] No new function with > 4 params (excluding self/cls)
[ ] radon CC ≤ 10, cognitive ≤ 15, nesting ≤ 4 on every new/edited function
[ ] overall line coverage ≥ 80% and not below G3 90.99 / 87.05; branch ≥ 75%
[ ] every new function has a test that would fail if deleted
[ ] no new vulture unused-import findings; no new duplication groups
[ ] quality-override comments used only with a real constraint
[ ] did not game metrics with dummy helpers (record the reductions you rejected)
[ ] new code aims at RULE 18 ideals (function 4–20, file 150–300, module 5–15);
    every deviation carries an ideal-size: reason that names a constraint
[ ] complexity/size remediation followed RULE 19
    (nesting → cyclomatic → cognitive → size last; long-and-flat → size)
[ ] SYSTEM_OF_RECORD.md + docs/README.md updated if behaviour/docs moved
[ ] did not grow a §16.5 landmine (Collector, HistoryBridge, UndoService,
    RunCoordinator, history_query until H1 lands, db_lifecycle, …)
[ ] ratchet numbers only move down
[ ] AGENT_RULES.md does not grow; extract first if a sentence must be added
```

H1's shape against RULE 19: `page` and `_search` are long-and-flat
(§19.5), so size-extraction is the first tool, not flattening. Nesting
is already ≤ 4; CC 10 on `page` falls because the three window queries
leave the function, not because a decision was deleted.

## 13. What this session does not do

* Does not implement H1–H8.
* Does not refresh goldens, lower ratchets, or delete unused imports.
* Does not re-run the Python suite (production is the G3 tree; quoting
  G3 is honest). JS 26/26 *was* re-run for the audit.
* Does not edit archived Round F / G docs except as RULE 17 allows a
  one-line pointer. Round G's "G4–G7 remain planned" is true as of its
  date; this document is the successor plan, not a rewrite of that one.

## Reproduction (the measurements this plan rests on)

Same commands as `reports/CODE_QUALITY_METRICS_2026-09-13.md` §Reproduction.
The audit JSON for this session lived at `/tmp/audit_h.json` (outside
the checkout, same reason as the 09-12 audit: coverage artifacts are
not gitignored).
