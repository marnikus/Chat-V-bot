# DB Creation & Deletion Redesign — Unified Single-DB ("One DB = One World")

Date: 2026-09-08
Status: **design, written before the code changes** (repo process). Implemented
in the same branch; the test map at the bottom is the acceptance gate.

Feature request: "One DB = One Complete World" — every database is a fully
independent, self-contained world; deletion is permanent and leaves no orphans;
the last world cannot be deleted; every switch starts the app fresh; all
information lives in ONE database file per world.

---

## 1. Problem statement (what the DB Connection window showed)

```
● neDBv3.db — 136 KB — CONNECTED — [Delete]
    Full DB Size: 65 MB (DB file + WAL + temp)
    Images Folder: 65 MB (59 files in saved_media)
    People: 2 rows in this database
○ chat.db — missing
○ chatbot.db — 345 KB — [Load] [Delete]
○ history.db — missing
```

Five visible defects, all with the same root cause: **one logical world is
split across several files, several of which no switch ever touches.**

| # | Defect on screen | Root cause in code |
|---|---|---|
| V1 | "missing" ghost rows (`chat.db`, `history.db`) | `DbManager.list_dbs()` merges remembered paths (`state.db_recent`) even when the file is gone; nothing ever prunes them |
| V2 | `chatbot.db` listed — the user can **[Delete]** their People queue from the DB window | the list is "every `*.db` in the folder"; `chatbot.db` (UserMemory queue) is not a world, it is a second file of the SAME world |
| V3 | "Images Folder 65 MB in saved_media" attributed to one DB | `saved_media/` is ONE shared folder for every DB; one world's bytes are measured (and would be orphaned) when another world is deleted |
| V4 | "People: 2 rows" — but the People *list* comes from a different file that never switches | `UserMemory` hardcodes `chatbot.db`; `HistoryService.switch_db()` only re-binds the archive (`persons/messages/media/cursors/gaps`) |
| V5 | Labels, undo history, per-DB settings are invisible ghosts of shared state | `config.json` holds `labels`, the global undo timeline and the history/collector settings for ALL worlds |

Consequences already reported by the user: ghost messages, wrong person
records after a switch, "deleted" worlds leaving data behind, and no way to
tell which file owns which data.

## 2. Current storage audit (verified against code, 2026-09-08)

| Data | File | Tables / shape | Owner | Switches with the DB? |
|---|---|---|---|---|
| Archive | `history.db` (SQLite WAL, schema v5) | `schema_meta`, `persons`, `media`, `messages`, `cursors`, `gaps` (+ `messages_fts`) | `HistoryDB` / `HistoryService` | ✅ connection re-bound |
| People queue | `chatbot.db` (SQLite) | `users` (nick, gender, registered, messaged, …) | `UserMemory` | ❌ fixed path, fixed connection |
| Labels + assignments + include/exclude filter | `config.json → "labels"` | JSON `{defs, assign, filter, next_id}` | `LabelStore` (sync API) | ❌ shared by all worlds |
| Undo/redo timeline (100 entries) | `config.json → "state.undo_history"` | JSON list, kinds `stack/grid/people/labels/archive/dbconn` | `Bridge` | ❌ shared by all worlds (even the world-bound kinds) |
| Recently used DBs | `config.json → "state.db_recent"` | list of paths | `DbManager` | ❌ ghosts accumulate |
| Per-world settings (my nick, media caps, preview) | `config.json → "history"/"collector"` | JSON | `HistoryService` | ❌ shared by all worlds |
| Media bytes | `saved_media/<nick>/images|gifs/…` | files; `media.cache_path` stores **absolute** paths | `MediaStore` | ❌ one folder for every world |
| Trashed DBs | `db_trash/` | copies of deleted/cleaned files | `DbManager` | — |
| "already collected" markers | `history.db → cursors` | per-person `last_ord/bootstrapped/…` | `HistoryRepo` | ✅ (already per-world) |
| Radar session state (partner, counters) | **memory only** (`Collector`) | `_nick/_added/_total/_last_sync_*` | `Collector` | ⚠️ reset on switch, lost on restart |

## 3. Guiding decisions

### D1 — One file = one world. The archive file becomes the world file.

A "world" is everything collected in one session/project. It is ONE SQLite
file containing **every** table, so creation, deletion and switching operate
on a single unit:

```
work.db  (SQLite WAL, schema v6)
├── schema_meta      key/value — schema_version, fts, migration flags
├── persons          archived persons (append-only, tombstones)     ← existing
├── messages         archived messages + metadata                   ← existing
├── media            media registry (url, sha256, cache_path…)      ← existing
├── cursors          per-person "already collected" markers         ← existing
├── gaps             collection gaps                                ← existing
├── users            People queue (was chatbot.db)                  ← NEW
├── labels           label definitions (was config.json)            ← NEW
├── label_assigns    nick → label id                                ← NEW
├── undo_history     world-bound undo entries (was config.json)     ← NEW
├── gaze_data        radar/observation session state (was memory)   ← NEW
├── app_settings     per-world settings (was config.json)           ← NEW
└── messages_fts     FTS5 virtual table + triggers                  ← existing
```

Every new table is defined in `TABLE_COLUMNS` (the single source of truth for
creation **and** validation, AGENT_RULES parity) — a fresh file is created
with all 12 tables, and an existing file is widened in place on open by the
existing `_repair_tables()` path (no data migration, no copy).

`config.json` keeps only what is genuinely **app-level**: chrome/scroll/
delays, URL presets, stack/grid/window state, action-stack presets, templates,
custom blocks, `history.db_path` (which world is current) and `state.db_recent`
(remembered world files — now pruned, see D3).

RULE 14 still holds *inside* the file: `users` may shrink (filters, edits),
`persons`/`messages` are append-only; the two tables are joined by nick at
read time only. What changes is the file boundary — they now share one world.

### D2 — Media bytes get a per-world folder; deletion does a reference scan.

New writes go to `saved_media/<world-stem>/…` (stem of `work.db` →
`saved_media/work/`). `media.cache_path` stays an **absolute** path, so:

* rows written by old builds (absolute paths in the shared `saved_media/`)
  keep working without any rewrite;
* the world's media footprint on delete is exactly the set of files its
  `media.cache_path` rows name — plus its per-world folder.

Deleting a world collects that footprint, opens every **other existing world
read-only** and asks "do you reference any of these paths?" and unlinks only
what nobody else owns (two worlds can share a file: same bytes, same sha256,
two rows — RULE 15 filed the bytes under one owner, dedupe shares the file).
Per-world folders from the new layout are deleted outright (exclusive by
construction). No copy is made — see D4.

### D3 — "missing" is a bug, not a state.

`state.db_recent` is a *recall list*, not a registry: any remembered path
whose file no longer exists is dropped from the list (and the list is
persisted) before it can be rendered. `list_dbs()` then emits **only files
that exist on disk**. The UI keeps its defensive `missing` styling, but the
backend can no longer produce such a row. After migration (D6) `chatbot.db` no
longer exists as a separate file, so the queue can never again be listed —
let alone deleted — from the DB window.

### D4 — Delete is permanent. Clean stays reversible.

* **Delete DB** = permanent. The file, its `-wal`/`-shm` siblings, its media
  footprint (D2) and every reference to it (db_recent, `history.db_path`) are
  removed. No `db_trash` copy — a 65 MB trash folder next to the app is
  exactly the "ghost data" this redesign removes, and the user asked for
  "no restore possible after deletion". The UI says so in the confirm dialog:
  *This permanently deletes the database and its media. This cannot be
  undone.*
* **Clean DB** = still reversible (it empties tables, it does not destroy a
  world): the file backup goes to `db_trash/` as today, and the world's
  per-world media **folder** is moved to `db_trash/` next to it (no copy —
  bytes preserved, world left clean). Media rows restored by Ctrl+Z point at
  files the downloader can re-fetch; the folder in `db_trash` makes even that
  unnecessary.

### D5 — The last world cannot be deleted.

Invariants, enforced in the backend (the UI is not the only client) **and**
mirrored in the UI:

1. `DbManager.delete()` refuses when deleting would leave **zero** existing
   worlds ("the system must always have at least one active database").
2. `list_dbs()` tags every item `can_delete` + a `delete_hint` tooltip. The
   DB window disables the button on the last remaining world with the hint
   *"Create a new database before deleting the last one."*
3. Deleting the **active** world of two is allowed: the flow switches to the
   other world first (full switch, D7) and only then unlinks.

### D6 — One-time migration of an existing install (startup, idempotent).

An install that predates this design has a world split across
`chatbot.db` + `history.db` + `config.json` + shared `saved_media/`. On
startup, **before the UI can act**, the migration re-homes the split parts
into the world that currently owns the session (the one in
`history.db_path`). It is a re-homing of *the current world's* data, never a
transfer between worlds (R6 is intact):

1. **Queue merge.** `chatbot.db` exists → its `users` rows are inserted into
   the active world's `users` table (rows that already exist by nick are
   kept, never overwritten), then `chatbot.db` is **renamed**
   `chatbot.db.migrated-<stamp>` — preserved, but no longer a `.db`, so the
   DB list can never see it again.
2. **Labels import.** The config `labels` section is non-empty AND the active
   world's `labels` table is empty AND no import flag is set → defs,
   assignments and the filter are written into the world, and
   `schema_meta: labels_migrated_from_config=1` is stamped. The config
   section is left in place as a dormant backup (never read again). New
   worlds start with no labels — isolation.
3. **Ghost pruning.** `db_recent` is pruned (D3) and persisted.
4. **Undo re-home.** World-bound undo entries (`people/labels/archive/
   dbconn`) currently living in config are written into the active world's
   `undo_history` table, with their existing order preserved (seq numbers,
   D8); the config keeps only `stack/grid` entries.
5. **Media.** Nothing moves. Old absolute `cache_path`s stay valid; D2's
   reference scan at delete time handles the legacy layout.

Every step is gated by a flag or an existence check, so it runs exactly once
per install (and is safe to re-run after a crash).

### D7 — Switching = a full world restart (not a re-bind).

Today `switch_db()` re-binds four objects and resets the collector's
conversation buffer. The new flow tears the whole world down and rebuilds it,
so **no state object can outlive the switch**:

```
switch_db(target):
  1. park the collector (exact running/paused state captured)
  2. persist the outgoing world's state: undo table, gaze_data
  3. close archive connection + close queue connection
  4. open target archive (schema v6 repair/validate)
     open/point queue connection at the SAME file
  5. load the target's world state:
       app_settings  → my_nick, media caps, preview
       labels + label_assigns + label filter → LabelStore memory
       undo_history  → world half of the timeline
       gaze_data     → radar partner + counters (verified gate stays COLD — RULE 15 fails closed)
  6. reset everything volatile: collector conversation state, MediaStore
     folder cache, LabelStore dirty flags
  7. emit to the UI (one burst, in order):
       users_updated      → People list rebuilt from the new file
       userdb_changed     → Full User Database re-read
       labels_changed     → Label panel + badges re-read
       history_changed    → undo timeline re-read
       db_changed{switched:true}  → DB window re-measures; JS caches reset
                                    (HistoryStore.reloadCurrent, HistoryDb,
                                     CollectorPanel — already wired)
  8. resume the collector exactly as it was parked, on the new world

  FAILURE: if the target cannot be opened, re-open the previous file,
  re-load the previous world's state (undo/labels/gaze/settings), re-bind,
  resume the collector and report the error. A failed swap never leaves the
  app without a world, and never leaves half of one world's state attached.
```

"Full app restart" from the request is delivered as a **full in-process
teardown/rebuild**: the same guarantees (no cache, counter, marker or watcher
survives) without losing the user's grid layout, connected URL and running
session — a literal process re-exec would throw those away.

### D8 — Undo timeline: one timeline, two owners, seq-ordered.

RULE 12 keeps ONE chronological timeline in the UI (one Ctrl+Z). Persistence
splits by **ownership**:

* app-level entries (`stack`, `grid`) → `config.json` (they are not a world's
  data);
* world-bound entries (`people`, `labels`, `archive`, `dbconn`) → the active
  world's `undo_history` table.

Every entry carries a monotonic `seq` (starting above the max of both
stores, persisted per store). On startup/switch the timeline is rebuilt as
`sorted(app entries + world entries, key=seq)` — the original interleaving is
reconstructible, so undoing a people edit still reverses exactly that edit
even after a restart or a round-trip through another world. Push/undo-truncation
rewrites **both** stores (≤100 tiny JSON rows; trivial). After a switch, a
world-bound entry from the previous world is simply absent — its undo belongs
to that world, which is exactly "no stale data from the previous DB".

### D9 — New world creation seeds settings, never data.

`create(name)` builds an empty file with the full v6 schema (all 12 tables),
then performs a full switch (D7) into it. The new world's `app_settings` is
seeded from the app config (my nick, media caps, preview) so a fresh world
behaves like the user's other worlds; its `users`/`labels`/`undo_history`/
`gaze_data` start EMPTY and its media folder `saved_media/<stem>/` is created
on first use. Nothing is copied from the previous world (R6).

## 4. Deletion flow (permanent, clean break)

```
delete(target):
  exists?                     → refuse "that database does not exist"
  existing_worlds == 1?       → refuse "cannot delete the last database —
                                 create a new one first"      (D5)
  if active:                  → full switch to another existing world (D7)
  close every connection that still points at the file
  unlink  <file>, <file>-wal, <file>-shm
  media footprint = {cache_path of the world's media rows} ∪ {per-world folder}
  other references  = union of cache_path sets of all OTHER existing worlds
                      (opened read-only; unreadable files contribute nothing)
  unlink footprint − other references; rmtree the per-world folder and
  any legacy folder left empty by the unlink
  drop target from state.db_recent (persist); if history.db_path == target
  → point it at the new active world (persist)
  → result {ok, op:"delete", path, deleted_media_files, ...}; bridge emits
    db_changed (UI re-measures)
```

Clean-break checklist (all covered by tests):

* no "missing" row left in the DB list (db_recent pruned, D3);
* no other world's row points at a deleted file (reference scan, D2);
* the world's per-world media folder is gone;
* `history.db_path` and `db_recent` name only existing files;
* the surviving world is fully connected and functional.

## 5. Schema additions (v6)

```sql
users (id INTEGER PK AUTOINCREMENT, nick TEXT UNIQUE NOT NULL,
       gender TEXT DEFAULT 'unknown', registered BOOLEAN DEFAULT 0,
       anonymous BOOLEAN DEFAULT 0, guest BOOLEAN DEFAULT 0,
       first_seen TEXT, last_seen TEXT, messaged BOOLEAN DEFAULT 0,
       message_count INTEGER DEFAULT 0, last_messaged TEXT, notes TEXT)
labels (id TEXT PK, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        color TEXT NOT NULL, created_at TEXT, next_id stored in schema_meta)
label_assigns (nick TEXT NOT NULL, label_id TEXT NOT NULL,
               PRIMARY KEY (nick, label_id))
undo_history (id INTEGER PK AUTOINCREMENT, seq INTEGER NOT NULL UNIQUE,
              kind TEXT NOT NULL, value TEXT NOT NULL, created_at TEXT)
gaze_data (key TEXT PK, value TEXT NOT NULL, updated_at TEXT)
app_settings (key TEXT PK, value TEXT NOT NULL, updated_at TEXT)
```

Existing files: created by `_repair_tables()` on open (the canonical
`TABLE_COLUMNS`/`TABLE_SQL` parity the repo already pins with a test).
`SCHEMA_VERSION` → `"6"`.

## 6. UI changes (DB Connection window)

* **Delete** button: disabled with tooltip *Create a new database before
  deleting the last one* whenever the backend says `can_delete: false`
  (last remaining world). Confirm dialog: permanent wording, names the
  media folder, states *cannot be undone*.
* **List**: only existing files (ghosts impossible, D3); each row shows
  size; the connected row is tagged; `chatbot.db` can no longer appear.
* **Stats**: the "Images folder" row names the world's own folder
  (`saved_media/<stem>`), so the 65 MB question answers itself.
* **After a switch**: status line *Fresh world "X" loaded — all caches
  cleared.* (db_changed carries `switched: true`.)

## 7. Failure modes kept / added

| Situation | Behaviour |
|---|---|
| switch target corrupt | previous world re-opened, **its** state re-loaded, error reported (existing, extended to full state) |
| delete last world | refused, both in `DbManager` and at the `db_delete` bridge slot |
| delete busy file | refused, app stays connected (existing guard, kept for crash-safety) |
| other world unreadable during reference scan | it contributes no references; the shared file is kept (never destroy what we cannot verify) |
| media row names a file outside `saved_media/` | kept — the scan only ever unlinks under the media roots it knows |
| crash mid-migration | every step idempotent (flags + existence), re-run on next start |

## 8. Explicit non-goals

* No merge of *different* worlds (`chat.db` + `chat2.db` stay separate
  worlds — the user can load either; merging would violate R6).
* No FTS changes, no collector algorithm changes (RULE 15 gate untouched —
  the verified flag is deliberately NEVER persisted in `gaze_data`).
* No process re-exec (D7 delivers the guarantees without it).
* No new DB engine — SQLite WAL already gives us one file + atomicity.

## 9. Code & test map

| Area | Files |
|---|---|
| v6 schema | `backend/history_db.py` |
| queue follows the world | `backend/user_memory.py` (`switch_db`) |
| labels per world | `backend/label_store.py` (sync facade, async write-through) |
| world switch/restart, settings, gaze, migration | `backend/history_service.py` |
| permanent delete, last-DB guard, list pruning, per-world media | `backend/db_manager.py` |
| undo split + switch signals + delete guard | `backend/bridge.py` |
| startup wiring + migration hook | `main.py` |
| DB window UX | `ui/js/db-panel.js` |
| migration | startup hook in `history_service.migrate_install()` (D6) |
| tests (RULE 8 — real files, real services) | `tests/test_db_manager.py` (updated), `tests/test_db_unified_world.py` (new), `tests/test_db_switch_restart.py` (new), `tests/test_db_migration.py` (new), `tests/test_db_switch_e2e.py` (re-run), `tests/test_person_labels.py` (updated fixture) |

Acceptance = the four PHASE-4 scenarios from the request:

1. create → all 12 tables present; queue/label writes land in the world file;
2. delete → file + wal/shm + media gone, other worlds intact, no "missing",
   no cross-world reference left, config repointed;
3. switch → zero A-data visible from B (users/labels/undo/radar/media), A
   intact after switching back, UI caches reset by signals;
4. delete-last → backend refuses + `can_delete: false` + tooltip.
