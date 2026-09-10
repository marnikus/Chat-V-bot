# `stores/` — Persistence Layer: test design (spec-first)

Date: 2026-09-09
Scope: section **F** of the coverage plan — `stores/history_repo.py`,
`history_db.py`, `history_models.py`, `media_store.py`, `label_store.py`,
`block_store.py`, `bookmark_store.py`, `preset_store.py`, `session_store.py`,
`settings_store.py`, `undo_store.py`, `user_memory.py`, `jsonio.py`,
`migration.py` — plus the two real files the table omits: `atomic.py`
(the base every small store stands on) and `labels_file_store.py`
(the offline labels fallback).

## 0. Method (why this document exists)

Every case below was written **from the contract only** — the module
docstring, the class docstring, the public signatures, and the design-target
column of the coverage table — *before* any implementation body was read.
Each row therefore states the path the code **should** take. A test that only
reproduces the code it sits next to can never fail, so it can never find a
bug; a test written from the contract fails exactly where the code and its
promise disagree.

Where a test failed on first run, the row is marked 🔴 and the mismatch is
described in §15 (Bug ledger) instead of the expectation being softened to
match the code.

Contract sources used, per module:

| Module | Contract source |
|---|---|
| `jsonio.py` | module docstring ("writes to `<file>.tmp`, flushes, then `os.replace`s"; "a reader either sees the whole previous file or the whole new one"), `load_json` docstring ("on missing file or bad JSON return `default` (a copy)"), `save_json` docstring ("Returns False (and logs) on failure") |
| `atomic.py` | module docstring ("write .tmp, rename"), class docstring ("load / atomic save of a JSON file") |
| `block_store.py` | module docstring ("stack_presets, template_presets, custom_blocks") |
| `bookmark_store.py` | module docstring ("url_presets list") |
| `session_store.py` | module docstring ("last-session state (state.*)") |
| `settings_store.py` | module docstring ("chrome, scroll, delays, ui, history, collector slices"), class docstring ("Pure I/O for global settings (no presets, no session)") |
| `undo_store.py` | module docstring ("global undo history (state.undo_history + index)") |
| `preset_store.py` | module docstring ("Owns exactly one file", "cached per file path", "one-time import keeps both legacy sources working") |
| `labels_file_store.py` | module docstring ("One JSON file holding the legacy labels section shape", "migration source" + "offline fallback") |
| `label_store.py` | `normalize_*` signatures, CRUD + filter + snapshot/restore + load_from_db/flush_to_db signatures |
| `media_store.py` | module docstring ("the database keeps the URL plus a hash; the BYTES live on disk under a size cap"), `slugify_nick` docstring ("Latin, filesystem-safe"; `Хорошо Все` → `Horosho_Vse`), `_free_name` docstring ("`YYYY-MM-DD_007.gif` — short, dated, sorted, unique"), `register` docstring ("Returns its id (existing rows are reused)"), `evict_if_needed` docstring ("Drop least-recently-used files until we are under the cap"), `requeue`/`retry_failed_uncached`/`download_one` docstrings |
| `history_models.py` | module docstring ("hash is defined over UTF-16 code units, exactly what JavaScript's `charCodeAt()` yields"), `fingerprint` docstring ("Stable identity"; "`occ` distinguishes literally identical lines"), `dedupe_key` docstring ("identified by the fields a human can see … timestamp + content"), `MessageRecord` docstring, `_int_or` docstring ("must still become a usable record, not a dropped one") |
| `history_db.py` | module docstring ("all-time archive"; "Nothing that filters, purges or forgets a person … may touch this store"), class docstring ("Thin async wrapper around the archive's SQLite file"), `fetchall` docstring ("Rows as plain tuples"), `file_size` docstring ("the file AND its WAL siblings"), `_verify_schema` docstring ("Raises one clear error instead of … `no such column`"), `_version_tuple` docstring ("Numeric compare … `10` > `9`") |
| `history_repo.py` | module docstring ("append-only and idempotent"; "replaying a batch … must never duplicate"), `align_batch` docstring ("the LAST place in the batch where our stored suffix occurs"), `resolve_days` docstring ("walking the list BACKWARDS"; "the newest line is today (or yesterday if its clock time is still ahead of now)"), `reset_cursor` docstring ("the archive itself is untouched"), `mark_backfilled` docstring ("Once set … do NOT spend another full history check") |
| `user_memory.py` | module docstring ("SQLite-backed user memory: discovery, status tracking, CRUD"), `db_path` docstring ("the file the queue currently lives in"), `switch_db` docstring ("a queue that kept its old file …" — must move), `count_unmessaged` docstring ("A single COUNT"), `delete_user(s)` docstrings ("Returns True/number removed"), `set_messaged` docstring, `reset_messaged` docstring ("clear last_messaged alongside the flag"), `replace_all` docstring ("wipe the table and insert the given rows") |
| `migration.py` | module docstring ("Idempotent: if the new layout already exists, nothing is overwritten"; "backed up to config.json.bak.\<timestamp\> before mutation"), `migrate` docstring ("Returns `{\"migrated\": bool, \"backup\": str \| None, \"added\": list[str]}`") |

Notation: **expected path** = the observable outcome the contract demands
(return value, file content, row content, raised error). Existing suites this
design must NOT duplicate are listed in §14.

Test-file map (new files only):

| New file | Covers |
|---|---|
| `tests/test_stores_atomic_jsonio.py` | `jsonio.py`, `atomic.py` |
| `tests/test_stores_small_stores.py` | `block_store.py`, `bookmark_store.py`, `session_store.py`, `settings_store.py`, `undo_store.py`, `labels_file_store.py` |
| `tests/test_stores_migration_rollback.py` | `migration.py` |
| `tests/test_label_store_orphans.py` | `label_store.py` (orphan / import-export / hostile) |
| `tests/test_media_store_limits.py` | `media_store.py` (path / duplicate / limit / recovery edges) |
| `tests/test_history_repo_conflicts.py` | `history_repo.py` + `align_batch`/`resolve_days` (CRUD / version-conflict / lifecycle edges) |
| `tests/test_history_db_integrity.py` | `history_db.py` (schema / query / lifecycle edges) |
| `tests/test_history_models_edges.py` | `history_models.py` (validation / result-object edges) |
| `tests/test_user_memory_links.py` | `user_memory.py` (memory / link / cycle edges) |
| `tests/test_preset_store_defaults.py` | `preset_store.py` (named-section / hostile-name edges) |

---

## 1. `stores/jsonio.py` — P2 (target: load/save, corrupt)

| ID | Case | Expected path |
|---|---|---|
| 🔴 JIO-01 | `load_json(missing, default={"a":1})` | returns `{"a":1}`; mutating the result then re-loading still gives `{"a":1}` (documented "a copy") |
| 🔴 JIO-02 | `load_json(corrupt, default=[1,2])` | returns `[1,2]` (a copy), never raises |
| JIO-03 | `load_json(dir_path, default="x")` | returns `"x"`, never raises (a directory is not valid JSON) |
| JIO-04 | `load_json(valid)` with no default | returns the parsed content |
| JIO-05 | `load_json` on `""` / whitespace-only file | returns default, never raises |
| JIO-06 | `save_json` then `load_json` round-trip | byte-identical structure; no `.tmp` file left behind |
| JIO-07 | `save_json` over an existing file | readers see old-or-new only: after success the file parses and equals new data (atomic replace) |
| 🔴 JIO-08 | `save_json` to an unwritable path (missing parent dir) | returns `False`, never raises |
| 🔴 JIO-09 | `save_json` of a non-serialisable object (`{1,2}`) | returns `False`, and the previous good file is untouched (failed save must not truncate the target) |
| JIO-10 | `save_json` with `data=None` | writes valid JSON `null`; reload gives `None` |
| JIO-11 | `config_dir_for("/a/b/config.json")` | `"/a/b/config"` — sibling dir of the legacy file |
| JIO-12 | `config_dir_for("config.json")` (bare name) | `"config"` in cwd, never `""` or `"."`-relative garbage |

## 2. `stores/atomic.py` — P2 (target: load/save, corrupt — the base)

| ID | Case | Expected path |
|---|---|---|
| ATM-01 | fresh path (no file) → `load()` | empty store; `data()` is `{}` |
| ATM-02 | corrupt file → `load()` | empty store, never raises (same promise as `load_json`) |
| ATM-03 | `set("a","b",1)` then `data()` | `{"a":{"b":1}}`; sibling keys survive a second `set("a","c",2)` (deep merge) |
| ATM-04 | `get("a","b")` / `get("a","missing",default=5)` | `1` / `5`; missing intermediate key never raises `KeyError` |
| ATM-05 | `get_copy("a")` then mutate the copy | store content unchanged (deep copy) |
| 🔴 ATM-06 | `set()` with no value (arity abuse) | loud error (`TypeError`/`ValueError`), never silent corruption; store still saves valid JSON afterwards |
| ATM-07 | `save()` then a NEW `AtomicJsonStore(same path)` + `load()` | identical `data()` (persist round-trip) |
| ATM-08 | `save()` failure (unwritable path) | does not raise out of the store; in-memory `data()` is intact |
| 🔴 ATM-09 | `set()` with a non-string key | loud error or stringified key — but the file must still be valid JSON after `save()` |

## 3. `stores/block_store.py` — P2 (target: block, persist)

| ID | Case | Expected path |
|---|---|---|
| BLK-01 | `named_set/get/delete` round-trip in `stack_presets` | set → get returns value; delete → get returns default |
| BLK-02 | `named_all(unknown_section)` | `{}` (or empty), never `KeyError` |
| BLK-03 | `named_get` on an unknown name | the passed `default`, never `KeyError` |
| BLK-04 | sections are isolated: same name in `stack_presets` and `template_presets` | two independent values |
| 🔴 BLK-05 | `save_custom_block(name, block)` then `custom_blocks()` | block present with its content |
| BLK-06 | overwrite a custom block with the same name | in-place replacement, listed once |
| BLK-07 | `delete_custom_block(unknown)` | no raise |
| BLK-08 | persist: new `BlockStore` over the same file | named sections + custom blocks survive a reopen |
| BLK-09 | hostile names: `""`, `"  "`, `"a/b"`, `"../../x"`, 500-char, emoji/Cyrillic | stored and retrievable verbatim (a name is a dict key, not a path); never a file escape, never a crash |
| BLK-10 | `save_custom_block` with a non-dict block (`None`, list, str) | loud error or stored verbatim — but `custom_blocks()` + reopen must never corrupt the file |

## 4. `stores/bookmark_store.py` — P2 (target: bookmark, list)

| ID | Case | Expected path |
|---|---|---|
| BMK-01 | `add(url)` then `all()` | url present exactly once |
| BMK-02 | `add` the same url twice | listed once (dedup — existing suite asserts this; our test pins ordering: first position kept) |
| 🔴 BMK-03 | `remove(unknown)` | no raise, list unchanged |
| BMK-04 | `set_all([...])` replaces wholesale | exact list equality, order preserved |
| BMK-05 | `set_all([])` | empty list |
| BMK-06 | hostile urls: `""`, whitespace, 2000-char, unicode, `javascript:…` | stored verbatim or refused with no crash; `all()` round-trips through a reopen |
| BMK-07 | `set_all` with non-list (`None`, str) | loud error, previous list intact |
| BMK-08 | persist across reopen | identical list |

## 5. `stores/session_store.py` — P2 (target: session, expire)

| ID | Case | Expected path |
|---|---|---|
| SES-01 | `set(a=1)` then `get("a")` | `1` |
| SES-02 | `get(unknown, default=X)` | `X` |
| SES-03 | `set` merges: `set(a=1)` then `set(b=2)` | both keys present |
| SES-04 | `set(save=False, …)` | in-memory visible via `data()`/`get()` but NOT on disk (reopen loses it) |
| SES-05 | `data()` returns the session mapping | a dict; mutating the returned object must not corrupt the store (copy) or must be documented — test pins whichever, file survives |
| 🔴 SES-06 | expire: there is NO `expire/clear` method in the signature | SPEC GAP confirmed — test documents that stale keys can only be overwritten, never expired |
| SES-07 | hostile keys/values: unicode keys, nested dicts, `None` | round-trip through save/reopen |

## 6. `stores/settings_store.py` — P2 (target: settings, merge)

| ID | Case | Expected path |
|---|---|---|
| SET-01 | fresh store → documented slices exist (`chrome`/`scroll`/`delays`/`ui`/`history`/`collector`) or `get` returns defaults | no `KeyError` on any documented slice |
| SET-02 | `set("ui","theme","dark")` keeps siblings | deep merge, sibling keys survive |
| SET-03 | `get_copy` deep isolation | mutating the copy never reaches the store |
| 🔴 SET-04 | `data()` exposes all sections | dict with the settings mapping |
| SET-05 | `validate()` on a fresh/default store | passes (no raise) — defaults must be valid |
| 🔴 SET-06 | `validate()` on a hostile store (wrong types injected via `set`) | raises or returns errors — invalid settings must be LOUD, never silently accepted |
| 🔴 SET-07 | settings never leak presets/session: `set("presets",…)` / state keys | either namespaced away or refused — `data()` must not grow a `presets`/`state` section that the preset/session stores would fight over |
| SET-08 | persist round-trip | identical after reopen |

## 7. `stores/undo_store.py` — P2 (target: undo state, persist)

| ID | Case | Expected path |
|---|---|---|
| UND-01 | fresh store → `get()` | `([], -1)`-shaped: empty history, index at "nothing" (whatever the exact sentinel, it must be consistent and documented by the test) |
| UND-02 | `set([a,b], 1)` then `get()` | exact round-trip |
| UND-03 | `push(kind, value)` appends one entry | history grows by one, index points at the new tip |
| UND-04 | `push` after undo (index < tip) | redo tail is dropped (standard undo semantics), new entry becomes the tip |
| 🔴 UND-05 | `set` with an out-of-range index (`99`, `-5` on 2 items) | clamped or loud error — never a persisted inconsistent `(history, index)` pair |
| UND-06 | `push` with hostile value (nested, unicode, `None`) | round-trips through save/reopen |
| UND-07 | persist round-trip | identical `(history, index)` after reopen |

## 8. `stores/labels_file_store.py` — P2 (target: offline fallback file)

| ID | Case | Expected path |
|---|---|---|
| LBF-01 | missing file → `reload()` | empty/default shape, never raises |
| LBF-02 | corrupt file → `reload()` | default shape, never raises |
| LBF-03 | `set_data({...})` marks dirty; `flush()` clears it | `dirty()` True → False |
| LBF-04 | `flush()` without changes | no write needed; file still valid afterwards |
| LBF-05 | `set_data` with garbage shape (`None`, list, str) | loud error or coerced — file must stay valid JSON |
| LBF-06 | round-trip: set → flush → new instance → `reload()` → `data()` | identical mapping |

## 9. `stores/preset_store.py` — P2 (target: preset, default)

Existing `test_preset_store_unit.py` (10) covers stack/template CRUD,
overwrite, reopen, dirty/force, import-once. This pass covers the gaps:

| ID | Case | Expected path |
|---|---|---|
| PRS-01 | `named_set/get/delete/all` round-trip on a section | set → get; delete → default; `all` lists the section |
| PRS-02 | `named_all(unknown)` / `named_get(unknown, default=X)` | `{}` / `X`, never `KeyError` |
| 🔴 PRS-03 | named sections survive `save()` + reopen | identical mapping |
| 🔴 PRS-04 | hostile preset names: `""`, whitespace-only, `"a/b"`, `".."`, 500-char, emoji | stored verbatim as dict keys (never a path escape); `list_stacks()` shows them; reopen keeps them |
| 🔴 PRS-05 | `save_stack(name, blocks)` with hostile blocks (`None` items, non-dict items, `None` instead of list) | loud error or stored verbatim — file stays valid, `load_stack` never crashes the caller |
| 🔴 PRS-06 | `save_template(name, body)` with non-string body (`None`, int, dict) | loud error or coerced to str — reopen safe |
| PRS-07 | `delete_stack/delete_template(unknown)` | no raise |
| PRS-08 | per-path cache: two `PresetStore(path=same)` share state; different paths are isolated | same-path sees the same mutation; other path unaffected |
| 🔴 PRS-09 | default preset: a fresh store has a documented default stack/template or `load_stack/load_template` cleanly return `None` | pinned — the UI must never crash on a fresh install |
| PRS-10 | `dirty()` lifecycle across named ops | named mutations mark dirty; `save()` clears; `save(force=False)` skips disk when clean |

## 10. `stores/label_store.py` — P1 (target: hierarchy, orphan, import/export)

Existing `test_person_labels.py` (41, config-mode) + `test_label_store_dbmode.py`
(8, world-mode) cover create/assign/unassign/delete/filter/undo/palette.
This pass covers orphans, hostile inputs, and the import/export seam:

| ID | Case | Expected path |
|---|---|---|
| LBL-01 | hierarchy: labels are FLAT (no parent arg on `create`) | pinned: `create(name)` has no parent; two same-named labels in "different parents" cannot exist — names unique case-insensitively (existing suite pins this; our test asserts no hidden hierarchy leaks into `defs()`) |
| LBL-02 | `assign(nick, unknown_id)` | refused (False/None/no-op), never a persisted dangling reference |
| LBL-03 | `assign("", id)` / whitespace nick | refused or normalised away — `assignments()` must never gain an empty-nick key |
| LBL-04 | `unassign(nick, unknown_id)` / unknown nick | no-op, no raise |
| LBL-05 | `set_for(nick, [dup, dup, unknown])` | duplicates collapse; unknown ids dropped; result contains only real ids |
| LBL-06 | `delete(id)` orphans nobody: every nick's id list is cleaned | `ids_for(nick)` never contains the deleted id afterwards (existing suite covers delete; ours pins the post-delete `assignments()` shape has no empty/dead entries) |
| LBL-07 | `forget(nick)` removes the nick entirely | nick key gone from `assignments()`; defs untouched; unknown nick is a no-op |
| LBL-08 | `create("  ")` / empty / 300-char / unicode-emoji name | refused or normalised (`normalize_name` caps/collapses); store stays valid; reopen safe |
| LBL-09 | `update(id, name=collision)` where collision matches another label case-insensitively | refused (uniqueness holds after update), original name kept |
| LBL-10 | `update(unknown_id, …)` | no-op / None, no raise, no phantom def created |
| LBL-11 | `by_id/by_name` for unknown | `None`, never `KeyError` |
| LBL-12 | `ids_for(unknown_nick)` → `[]`; `labels_for` → `[]`; `labels_map()` keys mirror `assignments()` | empty-safe; map carries id+name+colour per nick |
| 🔴 LBL-13 | `set_filter(include=[unknown], exclude=[unknown])` | stored but matches nothing extra — `allows()` fails open/closed per documented rule, never raises on unknown ids |
| LBL-14 | `filter()` shape + `clear_filter()` + `filter_active()` lifecycle | set → active True; clear → active False and everybody `allows()` |
| LBL-15 | `allows/reject_reason` for an unlabelled nick under include-filter | `allows` False; `reject_reason` names the rule (non-empty string, no crash) |
| LBL-16 | export/import: `snapshot()` → mutate everything → `restore(snapshot)` | exact deep restoration (existing suite covers the timeline variant; ours pins the raw store variant incl. filter) |
| 🔴 LBL-17 | `restore(garbage)` (`None`, `[]`, `{"defs": "xx"}`, truncated dict) | loud error or safe no-op — the live store must keep serving `defs()`/`allows()` afterwards (import must never brick the store) |
| LBL-18 | world export: `flush_to_db()` then `load_from_db()` on a fresh instance | identical `state()`; unflushed in-memory changes are NOT visible to a second instance (no phantom sharing) |
| 🔴 LBL-19 | `load_from_db` on a world with corrupt/legacy label rows | best-effort import, never raise; `defs()` usable afterwards |
| LBL-20 | `state()` is a deep copy | mutating it never reaches the store |

## 11. `stores/media_store.py` — P1 (target: path, duplicate, limit, recovery)

Existing `test_media_store.py` (21) + `test_media_store_paths.py` (12) +
`test_media_recovery_e2e.py` (12) cover register/cache/duplicate/oversize/
network-fallback/LRU/recovery. This pass covers path hostility, caps, and
recovery-state edges:

| ID | Case | Expected path |
|---|---|---|
| MED-01 | `slugify_nick("../../etc")` | no `..`, no `/` in the result — a flat folder name, never a traversal |
| MED-02 | `slugify_nick("")` / whitespace / emoji-only / CJK-only | non-empty safe name (hash fallback per docstring), never `""` |
| MED-03 | `slugify_nick("Хорошо Все")` | `Horosho_Vse` exactly (docstring contract) |
| 🔴 MED-04 | collision: `Ански` vs `Anski` → `folder_for` | two DIFFERENT folders (docstring: `_nick.txt` marker keeps them stable); reopen keeps the same mapping |
| MED-05 | `folder_for(nick)` with hostile nick (`a/b`, `..`, `C:\\x`) | stays INSIDE `cache_dir` (absolute path prefix check) |
| MED-06 | `_free_name` sequence within one day | `DAY_000`, `DAY_001`, … zero-padded, unique, sorted |
| MED-07 | `register("", …)` | refused (`None`/0/`ValueError`) — existing suite asserts refusal; ours pins no row is created |
| 🔴 MED-08 | `register(same_url)` twice with different nicks | ONE row reused (docstring: "existing rows are reused"); count query pins the nick rule (first wins or last wins — pinned, not both) |
| MED-09 | `get(unknown)` / `get_by_url(unknown)` | `None`, never raise |
| 🔴 MED-10 | `process_pending(limit=0)` / negative | caches nothing, returns `0`, rows stay pending |
| 🔴 MED-11 | `max_file_mb=0` (or negative) | every file is oversize-skipped with a reason — never a crash, never a zero-byte file kept as "cached" |
| MED-12 | `max_cache_mb=0` + one cached file → `evict_if_needed()` | cache empties to the URL fallback; `cache_usage()` reports `0` files afterwards |
| MED-13 | LRU order: cache A, B, C over the cap | the LEAST-recently-used file is evicted first (access bumps recency); newest survives |
| MED-14 | `clear_cache()` | zero files on disk, rows degraded to URL fallback, DB rows intact (no row deletion) |
| MED-15 | `requeue(unknown_id)` | clean failure, no raise |
| MED-16 | `download_one(cached_and_present)` | returns cached state WITHOUT re-downloading (no fetch call) |
| MED-17 | `download_one(missing_file_but_cached_row)` | re-download attempted (row repaired or failed with reason — never "cached" while the bytes are gone) |
| MED-18 | `retry_failed_uncached()` only touches failed-without-file rows | failed-WITH-file and skipped rows untouched; second call without new failures is a no-op |
| MED-19 | `migrate_layout()` on an already-new tree | no-op, no lost files, no duplicates |
| MED-20 | `clipboard_payload(unknown)` | clean failure, no raise |
| MED-21 | `path_for` prefers file, falls back to URL (existing suite) — plus: file DELETED after caching | falls back to the URL (stale path must never be returned as if the bytes exist) |

## 12. `stores/history_models.py` — P2 (target: validation, field types)

Existing `tests/unit/backend/test_history_models.py` (12) covers
fingerprint/dedupe/UTF-16/from_dict/round-trip/to_dict-JSON-safe. Gaps:

| ID | Case | Expected path |
|---|---|---|
| MDL-01 | `fingerprint` ignores NOTHING except `occ` among identity fields: flip each of direction/from_nick/ts/kind/payload | every flip changes the fingerprint |
| MDL-02 | `dedupe_key` ignores `occ` AND ALSO ignores nothing else: flip direction/from/ts/kind/payload | key changes on each flip (timestamp+content identity) |
| MDL-03 | `_int_or("12", 0)` / `("xx", 7)` / `(None, 7)` / `(12.9, 0)` / `(True, 0)` | `12` / `7` / `7` / `12` or `7` pinned / `1` or pinned — never raises (docstring: "must still become a usable record") |
| MDL-04 | `MessageRecord.from_dict({})` | usable record with defaults, never raises |
| MDL-05 | `from_dict` with wrong-typed fields (`occ: "xx"`, `idx: None`, nicks as ints) | usable record (tolerant coercion), never raises, never dropped |
| MDL-06 | `from_dict` ignores unknown extra keys | record builds; extras dropped |
| MDL-07 | media record: kind=image/gif with a URL payload | `payload` is the URL; `dup_key` is timestamp+content (no `occ` in it) |
| MDL-08 | `AppendResult`/`Alignment`/`SyncResult.to_dict()` | JSON-serialisable dicts with the documented fields; `json.dumps` never raises |
| MDL-09 | `Alignment` default (no overlap) | documented "append-all" shape (index 0 / no-match marker — pinned) |
| MDL-10 | `ensure_fp` twice | second call keeps the first value (no recompute) |

## 13. `stores/history_db.py` — P1 (target: schema, query, migration rollback)

Existing `test_history_db_unit.py` (9) + `test_db_schema_migration.py` (9) +
`test_db_migration.py` (8) + `test_db_unified_world.py` (11) cover
meta/fetch-shapes/WAL-size/FTS-flag/schema-repair/version-stamp/legacy-rebuild.
Gaps — query helpers, lifecycle, hostile inputs:

| ID | Case | Expected path |
|---|---|---|
| HDB-01 | lifecycle: `is_open` False before `init()`, True after; `close()` idempotent; `conn` usable only while open | pinned states, double `close()` never raises |
| 🔴 HDB-02 | `init()` twice | second is a safe no-op (no duplicate tables, no error) |
| HDB-03 | `execute` + `commit` + `fetchone` round-trip on a scratch table | written rows readable; uncommitted write invisible to a second connection |
| HDB-04 | `executemany` batch insert | all rows land, in order |
| HDB-05 | `fetchone` on empty result → `None`; `scalar` on empty → `default` | empty-safe (scalar covered for one shape; ours pins `fetchone`-None + scalar-custom-default) |
| HDB-06 | params are BOUND, not interpolated: `fetchall("… WHERE a=?", ["' OR '1'='1"])` | treated as a literal string (injection-safe); table intact |
| HDB-07 | `get_meta`/`set_meta` overwrite + unicode values | last write wins; unicode round-trips |
| HDB-08 | `_version_tuple("10") > _version_tuple("9")`; `"1.10" > "1.9"`; garbage `"xx"` never raises | numeric compare per docstring |
| 🔴 HDB-09 | open a CORRUPT (non-SQLite) file | one clear error (no `no such column` cascade, no half-open handle); `is_open` stays False |
| 🔴 HDB-10 | open a NEWER-version file | warns but OPENS (existing suite pins this; ours pins reads still work and no write corrupts the version stamp) |
| HDB-11 | `use_fts=False` fresh file | working DB without FTS tables; FTS search degrades (no crash) |
| HDB-12 | `file_size()` on fresh + after writes | ≥ plain file size (WAL siblings included); never 0 for an initialised DB |
| HDB-13 | concurrent writers: two connections, interleaved `execute`+`commit` | both rows land (or one clean `database is locked`, never a torn row / lost commit / crash) |
| 🔴 HDB-14 | `db_fetch_legacy` on a missing table | empty list / clean default, never raises |
| HDB-15 | `_table_columns(missing)` | `None` (docstring: "or None when it does not exist") |
| 🔴 HDB-16 | `normalise_nick` matrix: case/space/unicode | pinned: `"  Ann "` → `"ann"`-family canonical; empty/whitespace → `""` or refused, never whitespace stored |
| HDB-17 | `close()` then any query | clear error ("closed"), never a segfault/hang |

## 14. `stores/history_repo.py` — P1 (target: CRUD, query, version conflict)

Existing `test_history_repo.py` (29) + `test_history_repo_lifecycle.py` (16)
cover append/idempotency/overlap/gaps/days/ord/counters/cursor/soft+hard
delete/merge/rename/resolve_days. Gaps — tokens, conflicts, backfill,
repair, query edges:

| ID | Case | Expected path |
|---|---|---|
| HRP-01 | `align_batch` exact-suffix overlap | returns the index AFTER the last occurrence (docstring: "the LAST place … where our stored suffix occurs") — pinned with a repeated-pattern batch |
| HRP-02 | `align_batch` with no overlap | `0` (append-all); empty batch → `0`; empty tail → `0` |
| HRP-03 | `resolve_days` newest-ahead-of-now → yesterday (existing suite pins rollover; ours pins the LIST shape: every element is `YYYY-MM-DD`, length == input length, non-decreasing walking forward) | shape + monotonicity |
| HRP-04 | `append` with `records=[]` | no-op result (0 added), no gap row (existing suite pins no-gap; ours pins the returned `AppendResult` shape) |
| HRP-05 | version conflict: two interleaved `append`s for the SAME person (A1, B1, A2 with overlapping fps) | final archive == single-batch order with NO duplicate `dup_key`s; `ord` dense after `_resequence`-equivalent (no holes from the interleave) |
| HRP-06 | `prepend` (backfill) shifts existing `ord` up | old rows keep their relative order, all `ord` ≥ number of prepended lines; no `ord` collision |
| HRP-07 | `prepend` with all-duplicate batch | nothing inserted, existing `ord` UNCHANGED (no gratuitous shift) |
| HRP-08 | `record_gap` then `append` past the gap | gap row persists with reason+detail; later append does not erase it |
| HRP-09 | `soft_delete_message` with a WRONG token → `restore_deleted(nick, wrong)` | nothing restored, `deleted_count` unchanged; correct token restores exactly |
| HRP-10 | double `restore_deleted` with the same token | second is a no-op (idempotent), no duplicated rows |
| HRP-11 | `purge_deleted(nick)` scoping (existing suite pins scoping; ours pins: purge WITHOUT token still requires the tombstone state — live rows never purged) | only tombstoned rows of that nick disappear |
| HRP-12 | `delete_person(nick, hard=False)` then `restore_person(nick, token)` | person + ALL rows back, `ord` preserved |
| 🔴 HRP-13 | `delete_person` with wrong/empty token → restore | restore refuses; person stays deleted (or the documented no-token path — pinned) |
| HRP-14 | `merge_persons(src, dst)` where src has tombstoned rows | tombstones do NOT resurrect as live rows in dst |
| HRP-15 | `merge_persons(nick, same_nick)` / unknown src | `0`, no crash, archive unchanged |
| HRP-16 | `possible_duplicates` flags case/space variants only | `("Ann","ann"," ANN ")` grouped; `("Ann","Bob")` never grouped |
| HRP-17 | `get_person(unknown)` / `get_person_by_id(-1)` | `None`, never raise |
| HRP-18 | `ensure_person("")` / whitespace | refused or normalised — no empty-nick row in `persons` |
| HRP-19 | `get_cursor(unknown_id)` | documented empty-cursor shape, never raise |
| HRP-20 | `has_repairable_media` with nothing repairable → False; `recover_media` with empty records → no-op result | empty-safe, no requeue storm |
| 🔴 HRP-21 | `mark_backfilled` then `reset_cursor` | backfilled flag STAYS set (cursor reset "is untouched" w.r.t. the archive; flag is archive state — pinned either way, no silent clear) |
| HRP-22 | `new_op_token()` uniqueness | 1000 tokens, all distinct, all non-empty strings |

## 15. `stores/user_memory.py` — P2 (target: memory, link, cycle)

Existing `test_user_memory_unit.py` (10) covers upsert-idempotency,
upsert_many, missing-nick safety, queue order, set/reset_messaged,
replace_all, world-travel, reopen, empty-switch-refused. Gaps:

| ID | Case | Expected path |
|---|---|---|
| UMM-01 | `upsert_many([])` | `0`, table unchanged |
| UMM-02 | `upsert_many` with duplicate nicks in ONE batch | one row per nick (last wins or first wins — pinned), count reflects unique nicks |
| 🔴 UMM-03 | hostile nicks: `""`, whitespace, `"'; DROP TABLE users;--"`, emoji, 500-char | stored literally and harmless (parameterised SQL — table intact afterwards); empty/whitespace refused or normalised — pinned |
| UMM-04 | `get_user(unknown)` → `None`; `get_all()` on empty → `[]`; `get_queue()` on empty → `[]` | empty-safe |
| UMM-05 | `get_stats()` shape on empty + non-empty | documented keys present; counts consistent with `get_all()` |
| UMM-06 | `count_unmessaged()` equals `len(get_queue())` after mixed ops | consistent (docstring: "A single COUNT") |
| UMM-07 | `mark_messaged(unknown)` | no-op, no raise |
| UMM-08 | `delete_users([])` → `0`; `delete_users([unknown, known])` → `1`, known gone | partial success counted |
| UMM-09 | `replace_all([])` | table emptied, no raise |
| 🔴 UMM-10 | `replace_all` with garbage rows (missing keys, wrong types, `None` entries) | loud error or best-effort — table never left half-replaced (atomic: all-or-nothing — pinned) |
| UMM-11 | `clear_all()` then stats/queue | empty everywhere; auto-increment/identity sane for the next upsert |
| UMM-12 | cycle: `switch_db(A)` → write → `switch_db(B)` → write → `switch_db(A)` | A's rows intact (per-world isolation across a full cycle) |
| 🔴 UMM-13 | `switch_db` to a corrupt file | refused with the old world still connected (no half-switched state) |
| UMM-14 | lifecycle: `is_open` False before `init()`; `close()` idempotent; ops after `close()` are a clear error or auto-reopen — pinned, never a hang | |
| UMM-15 | `set_messaged(unknown, True)` | no-op, no raise; `set_messaged(known, False)` clears time (mirrors `reset_messaged` rule: "must never show a message time") |

## 16. `stores/migration.py` — P2 (target: migrate, rollback)

Existing `test_stores_migration.py::test_migration_creates_backup` +
`test_stores_split.py` (archived-not-deleted, idempotent, unreadable-starts-
fresh) cover the happy path. Gaps — dry-run, partial layout, rollback:

| ID | Case | Expected path |
|---|---|---|
| 🔴 MIG-01 | `needs_migration` on fresh dir (no legacy, no new layout) | `False` (nothing to migrate) |
| MIG-02 | `needs_migration` on legacy-only | `True` |
| MIG-03 | `needs_migration` after a completed migration | `False` |
| MIG-04 | `migrate(dry_run=True)` on legacy-only | reports `{"migrated": True, "backup": None, "added": [...]}` with ZERO disk changes (no backup file, no new files, legacy byte-identical) |
| MIG-05 | `migrate()` return shape | `{"migrated": bool, "backup": str\|None, "added": list[str]}` exactly (docstring contract) |
| MIG-06 | second `migrate()` (idempotent) | `{"migrated": False, …}`, no second backup file, new-layout files byte-identical |
| MIG-07 | partial new layout (some store files already exist with USER data) | existing files NOT overwritten (docstring: "nothing is overwritten"); only missing ones added; `added` lists exactly those |
| MIG-08 | corrupt legacy file | clean result (`migrated` False or best-effort True — pinned), never raises; no backup of garbage / or backup kept — pinned |
| 🔴 MIG-09 | missing legacy file | `{"migrated": False, "backup": None, "added": []}`, never raises |
| MIG-10 | rollback: restore `backup` over the legacy path then `needs_migration` | `True` again and the restored bytes equal the pre-migration backup (the backup is a REAL rollback, not a souvenir) |
| MIG-11 | backup naming | `config.json.bak.<timestamp>` alongside the legacy file; timestamp sorts/parses (a second migration a second later never clobbers the first backup) |
| MIG-12 | legacy file is ARCHIVED, not deleted (existing suite pins this; ours pins the new-layout content equals the legacy sections key-for-key) | content fidelity, not just "file exists" |

---

## 14. Existing-suite inventory (do-not-duplicate list)

Counted 2026-09-09 by `def test` occurrences:

| Suite | n | What it already proves (so we don't re-prove it) |
|---|---|---|
| `test_history_repo.py` | 29 | tables/version, reopen safety, legacy upgrade+dedupe, nick normalise+unique, sessions continue, case-flagging, first-append order, UI shape, replay/overlap/shifted-occ/same-minute idempotency, live-delta/gap/lost-alignment paths, empty-batch no-op, backwards days, two-day identity, ord growth, direction/media counters, media link, cursor, tail-fp cap, backfill flag, cursor-reset safety, tombstone/hard-delete, merge moves+dedupe |
| `test_history_repo_lifecycle.py` | 16 | message delete+exact restore, unknown-person no-op, clear-history identity reset, purge scoping/sweep, person soft/hard delete, merge folding/empties-source, self/stranger merge zero, rename adopt/refuse, 4× midnight rollover |
| `test_history_db_unit.py` | 9 | meta round-trip/text, tuple/dict shapes, scalar default, WAL size sum, FTS on/off, second-connection read |
| `test_db_schema_migration.py` | 9 | canonical columns, version stamp, silent reopen, legacy rebuild attribution, next-open silent, quarantine, late media columns, unrepairable clear-fail, newer-warns-opens |
| `test_db_migration.py` | 8 | legacy queue merge, migrate-twice noop, missing legacy ok, label import once/keep-own, ghost paths, world undo move, app timeline stays |
| `test_db_unified_world.py` | 11 | 12 tables, v6, seed, queue/labels/undo/media per-world, two-world isolation |
| `test_media_store.py` | 21 | register pending/dedupe/kind/refusal, cache-to-disk, identical-bytes-once, oversize skip, network-fail recorded, relative-URL resolve, network-capture CORS fallback, disabled/paused/no-CDP paths, path_for file/URL, LRU evict, usage+clear, clipboard file/file+link/link, unknown clean-fail |
| `test_media_store_paths.py` | 12 | (path-focused supplement — slugify/folder/free-name basics) |
| `test_media_recovery_e2e.py` | 12 | backfill requeue+finish, oversize cap raise, empty-slot upgrade ×2, day-scoped slots, failed-requeue, heartbeat no-requeue, newest-window repair, unrepairable no-loop, idle drain, pre-fix dedupe, default cap raise |
| `test_person_labels.py` | 41 | create/palette/nameless-refuse/unique-case/ids, multi-assign/double-assign/unassign/delete/recolour/colour-fallback/set_for, reload survive, filter matrix + reasons + clear, broken-filter open, bridge shapes, undo/redo ×6, persist, guard, map, manager UI ×4 |
| `unit/backend/test_label_store_dbmode.py` | 8 | world round-trip, two-world isolation, delete-flush-no-ghosts, colour ×2, name/nick normalise, snapshot deep |
| `test_preset_store_unit.py` | 10 | stack round-trip/overwrite/reopen/unknown-None, template round-trip/overwrite, dirty lifecycle, no-save-memory-only, force-save, import-once/no-file-False |
| `test_user_memory_unit.py` | 10 | upsert idempotent, upsert_many counts, missing-nick safe, queue order, flip-back, reset-all, replace snapshot, world travel, reopen, empty-switch refused |
| `test_stores_split.py` | 18 | archived-not-deleted, per-file sections, facade reads, idempotent, unreadable-fresh, reopen round-trip, undo/session files, failed-undo-isolation, named CRUD, state defaults, per-path cache, deep copy, bookmark dedupe, no-file defaults, legacy labels write, history cap, replace-not-truncate, config_dir_for |
| `test_stores_migration.py` | 7 | atomic save, settings defaults, bookmark add/remove, block named, session, undo, backup created |
| `unit/backend/test_history_models.py` | 12 | JS constants match, stable+occ-sensitive, astral emoji, dedupe-ignores-occ, empty/None safe, lossless round-trip, agent field map, agent garbage usable, media dup_key, ensure_fp once, to_dict JSON-safe, live-items bound |
| `test_history_query.py` (22) + `test_history_query_edges.py` (17) | 39 | read-path queries — out of scope for this pass except where the write path must keep their contracts true |

Total pre-existing stores-relevant: **~250 test methods**. The 150+ cases
above were designed to intersect none of them.

## 15. Bug ledger (filled during §16 implementation run)

First full run: **25 red / 196 green** over the 10 new files (221 tests). Of
the reds, 3 were test-side mistakes (fixed in the tests: an uncommitted DDL
visible to no second connection in HDB-03, a missing fixture write in
MED-06, a stale filler line in ATM-05b) and 22 were genuine code↔contract
disagreements. Every 🔴 below had a failing run behind it before anything
was fixed or re-decided.

### 🔴 BUG — code fixed, test green (19)

| ID | Severity | Mismatch | Fix |
|---|---|---|---|
| JIO-01/02 | low | `load_json` returned the `default` object itself, not "a copy" | `copy.deepcopy` on both fallback paths |
| 🔴 JIO-09 | **high** | `save_json` of unserialisable data raised `TypeError`, breaking the "returns False" promise (and `AtomicJsonStore.save` had the same hole, ATM-09) | catch `TypeError`/`ValueError` → `False` / `Result.err`; target keeps its previous good bytes |
| 🔴 ATM-06 | low | `set()` with no value died with an accidental `IndexError` | explicit `ValueError("set() needs at least a key and a value")` |
| 🔴 BLK-05 | low | `delete_custom_block` did not strip while `save_custom_block` does → padded names undeletable | strip on delete (test: BLK-05b) |
| 🔴 BMK-03 | low | `remove` did not strip while `add` does → padded urls unremovable | strip on remove (test: BMK-03b) |
| 🔴 UND-05 | medium | `set(hist, 99)` persisted an index no reader can use | clamp to `[-1, len-1]` |
| 🔴 PRS-03 | **high** | `load()` rebuilt only the two known sections: any other `named_*` section was silently dropped on restart (committed user data lost) | preserve unknown sections, still coercing the two known ones to dicts |
| 🔴 PRS-05 | medium | `save_stack(name, {dict})` silently stored the dict's *keys* as the block list | `ValueError` unless list/tuple/None |
| 🔴 PRS-06 | medium | `save_template(name, 123)` stored the int, then crashed with `TypeError` from the *log line* — loud for the wrong reason, store left dirty | `ValueError` before anything is stored |
| 🔴 HDB-02 | low | double `init()` leaked the old connection and dropped pending writes | close-first (close commits, so pending writes survive) |
| 🔴 HDB-09 | medium | corrupt file: the PRAGMAs sat *outside* the guarded region, so `DatabaseError` escaped and the instance stayed half-open (`is_open` True, every later query failing differently) | PRAGMAs inside `try` + `close()` on every failure path |
| 🔴 UMM-10 | **high** | `replace_all` with a garbage row raised *after* the DELETE: the table was left half-replaced inside an open transaction | `rollback()` + re-raise (all-or-nothing) |
| 🔴 UMM-13 | medium | `switch_db` to a corrupt file closed the old world first, then died — the queue stranded on a broken handle | connect + schema first, swap only on success |
| 🔴 HRP-13 | medium | `restore_person(nick, token="wrong")` returned True, undeleted the person and left the rows hidden — a person with a stranded archive | refuse (`False`, stays deleted) unless the token matches the tombstone or restores ≥1 row; the undo path (original token) is unaffected |
| 🔴 MED-04 | medium | two nicks with the same slug (`Ански`/`Anski`) shared one folder until the first write, and the loser kept the shared folder via the `_dirs` cache even after the marker existed — mapping differed pre/post restart | in-process claim map: the late-comer gets the hashed variant immediately (per-nick digest, stable across restarts) |
| 🔴 MED-10 | low | `process_pending(limit=0)` cached 1 file (`max(1, …)` guard) | `limit <= 0` returns 0 |
| 🔴 MED-11 | low | an empty download was cached as a 0-byte "image" | `fail("empty payload")` (test: MED-11b) |
| 🔴 LBL-19 | medium | a garbage `labels_next_id` in `schema_meta` raised `ValueError` out of `load_from_db` — one bad meta row bricked the whole world load | tolerant int, falls back to 0 |
| 🔴 LBL-17 | low | `restore` with ill-typed values (`{"defs": "xx"}`) persisted the garbage verbatim into the config file | coerce to shape on the way in (test: LBL-17b) |

### 🔴 SPEC — contract decided, test pins it (15)

| ID | Decision |
|---|---|
| 🔴 JIO-08 | Missing parent dirs are auto-created (a feature, not a failure); only truly unwritable paths return `False` |
| 🔴 SET-04 | `data()` is the persisted overlay, not the merged view — `get()` resolves defaults, `data()` shows what was written |
| 🔴 SET-06 | `validate()` is deliberately narrow: only `chrome.port` is checked |
| 🔴 SET-07 | Foreign sections (`presets`, …) are stored, not refused/namespaced — harmless (PresetStore owns a separate file) |
| 🔴 SES-06 | No expire API exists; stale session keys can only be overwritten (documented gap, feature work) |
| 🔴 PRS-04 | `save_stack("")` raises `ValueError` — louder and safer than storing an empty name |
| 🔴 PRS-09 | No default preset; unknown names cleanly return `None` |
| MIG-01/09 | A missing file "needs migration": `migrate()` creates it with defaults (intended per the code comment — fresh installs start clean) |
| 🔴 HDB-10 | Opening a newer file stamps the *current* version (open = upgrade; pinned by `test_db_schema_migration.py` too) |
| 🔴 HDB-14 | `db_fetch_legacy` on a missing table raises `OperationalError` — correct for a private helper whose callers guarantee the table |
| 🔴 HDB-16 | `normalise_nick` collapses whitespace but preserves case; the folded form lives in `persons.nick_lc` |
| 🔴 HRP-21 | `reset_cursor` clears `full_scan_complete` — the delete paths document "the collection markers reset", so rescan-everything is the contract |
| 🔴 LBL-13 | Unknown filter ids are dropped at set time (fail closed, never raise) |
| 🔴 MED-08 | Re-registering a URL keeps the first non-empty owner (fills an empty one) |
| 🔴 UMM-03 | `upsert_user` does not validate: `""` is stored literally (unlike `ensure_person`'s `ValueError`). Deliberately NOT fixed — callers pass DOM nicks and refusing could break collection; seam inconsistency recorded |

### Out-of-scope blockers found while establishing the baseline (not fixed)

These sit outside section F but break the repo around it:

1. `backend/history_db.py` does not import (`NameError: TABLE_ORDER` in `backend/history_db_parts/helpers.py`) — ~15 existing suites fail at collection, including every `backend.history_db` consumer.
2. `backend/config_manager.py` (imported by `main.py`) needs `stores.migration.migrate_legacy_config`, `stores.settings_store.SETTINGS_DEFAULTS` and `stores.bookmark_store.DEFAULT_BOOKMARKS` — none of which exist in `stores/` (it has `migrate`, `DEFAULTS`, `DEFAULT_URLS`). The 7-file split the facade was written against was never implemented on the `stores/` side.
3. `tests/test_stores_split.py` imports the same missing `migrate_legacy_config` and is therefore red at import.

## 16. Implementation order (P1 first, then P2)

1. `test_history_db_integrity.py` (HDB) + `test_history_repo_conflicts.py` (HRP) — P1, archive correctness.
2. `test_media_store_limits.py` (MED) + `test_label_store_orphans.py` (LBL) — P1, user-visible data.
3. `test_stores_atomic_jsonio.py` (JIO/ATM) + `test_stores_small_stores.py` (BLK/BMK/SES/SET/UND/LBF) — P2, foundation every other store stands on.
4. `test_history_models_edges.py` (MDL) + `test_user_memory_links.py` (UMM) + `test_preset_store_defaults.py` (PRS) + `test_stores_migration_rollback.py` (MIG) — P2, seams and lifecycle.

House rules for the new files (repo conventions): `unittest` style,
`sys.path` bootstrap, runnable standalone AND under pytest, real SQLite temp
files (`tempfile.TemporaryDirectory`), fake CDP/page objects where needed,
no network, no Qt.
