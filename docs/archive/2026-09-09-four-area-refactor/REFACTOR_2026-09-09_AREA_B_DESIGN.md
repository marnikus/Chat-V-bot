# AREA B — `stores/` — design for the implementation

**Date:** 2026-09-09 · **Branch:** `arena/01a08849-chat-v-bot` (base `210ad03`)
**Implements:** `docs/archive/2026-09-09-four-area-refactor/REFACTOR_2026-09-09_FOUR_AREA_PLAN.md` §6.2 (AREA B) — B1 + B2
**Owns:** the 17 files of `stores/` + the 24 test files of §6.5 “AREA B”.
**Status:** design → tests → implementation (this document is written first).

---

## 0. Scope, ground rules, and how this was measured

Ground rules inherited from the plan (§6, §7.3) and honoured here:

* B edits **only** `stores/*.py` + its own test files (new B test files go to
  `tests/unit/stores/`); `bridge/*`, `core/*`, `app/*`, `main.py` are untouched;
* **frozen inside the package**: `stores/history_models.py`, `stores/jsonio.py`,
  `stores/migration.py` — read-only for B too;
* no symbol another area imports is renamed, moved or narrowed; every split is
  internal and the old public name stays and delegates;
* no import line outside `stores/` is edited (exit criterion 3).

AREA A is **not** merged in this checkout, so the two `sys.modules` poisoners
(`tests/integration/services/test_run_service_paths.py`, `tests/test_main_entry.py`)
and the stale `tests/test_stores_migration_rollback.py` are *ignored*, exactly as
the plan measures around them (§1). All numbers below are from
```
QT_QPA_PLATFORM=offscreen python -m pytest tests -q -p no:cacheprovider -rf \
  --ignore=tests/integration/services/test_run_service_paths.py \
  --ignore=tests/test_main_entry.py --ignore=tests/test_stores_migration_rollback.py \
  --deselect "tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine"
```
on Python 3.11.2 + PySide6 6.11.2 (headless, no stub libs needed).

### 0.1 What is already fixed in this checkout

The plan’s headline B numbers predate commit `210ad03`. Measured here:

| plan item | state in this checkout |
|---|---|
| P1-1 `UndoStore.history()/index()` | **done** (`undo_store.py:112`) |
| P1-2 `BookmarkStore.save()` | **done** (`bookmark_store.py:32`) |
| P1-3 small-store constructor + `save()` | **open** — 16 tests |
| P2-1 / P2-2 god-class decomposition | **open** — 4 files still > 400 SLOC |

### 0.2 Measured baseline (this checkout)

`52 failed / 1551 passed / 1 skipped / 1 xfailed`, 0 collection errors (after the
three AREA-A files are ignored). Grouped by the area that owns the fix:

| failing file | n | owner |
|---|---|---|
| `tests/test_stores_small_stores.py` | 16 | **B** (P1-3) |
| `tests/test_stores_split.py::FacadeCase::test_bookmarks_dedup` | 1 | **B** (Result truthiness) |
| `test_scroll_only_seek.py` 7 · `test_filter_purge.py` 7 · `test_merge_undo_enabled.py` 4 · `test_services_run.py` 4 · `test_live_status_and_order.py` 3 · `test_search_users.py` 2 · `test_repeat_loop.py` 2 · `test_db_manager_corrupt.py` 2 · `test_click_user_memory.py` 2 | 33 | C |
| `unit/backend/test_config_manager_contract.py` | 1 | D |
| `test_grid_persistence.py` | 1 | C |

**AREA B’s green target: 17 tests** (rows 1–2); the other 35 must not move.

`stores/` structural baseline (`tools/metrics/metrics.py` + `deep.py`):

| file | SLOC | class | mth | fields | LCOM4 | LCOM\* | worst CC |
|---|---|---|---|---|---|---|---|
| `stores/history_repo.py` | **1 070** | HistoryRepo | 44 | 33 | 2 | 0.94 | 34 `recover_media` |
| `stores/media_store.py` | **664** | MediaStore | 33 | 30 | 3 | 0.94 | 32 `_fetch_via_network` |
| `stores/history_db.py` | **605** | HistoryDB | 30 | 27 | 4 | 0.96 | 23 `_rebuild_legacy_messages` |
| `stores/label_store.py` | **472** | LabelStore | 38 | 19 | 7 | 0.93 | 28 `_normalized` |
| `stores/user_memory.py` | 230 | UserMemory | 21 | 5 | 2 | 0.78 | 14 `replace_all` |
| `stores/preset_store.py` | 204 | PresetStore | 20 | 8 | 1 | 0.80 | 11 `import_legacy` |

---

## 1. B1 — one contract for the seven config-file stores

### 1.1 The defect

Two constructor shapes exist today and neither accepts the other:

```python
BlockStore(atomic)      # ✓ stores/block_store.py:14   (atomic | path)
SessionStore(path)      # ✓ stores/session_store.py:38 (path only)
SessionStore(atomic)     # ✗ TypeError: stat: path should be … not AtomicJsonStore
```
`core/interfaces.py` (`SessionStoreProto`, `BookmarkStoreProto`, …) documents the
intended surface: `set(save=True, **updates)`, `add(url) -> bool`. The stores
disagree with it and with each other:

| store | ctor today | `load` | `reload` | `save` | `flush` | `path` | `dirty` | `set` save flag |
|---|---|---|---|---|---|---|---|---|
| `block_store` | atomic\|path | ✓ | ✓ | Result | Result | ✗ | ✗ | — |
| `bookmark_store` | atomic\|path | ✓ | ✓ | Result | Result | ✗ | ✗ | — |
| `session_store` | path | ✓ | ✗ | bool | ✗ | ✗ | ✓ | `save_now=` |
| `settings_store` | path | ✓ | ✗ | bool | ✗ | ✓ | ✓ | `save_now=` (kw-only) |
| `undo_store` | atomic\|path (path only used) | ✗ | ✓ | bool | ✓ | ✓ | ✓ | `save_now=` on `save_state` |
| `labels_file_store` | path | ✗ | ✓ | ✗ | bool | ✗ | ✓ | — |
| `preset_store` | config\|path | ✓ | ✗ | bool | ✗ | ✓ | ✓ | — |

### 1.2 The contract (target)

Every config-file store satisfies **all** of:

```python
Store(atomic: AtomicJsonStore | None = None, path: str = DEFAULT, *, data: dict | None = None)
Store(path)            # str in slot 1 stays legal  → ConfigManager untouched
Store(atomic)          # AtomicJsonStore in slot 1  → the store tests work
@property path -> str        # the file it owns
@property dirty -> bool
load() / reload() -> None    # re-read from disk (both names, one behaviour)
save(force: bool = False) -> bool
flush() -> bool                # save() when dirty
data() -> dict                 # deep copy of the live payload
```

Design decisions:

1. **`stores/atomic.py`** becomes the coercion point:
   `coerce_path(value)` (`AtomicJsonStore` → its path, `str`/`os.PathLike` → itself,
   anything else → `""`) and `AtomicJsonStore(atomic_or_path)` (an atomic may be
   cloned from another atomic). `AtomicJsonStore` gains `path`, `replace(data)`
   (swap the payload without saving) and a `makedirs` in `save()` so a store built
   from a path in a not-yet-created folder behaves like `jsonio.save_json`.
2. **`stores/json_store.py` (new)** holds `JsonFileStore`, the shared lifecycle:
   constructor coercion, `path`/`dirty`, `load`/`reload`/`save`/`flush`, and
   `set_*` save-flag handling (`save` **and** the legacy `save_now` keyword, the
   latter still used by `ConfigManager.set_state`). **The live payload stays
   `self._data` on the store** (not inside the atomic) because
   `tests/test_preset_store_unit.py:116` and friends mutate `_data` directly;
   the atomic (owned when a path was passed, borrowed when an atomic was passed)
   is only the loader/saver, so a borrowed atomic’s in-memory overlay is
   respected on `load()` and pushed through on `save()`.
3. **`save()` returns `bool`** everywhere (a *failed write* → `False`); the
   per-operation `Result` returns the tests pin (`named_*`, `add`, `remove`,
   `set_all`, `save_state`, `push`) keep returning `Result`.
4. **truthiness vs Result** — `bridge/cdp_bridge.py:87` does `if bookmarks.add(url):`
   to tell “added” from “already there”, and `tests/test_stores_split.py:184`
   pins `assertFalse` for the duplicate. A plain `Ok(None)` is always truthy and
   `core/result.py` is frozen, so **`stores/outcome.py` (new)** adds two
   truthiness-aware Result variants — `Outcome` (an `Ok[bool]` that is as truthy as
   its value) and `Refusal` (an `Err` that is falsy). `BookmarkStore.add/remove`
   return them; they are `Ok`/`Err` subclasses, so every existing `.is_ok` /
   `.is_err` / `.value` assertion still holds.

### 1.3 Per-file changes (B1)

| file | change | unblocks |
|---|---|---|
| `stores/atomic.py` | `coerce_path`, atomic-or-path ctor, `path`, `replace()`, `makedirs` on save, `clone()` | P1-3 |
| `stores/json_store.py` **new** | `JsonFileStore` base (lifecycle + coercion + save-flag handling) | P1-3 |
| `stores/outcome.py` **new** | `Outcome` / `Refusal` | `test_bookmarks_dedup` |
| `stores/session_store.py` | base + `set(save=True, save_now=None, **updates)` | 7 tests |
| `stores/settings_store.py` | base + `set(*keys, save=None, save_now=False)`; `get` default-walk moved to `stores/settings_defaults.py` **new** (`SETTINGS_DEFAULTS` re-exported) | 9 tests |
| `stores/labels_file_store.py` | base + `save()`, `data()/set_data()` keep the LABELS_DEFAULT shape coercion | — |
| `stores/undo_store.py` | base for load/save (clamp + `history/index/get/set/save_state/push` untouched) | — |
| `stores/preset_store.py` | base for load/save, `PresetStore(atomic\|path\|config)`, `reload()`, `flush()` | — |
| `stores/bookmark_store.py` | `path`/`dirty`/`reload`, `Outcome`/`Refusal` in `add`/`remove`, `all()` default seeding kept | 1 test |
| `stores/block_store.py` | `path`/`dirty`/`data()` added; keeps its `Result` surface (already conforms) | — |

`ConfigManager`, every bridge and every other area compile unchanged: they pass a
**path string**, which stays the first positional slot for all seven stores.

---

## 2. B2 — decomposing the six `stores/` god classes

### 2.1 The rule that makes an internal split safe here

Production code and tests **mutate store attributes** (`store.paused = True`,
`store.now = …`, `store._http_fetcher = fetch`, `db._repair_tables = broken`) and
call **private** helpers across the area border
(`backend/chat_parser.py:492` → `repo._last_ord(...)`).
So B2 extracts **behaviour, not state**:

1. state (`db`, `cdp`, `enabled`, `_dirs`, `_data`, `_memory`, `_scan_seq`, …)
   stays on the aggregate;
2. a collaborator is constructed with the aggregate and reads its attributes
   *at call time* — monkey-patching the store still changes behaviour;
3. the aggregate keeps every public **and** private method name the outside world
   uses, each one a one-line delegation;
4. any method a test replaces on an instance (`HistoryDB._repair_tables`) is
   called as `self._repair_tables()` inside the aggregate, never bypassed;
5. no call signature changes; no symbol is removed.

### 2.2 `stores/history_repo.py` → facade + 4 collaborators

| new module | class | takes (moved out of `HistoryRepo`) |
|---|---|---|
| `stores/history_repo_identity.py` | `ConversationIdentity` | `normalise_nick`, `ensure_person`, `get_person`, `get_person_by_id`, `_person_dict`, `possible_duplicates`, `rename_if_same_conversation`, `merge_persons` |
| `stores/history_repo_append.py` | `AppendPlanner` | `append`, `_prepend`, `align`/gap decisions, `_existing_dup_keys`, `_query_dup_keys`, `_slot_key`, `_slot_row_key`, `_empty_slot_rows`, `_take_empty_slot`, `_fill_slot`, `_ord_of`, `_media_id`, `_ui_record`, `_after_write`, `_touch_cursor`, `_recount`, `_last_ord`, `get_cursor`, `reset_cursor`, `mark_backfilled`, `record_gap`, `_record_gap` |
| `stores/history_repo_media.py` | `MediaRecovery` | `recover_media`, `_all_person_keys`, `has_repairable_media`, `_media_key`, the `media_scan_at` marker + `_scan_seq` counter |
| `stores/history_repo_lifecycle.py` | `PersonLifecycle` | `new_op_token`, `soft_delete_message`, `soft_delete_history`, `restore_deleted`, `_restore_rows`, `deleted_count`, `purge_deleted`, `delete_person`, `restore_person`, `_resequence` |

`stores/history_repo.py` keeps: the module docstring, `TAIL_FP_LIMIT`,
`align_batch`, `resolve_days`, `_minutes`, `_as_record` (all four are imported by
other areas/tests *from this module*), `HistoryRepo.__init__` and the 22 public +
5 private delegations. CC budget: the CC-34 `recover_media` body moves to
`MediaRecovery.repair` where the 169 lines are cut into `_scan_rows`, `_match`,
`_repair_row`, `_note_scan` (each ≤ CC 10, ≤ 40 LOC) — the same for the CC-33
`_signature_matches`/`_reattribute` split in `ConversationIdentity` and the CC-29
`append` split into `_plan` (alignment + gap) / `_collect` (dedupe + slots) /
`_commit` (counters + cursor).

**As delivered (B2).** `history_repo.py` is a 196-SLOC facade (was 1 070) and
each part is under the gate: `history_repo_append.py` 326,
`history_repo_lifecycle.py` 351, `history_repo_identity.py` 285,
`history_repo_media.py` 254. `HistoryRepo` keeps 22 public methods (§5 gate 2).
Three grouping decisions came out of the run rather than from the table:

* the static methods stay on `HistoryRepo` — `normalise_nick`, `_person_dict`,
  `_slot_key`, `_slot_row_key`, `_media_key`, `new_op_token`. A delegating
  instance stub loses `@staticmethod`, and `tests/test_repo_conflicts.py`
  (among others) calls `HistoryRepo.new_op_token()` on the class;
* `rename_if_same_conversation` went to `ConversationIdentity` (a rename *is*
  an identity question) and `_after_write` / `_recount` / `_touch_cursor` to
  `PersonLifecycle` (they write `persons.*` and the cursor). With the planner
  holding them, `history_repo_append.py` was 421 SLOC — over the gate;
* media recovery is `repo.media_recovery`, not `repo.media`: `MediaStore`
  already occupies `self.media` from `__init__`.

`align_batch`, `resolve_days`, `_minutes`, `_as_record` and `TAIL_FP_LIMIT`
moved *physically* to `history_repo_identity.py` (the writer's input
normalisation is the same question as "whose line is this") and the facade
re-exports them, so gate 3 — the 33 `from stores` imports outside the package —
did not move by one line.

The three long bodies are cut as planned. `recover_media` (CC 34, 169 lines)
became nine steps (`_broken_rows`, `_recover_row`, `_match_row`,
`_repair_stamped_row`, `_fill_empty_slot`, `_register`, `_retry_known_url`,
`_mark_scanned`, `_records_by_key`) sharing a module-level `_RecoveryPass`
record for the marker, the DOM index and the counters — the pass state was
nine locals threaded through one body, and a record is what made the split
possible without a second copy of the data. `append` (112) became `_align` /
`_write_rows` / `_insert_message` / `_collect` / `_report_unchanged`;
`_prepend` (82) reuses the same `_insert_message` on top of `_fresh_rows` +
`_plan_prepend`; `rename_if_same_conversation` (90) became `_same_conversation`
/ `_apply_rename` / `_reattribute`; `_ui_record` (CC 25) lost its media join to
`_ui_media`. Worst method in the four parts now: 54 lines (`append`) and
`maxcc` 18 (`_same_conversation`, kept as one boolean expression because it *is*
the evidence rule).

### 2.3 `stores/media_store.py` → facade + 3

| new module | class | takes |
|---|---|---|
| `stores/media_layout.py` | `MediaLayout` + module funcs | `slugify_nick`, `infer_kind`, `_extension`, `IMAGE_EXT`, `MIME_EXT`, `TRANSLIT`, `SAFE_CHARS`, `RESERVED`, `_now`, `folder_for`, `_person_dir`, `_marker`, `_write_marker`, `_free_name`, `_target_path`, `_day`, `NICK_MARKER` |
| `stores/media_fetch.py` | `MediaFetcher` | `_abs_url`, `_fetch_in_page`, `_fetch_via_python`, `_fetch_via_network`, `_finish_network_body`, `_twin`, `_fail`, `_skip`, `fetch_row` (was `_fetch_one`), `process_pending` |
| `stores/media_cache.py` | `MediaCachePolicy` | `cache_usage`, `evict_if_needed`, `_evict`, `clear_cache`, `retry_failed`, `retry_failed_uncached`, `requeue` |

`stores/media_store.py` keeps `MediaStore` (registry: `register`, `get`,
`get_by_url`, `_as_id`, `download_one`, `path_for`, `clipboard_payload`,
`migrate_layout`) and **re-exports** `slugify_nick`, `infer_kind`, `IMAGE_EXT`,
`MIME_EXT` (`backend/media_store.py:4` and three B test files import
`slugify_nick` from this module; the shim is frozen). `_fetch_one` and
`_free_name` stay as delegations (a B test calls `store._free_name`).

**As delivered (B2).** `media_store.py` 205 SLOC, `media_fetch.py` 394,
`media_layout.py` 150, `media_cache.py` 105. Differences from the table, all
three of them forced by the ceilings or by a pinned name:

* `_fetch_one` kept its name (a B test and `process_pending` call it) and was
  split into `_download` (the tier chain + the error join) and `_file_bytes`
  (dedupe, write, stamp) instead of being renamed `fetch_row`;
* the row registry stayed on `MediaStore` — `register`, `get`, `get_by_url`,
  `_as_id`, `_fail`, `_skip`, `path_for`, `clipboard_payload`, `download_one` —
  because all four parts need it; `_twin` went to `MediaCachePolicy` (reusing a
  twin is a cache decision, not a download decision) and `migrate_layout` with
  it, while `retry_failed`, `retry_failed_uncached`, `requeue`,
  `process_pending` and the whole fetch chain went to `MediaFetcher`;
* `NICK_MARKER` stays a class attribute of `MediaStore` (the layout reads it
  through the owner) because `backend/media_store.py` and a test take it from
  the class.

`_fetch_via_network` (CC 32, 88 lines) is now 26 lines plus a module-level
`_NetworkWatch` (the four CDP event handlers, the remembered request id and the
once-only future) and a `_cache_disabled` helper. The single
`stores → backend` edge moved with it: `media_fetch.py` imports
`backend.chat_agent_js` and `media_store.py` no longer imports `backend` at all
— the layering test now names `media_fetch.py` as *the* documented edge, which
is the same one inversion, one file deeper. `tests/unit/stores/
test_media_network_watch.py` pins the watcher (redirect keeps the id, `?query`
and `#fragment` are stripped, one body read per future, unresolved failures
ignored, handlers detached) — the part that used to be untestable without a
browser is now the part under test.

### 2.4 `stores/history_db.py` → facade + 2

| new module | contents |
|---|---|
| `stores/history_schema.py` | `SCHEMA_VERSION`, `TABLE_COLUMNS`, `TABLE_CONSTRAINTS`, `LEGACY_MESSAGES_CONSTRAINT`, `TABLE_ORDER`, `_create_table_sql`, `TABLE_SQL`, `INDEX_SQL`, `SCHEMA`, `FTS_SCHEMA`, `_version_tuple` |
| `stores/history_schema_repair.py` | `SchemaMigrator`: `_table_columns`, `_repair_tables`, `_rebuild_legacy_messages`, `_has_legacy_messages_constraint`, `_rebuild_messages_constraint`, `_person_for_nick`, `_count_rows`, `db_fetch_legacy`, `_read_version`, `_verify_schema`, `_migrate_dup_keys`, `_try_fts` |

`stores/history_db.py` keeps `HistoryDB` (lifecycle + query helpers + meta +
`file_size`) and re-exports every schema symbol
(`backend/history_db.py` imports `HistoryDB, SCHEMA_VERSION, TABLE_COLUMNS`;
`tests/test_history_db_integrity.py` imports `_version_tuple`; `LATE_COLUMNS` and
`_add_missing_columns` stay as the compatibility surface). `init()` keeps calling
`self._repair_tables()` / `self._verify_schema()` on the instance.

**As delivered (B2).** `history_db.py` 204 SLOC + `history_schema.py` 192 (the
tables, verbatim, zero logic) + `history_schema_repair.py` 352
(`SchemaMigrator`). Both over-ceiling bodies were cut:
`_rebuild_legacy_messages` (83) into `_drop_legacy_indexes` /
`_copy_legacy_rows` / `_stamp_legacy_identity` / `_finish_legacy_rebuild`, and
`_migrate_dup_keys` (62) into `_backfill_dup_keys` / `_drop_duplicate_rows` /
`_resequence_all`. `HistoryDB` keeps `init()`, the query helpers, `file_size`,
the re-exports and — deliberately — `_repair_tables` / `_table_columns` as
*instance* attributes pointing at the migrator, because another area's test
monkeypatches them on the instance.

### 2.5 `stores/label_store.py` → facade + 4

| new module | class | takes |
|---|---|---|
| `stores/label_rules.py` | (module) | `PALETTE`, `DEFAULT_COLOR`, `MAX_NAME`, `FILTER_KEY`, `_HEX`, `normalize_color`, `normalize_name`, `normalize_nick`, `normalize_id` |
| `stores/label_state.py` | `LabelState` | `SECTION`, `_initial_state`, `_memory_state`, `_raw_config`, `_raw`, `_write`, `_save`, `_normalized` |
| `stores/label_world.py` | `LabelWorldSync` | `db`, `is_bound`, `set_scheduler`, `load_from_db`, `flush_to_db`, `_schedule_flush`, `_guarded_flush` |
| `stores/label_assignments.py` | `LabelAssignments` | `defs`, `by_id`, `by_name`, `assignments`, `ids_for`, `labels_for`, `labels_map`, `state`, `create`, `update`, `delete`, `assign`, `unassign`, `set_for`, `forget`, `snapshot`, `restore` |
| `stores/label_filter.py` | `LabelFilter` | `filter`, `set_filter`, `clear_filter`, `filter_active`, `allows`, `reject_reason` |

`stores/label_store.py` keeps `LabelStore` — the object `bridge/label_bridge.py`,
`backend/label_store.py` (frozen shim, re-exports `PALETTE`, `DEFAULT_COLOR`,
`MAX_NAME`, `normalize_color`, `FILTER_KEY`) and `tests/test_person_labels.py`
construct — with `__init__(config, db=None, scheduler=None)` unchanged and every
method a one-line delegation. `_normalized` (CC 28) becomes `LabelState.normalize`
split into `_defs`, `_assign`, `_filter` (each ≤ CC 8); the three share the same
`seen_ids`/`seen_names` pass by returning a small `_DefIndex` record.

**As delivered (B2).** `label_store.py` 210 SLOC + `label_assignments.py` 191,
`label_state.py` 102, `label_world.py` 112, `label_filter.py` 56,
`label_rules.py` 44. Two differences:

* there is no `label_definitions.py`. The definition *reads* are four lines of
  `_raw()` unwrapping each, so `defs` / `by_id` / `by_name` live with the
  writes in `LabelAssignments` — one module that owns "the `defs` list" instead
  of two that share it;
* the parts sit on **private** attributes (`_state`, `_world`, `_assignments`,
  `_filter`), unlike the other facades: `LabelStore` already has public
  `state()`, `assignments()` and `filter()` methods, and an instance attribute
  with the same name would shadow them (`store.assignments()` would raise
  `TypeError: 'LabelAssignments' object is not callable`).
* `_normalized` kept its name on `LabelState` — a B test reaches
  `store._normalized` — and was **not** cut into `_defs`/`_assign`/`_filter`:
  it is 50 lines / CC 24, i.e. inside the ceiling, and the three passes would
  have had to share a `_DefIndex` record to stay correct, which is more
  machinery than the readability gain.

`stores/label_rules.py` is re-exported by the facade
(`PALETTE, DEFAULT_COLOR, MAX_NAME, FILTER_KEY, normalize_*`) because
`backend/label_store.py` — a frozen shim — imports those names from
`stores.label_store`; see §6 item 9 for how the API gate now recognises a
deliberate re-export.

### 2.6 Small ones

| file | change |
|---|---|
| `stores/user_memory.py` | `stores/user_query.py` **new**: `UserQuery` (`get_queue`, `get_all`, `get_stats`, `get_user`, `count_unmessaged`, `_row`, `_SELECT`); `UserMemory` keeps the connection, the writes and the delegations |
| `stores/preset_store.py` | `stores/preset_migration.py` **new**: `PresetMigration` (`from_sqlite`, `_read_stacks`, `_read_templates`, `_config_dir_of`); `PresetStore.import_legacy` delegates |

**As delivered (B2).** `user_memory.py` 216 + `user_query.py` 61
(`UserQuery`: `get_queue`, `get_all`, `get_stats`, `get_user`,
`count_unmessaged`, `_row`, `_SELECT`); `preset_store.py` 185 +
`preset_migration.py` 72 (`PresetMigration`: `from_sqlite`, `_read_stacks`,
`_read_templates`, `_config_dir_of`). Both as designed. `UserMemory._db` and
`PresetStore._data` stay on the aggregate (other areas' tests assign to them).

---

## 3. Public surface that must survive (checklist the tests pin)

| imported by | from `stores/` |
|---|---|
| `backend/config_manager.py` (D) | `BlockStore`, `BookmarkStore`, `DEFAULT_BOOKMARKS`, `SessionStore`, `SettingsStore`, `SETTINGS_DEFAULTS`, `UndoStore`, `LabelsFileStore`, `LABELS_DEFAULT`, `PresetStore`, `jsonio.config_dir_for`, `migration.migrate_legacy_config` |
| `backend/{history_db,history_repo,history_models,label_store,media_store,preset_store,user_memory}.py` — frozen shims | `HistoryDB`, `SCHEMA_VERSION`, `TABLE_COLUMNS`, `HistoryRepo`, `align_batch`, `LabelStore`, `PALETTE`, `DEFAULT_COLOR`, `MAX_NAME`, `normalize_color`, `FILTER_KEY`, `MediaStore`, `slugify_nick`, `PresetStore`, `UserMemory`, `UserRecord`, `_SCHEMA` |
| `backend/chat_parser.py` (D) | `HistoryRepo`, `align_batch`, `repo._last_ord`, `resolve_days` |
| `services/{history/__init__,history/export,collector_service,run/*}` (C) | `HistoryRepo`, `HistoryDB`, `MediaStore(cache_dir=…, max_file_mb=…, max_cache_mb=…, enabled=…)`, `UserMemory`, `UserRecord` |
| `bridge/{router,context}.py`, `app/bootstrap.py` | `PresetStore(config=…)`, `LabelStore`, `UserMemory` |
| `core/interfaces.py` Protocols | `get/set/section`, `add/remove/all`, `save_stack/load_stack/…`, `db_path`, `get_all/get_queue/get_stats` |

`stores/history_models.py`, `stores/jsonio.py`, `stores/migration.py` are frozen
and already < 400 SLOC, so they stay as they are.

**How a re-export is proven to still be surface.** Each split facade names its
promise in `__all__` (`stores/media_store.py`, `stores/label_store.py`,
`stores/history_repo.py`), and `tools/metrics/stores_api.py` records a module's
functions and classes when they are *defined there* **or** listed in its
`__all__`. Without that, moving `normalize_nick` to `stores/label_rules.py`
looked like removing `stores.label_store.normalize_nick` — the frozen
`backend/label_store.py` shim would still have worked while the gate screamed,
which is the wrong way round for both reader and tool.

---

## 4. Test plan (written **before** the refactor)

New directory `tests/unit/stores/` (owned by B; A owns `tests/unit/app/`):

| new file | pins | why it exists |
|---|---|---|
| `test_stores_contract.py` | the §1.2 table for all seven config stores: `atomic\|path` in either slot, `path/dirty/load/reload/save/flush/data`, `save()` returns `bool`, `load is reload`, the `save`/`save_now` aliases, and “a path store and an atomic store over the same file see each other” | the unified contract, so a future store cannot skip it |
| `test_stores_public_api.py` | **freezes** every public + the cross-area-used private name of all 17 `stores` modules (importable names, method presence, `inspect.signature` string of every public method) | the B2 split must not rename or re-signature anything (plan §7.3 rule 1) |
| `test_stores_delegation.py` | for each extracted collaborator: the aggregate **is** composed of it, the aggregate method and the collaborator method return the same thing, and **mutating an aggregate attribute is visible to the collaborator** (`store.paused`, `store.now`, `store._http_fetcher`, `store.cache_dir`) | the §2.1 rule, i.e. the split is real but behaviour-preserving |
| `test_stores_outcome.py` | `Outcome`/`Refusal` truthiness + `is_ok`/`is_err`/`.value`; `BookmarkStore.add` → `Err` on duplicate and on empty, `Ok(True)`/`Ok(False)` on `remove` | §1.2 decision 4 |
| `test_history_repo_split.py` | characterization of the four `HistoryRepo` collaborators against a real SQLite file (identity, append plan, media scan, lifecycle), including `rename_if_same_conversation`'s four refusal gates and `recover_media`'s marker/idempotence rules | the CC-34/33/29 bodies move; the facade must behave identically |
| `test_media_store_split.py` | `MediaLayout` (person-folder claim, `_free_name` sequencing, marker), `MediaFetcher` (3-strategy order, error join, cap), `MediaCachePolicy` (LRU + requeue counters) through the facade | same |
| `test_label_store_split.py` | `LabelState.normalize` edges (orphan ids, dup names, hostile colours), `LabelFilter.allows/reject_reason` matrix, `LabelWorldSync` round-trip through a real `HistoryDB` | same |
| `test_history_db_split.py` | `SchemaMigrator` (widening, legacy rebuild attribution, dup-key backfill + dedupe), re-export parity `stores.history_db.X is stores.history_schema.X` | same |
| `test_user_memory_query_split.py` | `UserQuery` result shapes + `UserMemory` write path on one connection | same |

Existing B-owned suites stay untouched and are the regression net:
`test_stores_small_stores.py`, `test_stores_atomic_jsonio.py`,
`test_stores_split.py`, `test_history_repo*.py`, `test_history_db_*.py`,
`test_media_*.py`, `test_label_store_orphans.py`, `test_person_labels.py`,
`test_preset_store_*.py`, `test_user_memory_*.py`, `test_history_models_edges.py`,
`test_db_schema_migration.py`, `unit/backend/test_history_models.py`,
`unit/backend/test_label_store_dbmode.py`.

Order of work: **tests first** (they must pass against the pre-split code where
they are characterization tests, and fail only on the three §1.1 gaps), then B1,
then B2 file by file, running `tests/unit/stores` + the B suite + the full suite
after every file.

---

## 4.1 Test files as delivered (status when B1 was committed)

| file | what it pins | state after B1 |
|---|---|---|
| `tests/unit/stores/test_stores_contract.py` | the seven-store contract: construction, lifecycle, dirty/flush, corrupt payloads, deep copies (29 cases, 100 subtests) | green |
| `tests/unit/stores/test_stores_public_api.py` | the frozen surface vs `api_baseline_pre_b1.json` + the §3 surviving-name checklist + the 33-import gate | green |
| `tests/unit/stores/test_stores_outcome.py` | `Outcome`/`Refusal` truthiness and the bookmark/bridge contract | green |
| `tests/unit/stores/test_stores_split_behaviour.py` | state liveness, reachable privates, one scenario per collaborator (23 cases, 74 subtests) | green after B2 — nothing skips, and `PresetStore._data` / `store._free_name` / `db._repair_tables` are still live |
| `tests/unit/stores/test_stores_structure.py` | the B2 gates: ≤400 SLOC, facade public-method counts, 60-line method ceiling, layering, composition | green after B2 (it *was* the to-do list; every part it demands exists) |
| `tests/unit/stores/test_media_network_watch.py` | the `_NetworkWatch` extraction: id matching, redirect MIME, once-only future, detach, tier chain | green (new in B2 — 12 cases, no browser needed) |

Status after B2: `tests/unit/stores` is **76 passed, 2 skipped, 700 subtests**,
and the wider B net (`tests/test_history_*.py tests/test_media_*.py
tests/test_stores_*.py tests/test_person_labels.py tests/test_label_store_orphans.py`)
is **542 passed, 2 skipped, 700 subtests**.
| `tools/metrics/stores_api.py` | dumps/diffs the surface; `--write` after a deliberate change | helper |

## 5. Exit criteria (§6.2 of the plan) and how each is checked

| # | criterion | command | target | **result after B2** |
|---|---|---|---|---|
| 1 | the 17 B-owned reds green, nothing else broken | full suite in a scratch worktree of the pre-B commit, same interpreter, and diffed (`comm -13`) | 0 new red | **0 regressions**, 17 fixed: 325 F / 1 035 P → 308 F / 1 129 P (+94 new B tests); 14 collection errors in *both* runs are this sandbox's missing `libGL.so.1` (PySide6 6.11), not the code |
| 2 | no `stores/` file > 400 SLOC, `HistoryRepo` < 30 public methods | `python tools/metrics/metrics.py` | max SLOC ≤ 400 (baseline 1 070) | **394** (`media_fetch.py`); `HistoryRepo` 22, `MediaStore` 15, `LabelStore` 25, `HistoryDB` 14 public methods; longest method in a split file 54 lines (≤ 60), worst CC 18 (was 34) |
| 3 | no other area edits an import | `grep -rn "from stores" services backend actions bridge app \| wc -l` | **33**, unchanged | **33** ✓ |
| 4 | stores coverage | `coverage run --branch --source=stores -m pytest tests` | ≥ 90 % line, ≥ 80 % branch | **91.4 % line, 82.7 % branch** (before B2: 91.7 / 85.5 — the branch dip is the ~110 one-line delegations, which have only one side to cover; `media_fetch.py` at 77 % line is the honest weak spot: real CDP/`aiohttp` paths) |
| 5 | public API parity | `tests/unit/stores/test_stores_public_api.py` | green | green: `diff(api_baseline_pre_b1, live, WIDENED) == []`, `api_baseline.json` **not** regenerated by B2 |
| 6 | frozen files untouched | `git diff --name-only \| grep -E '^(core\|bridge\|app)/\|^main\.py$\|^stores/(history_models\|jsonio\|migration)\.py$'` | empty | empty ✓ |

The gate commands, in the order that catches a mistake fastest:

```bash
cd /home/user/Chat-V-bot
python -m pyflakes stores/*.py                     # imports that moved wrongly
QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/stores \
    tests/test_history_repo_conflicts.py tests/test_history_db_integrity.py \
    tests/test_media_store_limits.py tests/test_person_labels.py \
    tests/test_stores_split.py -q                  # the B net
python tools/metrics/stores_api.py                 # surface diff (CLI view)
python tools/metrics/metrics.py                    # SLOC / CC table
grep -rn "from stores" services backend actions bridge app | wc -l   # 33
```

---

## 6. Deviations from the plan (and why)

1. **Plan §4.2 rows 1–2 (160 tests) are already green here** — `UndoStore.history/
   index` and `BookmarkStore.save` exist in this checkout. B1 therefore reduces to
   the constructor/`save()` contract (P1-3) + the bookmark truthiness.
2. **Gate 6 (byte-identical public signatures) cannot hold for `__init__`.**
   P1-3 *is* a constructor change; the widening keeps every existing call form
   valid (`Store(path)`, `Store(atomic)`, `PresetStore(config=…)`,
   `LabelStore(config, db, scheduler)`). The gate is enforced as an explicit
   allowlist instead of a blanket "signatures are frozen":
   `tests/unit/stores/api_baseline_pre_b1.json` (the surface AREA B found) is
   compared with the live one, and only the names in `WIDENED` may differ —
   each of which must still accept every parameter it used to have.
   `api_baseline.json` (the surface after B1) is what B2 may only add to.
3. **Collaborators borrow the aggregate instead of owning state** (§2.1) because
   production and other areas’ tests poke store attributes and private methods;
   moving the state would be a cross-area behavioural change, which B1–B2 forbid.
4. `test_stores_split.py::test_bookmarks_dedup` is fixed on the **production**
   side (`Outcome`/`Refusal`), not by editing the test — the test encodes what
   `core/interfaces.py:BookmarkStoreProto.add(url) -> bool` promises and what
   `bridge/cdp_bridge.py:87` needs.
5. **The `settings_defaults.py` extraction is dropped.** It was proposed to keep
   `settings_store.py` under the 400-SLOC gate; the file is 141 SLOC, so the move
   would only churn `backend/config_manager.py:30` (a frozen consumer that imports
   `SETTINGS_DEFAULTS` from the store). Defaults stay where they are.

6. **`SettingsStore.set` keeps its deferred default** (memory first, `save()`
   persists). `tests/test_stores_small_stores.py::…::test_settings_survive_a_reopen`
   (SET-08, red before B1 because of the constructor, spec-first) reads an
   auto-saving `set`; that default would have made `ConfigManager.set(…)` write
   `settings.json` halfway through a facade call, and
   `tests/integration/services/test_services_db_gaps.py::ConfigOnlyCase::
   test_active_path_default` — a file AREA B does not own — pins the opposite.
   SET-08 is therefore corrected to the real contract (memory → `save()` → lands)
   and a new SET-08b pins the `save=True` flag. `SessionStore.set` keeps its
   historical auto-save default, so both stores accept `save=` *and* `save_now=`
   with their own pre-split default.

7. **`BlockStore`/`BookmarkStore` answer `bool` from `save()`/`flush()`** (they
   returned the raw `AtomicJsonStore` `Result`) because `ConfigManager.save()`
   calls all seven stores and the lifecycle answer is "does the file match
   memory?". The per-operation calls (`named_*`, `set_all`, `save_custom_block`)
   keep returning `Result`s, and the new `stores/outcome.py` pair keeps the
   truthiness promise of deviation 4.

8. **`JsonFileStore` construction reads the file, never the borrowed handle's
   memory.** An unsaved `AtomicJsonStore.replace()` is somebody else's pending
   write; `reload()` is what brings it in (B1-03 in `test_stores_contract.py`).
   A store also keeps `self._path` as the live pointer, so re-pointing a store
   (`tests/test_stores_split.py:147` does exactly that to prove one file cannot
   damage another) keeps working through the split handle indirection.

9. **A facade says "this re-export is still mine" with `__all__`.** The API gate
   used to record only what a module *defines*, so moving `normalize_nick` to
   `stores/label_rules.py` read as `stores.label_store.normalize_nick removed`
   even though `backend/label_store.py` kept importing it fine. `stores_api.py`
   now also records names the module lists in `__all__`, and the three facades
   that re-export (`label_store`, `media_store`, `history_repo`) say so. The
   `# noqa: F401` marks stay: `pyflakes` cannot tell a re-export from debris
   either, and an automated "remove unused imports" pass over the split files
   is exactly what broke two of them mid-B2 (it deleted the re-export blocks).
   Every B2 move is therefore replayed from the pristine pre-split file rather
   than patched in place — which is why a damaged header cost a re-run, not a
   reconstruction.
10. **The facade-growth gate compares surfaces, not constants.**
    `test_public_method_counts` used to pin "≤ 15 public methods for
    `PresetStore`", and B1 legitimately gave it `data`/`flush`/`reload` — so the
    gate now reads the pre-B1 baseline and allows exactly the lifecycle names
    B1 promises (`data`, `dirty`, `flush`, `load`, `path`, `reload`, `save`),
    failing on *any* other addition. A split that quietly grew a facade is still
    caught; a contract that was agreed in B1 is not.
11. **The `stores → backend` inversion is neither fixed nor grown.** Plan §3.5
    defers it to the cleanup PR; B2 moved the one import (`chat_agent_js`) from
    `media_store.py` to `media_fetch.py` and `media_store.py` no longer touches
    `backend` at all. `test_stores_structure.ALLOWED_UPWARD_EDGES` names the new
    owner so a second edge cannot appear unnoticed.
