# Message History Archive — Master Architecture

Date: 2026-09-06
Status: **DESIGN ONLY — no code written for this feature yet**
Scope: feature request "Message History Database & Preview" + feature
request "Passive Private Chat Message Collector" (they are one system with
two faces — a writer and a reader — and are designed together here).

Companion documents (read in this order):

| # | Document | Covers |
|---|---|---|
| A | **this file** | data model, media, module map, bridge contract, invariants |
| B | `PASSIVE_CHAT_COLLECTOR_DESIGN_2026-09-06.md` | detection, delta algorithm, in-page agent, statuses, action block |
| C | `HISTORY_UI_WINDOWS_DESIGN_2026-09-06.md` | the 3 new grid windows, lazy loading, copy/select, search UX |
| D | `MESSAGE_HISTORY_IMPLEMENTATION_PLAN_2026-09-06.md` | milestones, dependency graph, tests, risks, open questions |

---

## 1. What is being built (restated from the request)

1. **Persistent archive** of every message exchanged with every person —
   text *and* images/GIFs, both directions, keyed by the person's nick.
2. **Person History window** — click a nick in the People Memory list, see
   the full chronological conversation inline (text + media), selectable
   and copyable text, click-to-copy media.
3. **Full User Database window** — every person ever recorded, across all
   sessions, merged by nick (never duplicated), browsable with lazy
   scrolling (configurable preload rows, images on/off), clickable into the
   history preview.
4. **Two access points** — People Memory (this session) and Full User
   Database (all time).
5. **Search** — inside one conversation, globally across all conversations,
   and by nick inside the user database.
6. **Passive background collector** — watches the active tab, recognises a
   private chat (me + exactly one other person), parses the conversation
   once, then appends new lines as they arrive, without freezing the UI,
   with a live status indicator and its own control window.
7. **Action block** — a stack block that parses the current conversation
   and writes new lines into the archive on demand.
8. **My Nick** — configurable (it changes between sessions), stored, shown
   in the pinned header, and recorded on every archived message.

### Decisions locked with the user before design

| # | Question | Decision |
|---|---|---|
| D-1 | Media storage | **Hybrid** — URL + SHA-256 in the DB, bytes cached on disk under a size cap, with a "cache media" toggle |
| D-2 | Where the new surfaces live | **Panels in the existing sash grid** (`SashCore.WINDOWS`), draggable/splittable like every other window |
| D-3 | Collector during an Action Stack run | **Keeps collecting, throttled**: longer heartbeat, smaller chunks, media downloads paused, and a priority lease on the CDP socket so the engine always wins |

---

## 2. Audit — what already exists that this must fit into

| Concern | Today | Consequence for this design |
|---|---|---|
| Chrome access | `backend/cdp_client.py` — one WebSocket, `evaluate()` already uses `awaitPromise:true`, `max_size=50 MB`, 30 s command timeout | Media can be fetched *inside the page* and returned as base64 through one `evaluate`. **Gap:** `_receive_loop()` throws away every message without an `id`, i.e. all CDP *events* → an event-subscription API must be added before push-based collection can work |
| People list | `backend/user_memory.py` → `chatbot.db`, table `users` (nick UNIQUE), queue semantics, purges | The archive must **not** live in this table and must **not** be purged with it (see §9, RULE 6 tension) |
| Settings + presets | `backend/config_manager.py` → single `config.json` (`get/set`, `named_*`, `get_state/set_state`) | All new settings go into the same file; `my_nick` becomes a first-class setting |
| Qt↔JS | `backend/bridge.py` — `@Slot` methods, Qt `Signal(str)` carrying JSON | New slots/signals follow the same shape; async DB reads answer through a `req_id`-correlated signal |
| Run engine | `backend/action_engine.py` — `report()`, `person_found`/`person_marked` signals, stop/pause flags | Collector subscribes to run start/stop to enter throttled mode; the action block reports through `engine.report()` (RULE 2) |
| Blocks | `actions/*.py`, registered via `__init_subclass__`, settings are plain attributes, mirrored in `ui/js/stack-dnd.js` | `COLLECT_HISTORY` follows exactly this (RULE 3) |
| UI shell | `ui/index.html` + `ui/js/sash-*.js`; window set validated **twice** (`SashCore.WINDOW_IDS` and `Bridge.WINDOW_IDS`) and a mismatching layout is **rejected** (RULE 13) | Adding 3 windows requires a coordinated **layout v1 → v2 migration** on both sides, or every user loses their saved layout on first start (see doc C §2) |
| Active-conversation resolution | `backend/media_handler.py` `CTX_PROBE_JS` already resolves the *visible* composer and returns CSS paths | Reuse the same idea to scope parsing to the visible conversation — never scrape a hidden main-room message list |
| Tests | `tests/js_harness.js` executes real probes against a DOM stub; pipelines run against fake CDP clients (RULE 8) | Same approach for the agent JS and the collector |

---

## 3. Verified DOM facts (extracted from the saved pages in this repo)

Source: `Вирт чат privat.html` (private chat) and `Вирт чат.html` (main
room, contains image/GIF messages). Everything below was read out of those
files, not assumed.

### 3.1 One message

```
app-messages > div.messages-root
  └── div                                   ← one wrapper per message
        ├── div.message-container [ my-message-background | general-background ]
        │     ├── mat-menu
        │     └── div.message-content
        │           ├── p.message
        │           │     ├── span.additional-icon
        │           │     │     ├── mat-icon[data-mat-icon-name=male|female]
        │           │     │     └── mat-icon[data-mat-icon-name=anonymous|registered]
        │           │     ├── span.from                    ← SENDER NICK
        │           │     ├── span " ▸ "
        │           │     ├── span.message                 ← TEXT   (text message)
        │           │     └── app-chat-image               ← MEDIA  (image message)
        │           │           └── div.image-wrapper
        │           │                 ├── mat-icon.source-indicator
        │           │                 └── img[loading=lazy][alt="chat image"][src=…]
        │           └── div.message-status
        │                 ├── span.sent-time               ← "17:31"  (HH:MM only!)
        │                 └── span.sent|sending|error.state-icon
        └── mat-divider
```

Facts that drive the design:

* **Direction is a class**: `my-message-background` = sent by me,
  `general-background` = received. `span.from` still carries a nick on both
  sides, so direction can be cross-checked against My Nick.
* **There is no message id and no date** — only `HH:MM`. Identity and
  ordering therefore have to be synthesised (§6).
* **Media is a plain `<img>`** inside `app-chat-image`; GIF vs still image
  is decided by the URL extension / content type (`…_.gif` in the sample).
* Text and media are *alternatives* inside the same `p.message`; a message
  can also carry both an icon set and text.

### 3.2 Private-chat evidence (all present in the saved private page)

| Signal | Selector | Value in the sample |
|---|---|---|
| Active tab | `.tab-item.active` | the private one |
| Tab kind | `.tab-item.active mat-icon.chat-type-icon[data-mat-icon-name]` | `user` (private) vs `room` (main) |
| Partner nick | `.tab-item.active p.chat-title` (minus `span.unread`) | `На работе 25` |
| Participant count | `users-header-item .users-counter` | `2` |
| Participants | `user-item .primary-text` | `HiHoney`, `На работе 25` |
| **Me** | `user-item .primary-text.bold` | `HiHoney` ← own row is bold |

The bold own-row is the basis of the "Detect my nick" button (doc B §2.4).

---

## 4. Design decisions and rejected alternatives

| # | Decision | Why | Rejected |
|---|---|---|---|
| A-1 | Archive lives in its **own SQLite file** `history.db`, not in `chatbot.db` | different lifecycle (append-only, all-time) from the queue table, which is purged/replaced wholesale by filters and undo; independent VACUUM/backup; a corrupt archive must never take the People list down | extra tables in `chatbot.db` — one `replace_all()`/purge bug away from wiping the archive |
| A-2 | Logical key = **nick**, physical key = `persons.id` | request says "link history to the person's nick as the primary key"; a surrogate int keeps `messages` narrow and rename-tolerant later | nick as literal PK in every row (fat indexes, painful merges) |
| A-3 | Nick matching is **exact after normalisation** (NFC + trim + inner-whitespace collapse), *not* case-folded | the site renders nicks with padding (` На работе 25 `), so normalisation is required; case-folding could silently merge two different people. A "possible duplicate" hint (same `nick_lc`) is offered in the UI with an explicit **Merge** action | automatic case-insensitive merge |
| A-4 | **Hybrid media** (D-1) | preview keeps working after the site expires an image; DB stays small; identical GIFs stored once | BLOBs in SQLite (DB bloat, slow lazy scroll), URL-only (dead previews) |
| A-5 | Media bytes fetched by **in-page `fetch()` → base64 → Python** | runs with the page's own cookies/origin, so no auth/CORS problem; `evaluate()` already awaits promises | `Network.getResponseBody` (only for still-live responses), canvas re-encode (kills GIF animation) |
| A-6 | Collection is **push-first** (in-page MutationObserver + CDP binding), with a cheap heartbeat supervisor | the only design where an idle chat costs ~0 CPU and a new line lands in <300 ms; full re-parse of a long chat is the thing the user explicitly asked to avoid | polling + full parse (O(n) per tick), polling + diff of full text (still O(n) transfer) |
| A-7 | Idempotency by **deterministic dedupe key + suffix alignment** | the DOM has no ids; re-parsing the same conversation must never duplicate rows | timestamp+text uniqueness alone (breaks on legitimately repeated lines) |
| A-8 | Deleting a person's archive is a **tombstone** (soft delete + Undelete), not a global-undo entry | RULE 12's timeline stores full snapshots; snapshotting a 50 000-row archive per edit is not viable, and silently losing an archive is worse than any of the surfaces it protects | pushing archive deletes into `undo_history` |
| A-9 | The collector **never scrolls the user's page** on its own | moving someone's viewport while they type is hostile, and the scroll-parse pipeline already documents how corrupting the scroll position breaks tracking | auto-scrolling to backfill silently (offered instead as an explicit "Backfill older" button) |
| A-10 | The collector **never writes to the `users` table** | that table means "queue membership under the current filter" (RULE 6); the archive means "this happened". Mixing them would resurrect filtered-out people | upserting every private partner into People |

---

## 5. Data model — `history.db`

SQLite, WAL mode, `foreign_keys=ON`, opened through `aiosqlite` (already a
dependency — **this feature adds no new pip dependencies**).

```sql
-- ── schema bookkeeping ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL);           -- ('schema_version','1'), ('created_at',…)

-- ── one row per person ever talked to ─────────────────────────────
CREATE TABLE IF NOT EXISTS persons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nick            TEXT NOT NULL,          -- normalised display nick
    nick_lc         TEXT NOT NULL,          -- lowercase, for search/dupe hint
    first_seen      TEXT NOT NULL,          -- ISO, first archived message
    last_seen       TEXT NOT NULL,          -- ISO, last archived message
    message_count   INTEGER DEFAULT 0,
    media_count     INTEGER DEFAULT 0,
    in_count        INTEGER DEFAULT 0,
    out_count       INTEGER DEFAULT 0,
    my_nicks        TEXT DEFAULT '[]',      -- JSON array: every My Nick used here
    gender          TEXT DEFAULT 'unknown', -- last observed
    registered      INTEGER DEFAULT 0,
    anonymous       INTEGER DEFAULT 0,
    guest           INTEGER DEFAULT 0,
    deleted_at      TEXT,                   -- tombstone (A-8); NULL = live
    notes           TEXT DEFAULT '');
CREATE UNIQUE INDEX IF NOT EXISTS idx_persons_nick ON persons(nick);
CREATE INDEX IF NOT EXISTS idx_persons_nick_lc    ON persons(nick_lc);
CREATE INDEX IF NOT EXISTS idx_persons_last_seen  ON persons(last_seen DESC);

-- ── one row per message ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id     INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    ord           INTEGER NOT NULL,      -- monotonic position in this conversation
    direction     TEXT NOT NULL CHECK (direction IN ('in','out','sys')),
    from_nick     TEXT NOT NULL DEFAULT '',
    my_nick       TEXT NOT NULL DEFAULT '',   -- My Nick at the time of collection
    kind          TEXT NOT NULL CHECK (kind IN ('text','image','gif','service')),
    text          TEXT NOT NULL DEFAULT '',
    text_lc       TEXT NOT NULL DEFAULT '',   -- Python .lower() → Cyrillic-safe LIKE
    media_id      INTEGER REFERENCES media(id),
    ts_display    TEXT NOT NULL DEFAULT '',   -- "17:31" exactly as the site shows it
    ts_resolved   TEXT,                       -- ISO best-effort (§6.3)
    ts_exact      INTEGER NOT NULL DEFAULT 0, -- 1 only when derived from a real date
    collected_at  TEXT NOT NULL,              -- ISO, always exact
    session_id    TEXT NOT NULL DEFAULT '',   -- one app run
    source        TEXT NOT NULL DEFAULT 'collector', -- collector|block|import
    dedupe_key    TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_dedupe    ON messages(person_id, dedupe_key);
CREATE INDEX        IF NOT EXISTS idx_msg_person_ord ON messages(person_id, ord);
CREATE INDEX        IF NOT EXISTS idx_msg_kind       ON messages(person_id, kind);

-- ── media registry (hybrid storage, A-4) ──────────────────────────
CREATE TABLE IF NOT EXISTS media (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256      TEXT UNIQUE,             -- NULL until bytes are fetched
    url         TEXT NOT NULL,
    url_hash    TEXT NOT NULL UNIQUE,    -- sha1(url) — the pre-download identity
    kind        TEXT NOT NULL DEFAULT 'image',   -- image|gif
    ext         TEXT DEFAULT '',
    bytes       INTEGER DEFAULT 0,
    width       INTEGER DEFAULT 0,
    height      INTEGER DEFAULT 0,
    cache_path  TEXT DEFAULT '',
    state       TEXT NOT NULL DEFAULT 'pending'
                CHECK (state IN ('pending','cached','failed','skipped','evicted')),
    fail_reason TEXT DEFAULT '',
    ref_count   INTEGER DEFAULT 0,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    last_read   TEXT);                   -- for LRU eviction
CREATE INDEX IF NOT EXISTS idx_media_state ON media(state);

-- ── per-conversation collection cursor (the resume point) ─────────
CREATE TABLE IF NOT EXISTS cursors (
    person_id      INTEGER PRIMARY KEY REFERENCES persons(id) ON DELETE CASCADE,
    my_nick        TEXT DEFAULT '',
    last_ord       INTEGER DEFAULT 0,
    dom_count      INTEGER DEFAULT 0,   -- messages-root child count at last sync
    head_sig       TEXT DEFAULT '',     -- fingerprint of the first rendered node
    tail_sig       TEXT DEFAULT '',     -- fingerprint of the last rendered node
    tail_fps       TEXT DEFAULT '[]',   -- JSON: last K=200 fingerprints, for alignment
    bootstrapped   INTEGER DEFAULT 0,
    updated_at     TEXT NOT NULL);

-- ── honest record of holes in the archive ─────────────────────────
CREATE TABLE IF NOT EXISTS gaps (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id  INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    after_ord  INTEGER NOT NULL,
    reason     TEXT NOT NULL,          -- 'alignment_lost'|'buffer_trimmed'|'app_offline'
    noted_at   TEXT NOT NULL);

-- ── full-text search (created only when FTS5 is available, §7.2) ──
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text, content='messages', content_rowid='id', tokenize='unicode61');
-- + AFTER INSERT / UPDATE / DELETE triggers keeping the index in sync
```

### 5.1 Why `ord` and not a timestamp

The site exposes only `HH:MM`. Two messages in the same minute, a chat left
open across midnight, and a re-parse after a reconnect all break
timestamp-ordering. `ord` is a per-conversation monotonic integer assigned
at insert time in DOM order — it is the **only** ordering used by the
preview. Timestamps are display data plus a best-effort ISO value.

---

## 6. Message identity, dedupe and time

### 6.1 Fingerprint (per DOM node, computed in the page)

```
fp = sha1( direction | from_nick | ts_display | kind | payload | minute_occurrence )
payload          = text            (kind=text)
                 | media URL       (kind=image|gif)
minute_occurrence = how many earlier nodes in the SAME rendered list have an
                    identical (direction, from, ts_display, kind, payload)
```

`minute_occurrence` is what makes "ok" sent three times at 17:31 three
distinct messages while keeping the value **deterministic** — recomputing
it from the same DOM always yields the same number.

### 6.2 Dedupe key (per stored row)

```
dedupe_key = sha1( day_bucket | fp )
day_bucket = the resolved calendar day (§6.3)
```

`UNIQUE(person_id, dedupe_key)` + `INSERT … ON CONFLICT DO NOTHING` makes
every write idempotent: re-running the action block on the same page, a
double bootstrap after a reconnect, or an overlapping delta insert nothing.
The day bucket means the identical "Привет 09:00" sent on two different days
is two rows, as it should be.

### 6.3 Resolving dates from `HH:MM`

Walking the rendered list **backwards** from the collection moment:

1. `day = today` for the newest message.
2. Going back, whenever the time *increases* relative to the message after
   it, the day rolls back by one (`23:58` before `00:04` ⇒ previous day).
3. Rows produced this way get `ts_exact = 0` — the UI shows them as
   "≈ 05 Sep, 17:31" with a tooltip explaining the site only exposes a
   clock time.
4. `collected_at` is always the exact wall-clock time the row was first
   seen, and is what "Last activity" in the user database sorts by.

If the site ever renders date separators, a single parser hook
(`parseDaySeparator`) upgrades those rows to `ts_exact = 1`.

### 6.4 Alignment (how a re-parse finds "where we stopped")

Given the fingerprint list of what is rendered now (`dom_fps`) and the last
K stored fingerprints (`cursor.tail_fps`):

```
find the longest suffix S of tail_fps that appears as a contiguous block in dom_fps
   ├─ found at index i  → everything in dom_fps after i+|S| is new  → append
   ├─ tail_fps empty    → first bootstrap                           → append all
   └─ no overlap        → the DOM buffer rolled past what we stored
                          → append all, and record a `gaps` row
                            (reason='alignment_lost') so the preview can
                            draw an explicit "— history gap —" marker
```

The archive is allowed to be incomplete; it is **never** allowed to be
silently incomplete (RULE 4 applied to data).

---

## 7. Subsystem designs

### 7.1 Media pipeline

```
parse finds <img src="…">
   │
   ├─ media_store.register(url)         → row in `media` (state='pending', ref_count++)
   │                                      message row links media_id immediately
   ├─ if cache disabled OR run active   → state stays 'pending', preview uses the URL
   └─ else enqueue on the download worker (bounded queue, 2 concurrent)
          │  in-page: fetch(url) → blob → FileReader → base64   (page cookies, no CORS)
          │  cap: max_file_mb (default 5) — bigger ⇒ state='skipped', reason logged
          ├─ Python: base64 decode + sha256 + write, both in asyncio.to_thread
          │          → media_cache/<sha[0:2]>/<sha>.<ext>
          │          → dedupe: identical sha256 already cached ⇒ reuse, no second file
          └─ emit `media_ready` so an open preview swaps the placeholder in place
```

* **Eviction**: LRU over `last_read` when the cache exceeds `max_cache_mb`
  (default 512); evicted rows keep `url` and flip to `state='evicted'`, so
  the preview degrades to the remote URL instead of showing a broken box.
* **Clipboard**: clicking an image calls `bridge.copy_media(media_ref)`;
  Python puts the *image* on the Qt clipboard via `QGuiApplication.clipboard()`
  (works for PNG/JPEG; animated GIFs are copied as a **file reference + URL
  text**, because no clipboard on any OS carries an animated GIF reliably —
  the UI says so in the toast rather than pretending).
* `media_cache/` and `history.db*` are added to `.gitignore` (the existing
  `*.db`, `*.db-wal`, `*.db-shm` patterns already cover the DB files).

### 7.2 Search

| Search | Backing | Notes |
|---|---|---|
| Inside one conversation | FTS5 `messages_fts` restricted by `person_id`, else `text_lc LIKE '%q%'` | returns `ord` values → the preview jumps and highlights |
| Global across all people | FTS5 with `bm25()` ranking, grouped by person | result row = nick + snippet + time + `ord`; click opens that conversation anchored at `ord` |
| By nick in the user DB | `nick_lc LIKE 'q%' OR nick_lc LIKE '%q%'` (prefix ranked first) | index-backed, no FTS needed |

**Cyrillic correctness** — SQLite's built-in `LIKE`/`lower()` only fold
ASCII. Two mitigations, both required: FTS5 with the `unicode61` tokenizer
(folds Cyrillic), and a Python-lowered `text_lc`/`nick_lc` column for the
non-FTS fallback path. FTS5 availability is probed once at startup
(`CREATE VIRTUAL TABLE … ` in a savepoint); the result is stored in
`schema_meta.fts` and surfaced in the DB window ("fast search: on/off").

---

## 8. Module map, dependencies and line budget

New/changed files (repo style: small, single-purpose modules):

```
backend/
  history_db.py      NEW  ~180  connection, PRAGMAs, DDL, migrations, FTS probe
  history_repo.py    NEW  ~200  WRITE path: upsert person, append batch, cursors,
                                gaps, counters, tombstones, merge
  history_query.py   NEW  ~190  READ path: paged messages, person list paging,
                                search (conversation/global/nick), stats
  media_store.py     NEW  ~210  register/fetch/cache/evict/clipboard export
  chat_agent_js.py   NEW  ~240  the in-page agent source + probe builders (strings)
  chat_parser.py     NEW  ~220  run probes, normalise records, fingerprints, alignment
  collector.py       NEW  ~260  supervisor task, state machine, statuses, throttle
  cdp_client.py      MOD   +45  event subscription (on_event/off_event), add_binding,
                                Runtime.bindingCalled fan-out, priority lease
  bridge.py          MOD  +230  history/userdb/collector slots + signals, WINDOW_IDS v2
  action_engine.py   MOD   +15  run_started/run_finished notification for throttling
actions/
  collect_history.py NEW   ~95  COLLECT_HISTORY block (doc B §9)
  __init__.py        MOD    +1  register it
ui/
  index.html         MOD   +95  3 panels + pinned-header My Nick field
  js/history-store.js NEW ~150  client cache + req_id correlation + settings mirror
  js/history-view.js  NEW ~390  Person History window (virtual list, copy, search)
  js/history-db.js    NEW ~270  Full User Database window (lazy rows, nick search)
  js/collector-panel.js NEW ~200 Collector window (status, controls, counters)
  js/sash-core.js    MOD   +70  3 window ids + layout v1→v2 migration
  js/sash-grid.js    MOD   +20  panel element ids + drag-ghost icons
  js/user-table.js   MOD   +30  nick becomes a history link (data-act="history")
  css/history.css    NEW  ~280  bubbles, media tiles, lazy skeletons, status LED
tests/                     NEW  8 suites — see doc D §3
docs/                      this set of 4 documents
```

### 8.1 Dependency graph (build order falls out of it)

```
                     cdp_client(+events,+lease)
                              │
        history_db ───────────┼──────────── chat_agent_js
            │                 │                   │
      history_repo        chat_parser ────────────┘
        │      │               │
history_query  media_store     │
        │      │               │
        └──────┴────► collector ◄──── action_engine(run signals)
                          │
                        bridge ───────────────► ui/js/history-store.js
                          │                        │        │        │
                    actions/collect_history   history-view history-db collector-panel
                                                   │
                                            sash-core/sash-grid (v2 window set)
```

Nothing in the UI can be built before `bridge`; nothing in `bridge` before
`history_query`; `collector` needs the CDP event API first. Doc D turns
this into milestones.

---

## 9. Bridge contract (Qt ↔ JS)

Async DB work cannot block a `@Slot`, so every read is a **request/response
pair**: JS passes a `req_id`, Python answers with a signal carrying the same
`req_id`. This matches the existing `users_updated` / `tab_match_result`
style while allowing concurrent pages.

### 9.1 Slots (JS → Python)

| Slot | Signature | Purpose |
|---|---|---|
| `history_open` | `(str req_id, str nick, str opts_json)` | open a conversation: newest page + header stats |
| `history_page` | `(str req_id, str nick, str anchor_json)` | older/newer page (`{before_ord|after_ord, limit}`) |
| `history_search` | `(str req_id, str query_json)` | `{q, scope:'person'|'global', nick, limit, offset}` |
| `history_stats` | `(str req_id, str nick)` | counts, first/last, my_nicks, media count |
| `history_delete_person` | `(str nick, bool hard)` | tombstone (default) or hard delete |
| `history_restore_person` | `(str nick)` | undo a tombstone |
| `history_merge` | `(str from_nick, str into_nick)` | explicit duplicate merge (A-3) |
| `history_export` | `(str req_id, str nick, str fmt)` | `txt`/`json`/`html` to a file |
| `userdb_page` | `(str req_id, str query_json)` | `{q, offset, limit, sort, include_deleted}` |
| `userdb_stats` | `(str req_id)` | totals for the DB window header |
| `copy_media` | `(str media_ref)` | put the image on the Qt clipboard |
| `copy_text` | `(str text)` | clipboard fallback that never needs browser permission |
| `media_path` | `(str req_id, str media_ref)` | local `file://` path or remote URL for `<img src>` |
| `collector_state` | `(result=str)` | current status snapshot (JSON) |
| `collector_set` | `(str settings_json)` | enable/disable, intervals, media toggle |
| `collector_command` | `(str cmd)` | `start`/`stop`/`resync`/`backfill_older`/`clear_error` |
| `get_my_nick` / `set_my_nick` | `(result=str)` / `(str nick)` | header field, persisted |
| `detect_my_nick` | `(str req_id)` | read the bold participant row from the page |
| `history_settings` | `(result=str)` / `(str json)` | preload rows, show images, cache toggles |

### 9.2 Signals (Python → JS)

| Signal | Payload | When |
|---|---|---|
| `history_page_ready` | `(req_id, json)` | any paged/opened result |
| `history_appended` | `(json)` | new rows landed for the conversation currently open |
| `history_search_ready` | `(req_id, json)` | search finished |
| `history_stats_ready` | `(req_id, json)` | stats finished |
| `userdb_page_ready` | `(req_id, json)` | user-DB page finished |
| `userdb_changed` | `(json)` | a person was created/updated/deleted → refresh the list badge |
| `media_ready` | `(json)` | a cached file appeared → swap the placeholder |
| `collector_status` | `(json)` | state machine changed (coalesced, ≤4 Hz) |
| `my_nick_changed` | `(nick)` | header ↔ collector panel stay in sync |
| `history_error` | `(scope, message)` | user-visible failure (RULE 4 — never silent) |

All payloads are JSON strings, `ensure_ascii=False`, and every list payload
carries `{"items": […], "total": n, "has_more": bool}` so the lazy loader
never has to guess.

---

## 10. Configuration additions (same single `config.json`)

```jsonc
{
  "history": {
    "db_path": "history.db",
    "enabled": true,
    "media": {
      "cache_enabled": true,          // D-1 toggle
      "dir": "media_cache",
      "max_file_mb": 5,
      "max_cache_mb": 512,
      "download_gifs": true,
      "pause_during_run": true        // D-3
    },
    "preview": {
      "preload_rows": 50,             // requested "how many rows to preload"
      "page_rows": 50,
      "show_images": true,            // requested "display or not display images"
      "keep_rendered": 1000,          // virtual-list window cap
      "thumb_px": 160,
      "show_gaps": true
    },
    "search": { "snippet_chars": 120, "max_results": 200 }
  },
  "collector": {
    "enabled": true,
    "my_nick": "",                    // pinned-header field, storable
    "auto_detect_my_nick": true,
    "mode": "live",                   // live | heartbeat_only | off
    "heartbeat_ms": 1500,
    "idle_heartbeat_ms": 3000,
    "batch_debounce_ms": 250,
    "max_batch": 40,
    "bootstrap_chunk": 80,
    "bootstrap_pause_ms": 40,
    "bootstrap_max_messages": 5000,
    "require_two_participants": true,
    "collect_room_tabs": false,
    "throttle_during_run": true,      // D-3
    "throttle_factor": 4
  },
  "state": {
    "my_nick_recent": [],             // last 5 nicks → header dropdown
    "history_last_person": "",        // reopen the last previewed conversation
    "grid_layout_version": 2
  }
}
```

`collector.my_nick` is the canonical value (a *setting*, backed up with
config.json); `state.my_nick_recent` is convenience history.

---

## 11. Invariants and AGENT_RULES compliance

| Rule | How this feature honours it |
|---|---|
| **RULE 1** (visual click runner) | The collector clicks **nothing**. The only interactive affordance ("Backfill older") scrolls a container via CDP with no `element.click()`, so the rule does not apply; if a future control ever clicks, it goes through `find_and_click` |
| **RULE 2** (report every step) | `COLLECT_HISTORY` reports find/parse/append/skip through `engine.report()`; the collector mirrors its own steps into the Log Console at `info`/`warn` |
| **RULE 3** (block settings are attributes) | `COLLECT_HISTORY` stores every setting as `self.*` with defaults, accepts `**kw`, declares `config_schema()`, mirrored in `ui/js/stack-dnd.js` |
| **RULE 4** (empty ≠ broken) | "No new messages" (OK/info) is a different status *and* a different block result from "Not in a private tab" (fail) and "Parse error" (error). Every new window ships an explicit empty state |
| **RULE 5** (incremental progress) | Bootstrap emits per-chunk progress; appended rows reach the open preview immediately via `history_appended`; callbacks are wrapped in try/except and accept sync or async |
| **RULE 6** (filtered-out must not persist) | Scoped to the **queue** (`users`). The archive is a different store with a different meaning; the collector never writes to `users`, and purging People never touches `history.db`. Proposed **RULE 14** below makes this explicit |
| **RULE 7** (stop is honoured everywhere) | Bootstrap checks `should_stop()` at every chunk *and* inside every wait; the collector task has a cancel path that closes the agent binding and reports "Stopped", distinct from "Failed" |
| **RULE 8** (tests run the real thing) | The agent JS runs under `tests/js_harness.js` against a DOM stub built from the saved private page; the parser/collector run against a fake CDP client that mimics prepends, trims and tab switches |
| **RULE 9** (a guard skips work, not the pipeline) | Throttling and "media paused during run" reduce work only; they never stop the delta append, and they return OK |
| **RULE 10** (one control per decision) | Media caching is decided by exactly one toggle; "show images" is a *view* setting and is explicitly documented as not affecting storage |
| **RULE 12** (one global undo history) | Archive edits stay **out** of the timeline (A-8) and are protected by confirm + tombstone + Undelete instead |
| **RULE 13** (never persist unreadable state) | The window-set change is the direct hazard: layout payloads are versioned `v:2`, a `v:1` payload is **migrated** (new leaves appended) rather than rejected, and the migration is symmetric in `sash-core.js` and `Bridge` |

### Proposed RULE 14 (to be added to `docs/AGENT_RULES.md` when this lands)

> **The archive is not the queue.** `users` (chatbot.db) answers "who should
> I message under the current filter" and may shrink at any time. `persons`
> /`messages` (history.db) answer "what was actually said" and are
> append-only. No filter, purge, undo, or People-list edit may delete
> archived messages, and no collector may add anyone to the queue. The two
> stores are joined by nick at read time only.

---

## 12. Error handling matrix

| Situation | Detection | Behaviour | User sees |
|---|---|---|---|
| Chrome not connected | `cdp.is_connected` false | collector idles, no polling | "Not connected" (grey LED) |
| Active tab is the main room | heartbeat: tab icon `room` | no parsing | "Not in private tab now" |
| Private tab but 3+ participants | `.users-counter` > 2 | no parsing, counted | "Group tab — not collecting" |
| My Nick empty | settings check | bootstrap still runs (direction from CSS class), rows flagged `my_nick=''` | amber LED + "Set My Nick for exact attribution" |
| Agent lost (SPA re-render) | heartbeat: `window.__cvbAgent` missing | re-inject, resync | brief "Re-attaching…" |
| DOM buffer trimmed | head fingerprint changed | resync + `gaps` row | "— history gap —" marker in the preview |
| Alignment lost | no overlap found | append all + gap row + warn | warn line in the log |
| Media fetch fails / too big | fetch error, size cap | `media.state='failed'|'skipped'` with reason | tile shows a placeholder + "open original" |
| Cache over budget | size check after write | LRU evict, `state='evicted'` | DB window shows cache usage |
| FTS5 unavailable | probe at init | fall back to `text_lc LIKE`, log once | "fast search: off" chip |
| DB locked / write error | sqlite exception | retry once with backoff, then buffer in memory (bounded 500 rows) and report | error toast + log |
| History window opened for an unknown nick | empty query result | explicit empty state, offer "collect now" | "No archived messages for X yet" |
| Layout payload from an older version | `v` field | migrate to v2 | nothing (silent success) — a *rejected* layout logs a warning |

---

## 13. What this document deliberately leaves open

Listed as questions for the user in doc D §6: date separators on the live
site, retention/auto-prune policy, whether non-private (room) chats should
ever be archived, whether background (non-active) private tabs should be
collected, and whether an automatic scroll-up backfill is ever acceptable.
