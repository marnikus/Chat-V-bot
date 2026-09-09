# Blockers fix design — history cluster shims + config split seam

Date: 2026-09-09. Repairs the two out-of-scope blockers left open by
`docs/STORES_TEST_DESIGN_2026-09-09.md` §15 (blockers 1–2). Closes
BUG-02 (`docs/ACTIONS_TEST_DESIGN_2026-09-09.md` §12).

- **Blocker 1 (BUG-02).** `backend/history_db_parts/helpers.py` builds
  `TABLE_SQL` at module level from `TABLE_ORDER` / `TABLE_COLUMNS`, which
  are defined nowhere in the repo → `NameError` on
  `import backend.history_db`. 19 test modules die at collection; 7 backend
  modules fail import (history_db, history_repo, media_store, history_query,
  history_service, chat_parser, collector — the last four transitively).
- **Blocker 2 (split seam).** `backend/config_manager.py` (production,
  imported by `main.py`) is a 7-file facade over a `stores/` API that was
  never implemented: `migrate_legacy_config`, `SETTINGS_DEFAULTS`,
  `DEFAULT_BOOKMARKS` are missing, and the small stores expose section-mode
  single-file shapes instead of the split per-file shapes the facade calls
  (`blocks.all()`, `undo.history()`, `session.set(save_now=…)`, …).
  `tests/test_stores_split.py` (18 tests) + the contract suites pin the
  intended behavior and are all red.

## 1. Scope

**In scope.**

1. Shim the duplicated backend persistence cluster to `stores/`
   (single canonical implementation): `history_db`, `history_repo`,
   `history_models`, `media_store`, `label_store`, `user_memory`.
2. Delete the dead mechanical-split debris `backend/history_db_parts/` and
   `backend/history_repo_parts/` (zero importers after the shims; verified
   by grep — the only `_parts` mentions in tests are BUG-02 prose).
3. Implement the split-stores API: per-file shapes, `load`/`save` /
   `reload`/`flush` lifecycle, `SETTINGS_DEFAULTS`, `DEFAULT_BOOKMARKS`,
   `stores/migration.py::migrate_legacy_config`.
4. Healing fallout in the same seam: the 5 missing protocols in
   `core/interfaces.py` (+ 2 reshaped, see §4) so
   `tests/unit/core/test_interfaces_full.py` collects; drop the 2 BUG-02
   `expectedFailure` pins (REG-02, CH-00); mark BUG-02 FIXED in the
   ACTIONS design doc.
5. Tests: new suites `tests/test_backend_shims.py` (SHM rows) and
   `tests/test_stores_split_stores.py` (LMC/BKS/BLS/SES/SET/UND rows);
   rewrites listed in §6.

**Out of scope (not touched).** Suites needing third-party modules absent
from `.venv` (`PySide6`, `websockets`); BUG-10 (Router mixins, `bridge/`
seam); `app/container.py` dead `atomic_store`/`settings_store` wiring
(registered, never resolved — resolving `settings_store` post-change would
fail, but nothing does; recorded, not fixed); `backend/preset_store.py`
old single-file design (zero consumers, heals transitively via
`config_manager`); `migrate()`/`needs_migration()` (kept as-is, still
pinned by MIG rows + `test_migration_creates_backup`); CF#7's
`expectedFailure` (`get()` keeps aliasing settings sections — §5.7);
`backend/history_parts/` + `backend/collector_parts/` (unique logic);
`backend/history_query.py`, `history_service.py`, `chat_parser.py`,
`collector.py` (unique, heal transitively — verified by probe, §2).

## 2. Blocker 1 — shims

Each file becomes a re-export shim (`<150 LOC` trivially, same pattern as
`backend/bridge.py`). No logic, no fallbacks: `stores/` is canonical and
already verified newer-or-equal everywhere (19 §F fixes included).

| Backend module | Canonical source | Re-exported names (all verified present) |
|---|---|---|
| `history_db.py` | `stores.history_db` | `HistoryDB`, `SCHEMA_VERSION`, `TABLE_COLUMNS`, `TABLE_CONSTRAINTS`, `TABLE_ORDER`, `LEGACY_MESSAGES_CONSTRAINT`, `SCHEMA`, `FTS_SCHEMA` |
| `history_repo.py` | `stores.history_repo` | `HistoryRepo`, `align_batch`, `resolve_days` |
| `history_models.py` | `stores.history_models` | `MessageRecord`, `SyncResult`, `dedupe_key`, `fingerprint`, `Alignment`, `AppendResult`, `MAX_LIVE_ITEMS` |
| `media_store.py` | `stores.media_store` | `MediaStore`, `slugify_nick` |
| `label_store.py` | `stores.label_store` | `LabelStore`, `PALETTE` |
| `user_memory.py` | `stores.user_memory` | `UserMemory`, `UserRecord`, `_SCHEMA` |

Notes:

- The bold names are the exact backend-side import survey
  (`HistoryDB`×21, `UserMemory`×24, …); the rest are generous
  same-module publics so future backend-side importers keep working.
- `_SCHEMA` (private!) is imported by `tests/test_db_migration.py:69`
  from `backend.user_memory` — re-exported deliberately.
- `SyncResult` lives in `stores.history_models` (not the repo).
- `TAIL_FP_LIMIT` / `LabelDef` do **not** exist in `stores/` — excluded.
- Each shim sets `__all__` to its name list.
- `backend/history_db_parts/mixin5c._recover_loop` is a mechanical-split
  artifact (a slice of `recover_media`), not new logic — dies with the
  debris dirs. Parts-union method sets were verified identical to
  `stores/` (32/32 db; repo equal modulo that artifact).

**Heals-transitively (no diff, verified by import probe after the shims):**
`history_query` (unique, imports `HistoryDB`), `history_service`,
`chat_parser`, `collector`, `db_manager` (if it imports the cluster),
`actions/collect_history.py` (REG-02), `tests/test_collect_history_block.py`.

SHM rows (`tests/test_backend_shims.py`):

| ID | What it takes | Expected path |
|---|---|---|
| SHM-01 | `backend.history_db` names | each `is` the `stores.history_db` object (single source, not a copy) |
| SHM-02 | all six shims | `import backend.<m>` succeeds; `__all__` non-empty; every name importable |
| SHM-03 | repo root | `backend/history_db_parts/` and `backend/history_repo_parts/` do not exist |
| SHM-04 | `HistoryDB` via the shim | `init()` in a tmpdir creates all `TABLE_ORDER` tables (+FTS if configured) |
| SHM-05 | previously-red importers | `import backend.chat_parser`, `actions.collect_history`, `backend.history_query` succeed |
| SHM-06 | `_SCHEMA` | `backend.user_memory._SCHEMA is stores.user_memory._SCHEMA` (private-name pin) |

## 3. Blocker 2 — split stores

The facade (`backend/config_manager.py`) is **not modified**. The call-site
checklist it needs (§3.6) is satisfied entirely from `stores/`.

### 3.1 Shapes (file content per store)

| File | Shape | Missing / corrupt / wrong-shape |
|---|---|---|
| `settings.json` | dict overlay, `{}` default | → `{}` (defaults served at read time) |
| `bookmarks.json` | bare list of str | → `list(DEFAULT_BOOKMARKS)` |
| `blocks.json` | bare list of `{"name","block","updated_at"}` | → `[]` |
| `session.json` | flat dict (no `"state"` wrapper) | → `{}` |
| `undo.json` | `{"history":[…], "index":n}` | → `{"history":[], "index":-1}` |
| `labels.json` | unchanged (`LabelsFileStore`) | unchanged |
| `presets.json` | unchanged (`PresetStore`) | unchanged |

All stores tolerate a directory-shaped path, undecodable bytes, and JSON
of the wrong shape by falling back to the default (CF#2/CF#3 isolation).
Reads never raise; writes go through `jsonio.save_json` (atomic replace +
`makedirs`, verified present).

### 3.2 Constructors

`Store(path)` — positional string, split-file mode, file owned via
`jsonio` directly (the `LabelsFileStore` template: `_path` plain attr,
`_data` in memory, no dirty flags — files are tiny, saves rewrite).
The `atomic=` section-mode parameter is **removed**; `AtomicJsonStore`
remains as a tested utility (`atomic.py` untouched, ATM rows green).
`undo._path` stays a plain settable attribute (sabotage test).

### 3.3 Method + return contracts

Uniform rules for the new/changed surface (grandfathered exceptions noted):

- **Wrong-type arguments raise `TypeError`** (loud contract).
  Empty-string domain values return `False` (soft refusal).
- `load()` / `reload()` → `None` (re-read, tolerate errors).
- `save()` / `flush()` → `Result[None]` (architecture: Result at
  boundaries). Exceptions: `PresetStore.save()` → `None` and
  `LabelsFileStore.flush()` → `bool` are pre-existing pins, untouched.
- Data handed out is a copy where mutation would corrupt the store
  (`all()`, `data()`); `SettingsStore.get` keeps returning the live
  object (CF#7 `expectedFailure` must keep failing — §5.7).

| Store | Methods (new ones ★) | Returns / notes |
|---|---|---|
| settings | `get`, `get_copy`, `set`, `data`, `validate`, ★`load`, ★`save` | `set` → **None** (was save-Result; protocol pins None); `save` → `Result`; rest unchanged (SET-01…08 semantics kept: deep-merge, overlay-only `data()`, chrome.port-only validator) |
| bookmarks | `all`, `add`, `remove`, `set_all`, ★`load`, ★`save` | `add`/`remove`/`set_all` → **bool** (True on change; dup/missing/empty → False; non-str / non-list → `TypeError`); strip-symmetric (BMK-03b kept) |
| blocks | `all`, ★`save_block`, ★`delete`, ★`set_all`, ★`load`, ★`save` | `save_block(name, block)` → bool (production name from `stack_bridge`; non-dict → `TypeError`; blank name → False; replaces in place, stamps `updated_at`); `delete` → bool; `set_all` → bool, non-list → `TypeError`; `named_*` **removed** (named presets live in `PresetStore`); `load`/`save` for the facade lifecycle (mutations also autosave) |
| session | `get`, `set`, `data`, ★`load`, ★`save` | `set(**updates, save_now=True)` → None (kwarg renamed `save`→`save_now` per the facade; SES-04 updated); `data()` deep copy kept |
| undo | `get`, `push`, `set`, ★`history`, ★`index`, ★`save_state`, ★`load_state`, ★`reload`, ★`flush`, ★`load`, ★`save` | `get`/`push`/`set` semantics kept exactly (tuple, Result, clamp+cap); `history()`→list copy, `index()`→int (facade + 2 suites pin list, not tuple); `save_state(h,i,save_now=True)`; `load_state()`=`get()` alias (protocol); `reload`/`flush` mirror labels naming (`flush`→Result, `load`/`reload`→None) |

### 3.4 Constants

- `stores/settings_store.py`: ★`SETTINGS_DEFAULTS` — the six settings
  slices (`chrome scroll delays ui history collector`) referenced from
  `DEFAULTS`. `DEFAULTS` (full tree) stays for internal fallback.
- `stores/bookmark_store.py`: `DEFAULT_URLS` renamed to
  ★`DEFAULT_BOOKMARKS` (sole importer is the BMK suite, updated; the
  two shipped URLs unchanged).

### 3.5 `migrate_legacy_config(legacy_abspath, config_dir)`

Semantics pinned by `tests/test_stores_split.py::MigrationCase`:

1. If `<config_dir>/settings.json` exists → return
   `{"migrated": False, "archived": None}`; the legacy file is **untouched**
   (idempotency: stores win).
2. If the legacy file is missing, unreadable, or unparseable → same
   return; a corrupt file is **kept** for repair.
3. Else parse (top-level non-dict JSON counts as empty), write all 7
   files (absent section → default content; hostile shapes → defaults —
   non-list `url_presets`/`custom_blocks`, non-dict `state`/preset
   groups; labels shallow-merged over `LABELS_DEFAULT`; undo index
   coerced to int, default `-1`), then rename the legacy file to
   `config.json.migrated-<UTC-stamp>` in its own directory
   (archived, never deleted). Return
   `{"migrated": True, "archived": <path>}` (`archived` is `None` if
   the rename itself fails — files already written, next construction
   skips via rule 1).
4. Settings file gets present-sections-only (`{}` when the legacy has
   none — the overlay design serves defaults at read time).

`migrate()` / `needs_migration()` are kept unchanged alongside (different
job: single-file key ensuring, still pinned).

### 3.6 Facade call-site checklist (no facade diff)

`settings.load/save/get/set(data)/data/validate` ✓ ·
`bookmarks.load/save/all/add/remove/set_all` ✓ ·
`blocks.load/save/all/set_all` ✓ · `session.load/save/get/set(save_now)/data` ✓ ·
`labels_file.reload/flush/data/set_data/named_*` ✓ (exist) ·
`presets.load/save/named_*/save_stack/…` ✓ (exist) ·
`undo.reload/flush/history/index/save_state/_path` ✓ ·
`migrate_legacy_config` ✓ · `SETTINGS_DEFAULTS` ✓ ·
`DEFAULT_BOOKMARKS` ✓ · `config_dir_for` ✓ (exists).

### 3.7 Protocols (`core/interfaces.py`) + fakes

`test_interfaces_full.py` fails at import (5 missing names) and pins
fake vocabularies. Protocols are consumed by **zero** production modules
(verified) — the tests are the authority (SPEC verdicts, §7):

| Protocol | Change |
|---|---|
| `SettingsStoreProto` | keep `{get, set, save}`; enrich `FakeSettings` with `save()` (save is real — the facade needs it) |
| `BookmarkStoreProto` | keep `{all, add, remove}`; annotations `add`/`remove` → `bool` (honest; `isinstance`-agnostic) |
| ★`PresetStoreProto` | add 8 methods mirroring `FakePreset` == real `PresetStore` |
| ★`SessionStoreProto` | add `{get, set}` |
| ★`BlockStoreProto` | add `{all, save_block, delete}` (production vocabulary); enrich `FakeBlock` with `save_block` |
| `UndoStoreProto` | reshape `{push, history}` → `{load_state, save_state}` (the fake's vocabulary; dissolves the tuple-vs-list contradiction — `history()` stays off-protocol) |
| ★`PeopleRepoProto` | add `{get_all, get_queue, get_stats}` methods-only (no `db_path`: data members break `runtime_checkable`) |
| ★`UserRecordProto` | add plain (non-runtime) Protocol with the documented fields (imported, never `isinstance`-checked) |

`core/result.py` is **not** touched (no `__bool__` — global blast radius).

## 4. Test plan

### 4.1 New suites

`tests/test_backend_shims.py` — SHM-01…06 (§2).
`tests/test_stores_split_stores.py` — rows below. Constructor for every
store: `Store(path)`.

| ID | What it takes | Expected path |
|---|---|---|
| LMC-01 | representative legacy file | 7 files land with the §3.5 mapping; legacy renamed to `config.json.migrated-*`, original gone |
| LMC-02 | legacy + existing `settings.json` | skipped: stores win, legacy byte-identical |
| LMC-03 | corrupt legacy (`{not json`) | fresh: `migrated` False, bad file kept |
| LMC-04 | missing legacy | fresh: `migrated` False, nothing written |
| LMC-05 | hostile legacy (`url_presets` dict, `state` list, preset groups str, labels partial, undo index `"x"`) | defaults substituted per §3.5, no raise |
| LMC-06 | legacy without `state`/undo keys | `undo.json` is `{"history": [], "index": -1}` |
| LMC-07 | valid JSON, non-dict top (`[1,2]`) | defaults migrated, legacy archived |
| LMC-08 | return value | `{"migrated": bool, "archived": path-or-None}` keys exact |
| BKS-01 | fresh file | `all()` == shipped defaults; file not created by reads |
| BKS-02 | add new / dup / `""` / `"   "` / non-str | True / False / False / False / `TypeError` |
| BKS-03 | remove present / missing / non-str | True / False / `TypeError` |
| BKS-04 | `set_all` ok / non-list | True + exact round-trip / `TypeError`, old list kept |
| BKS-05 | `load`/`save` + reopen | round-trip; corrupt file → defaults, no raise |
| BKS-06 | file shape | bare JSON list on disk |
| BLS-01 | `save_block` new / overwrite / non-dict / blank name | True / True in place + `updated_at` refreshed / `TypeError` / False |
| BLS-02 | `delete` present (padded) / missing | True / False (strip-symmetric) |
| BLS-03 | `set_all` ok / non-list | True + round-trip / `TypeError` |
| BLS-04 | `all()` copies | mutating the result never reaches the store |
| BLS-05 | file shape | bare JSON list of name/block entries on disk |
| BLS-06 | corrupt file / missing file | `[]`, no raise |
| BLS-07 | `named_*` gone | `hasattr(store, "named_set")` is False (moved to `PresetStore`) |
| SES-08 | `set(..., save_now=False)` + reopen | in memory, absent on disk; `save()` persists |
| SES-09 | `load`/`save` + reopen | round-trip; corrupt / dir-shaped / non-dict file → `{}`, no raise |
| SES-10 | file shape | flat dict on disk (no `"state"` wrapper) |
| SET-09 | `set` return + `load`/`save` | `set(...)` is None; round-trip through reopen |
| SET-10 | corrupt / non-dict file | overlay `{}`, defaults served, no raise |
| SET-11 | empty `set()` | raises `ValueError` (loud, preserved) |
| SET-12 | deep `set` through a clobbered section | scalar intermediate repaired to `{}`, no raise (hardened vs `AtomicJsonStore.set`, which crashed) |
| UND-08 | `history()` / `index()` | list copy + int; fresh is `[]` / `-1` |
| UND-09 | `save_state(h, i, save_now=False)` | memory updated, disk untouched until `flush()` |
| UND-10 | `load_state()` | == `get()` tuple |
| UND-11 | `reload`/`flush` | re-read tolerates corrupt; `flush()` → ok-Result |
| UND-12 | file shape | `{"history":[…], "index":n}` on disk |
| UND-13 | `load` normalizes a wild file | index 99 + 2 items → `get()` is `(hist, 1)` (write-invariant enforced on read) |

### 4.2 Rewrites (same files, contracts changed — SPEC, §7)

- `tests/test_stores_small_stores.py`: constructors `Store(atomic)` →
  `Store(path)` (drop the `AtomicJsonStore` import); BLK-01…10 →
  split-API (BLS vocabulary, `all`/`save_block`/`delete`/`set_all`);
  BMK-03/06 → bool; BMK-07 kept (`TypeError`); SES-04 `save=` →
  `save_now=`; SET rows unchanged (already return-agnostic); UND-01…07
  unchanged (semantics kept); LBF untouched.
- `tests/test_stores_migration.py::test_block_store_named` → split-API
  block round-trip (named-CRUD coverage already lives in PRS rows).
- `tests/unit/core/test_interfaces_full.py`: add `save()` to
  `FakeSettings`, `save_block` to `FakeBlock` (fixture enrichment —
  assertions preserved and extended, not weakened).
- Drop `@unittest.expectedFailure`: REG-02 (`test_action_registry.py:80`),
  CH-00 (`test_collect_history_contract.py:188`) — both assert normally
  after the fix.

### 4.3 Acceptance (existing suites turning green, no diff)

`test_stores_split` (18) · `test_config_manager*` (4+17) ·
`test_interfaces_full` (9) · the 19 BUG-02 collection-error modules ·
full `pytest tests/` with zero regressions (PySide6/websockets-excluded
suites aside, as at HEAD).

### 4.4 Doc updates

- `docs/STORES_TEST_DESIGN_2026-09-09.md`: update BLK/BMK/SES/SET rows to
  the §3 contracts (in place — the doc must describe current code);
  §15 ledger gains a pointer here.
- `docs/ACTIONS_TEST_DESIGN_2026-09-09.md` §12: BUG-02 → FIXED.

## 5. Risks / pins

1. CF#7 `expectedFailure` must keep failing — `SettingsStore.get` returns
   live objects; do not “fix” the aliasing.
2. `validate()` stays chrome.port-narrow (SET-06b + CF#6 pin it).
3. `MAX_STACK_HISTORY` re-export path (`stores/undo_store.py`,
   `config_manager`) unchanged.
4. Facade diff must be empty (`git diff --stat` shows no
   `backend/config_manager.py`).
5. No `Result.__bool__`, no `core/result.py` change.
6. `stores/history_*.py`, `media_store`, `label_store`, `user_memory`,
   `preset_store`, `labels_file_store`, `atomic`, `jsonio` logic diffs
   must be empty (only `migration.py`, small stores, `interfaces.py`).

## 6. Bug ledger

Filled during implementation. Verdicts: BUG (code violates the written
contract) / SPEC (contract decided/changed here).

| # | Test | Verdict | Detail |
|---|---|---|---|
| 1 | CF#1 `test_every_section_serves_a_documented_default` | BUG | `stores/settings_store.py` DEFAULTS `history.media.max_file_mb` was the stale pre-2026-09-07 value **2**; README §Settings, `BACKFILL_MEDIA_RECOVERY` F-1, `backend/history_parts/base.py` (`MAX_FILE_MB_DEFAULT = 25`) and the `MediaStore` ctor all say **25**. Fixed to 25. (§F never pinned the value — SET-01 only asserted non-None.) |
| 2 | `test_archive_delete_undo` (21× `NameError`) | BUG | `backend/collector_parts/mixin1.py` used `DEFAULTS` with the split having dropped the import; defined in `collector_parts/base.py`. Fixed with a base import (cycle-safe: base imports no mixins). Masked at HEAD by BUG-02. |
| 3 | cohort runs + pyflakes sweep | BUG | `collector_parts` mixins used `log` (5 files), `CollectorState` (3a/4a/4b), `IDLE_STATES` + `MAX_PROBE_PENALTY` (3a) without defining/importing them — same dropped-name split damage. Fixed (`log = logging.getLogger("chatbot")` per base.py convention + base imports). Repo-wide pyflakes sweep after the fix: zero undefined names in non-test code. |
| 4 | `test_collector_state` (31× `AttributeError`) | BUG | Backend `Collector` emits `status_changed` / `collector_log` / `history_appended` / `people_changed` and `bridge/collector_bridge.py` + tests connect all four, but the split dropped the `Signal` declarations. Declared all four as `Signal(str)` on `CollectorBase` (payloads are JSON strings). |
| 5 | pyflakes sweep | BUG | Undefined names in the healed import chain: `mixin3d` (`sync_conversation`, `UserRecord`), `mixin4b` (`verify_private`, `HistoryQuery`), `backend/chat_parser.py` (`AppendResult` missing from its own `history_models` import). Fixed with same-package imports. |
| 6 | full suite (327× `TypeError` in `object.__init__`) | BUG (test infra) | `tests/integration/services/test_run_service_paths.py` installed a fake `PySide6` into `sys.modules` unconditionally (`if "PySide6" not in sys.modules` — true at collection). With real Qt installed this shadowed it session-wide. Now stubs only when the real import fails. |
| 7 | repo working tree | BUG (test infra) | `tests/unit/backend/test_config_manager.py` constructed `ConfigManager()` against the CWD (docstring promised tmp isolation but never applied it): full-suite runs migrated and renamed the repo's tracked `config.json`. File restored byte-identical from git (`git checkout -- config.json`, verified against the archive content before deletion — zero loss). Test now `chdir`s into its tmpdir in `setUp` (assertions untouched). |
| 8 | out-of-tree runs | BUG (test infra) | 8 test files hardcoded `sys.path.insert(0, "/home/user/Chat-V-bot")` — breaks any other checkout and contaminated cross-tree baselines. Replaced with portable `dirname` chains (+ `import os` where missing). |
| S1 | BMK-03/06, `test_bookmarks_dedup` | SPEC | Bookmark `add`/`remove`/`set_all` return **bool** (split tests require falsy-on-dup; `Result` instances are always truthy and `__bool__` on `Result` was rejected as global blast radius). `BookmarkStoreProto` annotations updated. |
| S2 | BLK-01…10 | SPEC | `BlockStore.named_*` removed (named presets live in `PresetStore`); vocabulary is `all`/`save_block`/`delete`/`set_all`/`load`/`save` (`save_block` = production name from `stack_bridge`). |
| S3 | SES-04 | SPEC | `SessionStore.set` kwarg renamed `save` → `save_now` (facade contract is the authority). |
| S4 | SET-09 | SPEC | `SettingsStore.set` → `None` (protocol); new `save`/`flush` → `Result[None]`, `load`/`reload` → `None` (`PresetStore.save→None`, `LabelsFileStore.flush→bool` grandfathered pins). |
| S5 | UND-08, facade `get_state` | SPEC | `history()` → list + `index()` → int (facade + 2 suites overrule the stale `UndoStoreProto.history()->tuple`); protocol reshaped to `{load_state, save_state}`. |
| S6 | `test_interfaces_full` | SPEC | 5 protocols added, 2 reshaped/annotated (§3.7); `FakeSettings.save` + `FakeBlock.save_block` fixture enrichment (assertions preserved). `core/result.py` untouched. |
| S7 | CF#7 `test_get_returns_a_copy_too` | SPEC | Detector primed with a `set()` first: aliasing only manifests for overlay-resident values (defaults-fallback reads are copies by design). Now fails honestly (xfailed); `get()` aliasing preserved. |
| S8 | LMC-01…08 | SPEC | `migrate_legacy_config` semantics pinned (§3.5). |
| S9 | REG-02, CH-00 + 25 contract tests | SPEC | Post-fix the BUG-02 stub dance became a session-order-dependent no-op; replaced with a per-test `sync_conversation`→recorder patch (block/E2E split of responsibilities preserved). Both `expectedFailure`s dropped; tests assert normally. |
| S10 | SET-11/12 | SPEC | Empty `set()` → `ValueError` preserved (loud); deep `set` through a scalar-clobbered path repairs it (hardened vs `AtomicJsonStore.set`, which crashed with `AttributeError`). |
| S11 | UND-13 | SPEC | `UndoStore.load()` normalizes wild files through the write invariant (`_assign`); readers never see unusable `(history, index)` pairs. |
| S12 | BMK-01b, facade imports | SPEC | `DEFAULT_URLS` → `DEFAULT_BOOKMARKS` rename; `SETTINGS_DEFAULTS` added (6 slices referenced from `DEFAULTS`). |

## 7. Next blockers (out of scope — filed with evidence for the next section)

Full suite now: **1492 passed / 202 failed / 10 errors** (true HEAD
baseline: 837 / 110 / 52). Every remaining red line is either red at
baseline or in a module that was a collection ERROR at baseline
(mechanically verified: zero suspect lines); every failure reason is in
files this change never touched (`git status`: no `bridge/`,
`services/`, or `core/` source changes except `core/interfaces.py`).

| ID | Symptom | Evidence | Suspected seam |
|---|---|---|---|
| N1 | `ImportError: cannot import name 'ConnectionChanged'/'LogMessage'/'PeopleChanged' from 'core.events'` (19×) + 4 collection ERRORs | `core/events.py` is a 45-line string-topic `EventBus`; `bridge/cdp_bridge.py`, `bridge/collector_bridge.py`, `services/cdp_service.py`, `services/people_service.py`, `services/undo_service.py` import typed event classes. Two competing bus designs — needs a which-wins decision, not a patch. | `core/` + typed-events world |
| N2 | `ImportError: cannot import name 'DbService'` (3×) + 3 collection ERRORs | `services/db_service.py` defines only `DbManager`; `services/__init__.py` + `app/container.py` expect `DbService`. Unblocks nothing alone (N1 stands behind it). | `services/` rename drift |
| N3 | `ImportError: cannot import name 'Ok' from 'core.result'` (3×, all collection ERRORs) | `core/result.py` exports only `Result`; `test_core_contracts`, `test_core_integration`, `test_core_logic_coverage` expect `Ok/Err/ok/err` helpers. | `core/` API drift |
| N4 | `AttributeError: 'Router' object has no attribute …` (~150×: `_domains`, `label_create`, `save_grid_layout`, `_bridge`, …) | Already filed as BUG-10 (`docs/ACTIONS_TEST_DESIGN_2026-09-09.md` §12): `Router` never aggregates the domain bridges. | `bridge/` (architectural) |
| N5 | `test_container`/`test_di` `Container` API mismatches (`get`, `register_value`, not iterable) | `tests/unit/core/test_di.py` vs `core/di.py` — pre-existing, untouched here. | `core/di.py` |
