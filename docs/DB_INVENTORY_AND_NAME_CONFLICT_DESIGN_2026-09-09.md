# DB Connection: one filesystem inventory, visible name conflicts

Date: 2026-09-09
Branch: `arena/01a08228-chat-v-bot`
Baseline: `d17dccfb8f71d8dbb30bcf0762e3318affe459ed`
Status: **Implemented and verified locally. Design was written and presented before application-code changes.**

## 1. User requirement and scope

The panel displays only connected `b.db`, while Create reports `m.db already
exists`. Files that reserve a database name must not be silently hidden. An
existing database must be visible; a stale registry entry with no remaining
files must not reserve its name. Create/Delete must update the list immediately.

Database names will be clickable to **reveal the file in Explorer/Finder/the
file manager**, including a conflict's actual sidecar file. This does not load
the database, launch a `.db` file association, or change the active archive.
The earlier clarification question about Explorer was skipped; this is the
non-destructive interpretation consistent with the standing explicit-Load rule.

Keep all earlier protections: independent Create, validated/fail-closed Load,
last-valid-database deletion guard, protected People/Undo stores and aliases,
whole-operation locking, chronological undo, clean-slate conversation reset,
and the completed agent-v14 media repair. No user database is available in this
checkout; the screenshot alone cannot identify the contents of the user's m.db.

## 2. Diagnosis before application-code changes

`DbManager.create()` rejects any filesystem entry at the destination **or** its
`-wal`, `-shm`, `-journal` siblings. `list_dbs()` instead discards everything
failing full archive validation. Those are different definitions of existence.
The frontend further filters `manageable=false`, so it cannot show a read-only
conflict even if one were returned. Creation errors do not carry the conflicting
entry or a current list; the UI must wait for a separate stats/list request.

Reproduction with the real manager and SQLite in a temporary folder:

| On disk | Before-fix visible list | Create `m` |
|---|---|---|
| `b.db` + zero-byte `m.db` | `b.db` | `m.db already exists` |
| `b.db` + `m.db` with an incompatible older `messages(user_id, text)` schema | `b.db` | `m.db already exists` |
| `b.db` + orphan `m.db-wal`, no `m.db` | `b.db` | `m.db already exists` |
| `b.db`, nonexistent `m.db` in recents | `b.db` | Succeeds; b.db stays active |
| `b.db` + valid unregistered `m.db` | `b.db`, `m.db` | Correctly refuses overwrite |

A stale config name alone is already harmless. The confirmed bug is that real
files are hidden because presence is conflated with loadability. Other variants
include temporarily locked/unreadable files, directories named `*.db`, and file
aliases. None may be fixed by overwriting or silently deleting unknown data.

## 3. Design

### A. One inventory; separate presence from permissions

Introduce a small filesystem-inventory module used by `DbManager` discovery and
creation conflict checks. The inventory is rebuilt from actual paths, not kept
as a second registry. `db_recent` remains discovery hints for external files.

Candidate groups are the active path, recent paths, adjacent `.db` files and
SQLite sidecars, plus an explicitly requested creation target. Each existing
group supplies:

- visible file/name/path and actual group members;
- main-file existence separately from `blocking` (some real group member exists);
- status/detail: ready, migratable, empty, incompatible, unavailable, sidecars
  only, non-file/directory, broken link or alias;
- compatible/manageable, active, can_load, can_delete and can_reveal capabilities;
- the actual path to reveal (a sidecar when the main database is absent).

The panel displays present user-file conflicts even when they cannot be loaded
or deleted. These are diagnostic rows, not valid chat archives. Missing recents
with no group members disappear and stop reserving names. Existing but invalid
or temporarily unavailable external files are not forgotten merely for failing
schema validation. Same-file aliases remain visible by their own filenames but
are never counted as additional independent fallback databases.

Known reserved People/Undo paths, their aliases, trash and internal staging
files stay out of ordinary archive discovery and retain explicit reserved-path
errors. A renamed foreign database is a visible **non-loadable file**, never a
manageable archive. No protected store becomes a Load/Delete target.

### B. Reuse schema validation without concealing its result

Expose a detailed read-only inspection result beside `inspect_archive()`.
Keep the boolean API as a compatibility wrapper. Both use the existing canonical
schema contract, safe legacy recognition, integrity checks and reference checks.
Report why an existing file is not loadable rather than converting every error
to an invisible row. No Create, DDL or migration occurs during classification;
SQLite may use legitimate WAL sidecars, but a missing main database is never
initialized by discovery. Only explicit Load performs supported migrations.

An incompatible or unreadable file remains read-only in this panel. The user
can reveal it, preserve/rename/move it in the file manager, or choose another
name. Automatic deletion or repair of unknown data is outside this fix.

### C. Creation and mutation results use that same inventory

Separate the requested lexical filesystem location from canonical database
identity. This lets Create detect a dangling symlink/name collision without
following it and unexpectedly creating a different target. Canonical/same-file
checks remain mandatory for protected paths and live archive identity.

Create obtains its collision from the inventory and returns its path, status,
actual blocking files and the fresh list. Remember a conflicting external
location as a hint so a subsequent refresh does not hide it again. Error text
must distinguish an existing m.db from **sidecars without m.db**.

Keep exclusive staging and atomic no-overwrite publication. Recheck group
conflicts just before publication; if another creator wins, rediscover and
return the winner as a visible conflict. Never delete another process's file
or orphan WAL to make the error disappear. Schema failures still report exactly
`Failed to create database. Schema error.` and clean up only owned staging files.

Success results also carry the fresh inventory, so a created row appears before
a slower stats refresh. Bridge change events for Delete/Load/Clean/Undo carry
that same snapshot. Failed actions never enter undo or reset collection.

### D. Keep the last-valid-archive guard independent of display row count

Only distinct, compatible, non-alias archives can be fallback databases. Empty,
corrupt, foreign, locked, sidecar-only or alias rows must not unlock Delete for
the last working database. Deletion still requires a compatible target; active
deletion opens a validated independent fallback before moving any files.

Diagnostic rows are read-only. In particular, a direct Delete call on an alias
must not resolve it and accidentally delete its canonical target. Existing
valid-archive Delete still moves the whole file/WAL group to `db_trash`, forgets
the original path and stays reversible through global Undo.

### E. Frontend consistency and Explorer action

- Split **visible inventory rows** from **manageable archives**; do not filter
  out every row whose `manageable` flag is false.
- Render a status/reason for a conflict, full path in its tooltip, and a native
  keyboard-accessible filename button. Load/Delete honor backend capabilities;
  filename buttons reveal locations only. Show the inventory folder so the
  creation location is explicit.
- Apply a mutation's inventory immediately, including on `already exists`,
  before scheduling a stats refresh. Preserve completion/error notices. Existing
  request IDs/busy guards must reject pre-mutation replies that could re-hide a
  conflict or resurrect a deleted path.
- Add a non-mutating bridge reveal RPC. It rechecks inventory membership and
  actual files, then selects the file with Explorer (`/select,`) or Finder
  (`open -R`); on other desktops it opens the containing folder. Use argument
  arrays/Qt APIs, never shell interpolation or execution of the database file.
  A missing path or failed launcher is reported, not shown as success. Revealing
  creates no database, undo entry, history reset or load operation.

## 4. Verification plan

1. Reproduce the exact `b.db` / hidden `m.db` scenarios. Each real conflict must
   be present in discovery, Create's response and the rendered list, with no
   Load/Delete permission unless it is a valid independent archive.
2. Cover empty, corrupt, old-incompatible, valid-unregistered, safe legacy,
   temporarily locked, foreign, directory, broken-link and orphan-sidecar cases.
   Preserve original bytes and b.db's handle/settings/collector state.
3. Prove nonexistent recents are pruned and allow creation, while existing
   external conflicts survive refresh/restart. No operation may initialize a
   missing main DB while inspecting an orphan group.
4. Test Create → immediate visible row; duplicate Create → visible conflict;
   Delete → all original group members gone and row/recents gone; same-name
   Create after Delete → success without changing the active archive. Include
   atomic publication races and existing undo/redo behavior.
5. Prove invalid/alias rows never count toward the last-valid-DB guard and cannot
   bypass backend Load/Delete protection. Keep reserved-store/alias tests.
6. Run real bridge → frontend-module integration, not just hand-written expected
   DTOs: creation/error/list snapshots, stale replies and read-only status rows.
7. Filename click must invoke only reveal, passing the exact path. Test Windows
   paths/spaces/non-ASCII/argument safety, sidecar selection, disappearance and
   launcher failure using controlled platform launchers; do not launch Explorer
   in the test environment or claim a live Windows test.
8. Run all Python and JavaScript regressions, compile/whitespace checks, and
   report the existing unavailable Qt WebEngine smoke separately.

## 5. Implementation and verification record

### Implemented

- `backend/db_inventory.py` is the common file-group source for discovery,
  collisions and capabilities. It preserves lexical names, inspects main files
  read-only, detects sidecar-only groups and separates diagnostic rows from
  independent archives. Existing invalid external hints survive refresh/restart;
  genuinely missing groups are pruned from persisted recents.
- `history_db.inspect_archive_details()` explains empty/incompatible/unavailable
  recognition while the existing boolean API remains compatible. No schema or
  archive-version change was made; supported older archives migrate only on Load.
- `DbManager` sends inventory snapshots with successful **and failed** mutations.
  Atomic no-overwrite publication rechecks the file group and reports race
  winners as visible conflicts. Delete counts only valid independent archives,
  and moves broken sidecar links too, so it actually frees the original name.
- Alias checks also protect Restore: planting a symlink at a deleted filename
  cannot redirect Undo into the live database. Unaccounted hardlinks into an
  external file/backup remain read-only after their original name leaves the
  visible list. Known aliases are not counted as additional fallback archives.
- `Bridge.db_list`, `db_info`, changes and undo/redo carry the shared inventory.
  `db_reveal` authorizes an existing visible path and delegates to the native
  file-manager launcher, without Load, global undo or collection reset.
- The shipped panel renders read-only reasons, filenames as accessible buttons,
  the creation folder and full-path tooltips. Change snapshots are applied
  before stats refresh, including failures. Stale stats and reveal replies do
  not overwrite newer state/notices. Filename/reason text is not parsed as HTML.

A final filesystem check found that SQLite can establish WAL/SHM companions
while opening a WAL-mode database read-only. The inventory now samples its file
manifest/size **after** the probe, and fails closed if the main file disappears
during inspection. Two additional regressions cover these cases; discovery
still never creates a missing main database or discards orphan sidecar data.

### Repeated exact-case results

Re-ran the diagnosis matrix using temporary files and a real, open
`HistoryService`. In **every** case the original b.db connection stayed open and
was the very same connection object after Create.

| Files before Create | Visible inventory before Create | Create result / immediate inventory |
|---|---|---|
| Empty `m.db` | b.db connected; m.db empty/read-only | Refused with visible `m.db already exists`; b.db + m.db |
| Incompatible old-schema `m.db` | b.db connected; m.db incompatible/read-only | Refused without modifying old data; b.db + m.db |
| Only `m.db-wal` | b.db connected; m.db sidecar-only/read-only | Explicitly says m.db is missing and m.db-wal blocks the name; b.db + m.db |
| Stale recent, no m.db or sidecars | Only b.db; missing hint removed | Create succeeds; b.db + ready m.db immediately; no implicit Load |
| Valid unregistered `m.db` | b.db connected; ready m.db with Load | Correct duplicate refusal; both remain visible |

The true subtype of the user's m.db remains unknown; no user database was
supplied. This fixes how existing files are surfaced and protected, not a
speculative repair or recovery of that particular file.

### Automated verification

| Check | Result |
|---|---|
| New `tests/test_db_inventory.py` | **45 passed** (real filesystem/SQLite/manager/Bridge, native-launch boundaries and shipped panel/HTML) |
| Complete Python suite | **947 tests: 946 passed, 1 skipped**, 200.365 seconds; exit 0 |
| All 15 JavaScript test scripts | **360 passed, 0 failed**, including 33 DB-panel cases |
| Python compileall, JS syntax checks, `git diff --check` | Passed |
| `config.json` compared with HEAD | Unchanged |

The two older discovery assertions were deliberately updated: renamed foreign
stores and orphaned-reference archives are now **visible**, but retain explicit
Load/Delete refusal and do not unlock deletion of the last valid archive. No
safety assertion was replaced by accepting an incompatible Load.

Commands used:

```sh
REQUIRE_DOM_TESTS=1 QT_QPA_PLATFORM=offscreen \
  QTWEBENGINE_CHROMIUM_FLAGS='--no-sandbox --disable-gpu' \
  .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q

for file in tests/test_*.js; do node "$file" || exit 1; done
.venv/bin/python -m compileall -q backend actions tests
node --check ui/js/db-panel.js
node --check tests/db_inventory_panel_harness.js
git diff --check
git diff --exit-code -- config.json
```

The existing `TestSashWebEngine.test_grid_in_real_webengine` smoke test is skipped
because native QtGui/WebEngine cannot import without `libGL.so.1`. Existing
resource/pending-coroutine warnings remain in the broader suite. Windows/Finder
selection commands and launch-failure handling are tested through controlled
native boundaries; **an actual Windows Explorer window was not exercised**.
No real-user file, private chat or live browser session was accessed.

Local scratch evidence (not Git deliverables):
`/home/user/.cache/chat-v-db-inventory/reproduction.log`, `after-fix.json`,
`new-tests.log`, `python-full.log`, `node-full.log`.

### Applying and publication

After applying this update, restart the desktop app and refresh DB Connection.
A formerly hidden file/group will have a reason beside its name. Click that
name to reveal the exact location; use **Load** separately for a valid archive.
For read-only conflicts, preserve/inspect the file group or choose another name
rather than overwriting it. Refresh after making changes in the file manager.

Implementation branch: `arena/01a08228-chat-v-bot`. This update follows the media
fix `d17dccf` and retains the remote configuration updates through `89fae36`.
