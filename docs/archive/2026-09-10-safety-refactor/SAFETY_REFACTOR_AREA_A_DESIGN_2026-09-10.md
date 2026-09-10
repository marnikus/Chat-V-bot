# AREA A — Deletion Safety: New-Structure Design (implementation blueprint)

Date: 2026-09-10 · Branch: `arena/01a08b7b-chat-v-bot` · Baseline: `3820136`
Parent: `docs/archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_2026-09-10_PLAN.md` + `docs/archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_A_2026-09-10.md`
Status: **Design — tests to be written before any production change.**
Owner: AREA A only. No B/C files. Frozen files per master plan §2 are untouched.

> Process followed here: (1) understand fully, (2) design new structure doc
> first, (3) full test coverage before refactoring, (4) implement + run tests.

---

## 1. Problem restated (measured, not assumed)

Current flow (`DbLifecycle.delete`):

```
resolve/list → footprint (victim scan) → switch active world → detach
→ unlink main/WAL/SHM → scan other references → unlink media
→ rmtree whole world folder → forget → return success
```

Proved defects (master plan §1, reproduced on temp dirs):

1. **Per-file keep bypassed by `rmtree`.** `_delete_world_media` skips `keep`
   per file, then unconditionally `shutil.rmtree(world_folder)`. A shared file
   inside the victim folder does not survive. Reproduced.
2. **Unreadable scan looks empty.** `_media_references` catches all and returns
   `set()`. No completeness flag. Reproduced information loss.
3. **Scan happens too late.** `delete` unlinks SQLite files before
   `_other_references` runs. Code-inspection risk.
4. **Partial failures misleading.** Main file first in `SUFFIXES`; media unlink
   failures swallowed (`log.debug`); bridge logs complete success. No
   `removed/retained/failed` lists.
5. **Switch-before-failure not refreshed.** Fallback switch can succeed, later
   unlink can fail, but `emit_db_change(switched)` and `restart_world` are
   conditioned on `ok`. UI caches stay stale.
6. **Inventory incomplete.** `existing_worlds()` = active-folder scan + active
   file. `known_paths()` (remembered, possibly other folders) ignored. Victim's
   own directory ignored when it differs from active folder.
7. **Path policy weak.** `abspath` + string prefix; symlinks/junctions not
   handled; directory symlinks traversed implicitly; same-stem worlds share one
   `saved_media/<stem>/` folder but code treats it as exclusive.
8. **No serialization / TOCTOU.** Overlapping `delete`/`create`/`load`/`clean`
   on one manager interleave; reference scan → deletion window unguarded;
   no revalidation; cancellation has no defined boundary.

Contracts to preserve (master plan §3.1):

- Same Qt slot names/signatures, `bridge` object, signals, payload keys/types.
- Same `DbManager.delete(path) -> dict`; successful permanent deletion never
  creates undo; Clean stays reversible.
- Same public lifecycle entrypoints; no new global Qt fakes, schema migration,
  dependency, or cross-process lock.
- `services/undo_service.py`, `services/history/*`, `stores/*`, `core/*`,
  `backend/*`, `bridge/context.py`, `tests/conftest.py` are **frozen**.

---

## 2. Target structure

### 2.1 File map (A-owned only)

```
services/db_media_scan.py   NEW — strict read-only scan, URI escaping, schema rule
services/db_deletion.py     NEW — plan/result types, inventory, path policy,
                                  bounded filesystem helpers (no framework)
services/db_service.py      EDIT — keep _media_references for compat; fix
                                   misleading comment; delegate delete to lifecycle
services/db_registry.py     EDIT — add deletion inventory helper; keep all
                                   existing reads byte-compatible
services/db_lifecycle.py    EDIT — delete orchestration only (plus lock +
                                   unlocked delegates); create/load/clean/restore
                                   behavior unchanged except serialization
bridge/db_bridge.py         EDIT — truthful result handling; refresh on
                                   world_changed even when ok==False; never log
                                   false success; never push delete undo
ui/js/db-panel.js           EDIT ONLY IF needed — current error+refresh path
                                   already renders error; add partial test first
tests/integration/safety_deletion/  NEW — all A regressions (see §5)
tests/test_db_panel_js.js   EDIT — add partial/world_changed rendering cases
docs/archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_A_2026-09-10.md  EDIT — append implementation journal
```

No other production file is touched. In particular `emit_db_change` /
`restart_world` stay in frozen `services/undo_service.py`; `DbBridge` calls
them but does not change them.

### 2.2 New module: `services/db_media_scan.py`

Strict, read-only, fail-closed. Never returns “empty” for “unreadable”.

```python
@dataclass(frozen=True)
class MediaScanResult:
    path: str                 # world scanned (as passed, absolute)
    references: frozenset[str]  # abspath of each cached cache_path (may be empty when complete)
    complete: bool            # True only when the scan is trustworthy
    reason: str               # ok | missing_file | missing_media_table | unsupported_schema |
                              # corrupt | locked | io_error | query_error
    detail: str               # human-readable diagnostic (which world, what failed)
    schema_version: str | None

def sqlite_ro_uri(path: str) -> str
    # Correct escaping: quote path segments for ?, #, %, spaces, unicode.
    # file:<quoted-abs-path>?mode=ro  (POSIX; Windows handled via normpath+quote)

async def scan_world_media(path: str, *, timeout_s: float = 2.0) -> MediaScanResult
    # - missing file → complete=False, reason=missing_file (caller decides)
    # - open read-only via aiosqlite with short busy timeout; locked/busy → complete=False
    # - check sqlite_master for media table; missing → complete=False (not empty)
    # - read schema_meta.schema_version when present; versions {"5","6"} supported;
    #   missing version with media table present → still complete (legacy) but reason=ok?
    #   Decision: missing version + media present = complete (legacy world), schema_version=None.
    #   Missing media table = incomplete regardless of version (proves §A2 rule).
    # - SELECT cache_path FROM media WHERE state='cached' AND cache_path<>'' ...
    # - any sqlite error / decode error → complete=False, references=frozenset()
    # - success → complete=True, reason=ok, references as abspath set
```

Why `frozenset[str]` + `complete`: callers must branch on `complete` before
using `references`. Legacy `_media_references(path)->set` stays for old
callers/tests; destructive code never calls it.

URI edge matrix (tested): spaces, `?`, `#`, `%`, unicode (Cyrillic/emoji),
long names. Implementation uses `urllib.parse.quote(abs_path, safe="/:")` on
POSIX and `quote(normpath, safe="/:\\")` handling for Windows drive prefix.
Validated against real SQLite files with those names.

### 2.3 New module: `services/db_deletion.py`

Internal types + pure/bounded helpers. No generic transaction framework, no
new dependency, no cross-process lock.

```python
DB_GROUP_SUFFIXES = ("", "-wal", "-shm", "-journal")
# SUFFIXES in db_service stays ("","-wal","-shm") for compat; deletion uses
# the extended group (journal is best-effort: missing is fine, present is removed).
# file_group_size() keeps old tuple (no size-contract change).

SUPPORTED_SCHEMA_VERSIONS = {"5", "6"}
SUPPORTED_BOUNDARY = (
  "active folder scan + active file + victim-directory scan + "
  "remembered in-root .db paths (deduped). Worlds outside this boundary "
  "are NOT protected; deletion never claims otherwise."
)

@dataclass
class DeletionInventory:
    worlds: list[str]        # canonical abspaths, sorted, deduped, victim excluded for keep-scan
    complete: bool
    diagnostics: list[str]   # which source failed, if any
    victim_abs: str
    victim_in_scope: bool

def build_deletion_inventory(*, registry, victim_abs: str) -> DeletionInventory
    # Sources (all best-effort, failure → complete=False):
    #  1. registry.existing_worlds()  (active folder + active file)
    #  2. victim-directory *.db scan (when victim dir != active dir)
    #  3. registry.known_paths() filtered to in-root + exists + *.db
    #  4. active_path when it exists
    # Dedup by os.path.realpath fallback abspath; sort for determinism.
    # victim_in_scope = victim found in union OR victim dir scan succeeded.
    # If victim not in scope → caller refuses (unregistered/unsupported).

@dataclass
class DeletionPlan:
    victim_abs: str
    victim_folder_abs: str   # media_dir(victim)
    media_base_abs: str
    footprint_files: frozenset[str]  # victim refs inside base (abspath)
    discovered_files: frozenset[str] # walk of exclusive victim folder (no symlink dirs)
    keep: frozenset[str]             # union of other-world refs (complete scans only)
    candidates: frozenset[str]       # (footprint ∪ discovered) − keep, after path policy
    retained: frozenset[str]         # footprint/discovered ∩ keep  + policy-excluded
    folder_exclusive: bool           # False when another world shares same media_dir
    inventory: DeletionInventory
    scan_details: list[MediaScanResult]

@dataclass
class DeletionOutcome:
    ok: bool; phase: str; error: str; partial: bool; world_changed: bool
    active_path: str; removed_paths: list[str]; retained_paths: list[str]
    failed_paths: list[str]; media_files_removed: int
    # + compat keys: op="delete", path=victim, was_active, before_path=victim
    def as_dict(self) -> dict  # frozen contract §3.2 order

# Path policy (pure, tested without DB):
def canonical(path: str) -> str          # realpath fallback abspath+normpath
def is_within(child_abs: str, root_abs: str) -> bool
    # realpath both; commonpath == root and child != root. No string-prefix.
def should_descend_dir(dirpath: str) -> bool
    # False for symlink/junction (islink or not isdir after lstat check)
def classify_candidate(*, candidate_abs, base_abs, victim_folder_abs,
                       folder_exclusive, keep, other_world_folders) -> str
    # returns "remove" | "retain:shared" | "retain:outside_root" |
    #         "retain:root" | "retain:other_world_folder" |
    #         "retain:ambiguous_folder" | "retain:symlink" | "retain:not_file"
    # Rules:
    #  - symlink (islink) → retain (never follow; target always survives)
    #  - not within base → retain:outside_root
    #  - == base or == victim_folder when not exclusive? (see below)
    #  - within another world's folder → retain:other_world_folder
    #  - in keep → retain:shared
    #  - discovered file but folder not exclusive → retain:ambiguous_folder
    #  - not a regular file (dir, fifo, etc.) → retain:not_file (dirs pruned separately)
    #  - else remove

async def collect_discovered_files(victim_folder_abs, base_abs) -> set[str]
    # os.walk topdown, followlinks=False; prune symlink dirs in-place;
    # yield regular files only (islink → skip, record as retained elsewhere).
    # Any walk OSError → raise to caller (inventory/plan incomplete).

def plan_deletion(...) -> DeletionPlan  # pure combination + policy; no I/O except walk
def prune_empty_dirs(*, start_dirs, base_abs, victim_folder_abs, folder_exclusive,
                     other_world_folders) -> list[str]  # removed dirs (best-effort)
    # Only rmdir verified-empty dirs strictly inside base, never base itself,
    # never another world's folder, never outside victim folder unless legacy
    # footprint file's parent chain (still inside base). Never rmtree.
```

Filesystem helpers are bounded: `unlink_one(path) -> (ok, error)` catches
`OSError`, never raises for missing file (idempotent). `remove_db_group(victim)`
iterates `DB_GROUP_SUFFIXES` in order `["", "-wal", "-shm", "-journal"]`? Order
matters for crash-safety: main file first vs sidecars first. Current code does
main first. Spec warns “Do not blindly reorder sidecars before main without
proving DB is checkpointed and closed.” Decision: **keep main-first order**
(main, wal, shm, journal) because connections are closed/detached before unlink
and SQLite in WAL mode without main is unopenable anyway; sidecar-first would
leave a valid main with stale WAL on crash (worse). Documented; tested via
partial-injection at every element.

### 2.4 `DbLifecycle.delete` orchestration (phases)

```
validate → scan/plan → switch → detach → revalidate → database → media → finalize
```

Phase strings frozen: `validate|scan|switch|detach|database|media|finalize`.

Pseudocode (unlocked delegate; public wrapper holds lock):

```
async def delete(path):  # public, serialized (see §2.6)
    async with _deletion_lock_for(self):   # non-reentrant, per-manager + global fallback
        return await self._delete_unlocked(path)

async def _delete_unlocked(path):
    victim = registry.resolve(path)
    if not victim or not exists(victim): return refuse(validate, "that database does not exist")
    victim_abs = abspath(victim)
    existing = inventory_worlds_including_victim?  # for last-world rule use existing_worlds()
    if len(existing_worlds) < 2: return refuse(validate, last-database, last_database=True)
    # --- scan/plan BEFORE any switch/unlink (fixes late-scan) ---
    inventory = build_deletion_inventory(registry, victim_abs)
    if not inventory.complete: return refuse(scan, "cannot verify ...", inventory diagnostics)
    if not inventory.victim_in_scope: return refuse(scan, unsupported/unregistered)
    victim_scan = scan_world_media(victim_abs)
    if not victim_scan.complete: return refuse(scan, victim unreadable)
    other_scans = [scan_world_media(w) for w in inventory.worlds if w != victim_abs]
    if any incomplete: return refuse(scan, which world could not be verified)
    keep = union(other refs); footprint = victim refs inside base
    discovered = collect_discovered_files(...) if exclusive else set()
    plan = plan_deletion(...)  # pure policy
    # --- switch (only when victim was active) ---
    was_active = (victim_abs == abspath(active_path()))
    world_changed = False
    if was_active and service is not None:
        fallback = _pick_fallback(victim)
        if not fallback: return refuse(switch, "no other database to switch to")
        opened = await _load_unlocked(fallback)   # unlocked delegate, no deadlock
        if not opened.ok: return refuse(switch, opened.error, world_changed=False)
        world_changed = True
    # --- detach any lingering handle on victim ---
    try: detach/memory-close when pointing at victim
    except: return fail(detach, ..., world_changed)
    # --- revalidate (TOCTOU guard) ---
    re_scan = scan others again (same inventory + fresh inventory build?)
    if inventory changed (new/lost world) or keep grew:
        return refuse(database? or scan?, "references changed during deletion, retry",
                      world_changed, phase="database" with no removals)
    # Note: revalidation failure happens BEFORE any unlink → partial=False.
    # --- irreversible boundary starts here ---
    irreversible_started = False
    removed, failed = [], []
    try:
        # database group
        for suffix in DB_GROUP_SUFFIXES:
            p = victim + suffix
            if not exists(p): continue   # idempotent, not counted
            irreversible_started = True  # about to mutate (set before unlink? see cancellation)
            ok, err = unlink_one(p)
            (removed or failed).append(p)
        if failed:  # preserve remaining files/media, reconcile, report partial
            reconcile_active_path(); prune_remembered? NO — victim still exists partially → do NOT forget
            return partial(database, removed, failed, world_changed, active_path=observed)
        # media
        for cand in sorted(plan.candidates):
            irreversible_started = True
            ok, err = unlink_one(cand)
            ... count actual removals only ...
            on success: prune parent chain when empty (bounded, never base/other folder)
        # prune exclusive victim folder itself when verified empty (rmdir, never rmtree)
        # reconcile + finalize
        try:
            _forget(victim); if was_active: _persist_path(active_path())
        except Exception as exc:
            return partial(finalize, removed+media_removed, failed+[], world_changed, active=observed)
        return success(world_changed, removed, retained, media_files_removed=len(media_removed))
    except asyncio.CancelledError:
        # mandatory reconciliation after irreversible work, then propagate
        if irreversible_started:
            try: reconcile (prune remembered only if victim group fully gone? else keep)
            except: pass
            log.warning("delete cancelled after partial work: ...")
        raise
    finally:
        # try/finally for mandatory state reconciliation (active_path observation)
        pass
```

Key decisions:

- **No unlink before complete scans.** Victim + all inventory worlds scanned
  before switch/unlink. Any incomplete → refuse, no switch, no unlink, no
  config mutation. This fixes fail-open and late-scan in one move.
- **Switch only after approved plan.** Fallback switch still uses full
  `switch_db` (fail-closed inside HistoryService). Switch failure → victim
  untouched, original usable, `world_changed=False`.
- **Detach after switch, before revalidate.** Same guards as today, but with
  phase + `world_changed` propagation.
- **Revalidate before irreversible work.** Fresh inventory + fresh keep-scan;
  any new world, lost world, or grown keep → refuse with `phase=database`
  (or `scan`? decision: `database` with `partial=False`, `removed=[]` — the
  refusal happens at the database gate before any unlink). Test asserts no
  unlink. This invalidates stale plans without a cross-layer lock.
- **Main-first group order kept.** Documented crash rationale; journal added
  as 4th element (best-effort).
- **Never `rmtree`.** Per-file unlink + `rmdir` of verified-empty dirs only.
- **Counters truthful.** `media_files_removed` = actual unlinks, including
  discovered exclusive-folder files. Shared retentions are not failures.
- **Finalize failures are partial, not success.** Files stay reported as
  removed; `active_path` is observed (`registry.active_path()` after work),
  never a guessed fallback.
- **Cancellation:** before `irreversible_started` → no removal, propagate;
  after → reconcile + warn-log + propagate. No `shield()` around destructive
  loop.

Last-world rule stays on `existing_worlds()` (UI-visible list), not on the
wider inventory, to keep `can_delete`/`delete_hint` consistent. Inventory is
for safety scanning, not for the count gate. Documented.

### 2.5 `DbRegistry` addition

```python
def deletion_inventory_sources(self, victim_abs: str) -> dict
    # Returns the raw source lists for build_deletion_inventory (testable):
    # {"active_folder": [...], "victim_folder": [...], "remembered": [...], "active": ...}
    # Existing methods unchanged; new helper only reads.
```

`existing_worlds()`, `known_paths()`, `resolve()`, `list_dbs()`, `info()`
byte-compatible. No behavior change except the new helper.

### 2.6 Concurrency

- One `asyncio.Lock` per `DbManager` (`self._op_lock`, created lazily to avoid
  loop binding) + one **process-global** `asyncio.Lock` keyed by normalized
  root (`_GLOBAL_DELETE_LOCKS: dict[str, asyncio.Lock]`)? Decision for this
  area: **per-manager lock + global root lock, acquired in fixed order**
  (global first, then manager) with unlocked delegates for internal calls.
  Rationale: production has one manager/one service, but tests and future
  callers may build several managers over one root; root-keyed global lock
  prevents “two managers delete the last two worlds” while fixed order
  prevents deadlock. `HistoryService.switch_db` direct callers bypass the
  manager lock — documented limitation; destructive work checks
  `service.db.path` / inventory at revalidate time and refuses on surprise
  change rather than pretending to exclude external writers. No cross-process
  lock claimed.
- Public `create/load/delete/clean/restore_backup` acquire; internal
  `_create_unlocked/_load_unlocked/...` do the work. `delete` calls
  `_load_unlocked` (no deadlock). Non-reentrant: attempt to re-acquire from
  same task raises/defers? `asyncio.Lock` is not reentrant; internal callers
  must use unlocked variants — enforced by code review + test (delete of
  active world succeeds without deadlock).
- Overlapping deletes test: two concurrent `delete` of the last two worlds →
  one wins, other sees `<2` worlds and refuses `last_database`. At least one
  world survives. Implemented via locks + re-check of `existing_worlds()`
  inside the lock (not before).

Background media writes: `MediaStore` writes new files during collection.
Quiesce strategy within owned files: none (collector lives outside A). Instead
revalidate detects grown keep and refuses; newly written but unreferenced files
in victim folder are discovered at plan time — if written after plan, they
survive (safe direction: leftover, not deleted-while-referenced). Documented.

### 2.7 `DbBridge` handling

```python
async def work():
    result = dict(await runner(manager) or {})
    result["op"] = result.get("op", op)
    world_changed = bool(result.get("world_changed")) or (
        op in ("create","load","delete") and bool(result.get("ok"))
        and not result.get("unchanged") and not result.get("offline"))
    # Preserve explicit world_changed from manager; derive for legacy success.
    if result.get("world_changed") is None and world_changed:
        result["world_changed"] = True
    if result.get("ok") and not unchanged and not offline:
        if op in (...): await restart_world(...)
        if op != "delete": push undo
        bus.emit(LogMessage(success... level="success"))
    else:
        # NEW: even on failure, rebuild world-bound surfaces when the live
        # world actually moved (switch-only change / partial after switch).
        if op in ("create","load","delete") and result.get("world_changed"):
            try: await restart_world(...)
            except: log.warning(...)
            # ensure wire payload tells JS to drop caches
            result["switched"] = True
        if result.get("error"):
            # partial vs plain refusal: warn level, never success
            level = "warn"  # (LogMessage; emit_db_change also warns)
            bus.emit(LogMessage("⚠ "+error, level))
        # no undo push on failure; no delete push ever
    emit_db_change(bus, op, result)  # frozen; our pre-set switched survives
```

Guarantees: no success log when `ok==False`; no delete undo entry on any path;
`db_changed` always emitted; `switched=True` present when `world_changed`
even on failure (so `app.js` + `db-panel.js` drop caches via existing
handlers); `UserDbChanged` still emitted via `emit_db_change`.

`emit_db_change` itself is frozen and stays `switched`-on-`ok` — our pre-set
`result["switched"]` survives because the helper only adds, never clears.

### 2.8 JS (`ui/js/db-panel.js`)

Current `onChanged` already: on `error` → `refresh()` + show `⚠ error`;
on `switched` (no error) → stash “Fresh world” notice + `refresh()`;
always `refresh()` on change. That renders the additive contract without
change: partial payload has `error`, so it shows + re-measures; `switched`
pre-set on `world_changed` triggers cache-drop in `app.js` (which listens to
every `db_changed` regardless of `ok`).

Decision: **no production JS change unless the new JS test proves a gap.**
Add `tests/test_db_panel_js.js` cases: partial payload (`ok:false,
partial:true, world_changed:true, error, removed/retained/failed paths`)
renders error, triggers `db_info` re-measure, does not throw on unknown keys;
`switched:true + error` still refreshes. If any case needs a JS tweak (e.g.
`world_changed` without `switched`), make the minimal edit and re-run.

### 2.9 Result contract (frozen §3.2 + compat)

Success:

```python
{"ok": True, "op": "delete", "path": victim_abs_or_as_resolved,
 "was_active": bool, "before_path": victim,
 "media_files_removed": int,          # actual unlinks
 "phase": "finalize", "partial": False, "world_changed": bool,
 "active_path": observed, "removed_paths": [...], "retained_paths": [...],
 "failed_paths": []}
```

Refusal (no irreversible work): `ok False, partial False`, `phase` =
validate/scan/switch/detach/database(revalidate), `error` readable,
`removed/failed=[]`, `retained` may list would-be candidates? Decision:
`retained=[]` on pre-work refusal (nothing classified as removed/retained yet)
except scan-refusal which includes `unverifiable_worlds: [...]` extra key?
Master plan allows additive fields; keep `retained` for post-work safety
exclusions, add `unverifiable_worlds` on scan refusal for debuggability.
`world_changed` True only when switch already succeeded (switch-gate failure
after partial switch? No — switch failure means no change; revalidate refusal
after switch means True).

Partial: `ok False, partial True`, `phase` = database/media/finalize,
`error` readable, `removed/retained/failed` exact, `media_files_removed`
actual, `world_changed` as observed, `active_path` observed.

`world_changed` vs `partial` stay distinct: switch-only change with no unlink
is `world_changed True, partial False`.

---

## 3. Inventory, schema & path policies (decisions)

- **Supported worlds:** `*.db` files inside app root discoverable via §2.3
  sources. Others (outside root, non-`.db`, undiscoverable subfolders never
  remembered) are **not scanned, not protected** — stated in result `detail`?
  No, stated in docs + `SUPPORTED_BOUNDARY`. Deletion never claims global
  protection.
- **Schema rule:** media-table presence required. Missing table → incomplete.
  `schema_version` in {5,6} or missing-with-media-table (legacy) → supported.
  Other versions → incomplete (`unsupported_schema`). No force-delete.
- **Same-stem:** `media_dir(a)==media_dir(b)` (canonical) → shared folder →
  `folder_exclusive=False`, no discovery, no folder prune, per-file policy only.
- **Symlinks:** never followed, never descended, never unlinked (retained).
  Outside target always survives. Skip reason documented when platform lacks
  symlink perm.
- **Containment:** `realpath` + `commonpath`, not prefix. Root itself, other
  worlds' folders, outside-root paths never removed.
- **Journal:** 4th group member, best-effort. WAL/SHM/main required handling;
  missing members skipped silently (idempotent).

---

## 4. What is NOT done (scope limits)

- No trash/recovery for permanent delete; no cross-process lock; no crash
  atomicity across FS/config/SQLite; no clean/recovery redesign; no world
  storage redesign; no B/C files; no `undo_service`/`history` changes; no
  dependency added; no schema migration.

---

## 5. Test plan (written BEFORE implementation)

Directory: `tests/integration/safety_deletion/` — independent local fixtures
(temp dirs, real SQLite, real `DbManager`/`DbLifecycle`; fault injection only
at `os.unlink`/`os.rmdir`/`shutil.*`/`service.switch_db`/`config.save`/`scan`
boundaries, never by replacing the method under test).

| File | Group | Must assert (bytes/state/events, not only `ok`) |
|---|---|---|
| `test_last_and_validate.py` | last/invalid/missing/out-of-root | no unlink, no switch, no `db_recent`/`db_path` mutation, `phase=validate`, clear error |
| `test_shared_inside_victim.py` | shared inside victim folder | other world refs it; file+bytes survive full `delete`; victim DB gone on permitted delete (FAILS on baseline via rmtree) |
| `test_shared_outside_victim.py` | shared outside victim, inside root | retained; unrelated folders untouched; unshared legacy swept |
| `test_corrupt_scan_refusal.py` | corrupt/locked/unsupported other DB | `complete=False` distinguished; **no victim/media unlink** (FAILS on baseline which deletes) |
| `test_empty_scan_allows_cleanup.py` | valid empty refs | normal unshared cleanup works; not universal no-op |
| `test_inventory_and_uri.py` | in-root other folder, dupes, same-stem, spaces/unicode/`?#%`, scan failure | inventory includes remembered out-of-folder world; dedupes; same-stem retains; URI names scan correctly |
| `test_switch_failure.py` | switch fails | original usable (`is_open`, row counts), victim/media untouched, `world_changed=False` |
| `test_detach_failure.py` | detach/memory-close fails | no unlink; connected state + `phase=detach` accurate |
| `test_partial_sqlite.py` | inject at every group element | exact survivors, `partial=True`, `phase=database`, truthful lists/counts |
| `test_media_failures.py` | unlink/prune fails | no false success; shared intact; `removed/retained/failed` + counts exact |
| `test_finalize_failure.py` | config save fails | removed stay reported; `active_path` observed, stale not valid; `phase=finalize` |
| `test_traversal_symlink.py` | traversal/symlink/ambiguous | no escape, no root removal, no cross-world sweep; symlink target survives |
| `test_cancel_concurrency.py` | cancel before/after; overlapping deletes; stale plan | before→no removal+Cancelled; after→reconciled+Cancelled; two deletes leave ≥1 world; grown keep invalidates |
| `test_bridge_results.py` | bridge success/refusal/switch-only/partial | `db_changed` payload, log level, `restart_world` called on `world_changed`, no delete undo |
| `test_clean_load_regression.py` | clean/load/create | reversible clean + fail-closed switch unchanged |
| `tests/test_db_panel_js.js` (extend) | partial payload | renders `error`, re-measures, tolerates new keys |

Baseline demonstration: at least `test_shared_inside_victim` and
`test_corrupt_scan_refusal` must FAIL on baseline; all must PASS after.
Fault tests inspect files/bytes/config/events, use `IsolatedAsyncioTestCase`,
real `HistoryService` where cheap else minimal fake service exposing
`db.path/is_open`, `memory.db_path`, `switch_db/detach_db/media_base_dir`.

Coverage targets (master plan §5): new scan/deletion modules ≥90% line /
≥85% branch; `DbBridge` ≥85%/80%; global never below 80%/75% (baseline
88.44%/81.32% explained if reduced).

---

## 6. Implementation steps (after green-red baseline)

1. Land tests (red) + record failing baseline outcomes in journal.
2. Add `services/db_media_scan.py` + unit-probe via new tests (no caller yet).
3. Add `services/db_deletion.py` (inventory/policy/helpers) + pure tests.
4. Rewire `DbLifecycle.delete` to strict phases + locks/unlocked delegates;
   keep `create/load/clean/restore` behavior, add serialization only.
5. Fix `DbBridge` handling per §2.7; prove no false success / no delete undo.
6. JS test first; minimal `db-panel.js` edit only if proved necessary.
7. Run targeted → full Python → JS entrypoints → coverage → `git diff --check`.
8. Fill journal: branch/head, changed files, repros, commands/results,
   coverage, API compat, deferred risks.

Commit boundaries: (1) design doc, (2) failing tests, (3) scan+deletion
modules, (4) lifecycle+bridge fix, (5) journal+coverage. No standalone red
commit released.

---

## 7. Acceptance & gates

```bash
.venv/bin/python tools/build_stubs.py .venv /tmp/stublibs
export QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs
.venv/bin/python -m pytest tests --collect-only -q
.venv/bin/python -m pytest tests/integration/safety_deletion -q
COVERAGE_FILE=/home/user/analysis/.coverage .venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
COVERAGE_FILE=/home/user/analysis/.coverage .venv/bin/python -m coverage json -o /home/user/analysis/coverage.json
status=0; for f in tests/test_*.js; do node "$f" || status=1; done; test "$status" -eq 0
.venv/bin/python tools/metrics/current_audit.py > /home/user/analysis/current.json
git diff --check
```

- New safety tests pass; key tests demonstrated failing on baseline.
- Existing suite still passes; no new skip/xfail/exclusion.
- Coverage per §5; new helpers CC≤10/cog≤15/nest≤4 (no one-line scatter).
- JS 20/20 (baseline stale `test_bridge_router.js` failure remains until B;
  no new JS failures; new partial cases green).
- No unawaited coroutines / leaked handles / Qt contamination.
- Desktop smoke (manual, before release): two disposable worlds;
  switch/delete/cancel wait; people/labels/undo refresh; real-WebEngine on
  display/GL. Never valuable DBs.

---

## 8. Risks & explicit non-promises

- External processes / crashes mid-unlink can leave partial group; reported
  truthfully, never rolled back (no file resurrection claim).
- Direct `HistoryService.switch_db` callers bypass manager locks; revalidate
  refuses on surprise, but cannot exclude them.
- Worlds outside `SUPPORTED_BOUNDARY` are not protected; if product later
  allows sharing with such worlds, this design must be revisited (master plan
  §A2 blocker).
- Instance+root locks serialize in-process managers only; no cross-process
  guard.

---

## 9. Journal placeholder (filled after implementation)

- Actual branch/head, changed files, baseline repros, test commands/results,
  coverage (line+branch separately), API compat diff, deferred risks.
  (Full journal lives in `docs/archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_A_2026-09-10.md`.)
