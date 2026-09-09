# DB Connection safety and missing-text recovery

Date: 2026-09-08
Status: **Implemented and verified.** This design was written **before implementation**;
the dated implementation/test record is in §5.

## 1. Investigation / reproduced failures

The investigation used the real `HistoryService`, `DbManager`, repository and
SQLite files in a temporary directory, plus the shipped JS agent executed
against `tests/dom_stub.js`. No user database was supplied or modified.

1. `DbManager.create()` calls `load(create=True)`. Creating `new.db` immediately
   replaces the live archive instead of preparing an independent file.
2. `list_dbs()` lists every adjacent `.db`, including the People queue, then
   re-adds nonexistent `db_recent` entries. Deleting `new.db` reproducibly leaves
   `{name: "new.db", exists: false}` in the panel's data.
3. Applying the archive schema to a SQLite file with a legacy
   `messages(id, user_id, text)` table reproducibly raises
   `no such column: person_id`: index creation precedes compatibility checking.
   `CREATE TABLE IF NOT EXISTS` is not a migration or a validation.
4. `HistoryService.switch_db()` closes the good connection before attempting the
   target. Failure leaks the partially opened connection; rollback requires
   reopening the old file. Push, manual collection, UI queries and media work
   can still be in flight while collaborators' `.db` references change.
5. `chat_agent.js` caches parsed text forever. Parsing an empty span, setting its
   text, then reading again still returns `""`. The observer only considers new
   message containers, not changes inside existing ones. Media URL changes are
   special-cased, text changes are not.
6. Repository empty-slot repair explicitly assumes "text never renders late"
   and only repairs media. Both the collector and parser's unchanged-cursor
   fast paths can skip repair. The history renderer creates a blank body when
   neither text nor media was captured.
7. Delete has no last-valid-archive guard; its fallback can be an unrelated
   database. Backup copies are raw file/WAL copies, and failed backup creation
   does not prevent Clean from deleting rows.

### Existing storage contract (do not replace it with a parallel schema)

* Chat archive: `schema_meta`, `persons`, `messages`, `media`, `cursors`, `gaps`,
  optional FTS5 + its triggers. The canonical text/sender/time columns are
  `messages.text`, `from_nick`, `ts_display`/`ts_resolved`/`day`; media is linked
  by `media_id` to `media.url`, `kind`, `cache_path`, owner and timestamps.
* People queue: `UserMemory`, normally `chatbot.db`, separate from the archive.
  Existing installations may contain other legacy tables in that file.
* Global Ctrl+Z timeline: **`config.json` `state.undo_history`**, not a second
  SQLite archive in this checkout. Labels also live in config, keyed by nick;
  gender comes from People at read time. Preserve that contract instead of
  duplicating labels/gender into an incompatible new archive schema.

The report's suggested SQL column names are conceptual equivalents, not the
schema used by this application. Validation will cover the complete actual
schema, rather than introduce unused `message_text` / `sender` columns.

## 2. Required invariants

* Create never parks/resets the collector, swaps a collaborator, changes the
  configured active path, or emits an active-archive reset.
* A target is initialized/migrated and validated **before** the good archive is
  closed. Missing, foreign, malformed, unsupported-version and core-column-
  deficient files fail closed with no modification to the active store.
* Only existing compatible chat archives appear in the manageable list.
  Protected paths, symlink/hardlink aliases, queue/undo/non-archive schemas,
  trash files and missing recent entries are excluded. Backend guards apply
  independently of UI buttons, including undo/redo and restore paths.
* At least one valid archive remains after Delete. Active deletion first opens
  a validated alternative. Files are moved into `db_trash` for existing global
  undo semantics, but disappear completely from the managed list and recents.
* Every operation sees one consistent database generation. No multi-await
  write, read or download may start in one archive and finish in another.
* Missing payloads remain explicitly incomplete, never a successful full scan.
  A media-only message is legitimate; it must not be rejected for empty text.
  Repair preserves row identity/order and metadata, avoids duplicates, respects
  explicit deletions and never guesses a match from timestamp alone.

## 3. Design

### A. Canonical schema and fail-closed initialization

`HistoryDB` owns schema creation, known additive migrations and validation.
Separate table creation, additive migration, then index/FTS creation. Inspect
existing tables first: missing *late* columns in recognized older archives are
migratable; missing core columns, unknown/future versions and foreign stores
are incompatible, not silently repaired with meaningless defaults.

Use one structural contract derived from the shipped schema (columns,
primary/unique keys and named index definitions), plus schema identity/version
metadata. Validate the full result after migrations, including SQLite integrity
and reference checks for activation. Fresh schemas declare person/media
references. Historical schemas without declared FKs retain their existing
layout; they are accepted only under the recognized legacy contract and checked
for orphan references rather than destructively rebuilding users' archives.
FTS remains optional on SQLite builds without FTS5; if enabled, its table and
all update triggers must exist. Never swallow a migration error. Roll back and
close partially initialized connections on every failure/cancellation.

Create uses a private, exclusively reserved staging file in the destination
folder, the same `HistoryDB.init()` and validator, a close/checkpoint, then
publishes without overwriting an existing destination. Only then register it.
Failure removes only owned staging artifacts and reports
`Failed to create database. Schema error.` (with diagnostic detail in logs).
Load refuses incompatible targets with
`Database schema is incompatible. Cannot load.` and retains the active handle.

### B. Serialized lifecycle and operation boundary

Introduce a small task-reentrant async archive lock shared by service,
repository, query, media and collection entry points. Reentrancy is needed
because collection calls repo, which calls media, which calls DB helpers.
Protect whole operations, not individual SQL statements. Serializing manager
mutations also prevents two rapid deletes from both passing the last-DB check.

Candidate validation/opening happens independently of the active archive.
For a successful load, acquire the operation boundary, wait for in-flight work,
rebind every collaborator without an await between assignments, reset only the
old collector cursor/gate state, persist the chosen path, then close the old
connection. Preserve enabled/running/paused/throttled collector state. Push
must honor stopped collection and re-verify its chat after a switch. Settings
updates may not bypass this load path by changing `db_path`.

Clean/restore run inside the same boundary. Use SQLite's backup API for a
consistent snapshot, refuse Clean if backup fails, and reset live cursors only
after success. Restore validates a staged backup before replacing a destination;
failed copies/restores must leave a usable active archive. Trash names include
a collision-resistant suffix; partial file moves are rolled back.

### C. Discovery, deletion, UI and undo

Canonicalize paths (`realpath`, platform case normalization, same-file checks).
Explicitly reserve the actual People DB path and standard queue/undo names;
inspect schema identity to reject renamed foreign stores. Discover valid
archives adjacent to the active DB plus recent valid external archives. Prune
stale recents after deletion and during discovery. Include backend
`can_load`/`can_delete` capabilities and the last-database reason.

Delete last valid archive returns exactly:
`Cannot delete the last database. Create a new one first.`
For active deletion, try compatible alternatives before touching the source.
If none can be opened, abort. On move failure retain/restore the original
connection and report failure. Successful delete forgets the original path.
Undo restores/re-registers from trash; it must not expose trash itself as an
ordinary DB. Create undo/redo concerns the independently created file, **not**
an implicit database switch. Inactive delete/restore must not switch the user.

The panel filters missing/protected items defensively, disables all mutation
controls during an operation and disables last-DB Delete. Its method guard
also warns if directly invoked. Completion refreshes list/stats; stale
pre-operation responses cannot resurrect deleted entries or clear busy state.
Creation messaging explicitly says to click Load. Only successful active-
archive changes reload history windows, not independent Create or a failure.

### D. Text capture and recovery

Agent version increases. Extract text independently of media so a caption and
media URL coexist. Invalidate only affected message caches for child/text/src
mutations; incomplete records are re-parsed on probes as a fallback. Observe
`characterData` and relevant attributes as well as child lists. Push updated
existing records, not just new containers; unchanged complete records retain
cache efficiency.

Expose incomplete-count/content revision in state so a change in the middle
of a long conversation cannot hide behind unchanged head/tail fingerprints.
The parser retries incomplete ranges with bounded, interruptible waits,
rechecks the private-chat gate on rereads, logs failures, and leaves the cursor
incomplete when payload capture is still pending. Repository accepts historical
empty slots for recovery/diagnostics, not as captured text.

Add explicit text recovery on re-read/backfill, including an unchanged chat
with saved empty rows. Match same person, direction, normalized Unicode author,
resolved day and DOM occurrence/order evidence. Avoid stealing a media slot
when same-minute text/media is ambiguous; keep the placeholder and log that
recovery is unavailable rather than invent content. Keep existing text/media
and all unrelated metadata; update text/text_lc, fingerprint/dedupe identity
and FTS consistently. Do not resurrect deleted rows. Repair-only updates must
refresh Person History even when no new row was inserted. Recovery can only
recover text still obtainable from the original chat, not bytes never captured
and no longer served by the site.

Renderer: if there is neither non-whitespace text nor usable media display,
show **`[text not captured]`** as text, never HTML. Media-only rows keep their
image/restore marker without a spurious missing-text warning.

## 4. Verification plan

* Real temporary SQLite service tests: create during live writes (text, Unicode,
  media, metadata), explicit load, complete schema, known migrations, bad/future
  schemas, index defects, injected schema/copy/move failures and cleanup.
* Lifecycle tests: original connection object remains on failed load, in-flight
  push/manual sync/query/media vs switch, cancellation, collector state, two
  concurrent deletes, last-valid guard excluding missing/queue/corrupt files,
  inactive and active delete, stale recents/restart, aliases, restore and undo.
* Agent execution tests: late text, subtree/characterData mutation, multiline
  Unicode, text + media, middle-of-chat changes, bounded cache behavior.
* Parser/repo/collector integration: empty to text repair without duplicate
  bubbles, retry from live DOM, manual backfill on an unchanged chat, repair
  when media downloads are disabled, same-minute ambiguity, day/author/gate
  separation, deleted rows, refresh on repair-only sync and unavailable text.
* JS panel tests: capabilities, direct-call last guard, busy/repeated clicks,
  stale reply rejection, no ghost rows, create copy and recovery placeholder.
* Run the existing Python and Node suites; report environment-specific limits
  separately from regressions. Live Chrome/user archive validation is not
  possible without those inputs and will not be claimed.

## 5. Implementation record

Completed 2026-09-08 on `arena/01a08228-chat-v-bot`.

### Implemented structure

| Area | Implementation |
|---|---|
| Canonical schema | `backend/history_db.py`: schema v5, archive application/storage identity, complete table/column/default/key/index/FTS checks, known additive migrations inside one transaction, fresh foreign keys and explicit legacy reference validation. Failed/cancelled initialization closes its connection. |
| Independent creation | `backend/db_manager.py`: exclusive same-folder staging, validate + checkpoint/close, non-overwriting publication, then registration. No service swap, settings-path change, collector reset, or Person History invalidation. |
| Operation boundary | `backend/archive_lock.py`, repo/query/media decorators, complete collector/push/manual-sync/action boundaries and bridge read boundaries. Load opens the candidate before waiting for in-flight work, then rebinds under the same stable lock. Failed/cancelled operations roll back unfinished writes. Stale queued UI row IDs are discarded after a generation change. |
| Management safety | `backend/db_paths.py` and manager: same-file checks, actual queue/reserved-name/trash protection, full read-only compatibility/reference checks for discovery, no missing recents, serialized last-valid deletion guard, validated alternatives, rollback of partial file moves. |
| Backups and undo | SQLite backup API for Clean and restore staging. Active restore uses SQLite's backup transaction into the live connection, avoiding an unlink/reopen window. Inactive restore does not switch. Create undo/redo restores the created file, not an empty replacement or implicit Load. New backup references update the existing chronological command; failed undo does not advance its index. |
| Global settings safety | `ConfigManager.save()` now writes/fsyncs a same-folder temporary JSON file and atomically replaces the previous file. A failed recent-path/settings write cannot truncate the existing global undo/labels data. |
| UI | Backend capabilities, last-archive guard, disabled busy controls, error completion, stale-response rejection, immediate deleted-row removal, explicit “Click Load” messaging, and active-change-only history refresh. |
| Capture | Agent v10 independently extracts text/captions and media, preserves multiline/nested text, observes content/src changes, retries incomplete cached nodes, coalesces corrected pushes and exposes middle-content revisions. Failed agent upgrades fail closed. |
| Recovery | Bounded four-attempt range capture; gate checks on rereads; no new metadata-only collector writes. Saved missing text/captions can be repaired in place, including unchanged chats and downloads-off mode. Identity checks use day, Unicode author, direction, DOM position or known neighbors. Tombstones survive payload/fingerprint changes. Deferred middle rows are inserted between known neighbors, not at the beginning. |
| Visibility | `text_scan_at` / `text_recovered_at` diagnostics, automatic retry cooldown, manual backfill override, repair-only refresh events, Text capture status and `[text not captured]` rendering. |

**Startup recovery:** an earlier build may have persisted a queue, missing or
incompatible file as the archive path. Only when there is no usable active
connection, startup tries a valid existing default/recent/neighboring archive.
If none can be opened, it creates a separately named validated recovery file;
it never overwrites the incompatible original. This is separate from explicit
**Create**, which never changes a working connection.

**Compatibility:** the illustrative user-proposed SQL names were not added as
unused duplicate columns. The application continues using its existing
normalized archive fields, People gender data and config-based labels/global
undo. Recognized old archives gain only known late columns/indexes; core-
deficient/foreign files are refused rather than stamped “migrated”. Historical
empty slots remain supported as recovery input, while live collection now
defers empty payloads. The old auto-connect Create tests and README were updated
to the explicitly requested behavior, not used to justify auto-activation.

### Verification results

Commands run from the repository using Python 3.11 in `.venv` and Node 22:

```sh
QT_QPA_PLATFORM=offscreen \
QTWEBENGINE_CHROMIUM_FLAGS='--no-sandbox --disable-gpu' \
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q

for test in tests/test_*.js; do node "$test" || exit 1; done

git diff --check
```

* **Python: 810 tests run, 809 passed, 1 skipped; no failures** (140.074 s).
  The skipped existing Qt WebEngine layout smoke test cannot import the desktop
  widgets in this sandbox because `libGL.so.1` is unavailable. This is not a
  successful live-desktop validation. The broader suite also emits resource/
  pending-coroutine warnings from other tests; those are not reported as passes
  of a warning-free run.
* **JavaScript: 323 passed, 0 failed across all 15 test scripts.** In particular:
  agent **44/44**, DB panel **23/23**, history renderer **24/24**, and history
  panel integration **36/36**. These execute the shipped modules, not copied
  extraction/rendering logic.
* Added `tests/test_db_connection_safety.py`: **52 real-file/lifecycle tests**,
  including schema/creation failure cleanup and cancellation; writes, queries,
  manual capture, push and media work paused across a requested switch; last-
  database and concurrent-deletion protection; system aliases; WAL backups;
  restore; failed I/O/rollback; atomic config preservation; and repeated global
  undo/redo, including a queued old row ID that also exists in a new archive.
* Added `tests/test_text_capture_recovery.py`: **22 parser/repository/collector
  tests**, including a three-blank-message reproduction using the reported nick
  pair, recovery with unchanged signatures and downloads off, in-place metadata
  preservation, FTS updates, partial/exhausted retries, deferred middle ordering,
  captions, day/position ambiguity, private-chat changes, tombstones and repair-
  only UI events.
* Existing archive/query/media/private-gate/manual-action/undo suites continue
  passing. Legacy migration fixtures now represent complete recognized archives
  with valid person references, rather than a foreign isolated messages table.

### User-data recovery boundary

No user SQLite archive or live Chrome session was supplied. No user file was
modified, and the three reported messages have **not** been claimed restored.
The regression fixture demonstrates recovery when their actual text is still
available from the original private chat. After updating/restarting, open that
chat, enable/resume collection and choose **Backfill older**. The UI reports
successful repairs and leaves an honest placeholder if text is unavailable or
cannot be matched safely. Preserve the original files and backups when an old
schema is refused; do not “repair” them by inventing columns or message bodies.
