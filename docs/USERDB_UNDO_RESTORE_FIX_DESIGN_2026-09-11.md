# Person DB: undo restore + auto-refresh — root cause & fix design

Date: 2026-09-11 · Branch: `arena/01a08c75-chat-v-bot`
Report: "🐞 BUG — Person DB: Undo Fails to Restore Deleted Person" (CRITICAL data
loss + HIGH auto-refresh + MEDIUM confirm dialog).

## 1. What the user saw

1. Delete a person in the **Storage → Full User Database** window.
   Log: `🗑 "Mloni" and their history removed — Ctrl+Z restores both`.
2. Ctrl+Z. Log: `↩ Undo — archive restored` + `↩ People list restored — 189
   person(s)` (both halves *claimed* restored).
3. The person reappears in the **List** view (memory) but NOT in the **DB**
   view; searching for them finds nothing. Undo "reports success but silently
   fails".
4. Additionally: the DB list never auto-refreshes (add person / label change /
   undo), and deleting a person asks no confirmation.

## 2. What the data layer actually does (verified by code + existing tests)

Soft delete is tombstone-based (RULE 14, append-only archive):

- `history_delete_person` (bridge/history_bridge.py) →
  `repo.delete_person(nick, hard=False, token=T1)`:
  `UPDATE messages SET deleted_at=T1 …`, `UPDATE persons SET deleted_at=T1 …`;
  the person row is still in SQLite, only hidden. It also removes the memory
  (People list) row and pushes ONE undo entry:
  `{"op": "delete_person", "nick": …, "token": T1, "people": {before, after}}`.
- Undo (`UndoService.apply_command` → `_apply_archive_command`,
  forward=False):
  - `self._people.apply(before_rows)` → `memory.replace_all` →
    "↩ People list restored — N person(s)" (memory half, works);
  - `repo.restore_person(nick, token=T1)` → clears the person tombstone +
    un-hides the T1 messages, then emits `UserDbChanged` → re-emitted on the
    wire as `userdb_changed` → `HistoryDb.onChanged()` → re-fetch.
- `list_persons` filters `deleted_at IS NULL`, so a successfully restored
  person is visible again. **The simple delete→undo is covered by an existing
  green test** (`test_archive_delete_undo.py::test_undoing_a_person_delete_…`).

So the DB row comes back in the happy path. The reported data loss comes from
the layers around it:

## 3. Root causes

### RC-1 — the DB view can be frozen on a stale page (JS race, BUG 1 symptom)

`ui/js/history-db.js`:

- `_request` is guarded by `if (this.loading || !this.hasMore) return;`. A
  change event (delete, undo) arriving **while a page request is in flight**
  calls `reload()` → `_request(0)` → dropped silently. The change is never
  fetched.
- `onPage` applies **whichever response arrives**, with no generation check.
  Delete fires page-request A (offset 0); undo fires page-request B (offset
  0). If A's response (taken after the delete — person absent) lands **after**
  B's (person present), the view is left showing the pre-undo list forever:
  the person "never comes back" although the database has them. This matches
  the report exactly (List view has the person, DB view does not).

### RC-2 — restore failure is silently swallowed (false success, RULE 12/14)

`UndoService._apply_archive_command` schedules the restore coroutine and
**ignores its return value**:

- `repo.restore_person` returns `False` when the person row is gone (purged /
  DB switched in between) or when the HRP-13 token guard refuses (the person's
  current tombstone no longer matches the undo token — any intervening state
  change after the delete). The person then stays hidden **permanently**, yet
  the user already saw "↩ Undo — archive restored". No error, no warning.
- `repo.restore_deleted` can restore 0 rows for the same reasons; also
  ignored.

### RC-3 — the DB view subscribes to too few events (BUG 2)

`HistoryDb` only listens to `userdb_changed`, which fires on archive
delete/clear/undo/redo and DB switch. Missing:

- **new person** (collector): `people_changed` → `PeopleChanged` →
  `PeopleBridge._refresh` → `users_updated` wire — the DB view never sees it;
- **label change**: `labels_changed` wire — never seen (labels are shown per
  DB row, joined server-side);
- people-list changes (delete/mark/reset/clear/restore) — these *do* reach
  `users_updated`, which the DB view also ignores today.

### RC-4 — delete without confirmation (MEDIUM)

`HistoryDb.deletePerson` calls the bridge directly — one misclick on a row's
delete icon removes a person and their whole history (undoable, but a
destructive one-click).

## 4. Fix design

### 4.1 `ui/js/history-db.js` — make the view honest and event-driven

- **Generation guard.** `_gen` increments on every `reload()`; `_request`
  captures the gen; `onPage` ignores responses whose gen < current. A late
  stale response can never overwrite a newer view.
- **Pending reload.** `reload()` while a request is in flight sets
  `_pendingReload`; when the current gen's first page lands, the pending
  reload fires. Change events are never dropped (RC-1).
- **Debounce.** `onChanged()` coalesces bursts (250 ms) — an undo emits
  `UserDbChanged` AND `PeopleChanged`→`users_updated`, i.e. 2–3 wire events
  for one user action.
- **Scroll preservation.** a change-driven reload remembers `scrollTop` and
  restores it once the first page renders (so "auto-refresh" doesn't yank the
  user to the top on every label change).
- **Confirm before delete.** `deletePerson` asks `window.Dialog.confirm`
  ("Remove person and history?" — text states it leaves the database and
  Ctrl+Z restores both) before touching the bridge (RC-4). Same in-app modal
  the preset panel already uses — no native `confirm()` in Qt WebEngine.

### 4.2 `ui/js/app.js` — subscribe the DB view to the events it needs

- `b.users_updated` → also `HistoryDb.onChanged()` (new person from the
  collector, any people-list change — RC-3);
- `b.labels_changed` → also `HistoryDb.onChanged()` (labels shown per row —
  RC-3).

`onChanged` is debounced, so the extra events cost one coalesced re-fetch.

### 4.3 `services/undo_service.py` — surface restore failures (no false success)

In `_apply_archive_command.work()` (after the awaits):

- `restore_person` returned `False` → error `LogMessage`
  `❌ Undo failed for "X" (delete_person): <reason>`, with the reason
  split so the user learns WHICH half of the state drifted:
  `the person no longer exists in this database` (row purged / world
  switched) vs `the row's tombstone no longer matches this delete (state
  changed after the delete)` (HRP-13 refusal). It then emits
  `UserDbChanged(action="undo_failed", …)` so the view side can react and
  `ArchiveUndoApplied(ok=False)`.
- `restore_deleted` restored 0 rows for a non-empty token (a token is only
  minted when ≥1 row was hidden) → same error surfacing.
- redo-forward: re-delete of a person that no longer exists → warning
  `LogMessage` (state drift, not a crash).
- `core/events.py`: `ArchiveUndoApplied` gains `ok: bool = True` (frozen
  dataclass — default keeps every existing emit call valid).

The success log stays where it is (it describes the intent); the *failure*
now always produces a `❌ … error` line, which the Log Console shows in red.

### 4.4 What we deliberately do NOT change

- The tombstone model (`delete_person`/`restore_person`) — it is correct for
  the happy path and already tested; the bug was around it.
- `HistoryBridge`'s `UserDbChanged`→wire re-emit — already passes every
  payload through (including the new `undo_failed` action).

## 5. Tests (RULE 8 — real modules, fail if the fix is deleted)

`tests/test_userdb_undo_restore.py` (real repo + real query + real bridge
slots, real SQLite — same harness as `test_archive_delete_undo.py`):

1. delete person → undo → person is back in `list_persons` AND all messages
   visible (regression pin of the DB half through the full bridge);
2. delete a ZERO-message person → undo → person back (the `_restore_rows`
   count-0 path);
3. undo → redo → undo cycle stays consistent (person visible, hidden,
   visible);
4. **false-success pin (RC-2):** after a soft delete, re-stamp the person's
   tombstone with a foreign token (simulating intervening state) → undo →
   person stays hidden AND an error `LogMessage` is emitted AND
   `UserDbChanged` carries `action="undo_failed"`;
5. **missing row pin (RC-2):** hard-erase the person row after the soft
   delete → undo → error surfaced, no exception leaks;
6. redo of a person delete where the person vanished → warning log, no
   crash.

`tests/test_userdb_refresh_ui.js` (Node, real `ui/js/history-db.js` against
the DOM stub — same harness as `test_preset_io_ui.js`):

1. a late STALE page response (older generation) does not overwrite the
   current view (RC-1a);
2. a change event while a request is in flight → the reload happens once the
   in-flight request completes — never dropped (RC-1b);
3. `deletePerson` opens the confirm dialog and does NOT call the bridge
   until the user confirms; cancel → no bridge call (RC-4);
4. `onChanged` debounce: a burst of 3 events → 1 reload (250 ms timer);
5. wiring pins: `ui/js/app.js` calls `HistoryDb.onChanged()` from
   `users_updated` AND from `labels_changed` (RC-3).

## 6. Quality targets (RULE 16)

- Python: `_apply_archive_command` and its new failure-check helpers stay
  ≤ 30 LOC / CC ≤ 10 / cognitive ≤ 15 / nesting ≤ 4 (the failure handling is
  split into a small `_report_restore_failure` helper).
- JS: no new function > ~30 lines; `onPage`/`reload` restructured minimally.
- No metric gaming; new tests must fail when the fix is reverted.
- Full suite must not drop below baseline (2542 passed).

## 7. Revision 2 (2026-09-11) — RULE 16/18 compliance redesign

Final audit against `docs/AGENT_RULES.md` (RULE 16) found a real gap:

| Item | Before fix | Gate |
|---|---|---|
| `UndoService` methods | 26 at base → **31** (+5 added by this fix) | §6.2: a class already over 15 methods may not gain methods unless the PR extracts enough to stay ≤ the old count — **violated** |
| `UndoService` LOC | 444 → 494 | same §6.2 "must not worsen" |
| Reader's context budget (RULE 18) | the "what does Ctrl+Z do to a person delete?" logic sat in **five** methods buried inside a 444-line god class (a named landmine) | write for the reader's context budget — **violated** |

### Redesign

The apply/reverse semantics of one archive delete op move out of the class
into a dedicated module — a real domain concept, not a part1/part2 split:

```
services/archive_undo.py   (~95 lines — the whole archive undo story,
                           readable in one screen)
  apply_archive_op(bus, repo, value, forward)   # orchestrator: dispatch,
                                                # warn log, success events,
                                                # honest failure events
  apply_delete_forward(repo, value)             # redo: re-hide row(s)
  re_hide_message(repo, value, nick)            # redo of a single message
  apply_delete_restore(repo, value)             # undo: un-tombstone,
                                                # classify missing vs mismatch
  _failure_line(forward, op, nick, reason)      # the ❌ message text
```

`UndoService._apply_archive_command` (the pre-existing method) shrinks to
people-snapshot handling + `self._schedule(apply_archive_op(self._bus,
archive.repo, value, forward))`.

| Item | After (measured) | Gate |
|---|---|---|
| `UndoService` methods | **26 — exactly the base count** (net Δ 0) | §6.2 ✓ |
| `UndoService` LOC | **426** (< 444 base) | §6.2 ✓ (improved) |
| `archive_undo.apply_archive_op` | loc 23, params 4, radon B(7), cog 7, nest 1 | §1–§2 ✓ |
| `archive_undo.apply_delete_forward` | loc 14, params 2, radon B(9), cog 9, nest 3 | §1–§2 ✓ |
| `archive_undo.apply_delete_restore` | loc 22, params 2, radon B(10), cog 11, nest 2 | §1–§2 ✓ |
| `archive_undo.re_hide_message` | loc 8, params 3, radon A(4), cog 3, nest 1 | §1–§2 ✓ |
| `archive_undo._failure_line` | loc 3, params 4, radon A(2), cog 1, nest 0 | §1–§2 ✓ |
| new module coverage | 88% line / 87.5% branch (undo test files) | §3 floors 80/75 ✓ |
| reader budget | archive undo = one ~95-line module; the class loses 5 methods | RULE 18 ✓ |

No override comments are needed anywhere; no metric gaming (each extracted
function names a real responsibility; no dispatch-table-of-lambdas tricks).
