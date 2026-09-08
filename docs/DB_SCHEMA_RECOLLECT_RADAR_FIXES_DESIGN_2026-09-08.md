# DB Schema Errors, History Display, Re-Collection & Radar Count — Design

Date: 2026-09-08
Status: implementation design, written BEFORE the code changes (AGENT_RULES
process).
Bug report: 🔴 CRITICAL — five open bugs across `chat.db` / `history.db` /
`chat2.db` (schema errors on every connect, Person History without message
text, no re-collection after a history clear, Radar "Added 25 msg" vs an
empty archive, DB creation without schema validation).

---

## 1. Problem statement

Five linked defects, one per bug report section:

| # | Symptom | Root cause found in the code |
|---|---------|------------------------------|
| 1 | `⚠ no such column: person_id` on EVERY connect to every DB file | `HistoryDB.init()` runs `_migrate_dup_keys()` (and `SCHEMA`'s index statements) against whatever table shape the file happens to have. A file whose `messages` table predates `person_id` (or is otherwise incomplete) makes every open throw — and because the failure happens *before* any repair, the file never heals and the same warning repeats on every reconnect. `LATE_COLUMNS` only knows the columns added after the first release; `person_id` itself is not in the list, and there is no post-open validation. |
| 4b | re-collected lines silently NOT stored after a clear | `messages` also carried the pre-v4 table constraint `UNIQUE(person_id, fp, day)`. The hidden twin kept its `fp`+`day`, so every re-collected copy collided and `INSERT OR IGNORE` dropped it — "added 25", archive 0. Since v4 deduping is the partial unique index on `(person_id, dup_key)`, which ignores identity-released hidden rows; the old table constraint is removed (and rebuilt away on existing files). |
| 2 | Person History shows nicknames but no message text (2 rows, empty bodies) | In-page agent: `walk()` caches a node's parsed fields and only re-parses when the **media URL** changed. A node parsed before Angular rendered `span.message` (or before the title/nick settled) keeps `text=''` forever — the cache never invalidates on text. Those empty rows are archived as visible rows with no body. Also: the empty-slot repair path only accepts **media** records, so a same line that later renders its text can never fill its own empty slot — a second copy with text would duplicate the first empty one. |
| 3 | After 🧹 Clear history, messages are never re-collected | `soft_delete_history()` hides the rows but leaves the resume `cursor` (bootstrapped=1, dom_count, head/tail sigs, full_scan_complete=1) untouched, so the collector's `unchanged` shortcut answers "no new messages" forever. Even on a full re-read, every line's `dup_key` still matches its hidden row, so `_existing_dup_keys` + `idx_messages_dup_key` filter everything — nothing can come back. |
| 4 | Radar: "Added this session 25" but "In archive 0" | Three adders, none telling the truth together: (a) the collector panel accumulates `payload.added` across **all partners and DB switches** and never resets; (b) `_empty_slot_rows`/`recover_media` happily fill **soft-deleted** rows, so `append()` counts "added" rows that stay invisible (`_recount` only counts `deleted_at=''`); (c) after a partner nick change, new messages go to a NEW person while the panel still shows the old partner. |
| 5 | DB creation/switch system does not validate schema | Same as #1 — creation only worked because a fresh file gets the full `CREATE TABLE` script; any existing file was trusted blindly, with no canonical-shape comparison, no auto-migration and no schema-version check. |

Plus the report's side note: *"if User use Now diff name as Person in chat it
should be also correctly processed"* — a partner who RENAMES themselves, or
**my own nick** changing between sessions, currently produces a brand-new
empty person (or refuses collection outright, see §4.4) instead of
continuing the history.

## 2. Guiding decisions

### D1 — an old database file is repaired in place at open, never rejected

`HistoryDB.init()` becomes a validate → repair → verify pipeline:

1. `_repair_tables()` — for each canonical table: create it when missing;
   compare `PRAGMA table_info` with the canonical column list and
   `ALTER TABLE ADD COLUMN` everything missing (the old `LATE_COLUMNS`
   mechanism, generalised to the whole schema);
2. a `messages` table **without `person_id`** is rebuilt: the legacy table is
   renamed to `messages_legacy_<stamp>`, a canonical `messages` is created,
   and every legacy row is copied over, attributed to a person derived from
   the legacy `nick` column. When the rows cannot be attributed (no usable
   column) the legacy table is KEPT as quarantine and the app continues with
   an empty archive — no byte is ever destroyed by an open;
3. index names abandoned by the rebuild are dropped first (automatic
   indexes from table constraints cannot be dropped — they die with the
   table), so `CREATE INDEX IF NOT EXISTS` really recreates them on the new
   table;
4. a `messages` table still carrying the pre-v4 `UNIQUE(person_id, fp, day)`
   constraint (see 4b above) is rebuilt once on open — same columns, same
   rows, constraint gone;
5. `_verify_schema()` runs after migration: a file that still fails the
   canonical-column check raises ONE clear error ("cannot open … schema
   incomplete") instead of a different `no such column` on every later
   query — including when the repair itself failed. `switch_db` already
   falls back to the previous file on such an error, so the app stays
   connected (fail closed);
6. `schema_meta.schema_version` is stamped after a successful migration and
   checked against the code's version — a file written by a NEWER build logs
   a warning instead of failing mysteriously. `_migrate_dup_keys` backfills
   identity only for VISIBLE rows: a history clear's released identities
   survive an app restart, so the promised re-collection still happens.

`SCHEMA_VERSION` moves 4 → 5 (identity release + re-collection semantics,
§3). Fresh DBs are built from the same canonical definition that validation
compares against, so creation and validation can never drift apart (pinned
by a parity test).

### D2 — clearing a chat releases the messages' identity and re-arms the collector

RULE 14 keeps the tombstone (Ctrl+Z must work); what changes is *identity*:

* `soft_delete_history()` stamps the rows AND blanks their `dup_key`
  ("identity release"): a hidden row no longer claims `timestamp+content`,
  so it can neither block re-collection (dedupe lookup) nor collide with it
  (partial unique index only indexes `dup_key <> ''`);
* the same open also calls `reset_cursor()` — bootstrapped/dom_count/head/
  tail/full_scan are the "already collected" markers the bug report wants
  reset. `last_ord` is deliberately kept: ord never repeats (RULE: a delete
  must never make the next append reuse an ord);
* the bridge's clear path does both and pokes the collector
  (`person_cleared`) so the Radar's "In archive" goes to 0 immediately;
* the person record, `my_nicks`, first/last seen and the media cache are
  untouched — only message history and collection markers reset (the
  report's "keep tracking state" requirement).

Single-message deletes keep their `dup_key` — a deleted single message must
NOT resurrect on the next backfill (D1 of 2026-09-07, pinned by the existing
`test_a_deleted_message_never_comes_back_by_collecting_again`).

### D3 — undo of a clear does not duplicate what re-collection already brought back

`restore_deleted()` (and the person-restore path) recompute each restored
row's `dup_key` from its stored fields. A row whose identity already exists
on a **visible** row was re-collected while hidden: its stale tombstone copy
is dropped for good (the content survives in the re-collected twin) instead
of coming back as a visible double. Rows whose identity is free come back
with their key restored. Both paths resequence `ord` and recount.

### D4 — a line that renders late heals its own empty row

* the agent's node cache is invalidated whenever ANY parsed field changed
  live — nick, text, media URL, time — not just the media URL. A node whose
  `span.message` renders after the first parse is re-parsed on the next
  walk, and the push carries the real text (Bug 2 at the source);
* `_take_empty_slot()` accepts any payload-bearing record (text OR media),
  so the next full read fills the historical empty rows in place instead of
  inserting a duplicate next to them. Slot matching stays strict:
  direction + author + HH:MM + resolved day, consumed in `ord` order;
* empty-slot lookup and media recovery ignore soft-deleted rows — filling a
  hidden row can never again count as "added" (Bug 4b).

### D5 — a renamed partner continues the same person; a renamed "me" is adopted

* Partner rename: before creating a person for a changed tab title, the
  collector asks the repo: if the pane is LITERALLY the same pane element
  the previous probe watched (the agent reports `pane_same` — a rename
  happens inside the open pane, while switching conversations always swaps
  panes), the message count did not change, and the conversation's head AND
  tail still match what the previous partner's cursor ended with — compared
  with BOTH the exact signatures and the new author-agnostic ones
  (`head_any`/`tail_any`: fingerprint without the nick, because the site may
  re-render the past under the new nick) — then the person row is renamed in
  place, its stored lines are re-attributed to the new nick (identity
  recomputed), and the history, cursors and counters continue. Otherwise the
  old behaviour applies (new person; merge stays a manual action in the
  Storage window);
* My-nick rename: when the pane self-reports a `me` that differs from the
  configured My Nick and the configured nick does NOT appear among the
  pane's outbound authors, the configured value is stale — the collector
  adopts the pane's value for the session and logs the change. The private
  gate (`verify_private`) accepts the pane-reported `me` as a valid "me"
  identity, so old outbound lines under the previous nick can no longer make
  the gate refuse ("strangers") after a rename.

### D6 — the Radar counts what the database received, per partner

`Added this session` becomes a per-partner counter in the collector panel:
it resets when the archive database changes and when a person's history is
cleared/purged/deleted (`userdb_changed`), and it reads the counter of the
partner currently shown. `In archive` keeps coming from the collector's
`total`, which is now correct after every clear (D2) and after slot fills
(D4) because `_recount` is the single source of truth.

## 3. Message pipeline after the fix

```
detect (agent probe/push) → gate (verify_private) → align (cursor/dup_key)
  → validate (payload present; empty slots filled in place) → store (append)
  → confirm (recount → person.message_count → Radar "In archive";
             AppendResult.added → Radar "Added this session", per partner)
```

Every counter the user can see is derived from a committed write.

## 4. Implementation map

| Area | File | Change |
|------|------|--------|
| Schema validation + legacy repair | `backend/history_db.py` | canonical `TABLE_SQL`/`TABLE_COLUMNS`, `_repair_tables`, legacy messages rebuild, legacy-constraint rebuild, `_verify_schema`, version stamp/compare, `SCHEMA_VERSION="5"` |
| Identity release + re-collection | `backend/history_repo.py` | `soft_delete_history` blanks `dup_key` + resets cursor; `delete_person` (soft) likewise; restore recomputes keys, skips/drops re-collected collisions; empty slots alive-only and text-capable; media recovery alive-only; `rename_if_same_conversation` (pane identity + author-agnostic sigs + count, re-attributes stored lines); cursor gains `head_any`/`tail_any` |
| Rename + stale My Nick + clear poke | `backend/collector.py` | rename detection before `ensure_person`; adopt pane `me`; `person_cleared()` |
| Gate tolerates a renamed me | `backend/chat_parser.py` | `verify_private` uses the pane-reported `me` as an accepted identity |
| Late-render text at the source | `backend/js/chat_agent.js`, `backend/chat_agent_js.py` | full-field cache invalidation in `walk()`; author-agnostic fps + `pane_same` in `state()`; `VERSION` 9 → 10 |
| Clear wiring | `backend/bridge.py` | `history_clear_person` resets the cursor + pokes the collector; clear log wording mentions re-collection |
| Radar counters | `ui/js/collector-panel.js`, `ui/js/app.js` | per-partner "Added this session"; reset on `db_changed` / `userdb_changed` |
| Tests | `tests/test_db_schema_migration.py`, `tests/test_recollect_after_clear.py`, `tests/test_db_switch_e2e.py` (new), `tests/test_collector_panel_js.js` (new), `tests/test_history_agent_js.js` (+4 late-render/rename cases), `tests/test_chat_parser_delta.py` (FakePage models v10 probes), `tests/test_history_repo.py` (version bump), `tests/test_media_recovery_e2e.py` (date-robust) | see §6 |

## 5. Undo / safety surface

* Clear stays undoable: Ctrl+Z after a clear (with no re-collection yet)
  brings every message back with its identity recomputed — the existing
  `test_a_cleared_chat_comes_back_whole` still passes;
* Ctrl+Z after clear + re-collection restores the conversation as it was
  *re-collected* (no doubles);
* single-message delete stays permanent through backfills (dup_key kept);
* `purge_deleted` erases the tombstones (with blank keys) exactly as before;
* no open ever destroys data: unattributable legacy rows survive in a
  quarantine table and the archive continues empty;
* RULE 15 untouched — the two-step gate still guards every write path.

## 6. Verification plan

1. Fresh DB → open → `PRAGMA table_info` of every table equals the canonical
   column list; `schema_meta.schema_version = 5`.
2. Legacy file (messages without `person_id`, rows carry `nick`) → open →
   rows attributed to persons, counts correct, no warning on the NEXT open.
3. Collect a conversation → clear history → next tick re-collects the same
   lines; Radar "Added" equals the DB's alive rows for that person.
4. Clear → collect → Ctrl+Z → no duplicate rows, content present once.
5. Message text rendered late (JS stub) → the push carries the text; an
   existing empty row is filled, not duplicated.
6. Partner renames inside the same pane → the SAME person row is renamed,
   stored lines re-attributed, history continues; the same content in a
   DIFFERENT pane is never merged; own-nick rename is adopted and the gate
   keeps collecting.
7. The user's log scenario end-to-end (three DB files, create/switch/clear/
   re-collect) runs without a single "no such column" in the log.
8. Full test suite green (including the previously date-dependent media
   recovery test).
