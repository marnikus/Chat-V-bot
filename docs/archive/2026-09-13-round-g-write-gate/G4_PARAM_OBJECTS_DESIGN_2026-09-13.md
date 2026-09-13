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

#### Wave 1 — `backend/parser_requests.py` (NEW module, ~70 lines) + chat_parser (441→~445)

| function | p | new signature | object (fields = old params in order) |
|---|---|---|---|
| `chat_parser.sync_conversation` | 14 | `(parser, repo, nick, spec=None)` | `SyncRunSpec(my_nick="", require_private=False, verify_partner=False, max_messages=None, chunk_pause_ms=None, should_stop=None, on_progress=None, now=None, backfill_older=False, backfill_wait_s=2.0, media=None)` |
| `chat_parser.ChatParser.verify_private` | 5 | `(self, state, nick, query=None)` | `PrivateQuery(my_nick="", items=None, require_private=True)` |
| `chat_parser.ChatParser.settle_after_top` | 5 | `(self, first_state, spec=None)` | `SettleSpec(wait_ms=300, stable_polls=3, max_wait_s=6.0, minimum_count=0)` |

Callers: `actions/collect_history.py`, `backend/chat_sync_options.py`, `services/collector_service.py`,
`backend/chat_sync_session.py`, `backend/chat_sync.py` (seam builds spec from `options`+`**legacy`),
`backend/chat_parser.py` internals + ~7 test files. `spec=None` means "all defaults" — bodies start
`spec = spec or SyncRunSpec()` and reference `spec.field` (or a 2-line local unpack; prefer
`spec.x` reads).

#### Wave 2 — `backend/probe_requests.py` (NEW module, ~90 lines) + dom_probe/dom_highlight/visual_click/media_handler

| function | p | new signature | object |
|---|---|---|---|
| `dom_probe.build_probe` | 8 | `(selector, spec=None)` | `ProbeSpec(label_selector=None, match_text=None, match_mode=MATCH_CONTAINS, click=False, click_selector=None, click_root=False, max_candidates=6)` |
| `dom_highlight.build_find_probe` | 9 | `(selector, spec=None)` | `FindProbeSpec(label_selector="", match_text="", match_mode=MATCH_CONTAINS, highlight=True, highlight_ms=1200, color=COLOR_FIND, caption="FOUND", max_candidates=6)` |
| `dom_highlight.build_click_probe` | 6 | `(click_selector=None, spec=None)` | `ClickProbeSpec(highlight=True, highlight_ms=1200, color=COLOR_CLICK, caption="CLICK", click=True)` |
| `dom_highlight.build_highlight_probe` | 8 | `(selector, spec=None)` | `HighlightSpec(label_selector="", match_text="", match_mode=MATCH_EXACT, color=COLOR_COLLECT, caption="MATCH", highlight_ms=900, clear_first=True)` |
| `visual_click.find_and_click` | 12 | `(cdp, run)` | `ClickRun(selector, label_selector="", match_text="", match_mode=MATCH_CONTAINS, click_enabled=True, click_selector="", highlight_enabled=True, confirm_pause_ms=700, highlight_ms=1200, label="element", engine=None)` |
| `media_handler.attach_image` | 10 | `(cdp, run)` | `AttachRun(folder_path, file_pattern="", mode="auto", simulate_dialog=False, verify_timeout_ms=8000, highlight_enabled=True, confirm_pause_ms=700, report=None, verify_poll_ms=250)` |

(Find/Click/Highlight field lists finalized against the real defs at implementation; defaults copied verbatim.)
`dom_highlight.py` is a 532-line §16.5 offender: specs live in the NEW module and the three
builder defs must **shrink** (9p/8p/6p def lines → 2p), never grow. Callers: `actions/wait_page.py`,
`backend/message_injector_field.py`, `backend/message_injector_send.py`, `backend/scroll_parser_dom.py`,
`backend/visual_click.py` internals, `actions/attach_image.py`, `actions/base.py` + tests.

#### Wave 3 — backend singletons: `scroll_parser.__init__` 19p, `person_filter` 5p, `message_injector_type._run_type_strategies` 6p

* `ScrollParser.__init__(cdp, options=None, criteria=None)` — **options-first single surface**.
  G2 introduced `ScrollOptions` + `from_options`; the 19-knob ctor duplicates it. Post-G4:
  ctor = `(cdp, options or ScrollOptions(), criteria)`; `from_options` stays as a thin alias
  (golden method). The 18 bare annotations + `_KNOB_CASTS` loop from G3 are reused unchanged.
  G2's parity test (ctor knobs ↔ options fields) becomes **obsolete by design** — one surface
  cannot drift from itself; replaced by a pin that every `ScrollOptions` field is exposed as a
  parser property. ~5 test files migrate constructions to `ScrollParser(cdp, ScrollOptions(...))`.
* `PersonFilter` → `@dataclass(eq=False)` in place + `__post_init__` doing the four
  `normalize()` calls (body preserved exactly). All kwargs/positional callers unchanged.
* `_run_type_strategies(self, ctx: _TypeCtx)` — G3's injector split already created `_TypeCtx`;
  the 6 flat params are all derivable/packable into it (`noun_cap` from `ctx.noun`).

#### Wave 4 — `services/db_deletion_policy.py`: `DeletionSpec` + `CandidateContext` (module-owned, 203→~245)

| function | p | new signature | object |
|---|---|---|---|
| `plan_deletion` | 9 | `(spec)` | `DeletionSpec(victim_abs, victim_folder_abs, media_base_abs, footprint_files, discovered_files, keep, folder_exclusive, other_world_folders, inventory)` |
| `classify_candidate` | 7 | `(*, candidate_abs, ctx)` | `CandidateContext(base_abs, victim_folder_abs, folder_exclusive, keep, other_world_folders, is_discovered)` |

`plan_deletion` builds one `CandidateContext` and reuses it per candidate. Callers:
`services/db_deletion_scan.py` + 2 test files.

#### Wave 5 — `services/wiring_requests.py` (NEW module, ~60 lines): undo/people/world wiring bundles

| function | p | new signature | object |
|---|---|---|---|
| `undo_service.UndoService.__init__` | 8 | `(self, config, deps=None)` | `UndoDeps(archive=None, people=None, labels=None, dbs=None, memory=None, engine=None, bus=None)` |
| `undo_service.UndoService.attach` | 7 | `(self, deps)` | same `UndoDeps` |
| `undo_world.restart_world` | 6 | `(deps, undo, op)` | `RestartDeps(memory=None, archive=None, labels=None, bus=None)` |
| `people_service.PeopleService.__init__` | 5 | `(self, deps)` | `PeopleDeps(memory, engine=None, labels=None, undo=None, bus=None)` |
| `people_service.PeopleService.attach` | 5 | `(self, deps)` | same `PeopleDeps` |

Callers: `bridge/context.py` (both lazy builders + `.attach` at :115), `bridge/db_bridge.py`,
`services/undo_db.py` + ~6 test files. `UndoService` is a §16.5 landmine: method count and LOC
must not grow — init/attach bodies only shrink.

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
`services/history/__init__.py:39` (collector), `main.py:39` — see Wave 7. Test callers:
HistoryService ~34 sites / 19 files (mechanical rewrite), RunCoordinator 3 files, Collector 6 files.

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

## 2. Invariants & anti-gaming (§16.2)

1. **blocks golden byte-identical** — no block `__init__`/`config_schema`/`to_dict` is touched
   (ruling 1a). Verified by `dump_blocks` diff = empty.
2. **`public_api` + `backend_api_snapshot` refresh is deliberate and enumerated**: changed
   payloads ⊆ {sync_conversation, verify_private, settle_after_top, build_probe,
   build_find_probe, build_click_probe, build_highlight_probe, find_and_click, attach_image,
   ScrollParser.__init__, PersonFilter (+`fields` additive), to_scroll_options, build_parser,
   run_pipeline}; added classes ⊆ {SyncRunSpec, PrivateQuery, SettleSpec, ProbeSpec, FindProbeSpec,
   ClickProbeSpec, HighlightSpec, ClickRun, AttachRun, ScrollCallbacks, PipelineRun}; **zero
   removals**. A conservation script checks exactly this (removed = ∅).
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

* OUTCOME_WALKER: —
* OUTCOME_GOLDEN: —
* OUTCOME_GATES: —
* OUTCOME_SUITE: —
* OUTCOME_COV: —
