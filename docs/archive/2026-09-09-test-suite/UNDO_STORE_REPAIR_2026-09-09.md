# Undo timeline persistence repair — stores/undo_store.py (+ siblings)

Date: 2026-09-09 · Root cause for the "undo partly removed / broken" report.

## The one fatal break

The global undo timeline (`UndoService` → `ConfigManager` → `stores/undo_store.py`)
could not run at all after the stores-split refactor: `UndoStore` had been
reduced to a three-method stub (`get` / `set` / `push`) with a constructor
signature that mis-assigned its file path, while `ConfigManager` — the facade
every undo write/read flows through — expects a richer surface. The mismatch
surfaced as `AttributeError: 'UndoStore' object has no attribute 'history'`
the moment any undo entry was pushed, which broke undo **and redo** across every
domain (stack, grid, people, labels, archive, DB connection).

Concretely `UndoStore` was broken against all of its callers:

* `ConfigManager` builds it with a **path string** positionally, but the store
  signature was `(atomic, path="config.json")` and did `atomic or ...`, so
  `self._atomic` became the path string (no `.get`/`.set`/`.save`).
* `ConfigManager` calls `history()` / `index()` / `save_state()` /
  `reload()` / `flush()`; none existed.
* Its on-disk format was nested `state.undo_history`, but `migration.py` and the
  store tests both use the flat `{"history": [...], "index": N}` shape.

## The fix

`stores/undo_store.py` was rewritten to the store's documented contract:

* file shape `{"history": [...], "index": N}` (matches the migration),
* accept **either** an `AtomicJsonStore` (small-store tests) **or** a path
  string (`ConfigManager`),
* small-store API kept: `get()` / `set()` / `push()`,
* ConfigManager surface added: `history()`, `index()`, `save_state(...)`,
  `reload()`, `flush()`, `save()`, `.dirty`, `.path`,
* every write caps the timeline at `MAX_STACK_HISTORY` and clamps the pointer to
  `[-1, len-1]` so an inconsistent `(history, index)` pair never reaches disk.

`stores/bookmark_store.py` and `stores/block_store.py` carried the **same**
constructor bug (`ConfigManager` passes a path into the `atomic` slot) and were
missing the `load()`/`save()` lifecycle `ConfigManager.load()/save()` call.
`BlockStore` also lacked the `all()` / `set_all()` custom-blocks view the facade
uses. Both were brought to the same convention (path-or-atomic constructor +
`load`/`save`/`reload`/`flush`) — additive and non-breaking.

## Proof

Undo-dedicated suites are green:

| suite | result |
|---|---|
| `tests/test_stores_small_stores.py TestUndoStore` (UND-01…07) | 8 OK |
| `tests/integration/services/test_services_undo.py` (UndoService) | 35 OK |
| `tests/test_people_undo.py` (people-list undo/redo) | 11 OK |
| `tests/test_archive_delete_undo.py` (archive undo) | 25 OK |

Plus dependent non-Qt suites that go through `ConfigManager`: `test_db_manager`
(42), `test_db_unified_world` (11), `test_db_migration` (8), `test_bridge_router`
(9), `test_services_people` (23), `test_services_history` (32) all pass.

## Not in scope (pre-existing, unrelated)

A few config-split tests now *run* where they used to crash in `ConfigManager`
construction, exposing older independent gaps that are **not** part of the undo
timeline and were **not** touched:

* `test_stores_split::test_bookmarks_dedup` — `BookmarkStore.add()` returns a
  truthy `Ok` for a duplicate, while the test expects falsy; `cdp_bridge` reads
  the same return as a boolean.
* `config_manager_contract::test_to_dict...` — `SettingsStore.data()` returns the
  stored overlay, not merged defaults, so `to_dict()` on a fresh dir lacks the
  default sections.
* `test_grid_persistence::...flush_before_shutdown` — expects a
  `_request_grid_flush` hook in `main.py` (unrelated to undo).
* `test_merge_undo_enabled` / `coordinator.py` — `get_action_class` is not
  defined in `services/run/coordinator.py`.
* `test_stores_small_stores` `TestSessionStore`/`TestSettingsStore` — stale tests
  that pass an `AtomicJsonStore` into path-based stores.
