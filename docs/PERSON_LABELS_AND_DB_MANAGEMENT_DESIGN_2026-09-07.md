# Person History Management, Labels, Color Picker, Label Manager & DB Connection — Design

Date: 2026-09-07
Status: implementation design, written BEFORE the code changes (AGENT_RULES
process) — **implemented and shipped on 2026-09-07**; see “Implementation
status” at the end of this document for the code and test map.
Feature request: message-history DB features & management —
(1) delete person / one message / whole chat, (2) custom person labels with
colors, (3) a movable color-picker popup, (4) a Label Manager grid window,
(5) a DB Connection grid window with size info, (6) label-based filtering,
(7) every action reversible through the ONE global undo history.

---

## 1. Problem statement

The archive (`history.db`) can currently only *grow*. The UI can tombstone a
person from the Full User Database row, and that is all:

* a single wrong/garbage message cannot be removed;
* a conversation cannot be wiped while keeping the person;
* nothing about a person can be *categorised* — there is no way to say
  "this one is rude, never message them again";
* the database itself cannot be created, swapped, emptied or inspected from
  the app; the user has to find `history.db` in the file system;
* none of the destructive archive actions are reversible, while every other
  editable surface (stack, grid, people list) shares one `Ctrl+Z` timeline
  (RULE 12).

## 2. Current state audit

| Area | Where | Notes |
|---|---|---|
| People list (queue) | `chatbot.db` `users`, `backend/user_memory.py`, `ui/js/user-table.js` | may shrink at any time (RULE 14) |
| Archive | `history.db` `persons`/`messages`/`media`/`cursors`/`gaps`, `backend/history_{db,repo,query,service}.py` | append-only, joined to People by nick at read time |
| Person History window | `ui/js/history-store.js` + `history-view.js` (`createElement` only) | read-only |
| Full User Database window | `ui/js/history-db.js` | row click opens the person; a hidden `data-action="delete"` path calls `history_delete_person` |
| Grid windows | `ui/js/sash-core.js` (model, `VERSION = 2`, 10 windows), `sash-grid.js` (DOM), `backend/bridge.py` (`GRID_VERSION = 2`, validation + migration) | window set is validated on load; a mismatch is rejected |
| Global undo | `Bridge._push_global/undo/redo`, `App.recordGlobal` | kinds `stack` (state snapshot), `grid` (state snapshot), `people` (reversible command with `{before, after}`) |
| Settings/presets | ONE `config.json` via `backend/config_manager.py` | "all variables storable" already means: put it in config.json |

Gaps: no label concept anywhere, no per-message identity in the page payload
(`HistoryQuery._item()` omits the row `id`), no soft-delete column, no DB
management, no color picker, two new windows missing from the grid.

---

## 3. Guiding decisions

### D1 — Deletion in the archive is a *soft* delete (reversible), purging is explicit

RULE 14 says the archive is append-only and that no filter/purge/undo may
delete archived messages. A user pressing "🗑 delete this message" is a
different thing: an explicit, deliberate edit. To honour both RULE 14 and
"all actions connected to global undo history control" we do NOT erase rows:

* `messages` gains `deleted_at TEXT NOT NULL DEFAULT ''` (added through the
  existing `HistoryDB.LATE_COLUMNS` in-place upgrade path);
* every read (`page`, `around`, `search`, counts, stats) filters
  `deleted_at = ''`;
* a delete stamps the affected rows with ONE shared **operation token**
  `"<iso-timestamp>#<8 hex>"`, so the exact set can be reversed with a single
  `UPDATE … WHERE person_id=? AND deleted_at=?` — the undo entry stays tiny
  (a nick + a token) no matter how many thousands of messages were hidden;
* re-collection cannot resurrect a deleted line: `UNIQUE(person_id, dup_key)`
  makes the collector skip it, so the deletion sticks (RULE 15 untouched);
* erasing bytes forever is a separate, explicitly-labelled operation
  (DB Connection → **Clean DB** / **Delete DB**, and `hard=True` on
  `delete_person`), and those are backed up to a trash folder first so even
  they can be reversed.

Person deletion re-uses the existing `deleted_at` tombstone on `persons`
(already reversible via `restore_person`).

### D2 — Labels live in `config.json`, keyed by nick

Labels describe *the person*, and both tables that show them read from a
different database (People = `chatbot.db`, Storage = `history.db`). Putting
labels in either store would either duplicate them or break RULE 14's
"joined by nick at read time only". They are settings-shaped data (small,
user-authored, must survive a DB swap), so they belong to the single
settings store:

```jsonc
"labels": {
  "defs":   [ {"id": "lbl_1", "name": "Rude", "color": "#ff3b30", "created_at": "…"} ],
  "assign": { "Angelochenek": ["lbl_1", "lbl_2"] },
  "filter": { "include": ["lbl_3"], "exclude": ["lbl_1"] }
}
```

Consequences: labels survive `Clean DB` / `Load DB`, work with the archive
switched off, and the People and Storage rows are enriched at read time by
the Bridge (`_refresh_users()` / `userdb_page`), never by a join in SQL.

### D3 — Undo kinds: three new *command* kinds

`stack`/`grid` entries are **state snapshots**; `people` entries are
**reversible commands** (`{before, after}`). The new surfaces are commands
too, so `undo()`/`redo()` grow a shared notion of command kinds instead of a
fourth ad-hoc special case:

| kind | value | undo | redo |
|---|---|---|---|
| `labels` | `{before: <labels section>, after: <labels section>}` | write `before` | write `after` |
| `archive` | `{op, nick, token?, person?, people?}` | un-stamp / un-tombstone / restore People rows | re-apply |
| `dbconn` | `{op, before_path, after_path, backup?}` | switch back / restore the backup | re-apply |

`COMMAND_KINDS = {"people", "labels", "archive", "dbconn"}` in
`Bridge`, and the same list in `App` (`ui/js/app.js`) so the local mirror
keeps the entries. Stepping *onto* a command entry during a multi-step walk
applies its forward (`after`) half — identical to the existing `people`
behaviour.

### D4 — Two more grid windows ⇒ layout version 3

`labels` (Label Manager) and `dbconn` (DB Connection) are ordinary windows:
they live in the split tree, appear in the Windows menu with the
open/closed icon, and can be minimized/maximized/dragged like every other
panel. The persisted window set is validated, so the version goes 2 → 3 and
BOTH validators learn a generic "older version ⇒ migrate" path
(`SashCore.deserialize`, `Bridge._parse_grid_payload`) instead of the current
hard-coded "v1 has exactly the seven legacy windows" branch. Users keep
their arrangement; the new windows are appended as a bottom row.

---

## 4. Backend design

### 4.1 `backend/label_store.py` (new)

```python
class LabelStore:
    def __init__(self, config)                 # ConfigManager, section "labels"
    # definitions
    def defs(self) -> list[dict]
    def create(self, name, color="") -> dict | None      # unique by casefolded name
    def update(self, label_id, name=None, color=None) -> dict | None
    def delete(self, label_id) -> bool                   # + unassign everywhere + drop from filter
    # assignment
    def labels_for(self, nick) -> list[dict]
    def assign(self, nick, label_id) -> bool
    def unassign(self, nick, label_id) -> bool
    def set_for(self, nick, ids) -> bool
    def rename_nick(self, old, new) / def forget(self, nick)
    # filtering
    def filter(self) -> dict                             # {"include": [...], "exclude": [...]}
    def set_filter(self, include, exclude) -> dict
    def allows(self, nick) -> bool                       # exclude wins; include = whitelist
    # undo support
    def snapshot(self) -> dict ; def restore(self, snapshot) -> None
    def state(self) -> dict                              # defs + assign + filter, for the UI
```

Rules: ids are `lbl_<n>` (monotonic, never reused); colors are validated
`#rrggbb` (falls back to a palette colour); names are trimmed, ≤ 40 chars,
deduplicated case-insensitively; unknown ids are dropped on read so a corrupt
config can never crash the panel.

`allows(nick)`: a person with any excluded label is rejected; when the
include set is non-empty, a person must carry at least one included label.
That is the definition used by both the table filter and the run queue, so
"ignore all persons labeled Rude during auto-messaging" is one rule in one
place.

### 4.2 Archive changes

`history_db.py`
* `LATE_COLUMNS["messages"] += [("deleted_at", "TEXT NOT NULL DEFAULT ''")]`
* index `idx_messages_alive ON messages(person_id, deleted_at)`
* `file_size()` counts `-wal`/`-shm` siblings too; new `text_bytes()` helper is
  in the query layer.

`history_repo.py`
* `new_op_token()` → `"2026-09-07T18:22:31#9f3ac1de"`.
* `soft_delete_message(nick, message_id) -> token|""`
* `soft_delete_history(nick) -> token|""`  (every live message of the person)
* `restore_deleted(nick, token) -> int`  (exact reversal)
* `redo_delete(nick, token, ids)` is just the same stamp again — the token is
  reused so undo stays a one-liner.
* `delete_person(nick, hard=False)` also stamps the person's live messages
  with the token when soft, so "remove person WITH history" and "restore"
  are symmetric; `hard=True` still erases (used only by explicit purge).
* `purge_deleted(nick=None) -> int` — the only place rows are erased.
* `_recount()` and `_after_write()` ignore `deleted_at <> ''` so counters,
  `last_ord` and the resume cursor never count hidden rows.

`history_query.py`
* every `messages` query gains `AND m.deleted_at=''`;
* `_item()` exposes `"id"` (needed to delete one message) and `"deleted"`;
* `db_stats()` gains `text_bytes` (`SUM(LENGTH(text))`), `deleted_messages`,
  `db_bytes` (file + WAL), and the media folder size.

### 4.3 `backend/db_manager.py` (new)

Filesystem/lifecycle operations for the archive database, independent of the
running service:

```python
class DbManager:
    def __init__(self, config, service_getter)   # HistoryService or None
    def list_dbs(self) -> list[dict]             # *.db next to the active one + remembered paths
    async def info(self) -> dict                 # sizes: total / text / images / counts / paths
    async def create(self, name) -> dict         # new empty schema, becomes active
    async def load(self, path) -> dict           # switch the live service over
    async def delete(self, path) -> dict         # move file (+wal/shm) into db_trash/, never unlink
    async def clean(self) -> dict                # backup into db_trash/, then wipe all rows
    async def restore_backup(self, backup) -> dict
```

Undo: `create`/`load` remember `before_path`; `delete`/`clean` remember the
trash copy, so `Ctrl+Z` puts the file back and reconnects. The trash folder
(`db_trash/`) is inside the app folder and is `.gitignore`d.

`HistoryService.switch_db(path)` closes the current connection, re-opens
`HistoryDB` at the new path, re-points `repo`/`query`/`media`/`collector`,
and returns the new settings; the collector is paused during the swap and
resumed afterwards (fail-closed: a failed swap re-opens the previous file).

### 4.4 `backend/bridge.py`

New signals: `labels_changed(str)`, `db_info_ready(str, str)`,
`db_changed(str)`.

New slots (all thin, all reporting through the existing log/error channels):

```
labels_state() -> str                      label_create(name, color)
label_update(id, name, color)              label_delete(id)
label_assign(nick, id)                     label_unassign(nick, id)
label_set_filter(json)                     label_clear_filter()
history_delete_message(nick, message_id)   history_clear_person(nick)
history_delete_person(nick, hard)          (existing, now undoable + People row)
db_list() -> str                           db_info(req_id)
db_create(name)                            db_load(path)
db_delete(path)                            db_clean()
```

Enrichment: `_refresh_users()` adds `"labels": [...]` per person, and
`userdb_page` adds the same to every archive row — one place each, read time
only.

Run-queue integration: `ActionEngine.label_filter` is an optional callable;
`Bridge` sets it to `self._labels.allows`. `queue_order()` and
`_execute_cycle()` drop people the filter rejects, so the People-list `#`
column and the actual run agree (RULE 10: one control, one decision). This
is a *guard*, not a purge — nothing is deleted (RULE 6/11 stay intact).

---

## 5. Frontend design

### 5.1 `ui/js/color-picker.js` — movable popup

* `ColorPicker.open({ anchor, color, onPick, onCancel })` builds a
  ~280×320 dark popup with a title bar ("Pick Color" + ✕), a 5×4 grid of 20
  bright preset circles (Red, Orange, Yellow, Lime, Green / Teal, Cyan, Sky
  Blue, Blue, Indigo / Violet, Purple, Magenta, Pink, Hot Pink / Coral,
  Amber, Chartreuse, Spring Green, Aqua) and a Cancel button.
* Dragging the title bar moves it (pointer events, clamped to the viewport);
  the last position is remembered for the session.
* Clicking a circle gives it a white ring, fires `onPick(hex)` and closes;
  Cancel / ✕ / `Esc` closes without a change.
* Built with `createElement` only (same discipline as `history-view.js`), so
  hostile label text can never become markup.

### 5.2 `ui/js/labels.js` — model + pills + Label Manager window

* `Labels.state` mirrors the backend payload; `Labels.refresh()` pulls it,
  `labels_changed` pushes it.
* `Labels.pillsFor(nick, {onRemove})` returns a `<span class="label-pills">`
  with one compact rounded pill per label: semi-transparent bright
  background (`color` at 22 % alpha), a 1 px border in the colour, white
  text, and a `✕` button that removes the label **from this person only**.
* Used by BOTH tables (People and Full User Database) — the same renderer,
  so the two rows can never drift apart.
* The Label Manager window (`#winLabels`) has the four spec sections:
  1. **Active labels** — every label as a pill with ✕ = delete globally
     (also unassigns it everywhere);
  2. **Create new label** — text input + colour dot button (opens the color
     picker) + "+ Add Label";
  3. **Filter by labels** — a checkbox list plus the green
     "Include Selected" and red "Exclude Selected" toggles and a
     "Clear filter" button; the current role of each label (✓ include /
     ✕ exclude) is shown on its row, the resulting rule is applied live to
     both tables and to the run queue;
  4. **Assign to person** — a "Select person…" dropdown that *follows the
     current selection* (the person opened in Person History / clicked in
     either table) and shows which labels they already carry, a list of
     labels to toggle, and an "Assign" button.

### 5.3 `ui/js/db-panel.js` — DB Connection window

`#winDbConn` shows the active database path, the list of known databases
(click to load), the four buttons (**＋ Create new DB**, **📂 Load DB**,
**🧹 Clean DB**, **🗑 Delete DB**) and the info block:

```
Full size   12.4 MB      Text 1.9 MB      Images 10.1 MB (312 files)
persons 148 · messages 24 130 · hidden 12 · media 312
```

Sizes are refreshed after every DB action, after `userdb_changed`, and on a
manual ↻. Destructive buttons go through the existing in-app confirm modal
(`#confirmModal`) and then record one undo entry.

### 5.4 Person History / tables

* `history-view.js`: each message row gets a `msg-del` ✕ button
  (`opts.onDeleteMessage(id, row)`), hidden until the row is hovered so the
  transcript stays readable.
* `history-store.js`: toolbar gains "🧹 Clear chat" (keep the person) and
  "🗑 Delete person" (person + history), both routed through the confirm
  modal, both undoable.
* `user-table.js`: a new **Labels** column between Nick and Gender with the
  shared pills, plus a `🏷` button that opens the Label Manager focused on
  that person. Rows the label filter rejects are hidden (with a footer note
  saying how many are hidden and why).
* `history-db.js`: a **Labels** column and a row action group
  (`🏷 label`, `🧹 clear`, `🗑 delete`).

### 5.5 Grid registration

* `sash-core.js`: `WINDOWS += {labels: 'Label Manager', dbconn: 'DB Connection'}`,
  `VERSION = 3`, `V2_WINDOW_IDS` recorded, `deserialize()` migrates ANY older
  version through the existing `migrate()`; presets/default tree updated.
* `sash-grid.js`: `winElIds` + `WIN_ICONS` entries (`label`, `dns`).
* `bridge.py`: `NEW_WINDOW_IDS_V3`, `GRID_VERSION = 3`, `_migrate_grid_tree`
  appends whichever windows are missing (works for v1 and v2 payloads).

---

## 6. Undo matrix (RULE 12 — one timeline, one `Ctrl+Z`)

| User action | Entry | Reversal |
|---|---|---|
| create / rename / recolour / delete label | `labels` | previous labels section |
| assign / unassign label (incl. pill ✕) | `labels` | previous labels section |
| change the label filter | `labels` | previous filter |
| delete one message | `archive {op:"delete_message"}` | un-stamp the token |
| clear a person's chat | `archive {op:"clear_history"}` | un-stamp the token |
| delete person + history | `archive {op:"delete_person"}` | un-tombstone + un-stamp + restore the People row |
| create / load DB | `dbconn {op:"create"/"load"}` | switch back to `before_path` |
| clean DB | `dbconn {op:"clean"}` | restore the pre-clean backup |
| delete DB | `dbconn {op:"delete"}` | move the file back out of `db_trash/` |

Automatic side effects (collector writes, media eviction) are never recorded,
exactly as today.

---

## 7. Tests (RULE 8 — run the real thing)

| File | Proves |
|---|---|
| `tests/test_label_store.py` | CRUD, unique names, colour validation, assignment, cascade delete, include/exclude semantics, snapshot/restore |
| `tests/test_archive_delete_undo.py` | message/history/person soft delete hides rows and fixes counters; the collector cannot resurrect a deleted line; undo/redo restore exactly the affected set through the real `Bridge` global timeline |
| `tests/test_db_manager.py` | create/load/delete/clean, trash backups, size report (full/text/images), undo of each |
| `tests/test_labels_ui.js` | pills render as text (never markup), ✕ removes only from that person, the color picker has 20 presets + drag + cancel, Label Manager sections exist and are wired |
| `tests/test_sash_core_v2.js` (extended) + `tests/test_grid_layout_v2_migration.py` (extended) | v3 window set; v1 and v2 layouts migrate instead of being rejected |

---

## 8. Risks and mitigations

* **A huge conversation cleared** — the token makes undo O(1) in payload
  size; no message bodies ever enter `config.json`.
* **DB swap while the collector is writing** — the collector is stopped
  before the swap and restarted after it; a failed swap reopens the old file
  and reports the error (fail closed).
* **Corrupt `labels` section** — every read normalises and drops unknown
  ids/colours instead of throwing (RULE 13: never persist state you cannot
  read back).
* **Existing layouts** — generic version migration keeps arrangements; the
  validators still reject structurally broken trees.
* **Label text is hostile input** — pills are built with
  `createElement`/`textContent`, never with markup strings.

---

## Implementation status (2026-09-07)

Shipped exactly as designed. Code:

| Area | Files |
|---|---|
| Soft delete | `backend/history_db.py` (schema v4 + `deleted_at`, WAL-aware `file_size()`), `backend/history_repo.py` (`new_op_token`, `soft_delete_message`, `soft_delete_history`, `restore_deleted`, `purge_deleted`), `backend/history_query.py` (alive filters, `messages_hidden`, `text_bytes`) |
| Labels | `backend/label_store.py`, label hooks in `backend/action_engine.py`, `labels` in `backend/config_manager.py` |
| Databases | `backend/db_manager.py`, `_stop_collector`/`_restart_collector`/`switch_db` in `backend/history_service.py` |
| Bridge | `backend/bridge.py` — new slots/signals, `archive`/`labels`/`dbconn` undo kinds, `Bridge._schedule()` |
| UI | `ui/js/labels.js`, `ui/js/db-panel.js`, `ui/js/color-picker.js`, `ui/css/labels.css`, plus the two new grid windows in `ui/index.html` and grid **v3** in `ui/js/sash-core.js` / `sash-grid.js` |

Tests (all green):

| Suite | Cases |
|---|---|
| `tests/test_person_labels.py` | 41 |
| `tests/test_db_manager.py` | 34 |
| `tests/test_archive_delete_undo.py` | 25 |
| `tests/test_labels_ui_js.js` | 46 |
| `tests/test_db_panel_js.js` | 16 |
| `tests/test_history_panels_boot.js` (extended) | 35 |
| migrated to grid v3 | `tests/test_sash_core_v2.js`, `tests/test_grid_layout_v2_migration.py`, `tests/test_grid_persistence.py`, `tests/test_history_bridge.py` |

Deviations from the design: none of substance. Two hardening details were
added while testing — `Bridge._schedule()` (label slots run outside a running
event loop in tests) and the collector “parking” state returned by
`HistoryService._stop_collector()`, needed so a DB switch restores the
collector flag even when no background task was running.
