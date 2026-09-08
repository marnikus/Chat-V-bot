# Clean-slate collection reset; undo isolated from collection

Date: 2026-09-09
Branch: `arena/01a08228-chat-v-bot`
Baseline: `6ce29c998d71b20e260436eef87aa63604a06d66`
Status: **Implemented and verified.** The design was written before application-code changes.

## 1. Controlling requirement

The latest user instruction explicitly supersedes the previous hide/restore
semantics. Clear History and Delete Person must destroy the active archive's
knowledge of that person's messages. The next scan, including the same visible
DOM messages, is a first collection. Undo may retain an isolated snapshot, but
**normal collection must never read or consult it**.

- Clear retains the contact record/note, not message counts/dates/resume state.
- Delete removes the contact record as well as its message state.
- All message rows for the person are removed, including old tombstones.
- Individual-message Delete is a separate action; its behavior is unchanged
  until a whole-history/person reset removes all of that person's rows.
- The next automatic scan may recollect immediately if the chat is still open.
  There must not be a new "wait until reopened" or deleted-person denylist.
- Global undo stays one chronological timeline. Snapshot data is not an
  "already seen" registry and is not attached to the live SQLite connection.

## 2. Investigation / reproduced cause

Using the real service/repository with 25 messages in a temporary database:

```
After current Clear:
  stored messages = 25; visible messages = 0
  cursor.dom_count = 25; len(tail_keys) = 25; cursor.last_ord = 25
After resetting the cursor alone:
  visible messages = 0
After current Delete Person:
  person retained = true; person.deleted = true; stored messages = 25
```

This is not a browser extraction error. The bulk operations only stamp
`deleted_at`, leaving rows, unique keys and resume pointers in the collection
store. The writer queries those rows as known; the empty-slot deletion guard
also deliberately blocks their reappearance. The UI additionally keeps a
cumulative `_appended` count unrelated to the reset.

### Complete state inventory

| Layer | Existing message knowledge | Reset behavior |
|---|---|---|
| `messages` | IDs, `fp`, `dup_key`, `deleted_at`, occurrence/DOM index, text/media links, resolved timestamps, recovery scan markers | Delete **every** row for the person. Associated unique/ordinary/FTS index entries disappear in the same transaction. |
| `cursors` | DOM count, head/tail signatures, tail IDs/hashes, last ordinal, bootstrap/full-scan flags and time | Delete the person's cursor, not merely blank a subset of fields. |
| `gaps` | Earlier scan/alignment pointers and history-gap metadata | Delete for that person. |
| `persons` | Message/in/out/media counts, last ordinal, message-derived first/last dates, per-conversation self-name history, tombstone | Clear counts/ordinal/dates/history/tombstone on Clear; remove the row on Delete. Preserve note/contact identity only on Clear. |
| `media` | URL/ID registry, ref counts, download/recovery state | Remove exclusively referenced rows; recount shared references and retain media needed by other conversations. |
| media runtime/files | Nick-folder cache; cached payload files | Evict the target's folder mapping. Copy undo assets before removal; delete unreferenced active-cache files safely, retaining files referenced elsewhere. |
| Python collector | Current count, last sync/count/result, verified push gate, backfill state, diagnostics, session totals | Reset the affected conversation; discard its session counter; preserve enabled/paused/running/throttled settings and unrelated conversations. |
| parser/JS | Last range diagnostic, parsed-node cache, occurrence/fingerprint reuse, push buffer/timer, scroll restore state | Invalidate the target and require a reset handshake before its next accepted state. Agent reset epoch rejects pre-reset pushes arriving late. |
| UI | Paging model/IDs, old replies/live appends, session totals/log lines | Reset the target model/counters/log; reject obsolete generation-tagged responses. |
| global SQLite ID allocator | `sqlite_sequence` | Keep global monotonic allocation: it is not a per-person seen registry and must not cause unrelated row IDs to be reused. Per-person ordinal starts fresh. |
| user preferences/identity | Labels, notes, configured/current/declared former self nicknames | Not message dedupe. Preserve independent user preferences and move already trusted self declarations to a global identity-only list before dropping per-chat metadata, so the previous nickname fix is not broken. |

Temporary dedupe/slot dictionaries inside an append die with that operation;
there is no additional persistent in-memory seen-ID set to clear. The shared
operation lock must drain an in-flight append/read/download before reset.

## 3. Proposed separation and lifecycle

### A. Explicit command-side undo store

Introduce `HistoryUndoStore`, used by the service's reset/undo command API,
not by the collector/parser or ordinary repository read/append path.

- Per-person SQLite snapshots in an opaque operation directory under
  `db_trash/history_undo/`, with referenced cached-media copies.
- A distinct storage/application identity makes them **not loadable as chat
  archives**, even if copied/renamed outside the trash directory.
- Snapshot contains the pre-command person/messages/media data and optional
  diagnostic cursors/gaps. Global undo stores only a reference and command
  metadata, not large message/media bodies in config JSON.
- Publish a complete, closed, validated snapshot before deleting live data.
  Snapshot/copy failure aborts the destructive operation.
- Never ATTACH the undo database to the collection connection. Ordinary append,
  sync, discovery, stats and media jobs must not open/read the undo snapshot.
- Copy media safely; never unlink another conversation's shared asset or a file
  outside the configured cache root. A failed post-commit orphan-file cleanup
  is reported, but cannot restore a message/dedupe marker in the active DB.

### B. One reset command boundary

`HistoryService.reset_conversation(nick, delete_person=...)` owns the operation:

1. Acquire the stable archive-operation lock; capture independent self identity
   declarations and the undo snapshot where requested.
2. In one live transaction, delete messages/cursor/gaps, clean media references,
   and reset or remove the person. Both live and previously hidden messages go.
3. Commit before advertising success. Failures roll back, leaving live data safe.
4. Invalidate parser/agent state and the collector's per-person counters/gate;
   bump the service/UI generation; emit a reset event before the next scan.
5. Re-verify the private chat on the next pass and collect normally. A failed
   browser reset remains pending and cannot let an old queued push through.

The normal Clear/Delete handlers and their redo path use this command, rather
than the old bulk tombstone operations. Individual-message deletion remains
separate. No change to Create's independent-file semantics or last-DB protection.

### C. Browser and UI causality

Agent v13 carries a capture epoch on state/slice/push. A per-person reset evicts
parsed fields; for the active target it also drops buffered pushes/timers and
advances the epoch. Tab changes likewise disarm old buffered content. The
collector accepts only the epoch it verified, so a queued old event cannot
undo a successful reset after a new pass has already started.

Parser reset requests contain only a target name/reset intent, not old counts,
IDs or fingerprints. They are applied on reconnect/next state before returning
usable collection data. An inactive reset does not discard another person's
buffer or change their archive/counters.

Use per-person session totals, not the UI's old global `_appended` accumulator.
A reset removes that person's entry. Service-generation tags reject stale
history replies/appends after reset. Clear the visible history and its old
paging state immediately; the next scan may naturally fill it again.

### D. Undo, redo and re-collected data

Undo is an explicit command that reads the isolated snapshot and merges data
back into the active archive. It must not duplicate messages already freshly
re-collected in the meantime or overwrite newer unrelated messages/persons.
Match current archive identities, remap media references safely, and retain
original message IDs where safe for compatibility with earlier undo commands.
Recompute active counts/order and invalidate resume/browser state; do not put
old DOM/full-scan pointers back into service.

Redo is another full clean-slate reset, with an updated command-side snapshot
when needed. It must not recreate active bulk tombstones. Archive-path checks
and the existing pending-edit guards protect the global timeline. Failures do
not advance the undo index. Full permanent purge remains non-undoable when the
user explicitly chooses that mode.

### E. Existing v12/older deletion state

A new reset must remove old hidden rows even when the visible count is already
zero. In addition, initialization/loading should isolate known legacy bulk
Clear and deleted-person tombstones before collection starts, so old installs
are not permanently stuck until a second manual Clear.

- Recognize `clear:` rows and old Clear tokens from command metadata; do not
  guess that every individual deletion was a whole-chat Clear.
- Snapshot before removing legacy data. Retain post-clear live rows for a
  non-deleted person; reset/rebuild resume state from only remaining active data.
- Keep legacy undo references usable through the command adapter/snapshot store,
  not through an active "deleted messages" registry. Legacy restoration actions
  must not reintroduce bulk tombstones that suppress future collection.
- Migration/undo compatibility work is storage maintenance, not part of message
  matching. Collection must not read the global undo list or snapshot files.

Remove the new "Restore cleared" requirement/UI for normal operation: the user
now explicitly wants ordinary collection to re-add the same messages. Old
undo commands remain command-side compatibility, not a collection dependency.

## 4. Verification plan

1. Real SQLite + generated DOM/protocol: collect 25 → Clear → assert zero live
   rows, tombstones, keys, cursors/gaps/counts → scan the SAME DOM → 25 new rows.
   Repeat Clear/recollect and Delete/recreate/recollect, plus restart/reopen.
2. Fill every cursor/count/recovery marker first, including old hidden rows and
   a fully bootstrapped unchanged cursor, to prove all blockers are removed.
3. Verify snapshot/undo data exists outside the active connection and remains
   unchanged during scans; make snapshot-reader calls fail if collection tries
   to use them. Clear must not require an explicit Restore action.
4. Assert new per-person/session totals are `25 → 0 → 25`, not 50. Other people,
   their cursors/counts, shared media and queue/filter state remain independent.
5. Verify agent cache/buffer reset, epoch rejection of delayed old pushes, safe
   deferred reset after disconnect, and fresh text extraction after reconnect.
6. Undo before/after re-collection, redo reset, repeated cycles, metadata/media
   fidelity, failure/cancellation rollback, wrong-DB refusal, and old bulk-state
   conversion. No snapshot/database/media artifacts enter Git.
7. Update obsolete hide-forever/Restore-cleared tests to the NEW explicit user
   requirement; retain individual-delete, identity, private-gate, media capture,
   DB lifecycle and undo regressions. Run the full Python/Node suites and report
   environment limitations separately from test results.

## 5. Implementation and verification record

Completed 2026-09-09. No application-code changes preceded this document.

### Implementation

- `HistoryService.reset_conversation()` is now the Clear/Delete/redo command
  boundary. `HistoryRepo.forget_messages()` physically removes all target rows,
  cursor/gaps/index identities, exclusive media metadata, and resets/removes
  the person. Deprecated bulk APIs also erase rather than hide; explicitly
  named legacy helpers remain only for old-data compatibility/tests.
- `backend/history_undo.py` contains the independent snapshot writer/reader.
  It copies only the target's archive data and referenced cached assets to a
  closed, validated SQLite snapshot with its own application/storage identity.
  No ATTACH is used. Ordinary collection never receives or opens the snapshot.
- Undo is an explicit merge, reusing current duplicates without adding a second
  copy. Original IDs are retained/recovered when safe for earlier undo commands;
  unrelated row IDs are not overwritten. Media links/bytes are remapped safely.
  Snapshot cursors/gaps are not used to resume collection. Redo updates the
  command-side snapshot and performs a new physical reset.
- Legacy Clear and deleted-person state is isolated before a database is used
  for collection. Post-clear live rows are retained/resequenced. Old commands
  are adapted to snapshot references; only matching entries are patched, so an
  awaited migration cannot overwrite concurrent edits to global undo history.
  Clean archives do not even consult undo command metadata on initialization.
- Agent v13 supports a reset handshake and epoch-tagged pushes; it clears
  obsolete fields/buffers, rejects old-chat buffers and makes late pre-reset
  payloads distinguishable. The parser retains reset intent only until the
  browser acknowledges it; a disconnected reset cannot verify an old capture.
- The collector owns per-person session totals and destroys the affected entry.
  Frontend paging/IDs/log/session state is reset; generation-tagged stale
  replies/appends cannot bring old messages/counters back. The obsolete Restore
  cleared UI and undo-derived hidden counts were removed from normal history.
- Trusted self declarations are retained independently in identity preferences,
  not as message knowledge. Other contacts/cursors/session totals/shared media
  remain intact. Delete's queue undo restores only the target, preserving
  people discovered afterward. Pause/running/throttle preferences are retained.

### Verification results

```sh
npm ci --prefix tests
REQUIRE_DOM_TESTS=1 QT_QPA_PLATFORM=offscreen \
QTWEBENGINE_CHROMIUM_FLAGS='--no-sandbox --disable-gpu' \
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q
for test in tests/test_*.js; do node "$test" || exit 1; done
git diff --check
```

- **Python: 881 tests run — 880 passed, one skipped, no failures** (171.167 s).
  The existing Qt WebEngine layout smoke test is skipped because `libGL.so.1`
  is unavailable. Other legacy tests emit pre-existing resource/pending-task
  warnings; this is not described as a warning-free run.
- **JavaScript: 337 passed, zero failures across all 15 scripts**. Agent tests:
  **51/51**; history-panel integration: **43/43**.
- Retry verification on 2026-09-09 reproduced the same results: **881 Python
  tests run, 880 passed, one skipped** (168.582 s), and **337 JavaScript tests
  passed**. Diff, Python compilation and new-file whitespace checks also passed.
  No additional application-code changes were needed for the retry.
- `tests/test_clean_slate_reset.py`: **26 reset/isolation regressions**, including
  real generated-DOM/protocol cases. Verified the requested **25 → 0 → 25**
  cycle, repeated cycles, Delete/recreate, all stored markers, cursor-only-reset
  insufficiency, fresh IDs/ordinals, session totals, restart, legacy conversion,
  different-person/shared-media isolation, cache bytes, old push rejection,
  deferred reset, rollback/cancellation, wrong-DB refusal, and undo after
  re-collection without duplicates.
- Snapshot isolation is behavioral: collection/restart tests replace the undo
  reader (and, for a clean archive, undo-history access) with a function that
  raises if called. Re-collection still succeeds; snapshot bytes stay unchanged;
  the active SQLite connection has no attached undo database.
- Old hide-forever / Restore-cleared expectations were replaced with the new
  explicit requirement. Identity/private-gate/read-error/individual-message
  deletion tests remain. Legacy tombstone-reading tests seed explicitly legacy
  data rather than treating normal Delete as a hide operation.

### Limits and operation notes

These are real SQLite and generated-JS/DOM/protocol tests, not access to the
user's live Chrome chat. No live private messages were claimed recovered here.
After applying the changes, restart and confirm **Capture agent v13**. Clear or
Delete, then use Collect now or revisit the same private chat: all visible
messages can be saved fresh. If collection is running with the chat open, the
next heartbeat may immediately refill the history; pause first to keep it empty.

Undo snapshots/asset copies are excluded from Git and never manageable as chat
databases. Global SQLite allocation sequences and independent user identity /
label/note preferences are not deleted-message registries. Logical SQLite
removal is not advertised as forensic secure erasure. If an OS file lock prevents
removing an unreferenced cache file, cleanup is reported without putting its
message/dedupe row back in the active store.
