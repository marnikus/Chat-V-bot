# AREA B — Stores Refactor: New Structure Design

**Date:** 2026-09-10  
**Area:** `refactor/b-stores` — all 17 files in `stores/` (3 974 SLOC)  
**Branch:** `arena/01a089c8-chat-v-bot` (from `210ad036`)  
**Status:** design — no production code changed by this document  
**Replaces / refines:** `docs/REFACTOR_2026-09-09_FOUR_AREA_PLAN.md §6.2` and `docs/STORES_TEST_DESIGN_2026-09-09.md` for the six god classes

---

## 1. Problem restatement (measured on this checkout)

| # | Symptom | Tests blocked | Root cause file |
|---|---------|---------------|-----------------|
| P1-1 | `AttributeError: 'UndoStore' has no attribute 'history' / 'index'` | 86 | `stores/undo_store.py` missing `history()`/`index()` convenience surface that `backend/config_manager.py:273` and the undo timeline call |
| P1-2 | `AttributeError: 'BookmarkStore' has no attribute 'save'` | 74 | `stores/bookmark_store.py` missing `save()` delegate to its `AtomicJsonStore` |
| P1-3 | `TypeError: stat: path should be string … not AtomicJsonStore` | 16 | Constructor split — `BookmarkStore/UndoStore/BlockStore` accept `(atomic: AtomicJsonStore \| None, path: str)` while `SettingsStore/SessionStore/LabelsFileStore/PresetStore` accept bare `path: str`. Tests call `SessionStore(AtomicJsonStore(path))` → crash. |
| P2-1 | `HistoryRepo` god class: 44 methods / 1 136 LOC / LCOM* 0.94; `recover_media` CC 34, `append` CC 29/14 params, `rename_if_same_conversation` CC 33 | 0 (structural debt, blocks velocity) | `stores/history_repo.py` 1 070 SLOC |
| P2-2 | Four more god classes over 200 SLOC and ≥20 methods | — | `MediaStore` 33 mth / `HistoryDB` 30 mth / `LabelStore` 38 mth / `UserMemory` 21 mth / `PresetStore` 20 mth |

**Already fixed in HEAD** (verified by reading `stores/undo_store.py`, `stores/bookmark_store.py`, `stores/block_store.py`):

* `UndoStore` now exposes `history()`, `index()`, `save_state()`, `reload()`, `flush()`, `save()`, `.dirty`, `.path` and clamps `[-1, len-1]` / caps `MAX_STACK_HISTORY`.
* `BookmarkStore` and `BlockStore` accept `(atomic | path)` and expose `load()/save()/reload()/flush()` + `BlockStore.all()/set_all()/custom_blocks()`.

**Still broken** (reproduced: `python3 -m pytest tests/test_stores_small_stores.py -q` → 16 failures, all `SessionStore(AtomicJsonStore)` / `SettingsStore(AtomicJsonStore)`):

* `SessionStore`, `SettingsStore`, `LabelsFileStore`, `PresetStore` do **not** accept `AtomicJsonStore`.
* `LabelsFileStore` has no `save()` (only `flush()`).
* No file in `stores/` is under 400 SLOC for the four god classes.

Exit criteria (from FOUR_AREA_PLAN §6.2):

1. All 176 P1 failures green.
2. No file in `stores/` over 400 SLOC; `HistoryRepo` under 30 public methods.
3. No import in `services/`, `backend/`, `actions/`, `bridge/`, `app/` needs editing (`grep -rn "from stores" … | wc -l` unchanged).
4. `stores` coverage ≥ 90 % line / ≥ 80 % branch.

---

## 2. Ground rules (from FOUR_AREA_PLAN §7.3 — frozen contract)

* Every production file belongs to **exactly one** area (this area owns all 17 `stores/*` files; no other area may edit them).
* Public function/class signatures across area boundaries **do not change** — every split is internal, callers are untouched. The old public name stays and delegates.
* Frozen for the duration (no area may edit): `core/*`, `bridge/*`, `app/*`, `main.py`, `stores/history_models.py`, `stores/jsonio.py`, `stores/migration.py`, `backend/cdp_client.py`, `actions/base_action.py`, and all `backend/*.py` compat shims.
* New helper modules are **private** (`stores/_*.py` or `stores/<name>_*.py`) and imported only by their facade; no external package imports them directly.

---

## 3. New file map — stores/ after B

```
stores/
├── __init__.py
├── atomic.py                  # + _coerce_path helper (shared)
├── block_store.py             # already conforms — no SLOC change
├── bookmark_store.py          # already conforms — no SLOC change
├── history_models.py          # FROZEN — untouched
├── jsonio.py                  # FROZEN — untouched
├── migration.py               # FROZEN — untouched
│
│  # — B1: small-store constructor unification (≤ 70 SLOC delta) —
├── session_store.py           # now (atomic|path) + save()
├── settings_store.py          # now (atomic|path) + data() stays overlay
├── labels_file_store.py       # now (atomic|path) + save() alias of flush()
├── preset_store.py            # now (AtomicJsonStore|str|config, path) + save() already
├── undo_store.py              # already conforms — no change
│
│  # — B2: god-class decomposition (internal collaborators only) —
├── history_repo.py            # FACADE ~280 SLOC, 24 public methods — delegates to:
├── _history_repo_alignment.py # align_batch, resolve_days, _minutes               (~90 SLOC)
├── _history_repo_writer.py    # AppendPlanner: append, _prepend, _existing_dup_keys,
│                              #   slot helpers (_empty_slot_rows … _fill_slot),
│                              #   _media_id, _ui_record, _after_write …          (~380 SLOC)
├── _history_repo_recovery.py  # MediaRecovery: recover_media, has_repairable_media,
│                              #   _media_key, _all_person_keys                    (~260 SLOC)
├── _history_repo_person.py    # ConversationIdentity + person/cursor lifecycle:
│                              #   ensure_person, get_person, possible_duplicates,
│                              #   rename_if_same_conversation, get_cursor,
│                              #   reset_cursor, mark_backfilled, _last_ord …      (~250 SLOC)
│
├── history_db.py              # FACADE ~340 SLOC — delegates to:
├── _history_db_schema.py      # SchemaMigrator: _repair_tables, _rebuild_legacy_messages,
│                              #   _has_legacy_messages_constraint,
│                              #   _rebuild_messages_constraint, _table_columns,
│                              #   _add_missing_columns, _migrate_dup_keys …      (~360 SLOC)
│
├── media_store.py             # FACADE ~320 SLOC (register, get, folder_for, _target_path …) — delegates to:
├── _media_fetch.py            # MediaFetcher: _fetch_one, _fetch_in_page,
│                              #   _fetch_via_python, _fetch_via_network,
│                              #   _finish_network_body, _abs_url               (~280 SLOC)
├── _media_cache.py            # MediaCachePolicy: cache_usage, evict_if_needed,
│                              #   _evict, clear_cache, _twin, migrate_layout    (~160 SLOC)
├── _media_nick.py             # slugify_nick, TRANSLIT, SAFE_CHARS, RESERVED,
│                              #   infer_kind, _extension                           (~90 SLOC)
│
├── label_store.py             # FACADE ~240 SLOC — delegates to:
├── _label_defs.py             # LabelDefinitions: create, update, delete, by_id/by_name,
│                              #   defs, normalize_*, PALETTE                       (~140 SLOC)
├── _label_assign.py           # LabelAssignments: assign, unassign, set_for, forget,
│                              #   ids_for, labels_for, labels_map, assignments    (~110 SLOC)
├── _label_filter.py           # LabelFilter: filter, set_filter, clear_filter,
│                              #   filter_active, allows, reject_reason            (~90 SLOC)
├── _label_io.py               # LabelStoreIO: load_from_db, flush_to_db,
│                              #   _schedule_flush, _guarded_flush, _write         (~130 SLOC)
│
├── user_memory.py             # FACADE ~160 SLOC — delegates to:
├── _user_query.py             # UserQuery: get_queue, get_all, get_stats,
│                              #   count_unmessaged, get_user, _row               (~70 SLOC)
├── _user_migrate.py           # (optional) replace_all transactional helper   (~30 SLOC)
│
└── preset_store.py            # FACADE ~150 SLOC — delegates to:
    └── _preset_migrate.py     # PresetMigration: import_legacy                     (~80 SLOC)
```

**SLOC math (worst case after split):**

| facade | original | after | helper max | total helpers |
|--------|----------|-------|------------|---------------|
| history_repo | 1 070 | ~280 | 380 | ~980 (no net growth, just moved) |
| media_store | 664 | ~320 | 280 | ~850 |
| history_db | 605 | ~340 | 360 | ~700 |
| label_store | 472 | ~240 | 140 | ~610 (3 helpers + io) |

All facades < 400; helpers < 400. `HistoryRepo` public methods drop from 44 → 24 (append, prepend, recover_media, rename…, get_person…, get_cursor…, soft_delete…, etc. remain; internal helpers become private `_…` or live on collaborators).

No external import changes: `from stores.history_repo import HistoryRepo` still works; same for `HistoryDB`, `MediaStore`, `LabelStore`, `UserMemory`, `PresetStore`.

---

## 4. B1 — Contract repair (do first, land as its own commit)

### 4.1 Shared helper — `stores/atomic.py`

Add a private helper used by every small-store constructor (no public API change):

```python
def _coerce_path(atomic: AtomicJsonStore | str | None, fallback: str) -> str:
    if isinstance(atomic, AtomicJsonStore):
        return atomic._path
    if isinstance(atomic, str) and atomic:
        return atomic
    return fallback
```

`AtomicJsonStore` itself stays `__init__(self, path: str = "config.json")` — it is the leaf; small stores do the coercion.

### 4.2 Per-store constructor change

Pattern (applied to `SessionStore`, `SettingsStore`, `LabelsFileStore`):

```python
# before
def __init__(self, path: str, data: dict | None = None):
    self._path = path
    ...

# after
def __init__(self, atomic: AtomicJsonStore | str | None = None,
             path: str = "config.json", data: dict | None = None):
    # positional compat: SessionStore("/tmp/x.json") → atomic="/tmp/x.json"
    # and SessionStore(AtomicJsonStore("/tmp/x.json")) → atomic=store
    if isinstance(atomic, AtomicJsonStore):
        self._path = atomic._path
    elif isinstance(atomic, str) and atomic:
        self._path = atomic
    else:
        self._path = path
    ...
```

For `LabelsFileStore` the same, but without `data`.

For `PresetStore` the signature is `__new__/__init__(cls, config=None, path=None)`. Extend the first arg to also accept `AtomicJsonStore`:

```python
def __new__(cls, config=None, path=None):
    # config may be AtomicJsonStore, a ConfigManager-like object with _path,
    # a plain path string, or None
    if isinstance(config, AtomicJsonStore):
        path = config._path
        config = None
    elif isinstance(config, str) and config:
        path = config
        config = None
    key = os.path.abspath(path) if path else ...
```

All four stores then expose a uniform persistence surface:

* `save(force: bool = False) -> bool` — atomic write (or delegated to `AtomicJsonStore.save()` / `save_json`).
* `load()/reload()` + `flush()` + `.dirty`/`.path` where they already exist; `LabelsFileStore` gains `save()` as alias of `flush()` (returns bool).
* No behaviour change for callers that already pass a string path (ConfigManager).

### 4.3 Verification (B1)

* `tests/test_stores_small_stores.py` — 16 currently failing tests for `SessionStore`/`SettingsStore` must go green; no other test may regress.
* New contract tests in `tests/test_area_b_contracts.py` (see §7) pin the atomic-or-path constructor and the `save()` lifecycle for all small stores.

---

## 5. B2 — God-class decomposition (internal splits only)

### 5.1 `stores/history_repo.py` → 4 helpers

**Current hot spots:** `recover_media` CC 34/169 LOC, `append` CC 29/112 LOC/14 params, `rename_if_same_conversation` CC 33/90 LOC, `_prepend` 12 params.

**Split:**

* `align_batch`, `resolve_days`, `_minutes`, `_as_record` → `stores/_history_repo_alignment.py` (pure functions, no state; imported by facade and by `_history_repo_writer`).
* `recover_media`, `has_repairable_media`, `_media_key`, `_all_person_keys` → `stores/_history_repo_recovery.py` class `MediaRecovery(repo: HistoryRepo)` (holds `repo.db`, `repo.media`, `repo._scan_seq`).
* `ensure_person`, `get_person`, `get_person_by_id`, `_person_dict`, `possible_duplicates`, `rename_if_same_conversation`, `get_cursor`, `reset_cursor`, `mark_backfilled`, `_last_ord` → `stores/_history_repo_person.py` class `ConversationIdentity`.
* `append`, `_prepend`, `_existing_dup_keys`, `_query_dup_keys`, empty-slot helpers (`_slot_key`, `_empty_slot_rows`, `_slot_row_key`, `_take_empty_slot`, `_fill_slot`, `_ord_of`), `_media_id`, `_ui_record`, `_record_gap`, `_touch_cursor`, `_after_write`, `_recount`, lifecycle (`new_op_token`, `soft_delete_*`, `purge_*`, `delete_person`, `restore_*`, `merge_persons`, `_resequence`) → `stores/_history_repo_writer.py` class `AppendPlanner`.

**Facade keeps:** `__init__(db, media, session_id)`, all public `async def …` methods with identical signatures, delegating:

```python
from stores._history_repo_alignment import align_batch, resolve_days
from stores._history_repo_person import ConversationIdentity
from stores._history_repo_writer import AppendPlanner
from stores._history_repo_recovery import MediaRecovery

class HistoryRepo:
    def __init__(self, db, media=None, session_id=""):
        self.db = db; self.media = media; self.session_id = session_id
        self._scan_seq = 0
        self._persons = ConversationIdentity(self)
        self._writer = AppendPlanner(self)
        self._recovery = MediaRecovery(self)

    async def ensure_person(self, nick): return await self._persons.ensure_person(nick)
    async def append(self, *a, **kw): return await self._writer.append(*a, **kw)
    async def recover_media(self, *a, **kw): return await self._recovery.recover_media(*a, **kw)
    # … every public method stays, but body is one delegation line
```

No call-site change: `HistoryRepo(db, media)` → same.

### 5.2 `stores/history_db.py` → ` _history_db_schema.py`

Extract `SchemaMigrator`:

* `_table_columns`, `_repair_tables`, `_rebuild_legacy_messages`, `_has_legacy_messages_constraint`, `_rebuild_messages_constraint`, `_person_for_nick`, `_count_rows`, `db_fetch_legacy`, `_read_version`, `_verify_schema`, `LATE_COLUMNS`, `_add_missing_columns`, `_migrate_dup_keys`, `_try_fts`.

Facade keeps: `TABLE_COLUMNS`, `TABLE_SQL`, `INDEX_SQL`, `SCHEMA`, `SCHEMA_VERSION`, `__init__`, `is_open`, `conn`, `init`, `close`, `execute`, `executemany`, `commit`, `fetchall`, `fetchdicts`, `fetchone`, `scalar`, `get_meta`, `set_meta`, `file_size`.

Internal: `await self._migrator.repair()` is called from `HistoryDB.init()`.

### 5.3 `stores/media_store.py` → `_media_fetch.py`, `_media_cache.py`, `_media_nick.py`

Pure constants/functions (`TRANSLIT`, `SAFE_CHARS`, `RESERVED`, `slugify_nick`, `infer_kind`, `_extension`, `IMAGE_EXT`, `MIME_EXT`) → `stores/_media_nick.py` (keeps `slugify_nick` import path via re-export: `from stores._media_nick import slugify_nick` at bottom of `media_store.py` so `from stores.media_store import slugify_nick` still works).

Fetch trio (`_abs_url`, `_fetch_one`, `_fetch_in_page`, `_fetch_via_python`, `_fetch_via_network`, `_finish_network_body`) → `stores/_media_fetch.py` class `MediaFetcher(store)`.

Cache policy (`cache_usage`, `evict_if_needed`, `_evict`, `clear_cache`, `_twin`, `migrate_layout`, `_free_name`, `_target_path`, `_day`, `folder_for` parts) → `stores/_media_cache.py` class `MediaCachePolicy`.

Facade keeps: `__init__`, `register`, `get`, `get_by_url`, `process_pending`, `retry_failed`, `requeue`, `download_one`, `retry_failed_uncached`, `path_for`, `clipboard_payload`.

### 5.4 `stores/label_store.py` → `_label_defs.py`, `_label_assign.py`, `_label_filter.py`, `_label_io.py`

* `_label_defs.py` — `normalize_color`, `normalize_name`, `PALETTE`, `LabelDefinitions(store)` (create/update/delete/by_id/by_name/defs/state).
* `_label_assign.py` — `LabelAssignments(store)` (assign/unassign/set_for/forget/ids_for/labels_for/labels_map/assignments).
* `_label_filter.py` — `LabelFilter(store)` (filter/set_filter/clear_filter/filter_active/allows/reject_reason).
* `_label_io.py` — `LabelStoreIO(store)` (load_from_db/flush_to_db/_schedule_flush/_guarded_flush/_write/_raw/_normalized/_save).

Facade `LabelStore` keeps: `__init__(config, db, scheduler)`, `db`/`is_bound`/`set_scheduler`, and every public method signature; bodies delegate to the four collaborators. `snapshot`/`restore` delegate to `defs+assign+filter` synthesis.

### 5.5 `stores/user_memory.py` → `_user_query.py`

Extract read/query helpers (`get_queue`, `get_all`, `count_unmessaged`, `get_stats`, `get_user`, `_row`) → `stores/_user_query.py` class `UserQuery(mem)`.  
Extract `replace_all` transaction (all-or-nothing with rollback) → helper in same file or `stores/_user_migrate.py`.  
Facade keeps `__init__`, `db_path`, `is_open`, `init`, `switch_db`, `close`, `upsert_user`, `upsert_many`, `mark_messaged`, `delete_user`, `delete_users`, `set_messaged`, `reset_messaged`, `clear_all`, `replace_all`.

### 5.6 `stores/preset_store.py` → `_preset_migrate.py`

Extract `import_legacy` → `stores/_preset_migrate.py` function `migrate_presets_from_db(store, db_path)`.  
Also extract `named_*` helpers if they push the file over 400 (currently 204, so optional). For now keep them in facade; only the migration moves.

---

## 6. Public API parity — frozen surface

Byte-identical signatures that must not change (checked by `tools/metrics` Gate 6 in FOUR_AREA_PLAN §8.3):

* `HistoryRepo(db, media, session_id)` + all 44 public `async def …` names and their parameter lists.
* `HistoryDB(path, use_fts)` + `init/close/execute/fetchall/.../file_size`.
* `MediaStore(db, cdp, cache_dir, max_file_mb, max_cache_mb, enabled)` + `register/get/process_pending/.../cache_usage`.
* `LabelStore(config, db, scheduler)` + every CRUD/filter/snapshot method.
* `UserMemory(db_path)` + every queue method.
* `PresetStore(config, path)` (cached per path) + every `save_stack/load_stack/list_stacks/delete_stack/…/named_*`.

New helper classes are **private** (`_AppendPlanner`, `_MediaRecovery`, etc.) and not imported outside `stores/`.

Re-exports for backward compat where helpers held public symbols:

* `from stores.media_store import slugify_nick, infer_kind` — re-exported at bottom of `stores/media_store.py`.
* `from stores.history_repo import align_batch, resolve_days` — re-exported.

---

## 7. Test coverage before refactoring (TDD gate)

### 7.1 New test file — `tests/test_area_b_contracts.py`

Written **before** any production edit (fails on main, passes after B1+B2). Covers:

**B1 contract (small-store unification):**

* `SessionStore(AtomicJsonStore(path))` constructs, `set` + `get` round-trips, `save()` persists and reopen sees it.
* `SettingsStore(AtomicJsonStore(path))` same, plus `validate()` still works.
* `LabelsFileStore(AtomicJsonStore(path))` constructs, `set_data` → `save()` → reopen sees it; `save()` is alias of `flush()`.
* `PresetStore(AtomicJsonStore(path))` constructs, `save_stack` persists.
* All four tolerate `AtomicJsonStore` **and** plain `str` path **and** bare `path=` keyword.

**Structural (B2) pins:**

* No file in `stores/` over 400 SLOC (`test_no_file_over_400_sloc` — expects failure before split, pass after).
* `HistoryRepo` public method count < 30 (`inspect.getmembers(HistoryRepo, predicate=inspect.isfunction)`).
* Collaborator modules exist and facade delegates (spy: patch helper and assert facade calls it).
* `stores` coverage stays ≥ 90 % line (run `coverage run --branch --source=stores -m pytest tests/test_area_b_contracts.py`).

**Existing suites that must stay green (no new failures):**

* `tests/test_stores_atomic_jsonio.py` (25)
* `tests/test_stores_small_stores.py` (58 → 74 after fix; 16 currently red)
* `tests/test_label_store_orphans.py` (LBL-* — label edge cases)
* `tests/test_media_store*.py`, `tests/test_history_repo*.py`, `tests/test_history_db*.py`, `tests/test_user_memory*.py`, `tests/test_preset_store*.py`, `tests/test_stores_split.py`

### 7.2 Running the gate

```bash
python3 -m pytest tests/test_area_b_contracts.py -v
# BEFORE B1 → 10 failures (atomic-path cases)
# AFTER  B1 → 0 failures
# AFTER  B2 → also structural tests pass
```

Coverage gate (from FOUR_AREA_PLAN §8.3 Gate 7):

```bash
python3 -m pytest tests/test_stores_small_stores.py tests/test_stores_atomic_jsonio.py \
  tests/test_area_b_contracts.py --cov=stores --cov-branch --cov-report=term
# stores: 90%+ line, 80%+ branch
```

---

## 8. Implementation order (mirrors FOUR_AREA_PLAN §6.2)

1. **B1 commit** — `stores/atomic.py` (_coerce_path), `stores/session_store.py`, `stores/settings_store.py`, `stores/labels_file_store.py`, `stores/preset_store.py` (+ tests). Verify `tests/test_stores_small_stores.py` drops from 16 failed → 0; full suite failures drop by 16.
2. **B2 commits** (one per god class, each independently green):
   * `history_db` + `_history_db_schema.py`
   * `media_store` + `_media_*.py`
   * `history_repo` + `_history_repo_*.py` (largest — last)
   * `label_store` + `_label_*.py`
   * `user_memory` + `_user_query.py`
   * `preset_store` + `_preset_migrate.py`
3. Final gate: `python3 -m pytest tests -q` — expected failures after A+B ≈ 20 (from 223), `vulture --min-confidence=90` 0 findings in `stores/`, `radon cc` no fn > CC 25 in stores (except already-high ones now isolated).

---

## 9. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Facade delegation introduces `await` double-wrapping / lost `self` | Helpers receive the facade instance (`ConcreteHelper(self)`) and access `self.facade.db` etc.; facade methods are `async` and `return await helper.<method>(…)` with identical signature (no `*args` leakage). |
| `PresetStore._by_path` cache breaks when path is coerced from `AtomicJsonStore` | Cache key is `os.path.abspath(path)` derived from `AtomicJsonStore._path` — same string as before, so existing cached instance is found. |
| New files increase total SLOC but each file must stay under 400 | Measure with `wc -l stores/*.py stores/_*.py`; if a helper exceeds 400, split it further (e.g., `_history_repo_writer.py` can be split into `_history_repo_slots.py` + writer). |
| `stores.media_store.slugify_nick` used by `services/people_service` and tests | Re-export it from `stores/media_store.py` (`from ._media_nick import slugify_nick`) so old import still works. |
| `history_repo.align_batch` used by `tests/test_history_repo_conflicts.py` and `services/collector_service` | Re-export at facade bottom. |

---

## 10. Deferred (not in B — stays in cleanup PR per §9)

* Retiring the 11 `backend/*.py` compat shims (0 production importers, 126 test refs) — would rewrite test files owned by B/C and break file-disjointness.
* `bridge/*` and `app/*` — explicitly out of scope.
* Layering inversion `stores/media_store.py → backend.chat_agent_js` — leaf import, does not transmit D changes into B.
* JS duplication and CI gates — after all four areas merge.

