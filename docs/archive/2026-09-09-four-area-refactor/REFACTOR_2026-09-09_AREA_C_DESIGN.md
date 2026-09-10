# AREA C — Services Refactor Design (Structure)

**Date:** 2026-09-09 · **Branch:** `arena/01a08849-chat-v-bot`
**Scope:** AREA C only, per `docs/archive/2026-09-09-four-area-refactor/REFACTOR_2026-09-09_FOUR_AREA_PLAN.md` §6.3.
**Status:** design — the implementation plan for the services refactor.
**Pre-refactor measurements in this doc were taken on this checkout** (210ad03),
with the two A-owned Qt-poisoning test files and the A-owned stale migration
test excluded, exactly as the plan prescribes.

---

## 0. TL;DR

| | pre-refactor (measured) | target (§6.3) |
|---|---|---|
| `Collector._tick` CC / LOC | **82 / 212** | ≤ 15 / ≤ 60 |
| `UndoService.migrate_global_history` CC | **34** | ≤ 10 |
| `services` line coverage (C-owned test set) | **86 %** | ≥ 85 % |
| `services/undo_service.py` line coverage | **76 %** | ≥ 70 % |
| C-owned test baseline | **32 failed / 648 passed** | 5 C-fixable → 0; 25+ A-caused stay red |
| `services/run/*` branch coverage | error_recovery 83 %, hooks 95 %, state_machine 81 % | branch tests added (mutation-proxy) |
| new `backend.*` imports from `services/` | n/a | **zero** |

The refactor is **internal-only**: every public class, method and signature in
`services/**` is preserved; the two A-owned files
(`services/run/{coordinator,progress}.py`) are not touched; no file outside
`services/**` and the C-owned test paths is edited (see §7 for the two
cross-area notes).

---

## 1. Measured current state

### 1.1 Baseline of the C-owned test set

Command (C-owned files from §6.5; A-owned `test_run_service_paths.py`,
`test_main_entry.py`, `test_stores_migration_rollback.py` excluded; webengine
test deselected; `TestUIWiring` (frozen `main.py` assertion) deselected):

```
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/python -m pytest \
  tests/integration/services tests/test_collector_state.py tests/test_private_gate.py \
  tests/test_db_manager*.py tests/test_db_*.py tests/test_engine_standalone_run.py \
  tests/test_action_engine_sequence.py tests/test_archive_delete_undo.py \
  tests/test_people_undo.py tests/test_filter_purge.py tests/test_scroll_only_seek.py \
  tests/test_search_users.py tests/test_repeat_loop.py tests/test_click_user_memory.py \
  tests/test_click_user_order.py tests/test_take_person.py tests/test_mark_person_messaged.py \
  tests/test_live_status_and_order.py tests/test_merge_undo_enabled.py \
  tests/test_grid_persistence.py tests/test_grid_layout_v2_migration.py \
  tests/test_history_service_lifecycle.py tests/test_history_bridge.py \
  tests/test_recollect_after_clear.py
```

→ **32 failed / 648 passed.** Classification:

| # | root cause | tests | fix lands in | C action |
|---|---|---|---|---|
| 1 | `ValueError: invalid transition: idle -> paused` | 1 | `services/run/state_machine.py` | **fix (P2-8)** |
| 2 | stop-while-paused emits no "stopped" debug line | 1 | `services/run/error_recovery.py` | **fix** |
| 3 | all-disabled stack returns `"ok"` → user marked messaged | 1 | `services/run/error_recovery.py` | **fix** |
| 4 | `DbManager.resolve()` lets `../evil` / absolute names escape the app folder | 2 | `services/db_service.py` | **fix** |
| 5 | `NameError: get_action_class` (coordinator.py:42) | ~24 | **A** (P0-1) | leave red; A owns the file |
| 6 | `NameError: UserRecord` (progress.py:150) | 2 | **A** (P0-2) | leave red |
| 7 | `SessionStore` ctor contract | 1 collateral in C set | **B** | leave red |

### 1.2 Coverage before refactoring (C-owned test set, branch)

| file | line % | branch % |
|---|---|---|
| services/cdp_service.py | 99 | — |
| services/collector_service.py | 87 | 85 |
| services/db_service.py | 80 | 78 |
| services/history/__init__.py | 97 | — |
| services/history/export.py | 82 | — |
| services/history/mutate.py | 92 | — |
| services/history/query.py | 88 | — |
| services/layout_service.py | 98 | — |
| services/people_service.py | 93 | — |
| services/run/error_recovery.py | 83 | — |
| services/run/hooks.py | 95 | — |
| services/run/progress.py | 87 | — |
| services/run/state_machine.py | 81 | — |
| services/undo_service.py | **76** | — |
| **TOTAL services** | **86** | 85 |

### 1.3 Complexity before refactoring

| function | CC | LOC | after |
|---|---|---|---|
| `Collector._tick` | 82 | 212 | delegate to tick state machine |
| `Collector.handle_push` | 15 | 39 | unchanged |
| `UndoService.migrate_global_history` | 34 | 73 | delegate to `UndoProjection` |
| `UndoService.sync_world_state` | 14 | 36 | delegate to `UndoWorldStore` |
| `DbManager.delete` | 21 | — | moved into `DbLifecycle`, split into steps |

---

## 2. Ground rules applied

1. **No signature changes across area boundaries.** `Collector`, `UndoService`,
   `DbManager`, `HistoryService`/`HistoryQueryService`/`HistoryMutateService`/
   `HistoryExportService`, `CdpService`, `PeopleService`, `LayoutService`,
   `RetryPolicy`, `RunExecutionMixin`, `RunHooks`, `RunHooksMixin`,
   `RunStateMachine`, `RunState`, module-level helpers (`safe_db_name`,
   `db_stem`, `folder_size`, `file_group_size`, `_merge`, `_db_stem`,
   `normalize_blocks`, `norm_level`, `RunTracer`, `emit_db_change`,
   `restart_world`, `people_row`, `_values_equal`, `_same_entry`) keep their
   exact names, signatures and observable behaviour.
2. **Internal splits only.** New collaborators are new symbols in new C-owned
   modules (`services/collector_tick.py`, `services/undo_support.py`,
   `services/db_lifecycle.py`, `services/db_registry.py`,
   `services/history/runtime.py`, `services/service_log.py`). Gate 6 (API
   parity) allows NEW symbols; no existing symbol may change or disappear.
3. **Frozen files untouched:** `core/*`, `bridge/*`, `app/*`, `main.py`,
   `stores/history_models.py`, `stores/jsonio.py`, `stores/migration.py`,
   `backend/cdp_client.py`, `actions/base_action.py`, all `backend/*.py`
   shims, and `services/run/{coordinator,progress}.py` (A-owned).
4. **Test ownership:** new tests land in new C-owned files under
   `tests/integration/services/`. C-owned test files that import the alias
   package `services.history_service` are repointed (allowed — C owns them).
   The A-owned test file is NOT edited (§8.4) — see §7.
5. **Zero new `backend.*` imports from `services/`.** The refactor only
   *moves* code that already lives in `services/`; the 8 existing
   `backend.*` imports stay exactly where they are.

---

## 3. Structure: `services/collector_service.py`

### 3.1 Problem

`Collector._tick` is a 212-LOC coroutine (CC 82) that mixes five jobs:
(1) in-page agent check + probe reading, (2) the four "refuse this tab"
gates, (3) My-Nick detection/adoption, (4) the two-step private-chat gate,
(5) the archive half (rename check, person rows, cursor check, backfill
planning, `sync_conversation`, media drains, UI notify). The plan names the
extraction: **a tick state machine** plus **`CollectorProbe`** and
**`CollectorArchive`**.

### 3.2 Target structure (new module `services/collector_tick.py`)

```
services/collector_tick.py
├── TickPhase(str, Enum)         # PROBE → GATE → NICK → VERIFY → ARCHIVE → TERMINAL
├── Refusal                      # frozen dataclass: (state, text)
├── Outcome                      # frozen dataclass: (state, text)
├── CollectorProbe               # phases PROBE / GATE / NICK / VERIFY
│   ├── __init__(self, host: Collector)
│   ├── async inspect(self) -> Probe | Refusal        # agent self-heal + _last_probe payload
│   ├── refuse_tab(self, probe) -> Refusal | None     # ok / private tab / participants / empty nick / self-chat
│   ├── adopt_my_nick(self, probe) -> str             # my-nick detection & stale-nick adoption (returns my_nick)
│   └── async verify(self, probe, nick, my_nick) -> PrivateCheck
├── CollectorArchive             # phase ARCHIVE (the write half)
│   ├── __init__(self, host: Collector)
│   ├── async maybe_rename(self, nick, probe)         # rename_if_same_conversation continuation
│   ├── async open_person(self, nick, probe) -> int   # ensure_person + _remember_partner + log
│   ├── async cursor_check(self, person_id, probe) -> CursorVerdict | Unchanged
│   ├── plan_backfill(self, cursor) -> (bootstrap, want_backfill)
│   └── async finish(self, result, nick) -> Outcome   # media repair log, drains, notify, COLLECTED/NO_NEW/NOT_PRIVATE
└── CollectorTick                # the state machine shell
    ├── __init__(self, host: Collector)
    └── async run(self) -> tuple[state, text]
```

`Collector._tick` collapses to:

```python
async def _tick(self) -> str:
    state, text = await CollectorTick(self).run()
    return self._set(state, text)
```

(2 statements, CC 1.) All `self._field` mutations move verbatim into the
collaborators, which hold a reference to the host `Collector` — the emitted
status payload (`state_payload`) is byte-identical for every path. Each
collaborator method is capped at CC ≤ 10 by construction (one gate per
method, guards instead of nested `if`s).

### 3.3 Behaviour contract (unchanged)

The full `_tick` matrix, asserted by the new phase tests (§6.1) and the
existing `test_collector_state.py` / `test_private_gate.py` /
`test_services_collector_gaps.py`:

- not running → OFF; disabled → OFF; paused → PAUSED; disconnected → DISCONNECTED;
- stale agent → `parser.install()` + self-heal count + log;
- `state.ok == False` / tab ≠ private / participants not 2 → NOT_PRIVATE / GROUP_TAB;
- empty partner nick → NOT_PRIVATE; partner == my nick → NOT_PRIVATE (ambiguous);
- My-Nick adoption: single outbound author; stale saved nick replaced when the
  pane self-reports a different one; detection logged;
- partner rename → `repo.rename_if_same_conversation` continuation ("the
  history continues");
- `verify_private` failure → `_gate_status` refusal (strangers / title_mismatch /
  self_chat / no_author_data);
- unchanged cursor → NO_NEW **and** media drains still run (Bug #2 2026-09-07);
- bootstrap / auto-backfill / forced backfill planning flags;
- sync added>0 → COLLECTED + `history_appended`; sync not ok → NOT_PRIVATE;
  no rows → NO_NEW; media repair/requeue counters logged.

`handle_push`, `_sync`, `backfill_older`, `run`, `reset_state`,
`person_cleared`, `note_probe_duration`, `next_interval_ms`, `state_payload`
stay on `Collector` untouched (they are small or public).

---

## 4. Structure: `services/undo_service.py`

### 4.1 Problem

`migrate_global_history` (CC 34) folds four concerns: per-kind validation of
the stored `undo_history`, the legacy `stack_history`/`grid_layout_history`/
`grid_layout` migration, the index clamping, and the persistence writes.
`sync_world_state` mixes pending-task settlement, world-table load, config
half load, merge-by-seq and commit. The plan names the extraction:
**`UndoProjection`** and **`UndoWorldStore`**.

### 4.2 Target structure (new module `services/undo_support.py`)

```
services/undo_support.py
├── UndoProjection               # pure timeline reads / projections (no I/O)
│   ├── __init__(self, entry_builder)          # builder = UndoService._history_entry (kind, value) -> entry
│   ├── from_raw_history(self, raw) -> list[dict]      # per-kind validation, seq preserved
│   ├── from_legacy_config(self, config) -> (list, index, canonical_grid | None)
│   ├── clamp_index(self, index, length) -> int
│   ├── clean(self, history) -> list[dict]             # stack blocks via normalize_blocks
│   ├── stack_projection(self, history, index) -> (list, int)
│   └── kind_projection(self, history, index, kind) -> (list, int)
└── UndoWorldStore               # the world-bound half (undo_history table)
    ├── __init__(self, host: UndoService)      # host ref; pendings stay on host._undo_pendings
    ├── split(self, history) -> (app_entries, world_entries)
    ├── schedule_save(self, entries) -> None   # asyncio.ensure_future + done-callback bookkeeping
    ├── async settle(self) -> None             # gather all pending saves
    ├── async load(self) -> list[dict]         # archive.load_world_undo (guarded)
    └── async save(self, entries) -> None      # archive.save_world_undo (guarded)
```

`UndoService` keeps every public method; the two heavy ones become thin:

```python
def migrate_global_history(self) -> tuple[list, int]:
    raw = self._config.get_state("undo_history", None)
    if isinstance(raw, list) and raw:
        return self._projection.from_raw_history(raw)
    history, index, canonical = self._projection.from_legacy_config(self._config)
    if canonical is not None:
        self._config.set_state(grid_layout=canonical)
    self._config.set_state(undo_history=copy.deepcopy(history),
                           undo_history_index=index)
    return history, index
```

(CC ≈ 4.) `_commit_timeline` delegates the app/world split and the world-save
scheduling to `UndoWorldStore`; `sync_world_state` delegates settle/load.
**Compat note:** `tests/integration/services/test_services_undo.py:253`
reads `self.undo._undo_pendings` directly — the attribute stays on
`UndoService` (the world store manipulates it through the host), so the
existing test keeps working unchanged.

### 4.3 Behaviour contract (unchanged)

- stored `undo_history` entries: stack lists, grid strings (canonicalised via
  `LayoutService.canonical_grid_payload`), people `{before, after}` dicts,
  labels/archive/dbconn dicts — invalid shapes skipped; `seq` preserved when
  positive int;
- legacy: `stack_history` lists, `grid_layout_history` strings, current
  `grid_layout` canonicalised and appended when different + written back;
  cap at `MAX_STACK_HISTORY`; index rules (has_grid → last, legacy index
  clamped, else last);
- world split: `WORLD_UNDO_KINDS = {people, labels, archive, dbconn}` → world
  table; the rest → `config/undo_history`;
- merge by `(has_seq, seq)` sort in `sync_world_state` unchanged.

---

## 5. Structure: `services/db_service.py`

### 5.1 Problem

`DbManager` (27 methods) mixes two jobs: the *registry* (remember / list /
switch / info — reads) and the *lifecycle* (create / load / delete / clean /
restore — mutating operations with the media-reference scans). The plan names
the split: **`DbLifecycle`** (create/delete/clean/restore) and
**`DbRegistry`** (remember/list/switch). The same file also carries the
containment defect (1.1 row 4).

### 5.2 Target structure (new modules `services/db_registry.py`, `services/db_lifecycle.py`)

```
services/db_registry.py
└── DbRegistry
    ├── __init__(self, host: DbManager)
    ├── active_path() / resolve() / trash_dir() / media_base_dir() / media_dir()
    ├── known_paths() / _remember() / _prune_remembered()
    ├── existing_worlds() / list_dbs()
    └── async info()

services/db_lifecycle.py
└── DbLifecycle
    ├── __init__(self, host: DbManager)
    ├── async create(name) / async load(path, create=False)
    ├── async delete(path)           # split into steps: _guard, _switch_away, _unlink, _forget
    ├── async clean() / async restore_backup(backup, target="")
    ├── async _world_footprint() / _other_references() / _delete_world_media()
    ├── _forget() / _pick_fallback() / _stamp() / _copy_to_trash() / _persist_path()

services/db_service.py               # module helpers stay here:
├── safe_db_name / db_stem / folder_size / file_group_size / _media_references
├── TRASH_DIR / SUFFIXES
└── DbManager                        # facade, identical public API
    ├── __init__(config, service, root) → creates self.registry = DbRegistry(self),
    │                                      self.lifecycle = DbLifecycle(self)
    └── every former public method is a one-line delegate
```

`DbManager` keeps **all** current public names (`active_path`, `resolve`,
`trash_dir`, `media_base_dir`, `media_dir`, `known_paths`, `existing_worlds`,
`list_dbs`, `info`, `create`, `load`, `delete`, `clean`, `restore_backup`,
`attach`, `service` property) as thin delegates — callers (the frozen
`backend/db_manager.py` shim, `bridge/db_bridge.py`, `services/undo_service.py`)
see no change. Collaborators call each other through the host
(`host.registry.resolve(...)`, `host.lifecycle.load(...)`), so cross-method
behaviour is byte-for-byte the old code moved around.

### 5.3 Containment fix (P-bug 4 in §1.1)

`resolve()` is the choke point every mutating entry passes. It gets the
containment rule its own docstring already promises ("kept inside the app"):

```python
def resolve(self, name_or_path: str) -> str:
    ...  # current computation unchanged
    root = os.path.abspath(self.root)          # root = the app folder
    if not os.path.abspath(candidate).startswith(root + os.sep) \
            and os.path.abspath(candidate) != root:
        return ""                               # refuse to escape the app folder
    return candidate
```

- `create("../evil")` → refused (`""` → the existing "give the database a
  name" error path, i.e. a loud refusal — the containment tests accept both
  refusal and clamping);
- absolute paths **inside** the root keep working (the DB window passes real
  absolute paths of existing worlds);
- `load`/`delete`/`restore_backup` of outside paths are refused with their
  existing error strings.

Existing green tests that create worlds under the root temp dir are
unaffected; the two `TestCreateContainment` tests flip green.

---

## 6. Structure: `services/history/*`

### 6.1 Problem

`HistoryExportService` (16 methods, LCOM* 0.94) is four services stapled
together: CDP push binding, collector runtime, world switching, migration,
export. `query.py` / `mutate.py` have thin coverage of their edge branches
(load_app_settings JSON guards, migrate_install branches, switch_db
fail-closed path).

### 6.2 Target structure (new module `services/history/runtime.py`)

```
services/history/runtime.py
├── PushBindings(host)      # _install_push_binding / _rebind / _on_disconnected / _on_binding
├── CollectorRuntime(host)  # start / _stop_collector / _restart_collector
├── WorldSwitcher(host)     # detach_db / switch_db / _rebind_db / _flush_labels / _load_world_state
├── HistoryMigration(host)  # migrate_install (queue merge, label import, recent prune, undo rehome)
└── ChatExporter(host)      # export_chat (json/text/csv)
```

`HistoryExportService` keeps every current method name and signature; each is
a one-line delegate to a lazily-created collaborator (memoised property with
a `host` reference — no `__init__` change, so `HistoryService.__init__`
(which deliberately calls no `super().__init__`) is untouched). State
attributes (`_binding`, `_task`, `_detached_running`) stay on the host
exactly where they are set today.

`query.py` / `mutate.py` are already cohesive (they map 1:1 onto
`HistoryQueryService` / `HistoryMutateService`); they are **not** restructured
— the missing part there is tests (§7).

### 6.3 Contract tests added (before the refactor, per process step 3)

New C-owned file `tests/integration/services/test_history_service_contract.py`
covers, on fakes + real SQLite temp files (no Qt):

- `HistoryQueryService`: `_migrate_media_cap` (≤ OLD_MAX_FILE_MB → default),
  `load_app_settings` (my_nick str / media caps / preview merge / bad JSON),
  `load_gaze` restore, `get_meta_flag` (missing table → False),
  `load_world_undo` (missing table → [], row decode), `page` payload,
  `to_json`.
- `HistoryMutateService`: `apply_settings` merge + `collector` key routing +
  persist, `set_my_nick` trimming, `seed_app_settings` (no clobber of existing
  keys), `save_gaze` (empty nick → no-op), `_merge_legacy_queue` (real legacy
  DB → merged + `.migrated-*` rename + memory switch), `_rehome_undo_entries`
  (seq assignment + world-kind move), `save_world_undo` (delete+insert round
  trip).
- `HistoryExportService`: `export_chat` json/text/csv shapes,
  `migrate_install` all four report flags, `_stop_collector` state dict +
  `_restart_collector` both branches, push binding install/rebind/disconnect/
  `_on_binding` routing, `switch_db` success + **fail-closed fallback**
  (corrupt target → previous world re-opened and reported).

---

## 7. Structure: `services/run/{error_recovery,hooks,state_machine}.py`

### 7.1 Behaviour fixes (smallest possible diffs)

**P2-8 — `idle -> paused`** (`state_machine.py`): `RunState.IDLE` currently
allows only `RUNNING`; the Run button can legitimately be paused while the
engine is idle, and `execute()` resets the pause flag at start. Fix:
`_ALLOWED[RunState.IDLE] = {RunState.RUNNING, RunState.PAUSED}`.
(Resume-from-idle already worked: IDLE → RUNNING.) All other rows unchanged.

**Stop-while-paused message** (`error_recovery.py`, `_execute_for_user`):
when `_stop_requested` is seen between users, the engine returns `"stop"`
silently while the queue loop emits `"⏹ Stack stopped by user"`. The
user-facing debug line moves into `_execute_for_user` next to the early
return (plus the matching tracer note), so stop is always announced.

**All-disabled stack** (`error_recovery.py`, `_execute_for_user`): the guard
returns `"ok"`, which the coordinator reads as "user completed" → the New
queue person is marked messaged without a single block running (the B5
regression). Fix: return `"skip"` — the coordinator then reports
`user_complete(nick, False)` and does **not** mark messaged, matching the
test contract and the UI wording "nothing to run".

### 7.2 Branch tests added

New C-owned file `tests/integration/services/test_run_state_machine_contract.py`:

- `RunStateMachine`: full transition matrix (each valid edge, each invalid
  edge raises `ValueError` with the `a -> b` text), `mark_running` from
  ERROR/DONE resets first, `mark_stopping` from RUNNING/PAUSED and no-op
  elsewhere, `mark_error` from IDLE, `mark_done` from RUNNING/STOPPING,
  **idle → paused → resume** round trip (P2-8).
- `RetryPolicy`: `should_retry` (transient vs permanent, attempt bounds),
  `retry_with_backoff` (success, retry-then-success, exhausted fallback,
  exhausted raise).
- `RunExecutionMixin` (via `ActionEngine` with the `EngineCase` fakes):
  `_handle_step_result` OK/SKIP/FAIL, `_step_failed`, `mark_person_messaged`
  (missing / already / ok / error), stop-while-paused "stopped" message,
  all-disabled → `"skip"` and no marking.
- `RunHooks`/helpers: `normalize_blocks` (retired keys, `_`-keys, None
  enabled), `norm_level` full map, `RunTracer` note/close, `maybe_await`,
  `RunHooksMixin.report` / `unmessaged_nicks` / `is_stopping` /
  `person_rejected` / `note_selected` / `_expand_nick_on_block`.

The unused `coordinator` parameters of `RunHooks.{pre_run,post_run,
on_action_complete}` are **kept** — removing them changes the hook signature
that subclasses override, which would break the "no cross-boundary signature
changes" rule; the plan's dead-symbol deletion is deferred to the cleanup PR.

---

## 8. Structure: shared status helpers + alias packages

### 8.1 `_log` dedup (cdp / people / undo services)

`CdpService._log`, `PeopleService._log` and `UndoService._log` are identical
two-liners (`self._bus.emit(LogMessage(message=..., level=...))`). New
C-owned module `services/service_log.py` with

```python
def emit_log(bus, message: str, level: str = "info") -> None:
    bus.emit(LogMessage(message=message, level=level))
```

Each service keeps its private `_log` method as a one-line delegate (tests
may call `service._log(...)`), so nothing observable changes.
`LayoutService` has no duplication (pure functions, no bus); the remaining
status-forwarding copies live in `bridge/*`, which is out of every area's
scope (§9 of the plan).

### 8.2 Alias packages

| package | importers (measured) | action |
|---|---|---|
| `services/history_service/` | 2 C-owned tests (`test_services_history.py:25`, `test_services_db_gaps.py:166`) | repoint both to `services.history`, **delete the package** |
| `services/run_service/` | 2 C-owned tests (`test_services_run.py:28`, `test_services_undo.py:33`) + **1 A-owned test** (`test_run_service_paths.py:27`) | repoint the 2 C-owned tests to `services.run`; **keep the alias package** (deleting it would break the A-owned file, which §8.4 forbids C to edit) — cross-area request for the cleanup PR |

The two frozen backend shims (`backend/history_service.py`,
`backend/action_engine.py`) already import the real packages
(`services.history`, `services.run`) — no edit needed there.

---

## 9. Cross-area requests (raised here, landed in the cleanup PR §9)

1. Delete `services/run_service/` after repointing
   `tests/integration/services/test_run_service_paths.py:27`
   (`services.run_service` → `services.run`) — that test file is A-owned,
   so C raises this instead of editing it (§8.4).
2. The `RunHooks` dead `coordinator` parameters (plan §12.1, 100 %-confidence
   list) — signature changes need the cleanup PR.

---

## 10. Test-first plan (process step 3, executed before step 4)

New C-owned test files, written against the CURRENT code, all passing before
the refactor except the four explicitly behaviour-changing cases (marked
`@unittest.expectedFailure`-style via assert comments / run-and-record):

| new file | covers | behaviour-changing? |
|---|---|---|
| `tests/integration/services/test_collector_tick_phases.py` | §3.3 matrix through `Collector.tick()` with fakes (parser/repo/media/memory) | no |
| `tests/integration/services/test_undo_support_contract.py` | §4.3 migration/projection/world-store matrix | no |
| `tests/integration/services/test_history_service_contract.py` | §6.3 query/mutate/export contracts | no |
| `tests/integration/services/test_run_state_machine_contract.py` | §7.2 + the 3 fixes (idle→paused, stop message, all-disabled skip) | **yes (3)** |
| `tests/integration/services/test_db_manager_contract.py` | registry/lifecycle seams + resolve containment matrix | **yes (2)** |

Then the refactor lands (step 4) and the five behaviour-changing tests flip
green together with the five currently-red C-owned tests of §1.1.

---

## 11. Implementation order

1. **Fixes first** (smallest diffs, each verifiable alone):
   `state_machine.py` (P2-8) → `error_recovery.py` (stop message, skip) →
   `db_service.py` (containment). Run the 5 red tests → green.
2. **New tests** (§10) → all pass against current code (except the 5
   behaviour-changing ones, recorded as pre-fix failures).
3. **Refactor** in this order (each step keeps the suite green):
   collector tick machine → undo projection/world store → db lifecycle/
   registry → history runtime → service_log + alias repointing/deletion.
4. **Verification** (§12) + coverage/CC gates + API-parity diff.

## 12. Verification (exit criteria)

1. `Collector._tick` CC ≤ 15 and ≤ 60 LOC; `migrate_global_history` CC ≤ 10
   (measured with the same AST counter that produced §1.3).
2. `services` line coverage ≥ 85 % **and** `services/undo_service.py` ≥ 70 %
   on the C-owned test set (pre: 86 % / 76 % — must not regress; the new
   tests should push both up).
3. `services/run/*` branch coverage up (state_machine 81 % → ≥ 90 %,
   error_recovery 83 % → ≥ 90 % as the branch-test proxy for the plan's
   mutation gate).
4. `grep -rn "^from backend\|^import backend" services/ | wc -l` unchanged
   (zero new backend imports).
5. C-owned test set: 32 failed → ≤ 27 failed (the five C-fixable green, the
   A/B-caused ones unchanged and documented).
6. Public-API parity: `pkgutil`-based signature dump before/after — only NEW
   symbols, no changes, no removals (Gate 6 adapted to `services/**`).
7. Full suite (3 A-owned files excluded) does not regress outside the
   documented A/B set.

### 12.1 Results (2026-09-10, all gates measured)

| # | gate | measured | verdict |
|---|---|---|---|
| 1 | `_tick` ≤ CC 15 / 60 LOC; `migrate_global_history` ≤ CC 10 | CC **1 / 14 LOC**; CC **4** (12 LOC delegate); every split piece ≤ 10 (`_migrate_entry` = 10, tick phases ≤ 9) | ✅ |
| 2 | services ≥ 85 %, undo_service ≥ 70 % | **88 %** / **75 %** (undo_support 90 %, collector_tick 98 %, history/runtime 90 %, db_registry 84 %, db_lifecycle 79 %) | ✅ |
| 3 | run/* branch ≥ 90 % | state_machine **100 %**, error_recovery **100 %** (was 81/83; 12 new branch tests added → contract now 41 tests) | ✅ |
| 4 | zero new `backend.*` imports from services/ | 11 statements / 6 files, identical to HEAD (4 of them indented `TYPE_CHECKING`/function-local — a plain `^from backend` grep reports 7/4 and must not be used) | ✅ |
| 5 | C-owned set 32 failed → ≤ 27 | **28 failed / 776 passed / 1 skipped** — all 28 pre-existing A-owned (25× P0-1 `get_action_class` + 3 downstream); verified identical at a pristine HEAD worktree. Baseline doc's "~24" P0-1 count was an undercount — with the true 25+3 the arithmetic lands on 28, not 27 | ✅ (with correction) |
| 6 | API parity, only NEW symbols | only NEW symbols; one real hit fixed: `LayoutService` re-imported into `services/undo_service.py` (namespace parity). `services/history_service/` removal is the documented §8.2 deletion | ✅ |
| 7 | full suite (3 A-owned files excluded) | **47 failed / 1687 passed** vs baseline 52 / 1551 — exactly the 5 C-fixable green; the 47 are 25 P0-1 + 4 downstream + 17 B-stores + `TestUIWiring` (frozen main.py) + 1 D config_manager | ✅ |

**TestBlocksAndNick note (closes the one open item):**
`test_services_run.py::TestBlocksAndNick::test_load_stack_normalizes_and_skips_unknown`
fails at pristine HEAD with the OLD `services.run_service` import too — it is
P0-1 (`RunCoordinator.load_stack` calls the missing `get_action_class`). The
alias repointing never caused it; the earlier "passed pre-repoint" reading was
wrong. It stays red as A-owned.

**Verification environment:** the sandbox reset wiped `.venv` and
`/tmp/stublibs`; both were rebuilt (`python3 -m venv .venv` +
`requirements.txt` + pytest/pytest-cov; `/tmp/stublibs` now holds generated
stub `.so`s with the real versioned symbols Qt needs: `LIBDBUS_1_3`,
`V_0.5.0` xkb, egl/gl/glX, plus the full WebEngine import chain — nss/nssutil/
smime/nspr, gbm, xcb extension libs, X11 extension libs, asound/pulse —
built by scanning `objdump -T` UND symbols across all PySide6 Qt libs and
binding each symbol to its exact requested version node via `.symver`
aliases; apt is unreachable in this sandbox, so stubs are the only option).
One unrelated pollution source removed:
`config/blocks.json` (a migration-test by-product) made
`test_engine_standalone_run.py::TestSavedTabMainConfig` fail instead of skip;
deleted and re-deleted after the full run.

### 12.2 Results after AREA A integration (2026-09-10, second measurement)

AREA A's `e8c75bc` ("startup & test harness fixes") landed on the session
branch and was rebased under this commit. It adds `tests/conftest.py`
(imports `main` → the whole QtWebEngine chain must now import headlessly —
environment rebuilt, see above) and fixes P0-1/P0-2, so the 25 previously-red
`get_action_class` tests now pass. Re-measured on the rebased tree:

* C-owned subset: **820 passed / 0 failed** (pre-A baseline: 32 failed).
  All five contract files green; every C gate still holds.
* **New class of failures fixed here (C-owned):** once P0-1 was gone, 14
  order-dependent failures surfaced — C-owned test modules define fake
  blocks (`RecordingBlock`/`UserBlock`/`ScrollBlock`/`RepeatBlock`/…)
  with shipped `block_id`s (`CUSTOM_FIND`, `CLICK_USER`, `SCROLL_PARSE`,
  `REPEAT_LOOP`), which auto-register into the global `ActionRegistry` at
  import time and silently shadow the real actions for every later test
  module (filter/seek/repeat contracts). Fix: snapshot
  `ActionRegistry._classes` at module import and restore at module end
  (plus `addCleanup` in `EngineCase`) in the 9 affected C-owned test files.
* Full suite (3 A-owned files + `tests/test_sash_webengine.py` excluded —
  the webengine test needs real Chromium init, impossible against headless
  stub libs; the plan marks it "No area"):
  **19 failed / 1739 passed** — 17 B-owned stores failures, 1 `TestUIWiring`
  (frozen `main.py`), 1 D-owned `config_manager` contract. Zero C failures.

---

## 13. Risks

| risk | mitigation |
|---|---|
| `_tick` decomposition changes emitted payloads | phase tests pin `state_payload` per path; `_emit` signature dedup untouched |
| `UndoWorldStore` loses the `_undo_pendings` compat attr | attr stays on the host; existing test reads it unchanged |
| `DbLifecycle`/`DbRegistry` host refs change call order | collaborators call through the host exactly as the old methods did; `test_db_manager*.py` (534+ lines) is the oracle |
| containment fix over-refuses | boundary = `root` (the app folder); inside-root absolute paths (the DB window's normal input) still allowed; whole C-owned suite re-run |
| HistoryExportService collaborators change init order | lazy memoised properties; no `__init__`; `HistoryService` untouched |
