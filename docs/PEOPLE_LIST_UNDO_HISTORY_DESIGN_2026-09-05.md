# People-list actions join the global undo history — design

Date: 2026-09-05

## 1. Problem

Actions performed on the **People list** are not part of the global undo/redo
history and cannot be undone:

* removing a person (row 🗑 Delete, and “Delete selected”);
* changing a person's status (row ✔ Done / ↩ Undo → messaged ⇄ new);
* “Reset messaged flags” (the Reset messaged button — this is what the user
  means by “resetting the list”);
* clearing the whole list (Clear ALL users).

Also requested: **no confirmation dialogs** for remove / reset — the global
undo system is the safety net instead.

## 2. What already exists (the global history)

One chronological, tagged timeline lives in `state.undo_history` /
`state.undo_history_index` (config.json), mirrored on the JS side
(`App.globalHistory`), capped at 100 entries:

* `{kind:"stack", value: blocks}` — action-stack snapshots;
* `{kind:"grid",  value: layout}`  — sash-grid snapshots.

`Bridge` owns the authoritative copy:

* `_push_global(kind, value)` — dedupe vs. tip, truncate future, append,
  cap, persist;
* `undo()` / `redo()` — move the pointer and `_apply_global_entry(entry)` the
  entry that is now current; each entry holds the **after-state snapshot** of
  the surface it belongs to, so stepping onto an entry restores that surface
  to the state it had after that edit.

Entry kinds are also mirrored client-side so Ctrl+Z / Ctrl+Y stay in sync.

## 3. Design

### 3.1 New history kind: `people`

A people-list edit is recorded as **one** history entry:

```json
{ "kind": "people",
  "value": { "before": [ /* full rows before the edit */ ],
             "after":  [ /* full rows after the edit  */ ] } }
```

A row is the full record: `nick, gender, registered, anonymous, guest,
first_seen, last_seen, messaged, message_count, last_messaged, notes`.

Storing **both** halves (not just the after-state) is what makes every people
action reversible with a *single* Ctrl+Z even when stack/grid edits are
interleaved in the same timeline: undoing the tip people-entry restores its
`before`, redoing re-applies its `after`.

### 3.2 Recording — server-side, around the mutation

The people list lives in SQLite behind the async bridge handlers, so the
backend records history (single authority). Every user-driven mutation
handler snapshots **before** → mutates → snapshots **after** → if changed,
pushes one `people` entry:

* `_do_delete_one(nick)`        (row 🗑 Delete)
* `_do_delete_many(nicks)`      (Delete selected)
* `_do_clear()`                 (Clear ALL users)
* `_do_reset()`                 (Reset messaged)
* `_do_set_messaged(nick, bool)` (✔ Done / ↩ Undo status toggle)

No-ops (nothing deleted / flags already in the requested state / identical
before+after) push nothing. Automatic engine side-effects (a run marking
people messaged, filter purges, live collection) are **not** recorded — only
explicit user actions on the list.

### 3.3 Applying — restore a snapshot

* `UserMemory.replace_all(rows)` — wipe the table and insert the snapshot
  rows verbatim (preserving `first_seen`, `last_messaged`, `message_count`,
  `notes`, not just the flags), one transaction.
* `Bridge._apply_people(rows)` schedules the async wipe+insert and then
  `_refresh_users()` so the table and the stats panel re-emit.

### 3.4 undo() / redo() become people-aware

The tip entry is the one whose action must be reversed:

* `undo()`: when the **tip** entry is `people`, apply its `before`
  (schedule restore, move pointer back, return `{kind:"people",
  value:before, index}`). Otherwise the existing snapshot-stepping path is
  unchanged.
* `redo()`: when the entry being re-entered is `people`, apply its `after`.
* `_apply_global_entry()` learns `people` → applies the entry's `after`
  (used when a people entry is reached while walking through older entries,
  which mirrors how stack/grid entries behave).

### 3.5 Frontend stays in sync

* New Qt signal `history_changed` emitted by `Bridge` after any
  `_push_global`/undo/redo so the JS mirror never drifts. JS re-fetches the
  authoritative `get_undo_history()` and updates `App.globalHistory` +
  `App.globalHistoryIndex` (keeps the Undo/Redo buttons honest even though
  people entries are created server-side).
* `App.loadGlobalHistory()` accepts `kind:"people"` (session restore).
* `App._applyGlobalResult()` handles `kind:"people"` → `UserTable.render(...)`
  from the returned snapshot rows (extra row fields are ignored by the
  renderer), then a `refresh_users()` round-trip re-syncs stats.

### 3.6 Confirmation dialogs removed

Per the request, `ui/js/user-table.js` drops the `PresetsUI.confirm(...)`
wrappers for row delete, delete selected, Clear ALL users and Reset messaged
flags — each now runs immediately and is one Ctrl+Z away from being undone.
The ✔ Done / ↩ Undo toggle already had no dialog.

## 4. Files touched

* `backend/user_memory.py` — `replace_all(rows)` snapshot restore.
* `backend/bridge.py` — `history_changed` signal; `_people_rows()` snapshot
  helper; `_push_people_entry(before, after)`; before/after capture in the
  five `_do_*` handlers; `_apply_people()`; people-aware `undo()`/`redo()`/
  `_apply_global_entry()`.
* `ui/js/app.js` — accept `people` kind in load/apply; `_syncFromServer()`
  wired to `history_changed`.
* `ui/js/user-table.js` — remove confirm dialogs (delete/reset/clear run
  immediately).
* `docs/…`, `tests/test_people_undo.py` (new).

## 5. Acceptance

* After deleting a person (single or selection), Ctrl+Z restores them with
  their original fields; Ctrl+Y removes them again.
* After marking a person messaged/new or clicking Reset messaged, Ctrl+Z
  restores the previous flags in one step; Ctrl+Y re-applies.
* After Clear ALL users, Ctrl+Z restores the whole list.
* People edits share ONE timeline with stack/grid edits; the buttons and
  Ctrl+Z/Ctrl+Y stay in sync.
* No confirmation dialogs on delete / clear / reset.
* Existing Python + Node suites stay green.
