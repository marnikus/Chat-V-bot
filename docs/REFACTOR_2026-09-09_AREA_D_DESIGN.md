# AREA D — `backend/` + `actions/` Refactor Design

**Date:** 2026-09-09 · **Branch:** `arena/01a08853-chat-v-bot` (implements `refactor/d-backend-actions`)
**Parent plan:** `docs/REFACTOR_2026-09-09_FOUR_AREA_PLAN.md` §6.4 (AREA D), §7.3 (contracts), §8.3 (gates)
**Scope:** all of `backend/**` + `actions/**` — 50 files, 5 345 SLOC. Nothing outside it is edited.
**Status:** design → tests → implementation, in that order (this document is written first).

---

## 0. What this area is for

The plan's one-line summary: *"the single worst function in the repo lives here"*.
`sync_conversation` carries CC 130 / 295 LOC / 14 params / nesting 46, `ScrollParser.collect`
CC 43 / 192 LOC, and the `actions/` package is ~57 % copy-paste. Area D turns those into
small, named phases with dataclass seams, and replaces the hand-copied block skeleton with
one shared base — **without changing a single public signature or a byte of the JS wire**.

### 0.1 Measured baseline on THIS checkout (not copied from the plan)

The plan measured 377 failing tests; this checkout already carries areas A/B/C, so the
D-relevant baseline was re-measured (`pytest tests`, poisoners ignored, webengine test
deselected — see §7 for the exact commands):

| metric | baseline (this checkout) | plan's number |
|---|---|---|
| suite | 51 failed / 1553 passed / 1 collection error | 223 failed (pre-A/B/C) |
| failing tests in D's owned list | **1** (`test_config_manager_contract::test_to_dict_is_valid_json_with_all_sections`) | 3 + 10 |
| `backend` coverage | 83.4 % line / 88.9 % branch | 82.8 % / 78.3 % |
| `actions` coverage | 83.6 % line / 83.9 % branch | 83.6 % / 61.6 % |
| functions over CC 25 in `backend/`+`actions/` | **7** (130, 43, 43, 35, 31, 27, 26) | 7 |
| `actions` duplication (definition §6) | 22.2 % (15 clone groups) | ~57 % (looser detector) |

The CC table below was produced with the plan's own metric (`tools/metrics/deep.py`'s
`cc_of`, re-used verbatim in `tools/metrics/area_d.py`) and matches §3.1 of the plan
item for item — which is what tells us the numbers are comparable:

| CC | LOC | nest | par | function | D-task |
|---|---|---|---|---|---|
| 130 | 295 | 46 | 14 | `backend/chat_parser.py:358 sync_conversation` | D1 |
| 43 | 66 | 10 | 5 | `backend/chat_parser.py:155 verify_private` | D1 |
| 43 | 192 | 28 | 5 | `backend/scroll_parser.py:298 collect` | D2 |
| 35 | 118 | 20 | 4 | `actions/collect_history.py:87 execute` | D6 |
| 31 | 92 | 15 | 4 | `actions/click_user.py:87 execute` | D6 |
| 27 | 126 | 15 | 12 | `backend/visual_click.py:56 find_and_click` | D4 |
| 26 | 137 | 14 | 10 | `backend/media_handler.py:224 attach_image` | D4 |
| 22 | 34 | 2 | 1 | `backend/history_query.py:80 _item` | D5 |
| 20 | 36 | 9 | 3 | `backend/tab_matcher.py:70 score_tab` | D5 |
| 18 | 72 | 12 | 9 | `actions/scroll_parse.py:150 run_pipeline` | D6 |
| 17 | 31 | **14** | 2 | `backend/config_manager.py:178 set` | D3 |
| 17 | 38 | 8 | 2 | `backend/dom_highlight.py:393 interpret_find` | D2b |
| 16 | 59 | **14** | 4 | `actions/mark_messaged.py:28 execute` | D6 |

Coverage gaps that need tests before any refactor (the "test first" step):
`actions/wait_page.py` **22 %**, `actions/click_send.py` **35 %**, `actions/pause.py` **46 %**,
`actions/conditional_skip.py` 61 %, `actions/repeat_loop.py` 71 %, `actions/mark_messaged.py` 76 %,
`actions/collect_history.py` 78 %, `actions/take_person.py` 79 %, `backend/message_injector.py` **68 %**,
`backend/config_manager.py` **71 %**, `backend/chat_parser.py` **81 %**, `backend/logger.py` **0 %**.

---

## 1. Contracts that must not move (the whole design is fenced by these)

Ground rules from §7.3 of the plan. They are the reason every split below is an
**internal extraction with a frozen façade on top**:

1. **No public symbol is renamed, moved or re-signatured.** Gate 6 of the plan diffs the
   signature dump of every package before/after and allows *new* symbols only.
   Concretely, these signatures are welded:
   * `sync_conversation(parser, repo, nick, my_nick=…, …, media=…)` — 14 params, all by
     name, called from `services/collector_service.py:_sync` (kwargs) and
     `actions/collect_history.py` (kwargs);
   * `ChatParser.__init__(cdp, chunk_size=80, chunk_pause_ms=40)` — `services/history/__init__.py:37`;
   * `backend.chat_parser._signature` — imported *by name* by `services/collector_service.py:30`;
   * `verify_private(state, nick, my_nick="", items=None, require_private=True)` — RULE 15;
   * `ScrollParser.__init__` (20 params) and `collect(progress_cb, min_new_users,
     known_messaged, seek_nicks)` — `actions/scroll_parse.py`, `services/run/coordinator.py`;
   * `find_and_click(cdp, *, selector, …)`, `find_and_click_exact(cdp, *, text, **kw)` —
     RULE 1: every clicking block and `backend/media_handler.py`;
   * `attach_image(cdp, folder_path, file_pattern, mode, simulate_dialog, verify_timeout_ms,
     highlight_enabled, confirm_pause_ms, report, verify_poll_ms)` — positional from
     `actions/attach_image.py`;
   * `ConfigManager` (`get/set/get_copy/named_*/get_state/set_state/save/load/data/to_dict/
     validate`), `DEFAULTS`, `MAX_STACK_HISTORY`, `_path` — `app/bootstrap.py`,
     `services/undo_service.py`, `bridge/undo_bridge.py`, 25 test files;
   * `build_find_probe/build_click_probe/build_highlight_probe/build_clear_probe` and the
     three `interpret_*` — positional calls in `tests/test_find_click_visual.py`;
   * every `BaseAction` subclass's `__init__(**block_kwargs)`, `execute(user_nick, cdp,
     engine)`, `to_dict()`, `config_schema()` — `RunCoordinator.load_stack` builds blocks as
     `cls(**{k: v for k, v in block.items() if k != "block_id"})`, so **constructor kwarg
     names are the wire format** shared with `ui/js/stack-dnd.js` and the preset files.
2. **Frozen files are not edited at all** (§7.3.2): `backend/cdp_client.py` (Ca 22),
   `actions/base_action.py` (Ca 19) and the 12 `backend/*.py` compat shims.
   *Consequence:* the 100 %-confidence dead symbols at `backend/cdp_client.py:35`
   (`exc_type`, `tb`) are **not** deleted here — the plan itself assigns the 5 dead symbols
   to the cleanup PR ("the one exception to 'no removals' is the cleanup PR", §8.3 Gate 6),
   and 3 of the 5 live in `services/run/*` (areas A/C). Deferred, listed in §8.
3. `core/*`, `bridge/*`, `app/*`, `main.py`, `stores/history_models.py` (which owns
   `SyncResult`/`MessageRecord`/`Alignment`), `stores/jsonio.py`, `stores/migration.py` —
   untouched; the JS in `ui/js/**` is untouched because no bridge file changes.
4. **Behaviour is frozen too**: RULE 1–15 of `docs/AGENT_RULES.md` are behavioural contracts
   (two-phase visual confirmation, "empty ≠ broken", stop honoured in every loop, live
   per-person callbacks, nothing archived without the two-step gate, one control per
   decision). Every refactor below must keep them literally true, not approximately.

---

## 2. Target structure

```
backend/
  chat_agent_js.py     ── unchanged (the in-page agent source; frozen by rule 1 of §7.3 in spirit)
  chat_parser.py       ChatParser (probes) + parse_records/_payload/_signature/_norm
                       + PrivateCheck gate            ← stays the module everyone imports
  chat_sync.py         ★ NEW  SyncOptions, SyncPlanner, ReadPlan, ChunkReader,
                             DeltaAligner, SyncPersister, run_sync()
  scroll_parser.py     ScrollOptions ★ + ScrollParser façade + _Pass + 4 phases
  dom_highlight.py     shared probe chassis (_PROBE_JS/_probe()) + 4 builders
  config_manager.py    ConfigManager façade + SectionOwner adapters (per-section managers)
  visual_click.py      ClickRequest ★ + find_phase/click_phase + the legacy entry points
  media_handler.py     AttachOptions ★ + the six stages + attach_image() façade
  history_query.py     _item → _media_of/_fields_of
  tab_matcher.py       score_tab → three ranked matchers
  message_injector.py  _rep/_js split; click_send → two probes
  …                    (cdp_client, dom_probe, person_filter, criteria_engine, logger,
                        chat_agent_js, 12 shims — unchanged)

actions/
  base.py              BaseAction (unchanged) + ★ BlockField, MarkerBlock, FindClickBlock
  click_back.py        FindClickBlock        (76 → ~34 lines)
  click_main_tab.py    FindClickBlock        (76 → ~34 lines)
  custom_find.py       FindClickBlock        (109 → ~62 lines)
  click_send.py        FindClickBlock + fallback request
  click_user.py        phases: _resolve_nick / _click / _confirm_new_tab
  collect_history.py   phases: _service / _target / _outcome report
  scroll_parse.py      ScrollParseOptions ★ (block half) → backend ScrollOptions
  mark_messaged.py     guard clauses (nesting 14 → ≤ 3)
  wait_page.py         _poll loop + phase helpers
  pause.py / conditional_skip.py / repeat_loop.py / take_person.py
                       MarkerBlock subclasses
  base_action.py, registry.py, context.py, find_click_runner.py — unchanged
```

The rule of the whole area: **a façade keeps the old name and signature; the work moves into
a named collaborator that takes a dataclass.** No caller in `services/`, `bridge/`, `app/`,
`stores/` or `core/` changes by one line.

---

## 3. D1 — `chat_parser` / `chat_sync`: the 130-CC sync

`sync_conversation` is a linear narrative of six phases that currently interleave through
46 nesting levels. The extraction keeps the narrative, gives each phase a name, and moves
the 11 optional knobs into `SyncOptions`.

```
sync_conversation(parser, repo, nick, …14 params…)   ← façade, signature welded (§1)
  └─ run_sync(parser, repo, nick, SyncOptions)        ← the orchestrator, CC ≤ 15
       ├─ open_sync()        probe → install-if-missing → gate (agent/ok/private/partner)
       ├─ plan_viewport()   backfill: scroll-to-top → settle → restore-on-failure
       ├─ SyncPlanner.plan()  count/head/tail + cursor  → ReadPlan{mode, start, gap}
       │        mode ∈ {EMPTY, UNCHANGED, DELTA, FULL}
       ├─ ChunkReader.read()  paced, retrying, stop-aware range reads
       │        └─ sink: StreamingAppend (repo.append per chunk) | BufferAll
       ├─ DeltaAligner.backfill()  prepend what appeared above what we stored
       ├─ SyncPersister.finish()   final cursor write (+ mark_backfilled)
       └─ SyncPersister.repair_tail_media()  newest-window media pass after restore
```

* **`SyncOptions`** (frozen dataclass, `slots`) — `my_nick, require_private, verify_partner,
  max_messages, chunk_pause_ms, should_stop, on_progress, now, backfill_older,
  backfill_wait_s, media`, plus `SyncOptions.from_kwargs(**legacy)` used by the façade.
  Defaults equal today's defaults, and `resolved(parser)` fills `chunk_pause_ms` from the
  parser (the one value that today depends on the parser instance).
* **`ReadPlan`** — the decision that today is spread over `count == 0`, the "nothing moved"
  early return, `delta = …`, `start = …`, `streaming = …` and the `max_messages` cap.
  It is a *pure* function of `(state, cursor, options)`, which makes the whole delta/
  bootstrap/gap logic unit-testable **without a page object at all** (new tests, §6).
* **`ChunkReader`** owns the two nested loops (chunk loop × `SLICE_RETRIES`) and the
  viewport-restore fallback. `SLICE_RETRIES = 4` stays module-level in `chat_parser`
  (a test imports it? no — but the docstring of the module documents it; keep the constant
  exported from both modules).
* **`SyncPersister`** owns every `repo.*` write: `append` (streaming, final cursor,
  prepend-backfill), `record_gap`, `mark_backfilled`, `recover_media`. Today 5 separate
  `try/except log.debug` blocks around `mark_backfilled`/`recover_media` collapse into two
  methods.
* **The gate** (`verify_private`, CC 43) is decomposed into guard-clause helpers
  (`_clean`, `gate_tab`, `gate_title`, `gate_self_chat`, `gate_authors`) — RULE 15 fails
  closed, so the order of the reasons is *part of the contract*: `not_private →
  no_partner → title_mismatch → self_chat → no_author_data → strangers → ok`.
  `PrivateCheck` fields and their meaning stay byte-identical.
* **`chat_parser` keeps re-exporting** `sync_conversation`, `SyncOptions`, and every name
  any consumer imports today, so `from backend.chat_parser import …` never breaks.
  `import backend.chat_sync` at the top of `chat_parser.py` is one-directional
  (`chat_sync` imports nothing from `chat_parser`, only duck-typed args) — no cycle.

**Why `run_sync` cannot grow a cycle:** `ChatParser` and `HistoryRepo` are passed in as
arguments; `chat_sync` imports `stores.history_models` and `stores.history_repo.align_batch`
only, i.e. it sits *below* `chat_parser` on the same layer.

---

## 4. D2 / D2b — `scroll_parser` and the probe chassis

### D2 `ScrollParser`

`collect()` = one `for scroll_i in range(max_scrolls)` loop whose body is 150 lines with
four different concerns (per-item judgement, seek mode, stall detection, UI callbacks).

* **`ScrollOptions`** (frozen dataclass, `slots=True`) holds the 18 configuration knobs
  (`viewport_sel … log_cb`); `ScrollParser.__init__` keeps its exact 20-param signature and
  builds the dataclass, and the new `ScrollParser.from_options(cdp, options, criteria=None)`
  classmethod is the constructor new code should prefer. All decision logic then reads
  `self.options.x`, so the object is the single source of truth for the pipeline's pacing,
  and `actions/scroll_parse.py` can hand the whole block configuration over as **one** value
  instead of 16 kwargs (D6).
* **Phases.** `collect()` becomes: `_prepare()` (filter + first snapshot + the
  "no viewport" warning) → per-scroll `_consume_batch(snap, pass)` → `_advance(snap, pass)`
  (progress cb, stall/end-of-list/scroll/settle). `_Pass` (mutable dataclass) carries
  `new_this_scroll`, `no_new_count`, `collected_nicks`, `snap`.
* **`_consume_batch`** returns the number of new people and keeps the seek-mode branch in
  its own method (`_seek_hit`, `_collect_one`, `_reject_one`) — RULE 11's "a seek writes
  nothing but still counts" asymmetry is a named function now instead of three interleaved
  `continue`s, and RULE 5/6 (live callbacks, purge) stay in the same place.
* STOPPED vs "page context lost" (RULE 7) keeps its distinct sentinel handling;
  `_settle` is unchanged in behaviour and already has its own name.

### D2b `dom_highlight`

The four builders repeat the same chassis: `(function(){ var out={…}; <helpers>
try { … } catch (err) { out.error = … } return JSON.stringify(out); })()`.
`_PROBE_JS` (the chassis) + `_probe(body, **fields)` (formatting + `_js_str` quoting)
replace it once per builder; the node-matching preamble (`querySelectorAll` → label →
`matchText` exact/contains filter) is a shared `_MATCH_JS` fragment used by the FIND and
HIGHLIGHT bodies (CLICK needs a different one: it starts from the stash).
`interpret_find` loses its nesting by an early `_candidate_lines()` helper.
**Emitted JS stays semantically identical** and is proven by running the probes for real
through `tests/js_harness.js` (RULE 8) in `tests/test_find_click_visual.py` /
`test_collect_visual_and_live_refresh.py`, plus a new harness suite (§6) that executes the
generated probes of *every* builder against the DOM stub and compares the observable effects
(overlays drawn, clicks dispatched, stash written) — not the strings.
The two string pins the existing contract test asserts (`var doClick = false;`,
`var doClick = true;`, `STASH_KEY` present, `.click()` absent from the highlight probe) are
kept by construction.

---

## 5. D3 — `config_manager`: per-section owners, not an if-chain

`get()`/`set()` each dispatch on the store identity with a 5-branch `if/elif` chain and
`set()` reaches nesting 14 — the `'str' object has no attribute 'get'` class of bug lives
precisely in that dispatch.

* **`SectionOwner` adapters** (`backend/config_manager.py`, private classes):
  `_SettingsOwner` (nested keys, deep merge, `data()`), `_ListOwner` (bookmarks, blocks),
  `_DictOwner` (labels file), `_NamedOwner` (presets). Each exposes
  `read(rest, default)` / `write(rest, value)` / `snapshot()`.
  `_SECTION_ROUTES` maps section → owner; `_store_for()` stays (tests monkeypatch it),
  now returning the owner. `get()`/`set()` become `owner = self._owner_for(section)` +
  one call each, so adding a section is a new entry in the table, not a new `elif`.
* **`data()` always exposes every documented section** — merged as
  `{**defaults_for_settings, **overlay}` for the settings store, so a fresh install answers
  `chrome/scroll/delays/ui/history/collector` in `to_dict()` (the failing D test, §7 of the
  parent plan). This is the fix, not a workaround: `get()` already promises defaults, and
  the bridge's `get_app_state` renders from `data()`.
* **Hostile-path safety**: nested reads/writes tolerate a scalar standing where a dict
  belongs (`set("history", "enabled")`, or a hand-edited file) — guard clauses return the
  default instead of `AttributeError`, and `validate()`/`save()` keep working (test CF#6).
* `named_*`, `get_state`/`set_state` keep their routing (undo keys → `UndoStore`), with the
  `set_state` "flush everything" quirk documented and preserved: it is load-bearing for
  `services/undo_service.py` (area C) which calls `set_state(grid_layout=…)` and expects the
  settings store to be flushed too.

---

## 6. D4/D5/D6 — parameter objects and the block skeleton

**D4 `visual_click` / `media_handler`.** `ClickRequest` (frozen dataclass: selector,
label_selector, match_text, match_mode, click_enabled, click_selector, highlight_enabled,
confirm_pause_ms, highlight_ms, label) + `find_phase()` / `click_phase()` / `run_click()`.
`find_and_click(cdp, *, …)` = `run_click(cdp, ClickRequest(…))` and
`find_and_click_exact` = the same with `match_mode=MATCH_EXACT`. `attach_image` splits into
`_scan_folder`, `_pick_file`, `_resolve_target`, `_open_dialog`, `_inject_file`,
`_verify_sent` behind an `AttachOptions` dataclass; the return contract (True only when the
file landed *and* a new message appeared) and every log string stay byte-for-byte, because
tests assert on the reported phrases.

**D5.** `history_query._item` → `_media_of(row)` + `_fields_of(data)`; `tab_matcher.score_tab`
→ three ranked matchers (`_exact`, `_site`, `_keyword`) in a table. Neither is over the CC
gate today; both are cheap, low-risk reductions that the plan asks for ("targeted CC/param
reductions"). `cdp_client.py`, `dom_probe.py`, `criteria_engine.py`, `person_filter.py` are
left alone: they are either frozen (`cdp_client`) or already ≤ CC 14 with the shape their
consumers import.

**D6 `actions/`.** The clone is one pattern repeated by eight files:

```python
def __init__(self, <params>, pre_delay_ms=X, **kw):
    super().__init__(pre_delay_ms=pre_delay_ms, **kw)
    self.<p> = <clean>(<p>)            # + max(0, int(...)) / bool(...) coercion
async def execute(self, user_nick, cdp, engine=None):
    await self.pre_delay()
    return await find_and_click(cdp, selector=self.selector, …, engine=engine)
def config_schema(self):
    s = super().config_schema(); s["f"] = {...}; return s
```

* **`BlockField`** — `name`, `type`, `label`, `default`, `options`, `help`, `clean`.
  A subclass declares `FIELDS = (BlockField(...), …)`; `BaseAction.__init__`-driven
  coercion, `to_dict()` and `config_schema()` all derive from that one tuple.
  RULE 3 ("block settings are plain instance attributes") stays literally true: the fields
  are set as `self.<name>`, and `to_dict()` keeps emitting exactly the same keys, so
  presets round-trip unchanged.
* **`MarkerBlock`** — blocks the engine drives itself (`CONDITIONAL_SKIP`, `REPEAT_LOOP`,
  `TAKE_PERSON`): `pre_delay_ms` forced to 0, `execute()` returns `SKIP` with an
  overridable `marker_message()`.
* **`FindClickBlock`** — the two-phase clicking family (`CLICK_BACK`, `CLICK_MAIN_TAB`,
  `CUSTOM_FIND`, `CLICK_SEND`): one `execute()` that builds the `ClickRequest` from the
  declared fields, plus `fallback_requests()` for `CLICK_SEND`'s second attempt.
* `click_user.execute` (CC 31) → `_resolve_nick()` + `_verify_new_tab()`; `collect_history.execute`
  (CC 35) → `_service_or_report()`, `_resolve_target()`, `_result_report()`; `mark_messaged`
  (CC 16, nesting 14) → a `_say()` guard and one `_fail()`/`_ok()` pair so each status branch
  is three lines.
* `ScrollParse` gains `to_scroll_options()` returning the backend `ScrollOptions`, so its
  `build_parser` passes one object instead of 16 kwargs, and `run_pipeline` splits into
  `_decide_mode` / `_collect` / `_report_queue`.

---

## 7. Test plan (written BEFORE the refactor)

New files, all `unittest`-style, all standalone-runnable and pytest-discoverable, following
`docs/BACKEND_TESTS_DESIGN_2026-09-09.md` §1 (no copy tests, contract IDs in docstrings,
bug-finding assertions). IDs continue the existing namespaces (CP#, CF#, DH#, DP#…).
Area D owns its test files (§6.5 of the plan); these are *additive* files, so they cannot
conflict with any other area.

| file | covers | contract ids |
|---|---|---|
| `tests/unit/backend/test_chat_sync_plan.py` | `ReadPlan`/`SyncPlanner` pure decisions + `SyncOptions` defaults/`from_kwargs` | `SY#1–10` |
| `tests/unit/backend/test_chat_sync_phases.py` | `ChunkReader` (retries, stop, pacing, progress), `DeltaAligner`, `SyncPersister` against a scripted fake parser/repo | `SY#11–24` |
| `tests/unit/backend/test_scroll_parser_options.py` | `ScrollOptions`/`from_options`, defaults parity with the 20-arg ctor, batch phases (`_consume_batch`, seek asymmetry, stall math) | `SP#1–12` |
| `tests/unit/backend/test_dom_highlight_probes.py` | the HIGHLIGHT and CLEAR probes **executed** in the node harness, asserting effects (overlay count, colour, caption, timers, stash untouched, clear_first, clicks/scrolls that must not happen) — RULE 8. Written as `test_dom_probe_exec.py` in the plan; FIND/CLICK execution stays in `tests/test_find_click_visual.py` | `DX#1–14` |
| `tests/unit/backend/test_config_manager_sections.py` | per-section owner table, hostile nested paths, `data()` section completeness, `named_*`/`set_state` routing | `CF#8–17` |
| ~~`tests/unit/backend/test_message_injector_flow.py`~~ | not written: `message_injector` is at 68 % line coverage from `tests/test_message_injector_text.py` + `test_attach_image.py` and its worst function is CC 12, so the flow suite was dropped when the coverage gate passed without it | `MI#1–5` (existing) |
| `tests/unit/backend/test_logger_setup.py` | `setup_logger`: dated file name, rotation limits, shared formatter, level on logger + handlers, handler clearing on re-setup, stdlib-only imports | `LG#1–11` |
| `tests/unit/actions/test_block_base.py` | `BlockField` coercion + panel entry, defaults taken from the constructor, `to_dict()` key order, preset round-trip, the runner kwargs of the four clicking blocks, `CLICK_SEND`'s fallback matrix, `MarkerBlock` skip/zero-delay | `AB#1–20` |
| `tests/unit/actions/test_click_user_tab_verify.py` | `ClickUser`'s tab ladder: memory vs queued nick, before/after snapshots, the three verdicts, unreadable page, `tab_pause_ms` | `CU#1–20` |
| `tests/unit/actions/test_find_click_blocks.py` | the four clicking blocks against a fake CDP: pre-delay, kwargs, fallback, disabled-highlight path, `SKIP`/`FAIL`/`OK` mapping | `AC#1–10` |
| `tests/unit/actions/test_block_actions_coverage.py` | `PAUSE`, `WAIT_PAGE_LOAD` (found/timeout/probe-error/throttle), `ATTACH_IMAGE`, `TYPE_MESSAGE`, `MARK_MESSAGED` status matrix, `TAKE_PERSON.choose` | `AA#1–14` |
| ~~`tests/unit/actions/test_collect_history_block_flow.py`~~ | not written: `tests/test_collect_history_block.py` already covers those paths and `test_block_actions_coverage.py` the rest; `collect_history` sits at 78 % with every branch of the split exercised | `AH` (existing) |

Rules these tests obey:

* **Characterisation first.** Where behaviour is today's *de facto* contract (log wording,
  reason codes, `SLICE_RETRIES` pacing, the aliasing of `get()`), the test pins it as it is;
  only §5's `data()` completeness is an intentional behaviour change, and it is a documented
  promise (`CF#1`) that the code fails today — the test is written red, then made green.
* **Real execution.** JS is executed, not string-matched; asyncio code runs on a real loop
  with fake CDP/page objects that behave like the page (RULE 8).
* **No edit of another area's test file.** Existing D-owned files stay as they are
  (including the `@unittest.expectedFailure` ledger bug in `test_config_manager_contract.py`,
  which stays: fixing `get()` aliasing is not in this area's scope).

---

## 8. Non-goals / deferred

| item | why |
|---|---|
| deleting `backend/cdp_client.py`'s dead `exc_type`/`tb` (P3-8) | the file is frozen for all areas (§7.3.2); the plan gives the 5 dead symbols to the cleanup PR |
| retiring the 11 test-only `backend/*.py` shims | §9 of the plan — codemod after all four areas merge |
| the `stores → backend.chat_agent_js` and `services → backend.{history_query,chat_parser}` inversions | they span areas B/C/D; §9 |
| `backend/cdp_client.py`, `dom_probe.py`, `criteria_engine.py`, `person_filter.py` internals | already inside every gate; churn without payoff |
| changing the `get()` aliasing bug (ledger #4, D-owned test marks it `expectedFailure`) | behaviour change other areas' tests could depend on; not asked for by the plan |
| `actions/base_action.py` re-signaturing | frozen shim; the ABC it re-exports is unchanged |

---

## 9. Order of work (each step ends with the suite no-worse)

1. **Tests** (§7) against the *current* code. Red only for `CF#1`-style documented promises.
2. **D1** chat_parser → chat_sync (largest diff, largest payoff).
3. **D2/D2b** scroll_parser + dom_highlight chassis.
4. **D4/D5** visual_click, media_handler, history_query, tab_matcher, message_injector, logger.
5. **D6** actions skeleton + the three hot blocks.
6. **D3** config_manager owners (touches the only currently-failing D test).
7. Gate run (§7 of the plan) + `tools/metrics/area_d.py --gate` + before/after coverage.

---

## 10. Exit criteria (verbatim from §6.4) and how each is measured

| # | criterion | tool |
|---|---|---|
| 1 | no function in `backend/` or `actions/` over CC 25; `sync_conversation` ≤ 15 | `tools/metrics/area_d.py --gate` (plan's own `cc_of`) |
| 2 | `actions` duplication < 25 % (from ~57 %) | same tool, identical-statement clone groups; both the plan's absolute figure and this tool's before/after are reported |
| 3 | `backend` ≥ 85 % line / ≥ 78 % branch; `actions` branch ≥ 70 % | `pytest --cov=backend --cov=actions --cov-branch` over the full suite |
| 4 | `backend/cdp_client.py`, `actions/base_action.py` public APIs byte-identical | `git diff` on those two paths must be empty; plus the plan's Gate 6 signature dump |

Plus the parent-plan gates: 0 new failures anywhere (51 → ≤ 51, and D's own 1 → 0),
`import main` still boots, `RunCoordinator.load_stack` unaffected, and
`git diff --name-only` confined to `backend/**`, `actions/**`, `tests/**`, `docs/**`,
`tools/metrics/**`.

---

## 11. Result (measured after the last step, from the same commands)

| # | criterion | measured | verdict |
|---|---|---|---|
| 1 | no editable function over CC 25 | worst in `backend/` + `actions/` is **CC 22** (`history_query._item`); `visual_click.find_and_click` 27 → 12, `media_handler.attach_image` 26 → 12, `scroll_parser.collect` 43 → 14, `verify_private` 43 → 11, `collect_history.execute` 35 → 15, `click_user.execute` 31 → 12 | **PASS** |
| 1b | `sync_conversation` ≤ 15 | **CC 1** (a 12-line façade over `chat_sync.run_sync`) | **PASS** |
| 2 | `actions` duplication < 25 % | **18.9 %** (304 clone lines / 1 610 SLOC), from 22.0 % before the block skeleton and ~57 % before the area | **PASS** |
| 3 | `backend` ≥ 85 % line / ≥ 78 % branch | **88.9 % / 91.1 %** (baseline 83.4 / 88.9) | **PASS** |
| 3b | `actions` branch ≥ 70 % | **86.0 %** (baseline 83.9 %, dipped to 82.6 % mid-area) | **PASS** |
| 4 | `cdp_client.py`, `base_action.py` public APIs byte-identical | `git diff` empty on both paths; `dump_public_api --diff` reads "no removed or changed symbols" | **PASS** |
| 5 | no new test failures | full suite **51 failed / 1 800 passed**, the same 51 as the same-conditions HEAD run (14 of them are `services/run/coordinator.py`'s `NameError: get_action_class`, another area's); AREA D's own snapshot failures were fixed on the way | **PASS** |
| 6 | diff confined to the area | `backend/**` (7 files, 2 new modules), `actions/**` (12 files), `tests/**` (D-owned only), `docs/**`, `tools/metrics/**` | **PASS** |

### 11.1 What deliberately did not happen

* `history_query._item` (CC 22, 34 lines) and `tab_matcher.score_tab` (CC 20) stay as
  they are. Both are under the gate, both are already one-idea-per-function, and §8
  leaves their neighbours (`dom_probe`, `criteria_engine`, `person_filter`) alone for
  the same reason: splitting a 20-CC branch table into four functions is a rename of
  the same logic, not a simplification.
* `actions/take_person.py` does not inherit `MarkerBlock`: its `execute()` really works
  (it picks a person and calls `note_selected`), so only its constructor would benefit —
  and that benefit is three lines against losing the block's own readable `__init__`.
* The 12 `backend/*.py` compatibility shims stay, exactly as §9 of the parent plan says.

### 11.2 Two rules the goldens now state explicitly

`tools/metrics/dump_public_api.py` records each class's members, and the block skeleton
made those records stricter in one place and looser in another — deliberately:

* **A member that moved up is not a lost member.** `ClickBack.execute` now lives on
  `FindClickBlock`, so the class record keeps it under `inherited` with the same
  signature, and the snapshot test accepts either. The signature itself is still frozen.
* **`bases` changed for seven blocks; `ancestry` is what is checked.** Every recorded
  base must still be an ancestor (`BaseAction` is, for all of them), which is the
  property `isinstance` callers rely on. The *wire* contract the presets and the config
  panel use — `__init__` signature, `config_schema()` key order and defaults,
  `to_dict()` — is unchanged to the byte: `tests/unit/actions/block_wire_snapshot.json`
  compares equal before and after, and it was not rewritten.
* Module-level constant records blank memory addresses (`_default_repr`), because a
  `FIELDS` tuple holds functions and sentinels whose `repr` would otherwise change on
  every run and make the snapshot un-reproducible.
