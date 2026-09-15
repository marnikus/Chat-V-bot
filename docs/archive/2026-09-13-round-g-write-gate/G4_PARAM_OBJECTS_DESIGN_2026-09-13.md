# Round G · Step 4 — design: parameter objects for the remaining wide functions

Date: 2026-09-13 · Branch: `arena/01a09b73-chat-v-bot` · Status: **APPROVED DESIGN — IMPLEMENTING**

Predecessor: `docs/archive/2026-09-13-round-f/F5_PARAMETER_OBJECTS.md` (F5: 70 → 51, 19 migrations, pattern fixed).
Plan: `ROUND_G_DESIGN_2026-09-13.md` §4 — G4 "wide params: 44 → floor".

## 0. Measured starting point (fresh walk, ROUND_F_DESIGN §10.4 walker)

`wide(>4 params) = 51`, worst = 20 (`ScrollParse.__init__`). Identical to the F5 handoff —
G2/G3 changed bodies and file structure but no signature widths.

| root | wide |
|---|---|
| actions | 15 |
| backend | 13 |
| services | 13 |
| stores | 7 |
| bridge | 2 |
| app | 1 |

Per the plan line, G4 adjudicates the **44 outside `stores/`**. The 7 `stores/` offenders
(`history_repo_append.append` 13, `history_repo.append` 13, `history_repo.rename_if_same_conversation` 8,
`history_repo.recover_media` 6, `media_store.__init__` 6, `history_models.fingerprint` 6,
`history_models.dedupe_key` 5) are **deferred to G7 backlog** — they are golden-pinned store
API and the stores module has its own import-budget baseline (42); touching them deserves its
own design pass. This is a scope ruling, not a freeze: owner lifted AREA-B/D freezes (F0).

## 1. Rulings — 44 functions, three dispositions

### 1a. DOCUMENTED CONSTRAINTS (11) — `quality-override:` comment on the def line (§16.4)

| # | function | p | constraint |
|---|---|---|---|
| 1 | `actions/scroll_parse.py::ScrollParse.__init__` | 20 | RULE 3 block wire |
| 2 | `actions/click_user.py::ClickUser.__init__` | 13 | RULE 3 block wire |
| 3 | `actions/custom_find.py::CustomFind.__init__` | 11 | RULE 3 block wire |
| 4 | `actions/collect_history.py::CollectHistory.__init__` | 9 | RULE 3 block wire |
| 5 | `actions/attach_image.py::AttachImage.__init__` | 9 | RULE 3 block wire |
| 6 | `actions/click_send.py::ClickSend.__init__` | 7 | RULE 3 block wire |
| 7 | `actions/click_main_tab.py::ClickMainTab.__init__` | 7 | RULE 3 block wire |
| 8 | `actions/click_back.py::ClickBack.__init__` | 7 | RULE 3 block wire |
| 9 | `actions/type_message.py::TypeMessage.__init__` | 5 | RULE 3 block wire |
| 10 | `backend/chat_sync.py::run_sync` | 5 | compat seam |
| 11 | `bridge/router.py::BridgeRouter.__init__` | 8 | Qt compat facade |

**Why the 9 block `__init__`s are wire, per F5's own guidance** ("wide block `__init__` may be a
documented constraint — decide per block"): blocks are never constructed by hand in production.
`services/run/coordinator.py::load_stack` builds every block generically:
`cls(**{k: v for k, v in block.items() if k != "block_id"})` — the flat-kwarg constructor **is**
the preset/block wire contract (RULE 3), pinned byte-for-byte by
`tests/unit/actions/block_wire_snapshot.json` (init signature per block). A parameter-object
ctor would require an adapter layer in `load_stack` and change every saved preset's shape for
zero reader gain. F5 left them unmigrated for exactly this reason; G4 makes the ruling explicit
in-file. `ScrollParse.__init__` (20p) is included: G3 already migrated its *body* mechanics;
its signature is wire. Blocks golden must therefore stay **byte-identical** in G4.

`run_sync` (5p): already has typed `options: SyncOptions`; the 5th slot is `**legacy`, the
absorbing compat seam for pre-G2 callers of `sync_conversation`. `BridgeRouter.__init__` (8p):
`**_legacy` absorbs the old monolithic bridge ctor; real state lives in `BridgeContext`
(which G4 converts to a dataclass, below). Both signatures carry overrides.

Override text (exact §16.4 format), e.g. block 1:
`# quality-override: params=20 reason=RULE 3 block wire — load_stack constructs cls(**preset_dict); flat kwargs are the saved-preset contract`

### 1b. MIGRATIONS (33) — eight waves, F5 pattern (in-place signature change, all call sites same commit, no `_v2` twins)

Fields keep old-parameter order and exact defaults. Dataclass `__init__` is synthesized
(invisible to the walker — same accounting F5 used for `PersonPageRequest`, 6 fields).
Where a class **is** already a pure value bundle, the class itself becomes the dataclass
(`eq=False` to keep identity semantics and hashability — behavior-neutral).

#### Wave 1 — `backend/parser_requests.py` (NEW module, ~35 lines) + chat_parser (441→~420)

| function | p | new signature | object (fields = old params in order) |
|---|---|---|---|
| `chat_parser.sync_conversation` | 14 | `(parser, repo, nick, options=None)` | **existing `SyncOptions`** — no new type; the façade body already gathered its 11 kwargs into `SyncOptions.from_kwargs(...)` before forwarding to `run_sync`, so the object exists and the migration only lifts the gathering to the callers |
| `chat_parser.ChatParser.verify_private` | 5 | `(self, state, nick, my_nick="", query=None)` | `PrivateQuery(items=None, require_private=True)` — `my_nick` stays positional: like `nick` it is an *identity* input, not a gate knob; all 3-positional-arg call sites (16 in `test_private_gate.py`) keep working |
| `chat_parser.ChatParser.settle_after_top` | 5 | `(self, first_state, spec=None)` | `SettleSpec(wait_ms=300, stable_polls=3, max_wait_s=6.0, minimum_count=0)` |

Callers: `actions/collect_history.py:220` (flat kwargs → `SyncOptions(...)`),
`services/collector_service.py:146/148` (kwargs dict → `SyncOptions.from_kwargs(**kwargs)`),
`backend/chat_sync_session.py:56/222` (`SettleSpec(...)`, `PrivateQuery(require_private=…)`),
`services/collector_push.py:69` (`PrivateQuery(items=…)`) + ~5 test files.
`query=None`/`spec=None`/`options=None` mean "all defaults" — bodies start
`x = x or Default()` and reference `x.field`.
G2 docstrings claiming `sync_conversation()` "still takes its keyword arguments"
(`chat_sync.py:25`, `chat_sync_options.py:4/21`) are corrected in the same commit.

#### Wave 2 — `backend/probe_requests.py` (NEW module, ~90 lines) + dom_probe/dom_highlight/visual_click/media_handler

| function | p | new signature | object |
|---|---|---|---|
| `dom_probe.build_probe` | 8 | `(selector, spec=None)` | `ProbeSpec(label_selector=None, match_text=None, match_mode=MATCH_CONTAINS, click=False, click_selector=None, click_root=False, max_candidates=6)` |
| `dom_highlight.build_find_probe` | 9 | `(selector, spec=None)` | `FindProbeSpec(label_selector="", match_text="", match_mode=MATCH_CONTAINS, highlight=True, highlight_ms=1200, color=COLOR_FIND, caption="FOUND", max_candidates=6)` |
| `dom_highlight.build_click_probe` | 6 | `(click_selector=None, spec=None)` | `ClickProbeSpec(highlight=True, highlight_ms=1200, color=COLOR_CLICK, caption="CLICK", click=True)` |
| `dom_highlight.build_highlight_probe` | 8 | `(selector, spec=None)` | `HighlightSpec(label_selector="", match_text="", match_mode=MATCH_EXACT, color=COLOR_COLLECT, caption="MATCH", highlight_ms=900, clear_first=True)` |
| `visual_click.find_and_click` | 12 | `(cdp, request=None, engine=None, **legacy)` | **existing `ClickRequest`** (G2) — the 12-param body already built one; the façade now takes it typed, and `**legacy` keeps every keyword call site (`actions/base.py`'s dict forwarding, `find_and_click_exact`, all tests) working unchanged. 4 params, under the cap → migration, not constraint |
| `media_handler.attach_image` | 10 | `(cdp, folder_path="", options=None, **legacy)` | **existing `AttachOptions`** (G2) — same shape; `folder_path` stays positional because every test calls it that way; the block (`actions/attach_image.py`) migrates to typed `options=` |

Spec dataclasses live in the NEW leaf module `backend/probe_requests.py`, which also **owns the
moved constants** `MATCH_CONTAINS`/`MATCH_EXACT` (from `dom_probe`) and `COLOR_FIND`/`COLOR_CLICK`/
`COLOR_COLLECT` (from `dom_highlight`); both old modules re-export them, so every existing import
site is unchanged and the AREA-D dumper (which skips plain str constants) sees no move.
`dom_highlight.py` is a 532-line §16.5 offender: the three builder defs **shrank** 532→514.
Callers migrated: `message_injector_send`, `scroll_parser_dom`, `visual_click`'s `ClickRequest`
probe methods, `actions/attach_image`, + 59 builder call sites in 5 test files (AST-rewritten;
note: AST col offsets are UTF-8 byte offsets and `str.splitlines()` splits on `\u2028` —
the rewrite script must handle both). `wait_page`, `message_injector_field`, `media_handler`'s
own `build_probe(selector=…)` calls are keyword-compatible unchanged.

#### Wave 3 — backend singletons: `scroll_parser.__init__` 19p, `person_filter` 5p, `message_injector_type._run_type_strategies` 6p

* `ScrollParser.__init__(cdp, options=None, criteria=None)` — **options-first single surface**.
  G2 introduced `ScrollOptions` + `from_options`; the 19-knob ctor duplicates it. Post-G4:
  ctor = `(cdp, options or ScrollOptions(), criteria)`; `from_options` stays as a thin alias
  (golden method). The 18 bare annotations + `_KNOB_CASTS` loop from G3 are reused unchanged.
  G2's parity test (ctor knobs ↔ options fields) becomes **obsolete by design** — one surface
  cannot drift from itself; replaced by a pin that every `ScrollOptions` field is exposed as a
  parser property. ~5 test files migrate constructions to `ScrollParser(cdp, ScrollOptions(...))`.
* `PersonFilter` → `@dataclass(eq=False, repr=False)` in place + `__post_init__` doing the four
  `normalize()` calls (body preserved exactly). All kwargs/positional callers unchanged.
  `repr=False` too, so the only golden-visible deltas are the synthesized `__init__` (same
  rendered defaults) and the additive `fields`/`__post_init__` entries.
* `_run_type_strategies(ctx: _TypeCtx)` — G3's injector split already created `_TypeCtx`; the
  ladder's `kind` moved onto it as a field, `noun`/`warn_direct`/`warn_paste` are derived in
  `__post_init__` via `_ladder_words(kind)` and `noun_cap` is a property. Both callers
  (`type_message`, `type_search` in the seam) build the ctx inline; no test referenced the
  private ladder, so zero test churn.
* Parity tests rewritten as planned: SP#1 pins the ctor's exact parameter list
  `(self, cdp, options, criteria)` + bare-parser defaults field-for-field; SP#2 (renamed
  `…equals_the_ctor_call`) still compares the two construction paths behaviourally;
  SP#3 became "a knob inside the options reaches the parser".

#### Wave 4 — `services/db_deletion_policy.py`: `DeletionSpec` + `CandidateContext` (module-owned, 203→220)

| function | p | new signature | object |
|---|---|---|---|
| `plan_deletion` | 9 | `(spec)` | `DeletionSpec(victim_abs, victim_folder_abs, media_base_abs, footprint_files, discovered_files, keep, folder_exclusive, other_world_folders, inventory)` — frozen, fields = old kw-only params verbatim |
| `classify_candidate` | 7 | `(*, candidate_abs, ctx, is_discovered)` | `CandidateContext(base_abs, victim_folder_abs, folder_exclusive, keep, other_world_folders)` — the module's private `_PathPolicy` **promoted and renamed** to the old parameter names; its `verdict()` helper survives. `victim_folder_abs` is carried by the contract although the ladder never reads it — noted in the docstring, removal is separate work |

`plan_deletion` builds one `CandidateContext` and reuses it per candidate. Callers:
`services/db_deletion_scan.py` (builds `DeletionSpec` through the shim) + the shim
`services/db_deletion.py` (re-exports both new names, `__all__` extended) + 20 test call
sites in `tests/integration/safety_deletion/` (AST-rewritten).

#### Wave 5 — `services/wiring_requests.py` (NEW module, ~60 lines): undo/people/world wiring bundles

| function | p | new signature | object |
|---|---|---|---|
| `undo_service.UndoService.__init__` | 8 | `(self, config, deps=None)` | `UndoDeps(archive=None, people=None, labels=None, dbs=None, memory=None, engine=None, bus=None)` |
| `undo_service.UndoService.attach` | 7 | `(self, deps)` | same `UndoDeps`; None fields keep the current wiring (old semantics preserved) |
| `undo_world.restart_world` | 6 | `(deps, op)` | `RestartDeps(memory, archive, labels, undo, bus)` — `undo` folded in, so the pair is (deps, op) |
| `people_service.PeopleService.__init__` | 5 | `(self, deps)` | `PeopleDeps(memory=None, engine=None, labels=None, undo=None, bus=None)` |
| `people_service.PeopleService.attach` | 5 | `(self, deps)` | same `PeopleDeps` |

Callers: `bridge/context.py` (both lazy builders, `_crosswire`, `sync_services`),
`bridge/db_bridge.py` ×2, `services/undo_db.py` ×2 + 23 AST-rewritten test call sites in
4 integration files + 2 `restart_world` sites in `test_world_events.py`. Two pinned fakes
migrated in-step (`test_collector_tick_phases.fake_sync` → `(parser, repo, nick, options=None)`;
`test_services_undo_gaps.fake_restart` → `(_deps, op)`). `UndoService` is a §16.5 landmine
with a **class-span ratchet ≤179** (`test_undo_structure`): the first draft grew the span by 2
and the ratchet caught it — init/attach comments were trimmed until the file returned to its
241-line size, ratchet green.

#### Wave 6 — run/history/collector families: `services/run/requests.py` (NEW), `services/history/requests.py` (NEW), `services/collector_states.py` (extend)

| function | p | new signature | object |
|---|---|---|---|
| `run/coordinator.RunCoordinator.__init__` | 8 | `(self, deps, parent=None)` | `RunDeps(cdp, memory, criteria, bus=None, hooks=None, retry_policy=None, progress=None)` |
| `run/error_recovery._handle_step_result` | 5 | `(self, block, result, step)` | `StepContext(nick, idx, started)` |
| `history/__init__.HistoryService.__init__` | 6 | `(self, deps)` | `HistoryDeps(cdp, config=None, db_path=None, session_id="", memory=None, labels=None)` |
| `collector_service.Collector.__init__` | 8 | `(self, deps, parent=None)` | `CollectorDeps(cdp, repo, parser, media=None, settings=None, lease=None, memory=None)` |
| `collector_tick.maybe_rename` | 6 | `(self, nick, probe, sigs)` | `TailSigs(head_sig="", tail_sig="", head_any="", tail_any="")` |
| `collector_tick.cursor_check` | 6 | `(self, person_id, probe, ident, sigs)` | `TickIdent(nick, my_nick="")` + `TailSigs` |

`collector_tick` methods stay ON their class (the `collector_structure` tripwire pins method
placement, not signatures). `Collector` + `RunCoordinator` are §16.5 landmines — init bodies
shrink (deps unpack ≤ 2 lines). Prod callers: `app/bootstrap.py` (engine + history),
`services/history/__init__.py:39` (collector). Test callers: HistoryService ~34 sites,
RunCoordinator/ActionEngine ~40 sites, Collector 6 sites — one AST script rewrote all 45 files
(imports auto-inserted after each file's anchor import; `RunDeps`/`StepContext` also joined the
`services.run` lazy façade `__all__`, `CollectorDeps` the `backend.collector` shim).
Two implementation bugs the suite caught and the step fixed: a double-run of the rewrite script
double-wrapped one construction, and `cursor_check`'s status text kept a bare `nick` reference
after the parameters moved into `TickIdent` (`NameError` at runtime → `ident.nick`).
`CollectorDeps`/`TailSigs`/`TickIdent` live in `services/collector_states.py` (95→137, in band);
the coordinator's now-unused `EventBus` import was dropped (its only use was the old annotation;
`datetime`/`RunTracer` W0611s are pre-existing at HEAD and stay).

#### Wave 7 — `bridge/context.py` + `app/lifecycle.py`

* `BridgeContext` → `@dataclass(eq=False)` in place: 10 fields (cdp…bus, all `None`/exact
  defaults), `__post_init__` = `self.bus = self.bus or EventBus()` + the private lazy attrs.
  All 9 construction sites use kwargs or no args → **zero call-site changes**.
* `ApplicationLifecycle.__init__(self, deps)` with `AppDeps(app, cdp, memory, engine, history, bridge)`
  in `app/lifecycle.py` itself (75-line file). Callers: `main.py:39` + 2 tests.

#### Wave 8 — actions internals (golden-invisible privates + 3 public ScrollParse methods)

| function | p | new signature | object (in `actions/scroll_parse.py` / `actions/click_user.py`) |
|---|---|---|---|
| `scroll_parse.to_scroll_options` | 6 | `(self, panel_criteria=None, cbs=None)` | `ScrollCallbacks(log_cb=None, on_collect=None, on_reject=None, should_stop=None)` |
| `scroll_parse.build_parser` | 6 | `(self, cdp, panel_criteria=None, cbs=None)` | same |
| `scroll_parse.run_pipeline` | 8 | `(self, cdp, run)` | `PipelineRun(engine, panel_criteria=None, known_messaged=(), seek_nicks=(), cbs=None)` |
| `scroll_parse._collect` | 8 | `(self, cdp, run)` | same `PipelineRun` |
| `click_user._verify_new_tab` | 5 | `(self, cdp, engine, chk)` | `NewTabCheck(nick, label, before=None, before_count=0)` |
| `click_user._no_new_tab` | 6 | `(self, engine, chk, after_count, titles)` | same `NewTabCheck` |

`to_scroll_options`/`build_parser`/`run_pipeline` are public → `public_api` golden payload
changes (approved, §2). `_collect/_verify_new_tab/_no_new_tab` are private → invisible.
Callers: `services/run/collect_phase.py` (run_pipeline), block `execute` (self), tests.

**EXECUTED (as built).** Walker **24 → 18, worst 20** — G4's exit target reached.

* `ScrollCallbacks(log_cb, on_collect, on_reject, should_stop)` and
  `PipelineRun(engine, panel_criteria, known_messaged, seek_nicks, cbs)` live at module level
  in `actions/scroll_parse.py` (`@dataclass(frozen=True, slots=True)`); `NewTabCheck(nick,
  label, before)` in `actions/click_user.py`. File spans: scroll_parse 397→423, click_user
  264→280; the `ScrollParse` class span **shrank 306→302** (§16.5).
* **Deviations from the table, both fidelity-forced:**
  1. `PipelineRun` fields default to `None`, not `()` — `_decide_mode` branches on
     `seek_nicks is None` (engine-memory read); an empty-set default would silently change
     behavior. Every field is defaulted (`engine=None` too), so `PipelineRun(eng)` still binds
     positionally; `run_pipeline(cdp, run=None)` with `run = run or PipelineRun()`.
  2. `NewTabCheck` carries no `before_count` — both counts are derived from `before` inside
     `_tab_evidence`; duplicating it would have created a second source of truth.
* Call sites migrated: `collect_phase._call_pipeline` (local import of `PipelineRun`, same
  pattern as its `RunStopped` import), `ScrollParse.execute`, and in tests
  `test_scroll_only_seek.py` (its `parser()` helper splits `panel_criteria` out of `**kw`
  before building `ScrollCallbacks`), `test_filter_purge.py`, `test_scroll_parse_pipeline.py`,
  `test_collect_visual_and_live_refresh.py`.
* Two fake blocks with old `run_pipeline(self, cdp, engine, …)` signatures were migrated in
  step: `ScrollStop` in `tests/integration/run_safety/test_stop_contract.py` (it *called*
  `engine.stop()` — PipelineRun has no such method) and `ScrollParseBlock` in
  `tests/integration/services/test_run_state_machine_contract.py`.
* Battery: 4 scroll/filter test files + `tests/unit/actions/` + `tests/integration/` =
  **812 passed + 24 subtests** (after the two fake migrations; the only failure was
  `test_stop_during_collect_yields_stopped_not_empty`).

## 2. Invariants & anti-gaming (§16.2)

1. **blocks golden byte-identical** — no block `__init__`/`config_schema`/`to_dict` is touched
   (ruling 1a). Verified by `dump_blocks` diff = empty.
2. **`public_api` + `backend_api_snapshot` refresh is deliberate and enumerated**: changed
   payloads ⊆ {sync_conversation, verify_private, settle_after_top, build_probe,
   build_find_probe, build_click_probe, build_highlight_probe, find_and_click, attach_image,
   ScrollParser.__init__, PersonFilter (+`fields` additive), to_scroll_options, build_parser,
   run_pipeline}; added classes ⊆ {PrivateQuery, SettleSpec, ProbeSpec, FindProbeSpec,
   ClickProbeSpec, HighlightSpec, ScrollCallbacks, PipelineRun, NewTabCheck}; **zero
   removals**. A conservation script checks exactly this (removed = ∅).
   `test_find_click_blocks.py`'s drift guard ("the façade may not quietly change a default")
   is rewritten in-step: it now pins legacy-path ↔ typed-path equivalence plus the façade's
   4-slot parameter set — same protection, new signature shape.
3. Compat surfaces (`run_sync(**legacy)`, `BridgeRouter(**_legacy)`, `ScrollParse` wire) keep
   absorbing old callers unchanged.
4. No `_v2` twins; no speculative objects — every dataclass has ≥1 real production caller in
   the same commit (F5's dropped-8 lesson).
5. Dataclass conversions use `eq=False`: no `__eq__`/`__hash__` behavior change anywhere.
6. §16.5 landmines (`UndoService`, `RunCoordinator`, `Collector`, `dom_highlight.py`) only
   shrink; `dom_highlight.py` gains zero lines (specs in new module).
7. stores/ untouched; stores import-count baseline 42 unchanged.

## 3. Verification battery (per wave + final)

* walker re-run after each wave (expect monotone 51 → 18: 11 constraints + 7 stores).
* per wave: targeted tests of touched families; pylint (no new W0611/W0612/E, C0411);
  `rule16_gate.py --with-clones` EXIT=0; no-worsen vs HEAD (sloc/sizes/cc/cognitive).
* final: vulture ≥90 clean, golden refresh + conservation script, FULL suite with
  `--deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine`,
  coverage ≥ `/tmp/coverage_g3_final.json` (90.9855 / 87.0488), docs (ROUND_G plan §4,
  archive README, F5 doc pointer), commit + push.

## 4. Risks

* **Test churn** (HistoryService 34 sites): mechanical `HistoryService(X, …)` →
  `HistoryService(HistoryDeps(X, …))` rewrite, suite proves it.
* **ScrollParser options-first** touches G2-era tests written against the 19-knob ctor —
  justified: single configuration surface eliminates the drift class the parity test existed
  to police.
* **Golden payload diffs**: enumerated in §2.2; anything outside the list fails the step.
* `sync_conversation`'s `now` field: `datetime` import stays in parser_requests (typing only).

## OUTCOMES (filled during/after implementation)

* OUTCOME_WALKER: **wide 51 → 18, worst 20** (official §10.4 walker) — the exit target
  exactly: 11 documented constraints + the 7 deferred stores offenders. Per-wave: W1–W5
  51→32 (see wave records), W6 →26, W7 →24, W8 →18.
* OUTCOME_GOLDEN: `block_wire_snapshot.json` **byte-identical** (ruling 1a held through all
  eight waves — the override comments on the 9 block `__init__`s are AST-invisible).
  `backend_api_snapshot.json` refreshed deliberately: **removed = ∅**; changed = exactly the
  14 approved payloads (sync_conversation, verify_private, settle_after_top, build_probe,
  build_find_probe, build_click_probe, build_highlight_probe, find_and_click, attach_image,
  ScrollParser.__init__, PersonFilter.__init__, to_scroll_options, build_parser,
  run_pipeline); added = the 9 approved classes (PrivateQuery, SettleSpec, ProbeSpec,
  FindProbeSpec, ClickProbeSpec, HighlightSpec, ScrollCallbacks, PipelineRun, NewTabCheck)
  plus PersonFilter's sanctioned additive `fields`/`attrs`/`__post_init__`. Both snapshot
  drift tests green after the refresh.
* OUTCOME_GATES: `rule16_gate.py --with-clones` **EXIT=0**; stores_modules **EXIT=0**
  (import-count baseline 42→**41**, decremented with a dated ledger note in
  `test_stores_public_api.py`: W6's `CollectorDeps` bundle is uniformly `Any`-typed, so the
  annotation-only `HistoryRepo` import in collector_service.py went away with the old
  ctor signature — stores surface untouched); vulture --min-confidence 90: **7 findings,
  the unchanged known inventory** (registry.py `Iterator` + six protocol args), none new;
  node tests/test_*.js all pass; pylint on every touched file: no new findings (chat_parser's
  three W0611s are pre-existing at HEAD). No-worsen audit vs 296c3f1 (current_audit.py, both
  trees): **zero over-limit functions, zero grown >500-line offenders, removed=∅ at
  file/class level**; 30 sanctioned in-limit function growths remain, all pattern-inherent —
  12 façades at cc/cognitive +1 each from their `x = x or Spec()` default guard (worst:
  settle_after_top cc 8, build_probe cc 8 — cap 10), plus +1–3-line call wraps
  (click_probe 3→4, _sync 16→17, _handle_step_result 17→18 via its `nick, idx = step.…`
  alias, _call_pipeline 19→21 via the local import + hoisted `run=`, run/__init__
  `__getattr__` 9→12 via the sanctioned RunDeps/StepContext re-export branch). Class spans:
  _TypeCtx 16→27 (W2's post_init/noun_cap), PersonFilter 57→67, BridgeContext 103→109,
  CollectPhaseMixin 88→90, RunExecutionMixin 162→163 — every one inside its ratchet/limit;
  ScrollParse **shrank 306→302**, dom_highlight.py **532→514**, chat_parser.py **441→428**.
  Repack pass after the first audit (49 regressions → 30): to_scroll_options def re-joined
  (loc 30 = base), verify_private dropped its guard for a frozen `PrivateQuery()` default
  (**29 loc/cc 6/cognitive 5 = base exactly**; no caller passes None — all 5 call sites
  checked), type_message/type_search call `_TypeCtx` positionally (fields are in the old
  positional order, so both fit one line = base), restart_world shed its alias line and
  docstring addition (**31 < base 32**), undo_db gained module-level `_deps_of(o)` and both
  call sites fit one line (work **18 < base 21**), _build_undo 6→4 lines, db_bridge 4→3 ×2,
  collect_history's SyncOptions call repacked to base width, attach_image/scroll_parse/
  click_user `execute` calls re-joined to one line each, _verify_new_tab's two wraps
  re-joined, history/__init__ comment line dropped, _classify_file_group def re-joined.
  Two bugs caught in verification, both the W6 lesson (re-grep bare moved names):
  restart_world had two surviving bare `archive.db.path` refs after the alias removal
  (NameError at runtime only — fixed to `deps.archive.db.path`).
* OUTCOME_SUITE: **2808 passed, 2 skipped, 1 deselected (sandbox WebEngine), 1 xfailed,
  898 subtests** — same passed count as the G3 baseline. W8 battery en route: 812 + 24
  subtests (actions + integration + the four scroll/filter files) after migrating two
  old-signature fake blocks (test_stop_contract.py `ScrollStop` — it *called*
  `engine.stop()`, test_run_state_machine_contract.py `ScrollParseBlock`).
* OUTCOME_COV: **line 91.0949 % (floor 90.9855), branch 87.0557 % (floor 87.0488)** —
  both above; scope identical (main.py included via `--cov=main`, not `--cov=main.py` which
  coverage cannot resolve); no file dropped, +5 new files (the four `*requests.py` modules +
  probe_requests), 15745→15949 statements. Floor file for G5: `/tmp/coverage_g4_final.json`.
