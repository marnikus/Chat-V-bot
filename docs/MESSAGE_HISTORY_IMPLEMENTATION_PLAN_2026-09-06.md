# Message History + Collector — Implementation Plan

Date: 2026-09-06
Status: **DESIGN ONLY — no code written for this feature yet**
Reads with: doc A (`MESSAGE_HISTORY_ARCHITECTURE_DESIGN_2026-09-06.md`),
doc B (`PASSIVE_CHAT_COLLECTOR_DESIGN_2026-09-06.md`),
doc C (`HISTORY_UI_WINDOWS_DESIGN_2026-09-06.md`).

---

## 1. Dependency graph (what blocks what)

```
M0 CDP events + lease ──────────┐
                                ▼
M1 history_db / repo / query ─► M2 chat agent + parser ─► M3 collector
        │                              │                      │
        │                              └──────────► M4 COLLECT_HISTORY block
        │                                                     │
        ├─────────────► M5 media_store ──────────────────────┤
        │                                                     ▼
        └─────────────► M6 bridge API ───────────────► M7 UI (grid v2 first!)
                                                              │
                                                              ▼
                                                     M8 hardening & docs
```

Hard ordering facts:

* **M0 before M3** — push collection is impossible while `CDPClient`
  discards event frames.
* **grid v2 migration before any new panel** — otherwise the first save
  after adding a window id is rejected and users lose their layout
  (doc C §2, RULE 13).
* **M1 before M2** — the parser's alignment needs real cursors to test
  against.
* **M5 can lag** — messages store `media.url` immediately; caching is an
  enrichment, so the preview works before the cache exists.

---

## 2. Milestones

Each milestone is independently shippable, leaves the app green, and ends
with its own tests.

### M0 — CDP foundation (~90 lines, 1 file)

* `backend/cdp_client.py`: `on_event(method, cb)` / `off_event`, event
  fan-out in `_receive_loop`, `add_binding(name)`,
  `add_script_on_new_document(src)`, `CdpLease` (high/low priority).
* Tests: `tests/test_cdp_events.py`.
* **Acceptance:** existing suites unchanged; a fake websocket delivers
  `Runtime.bindingCalled` to a subscriber; a `high` request overtakes a
  queued `low` one.

### M1 — Archive storage (~570 lines, 3 files)

* `backend/history_db.py`, `history_repo.py`, `history_query.py` (doc A §5).
* Schema v1 + `schema_meta`, FTS5 probe with LIKE fallback, WAL.
* Tests: `tests/test_history_repo.py`, `tests/test_history_query.py`.
* **Acceptance:** append/align/dedupe is idempotent (replaying a batch adds
  0 rows); merge by nick never duplicates; paging returns stable pages
  while new rows arrive; search finds Cyrillic text case-insensitively on
  **both** the FTS and the fallback path; tombstone hides a person from the
  default listing and `restore` brings it back intact.

### M2 — Page agent + parser (~460 lines, 2 files)

* `backend/chat_agent_js.py` (agent source + probes),
  `backend/chat_parser.py` (records, fingerprints, alignment).
* Tests: `tests/test_history_agent_js.js` (js_harness + a DOM stub derived
  from `Вирт чат privat.html`), `tests/test_chat_parser_delta.py`.
* **Acceptance:** the four saved private messages parse to exactly the four
  expected records (direction, nick, text, `17:31`/`17:32`); the main-page
  GIF message parses as `kind='gif'` with its URL; bootstrap → delta →
  prepend → trim → alignment-lost all produce the right inserts and exactly
  one `gaps` row where expected.

### M3 — Collector service (~275 lines, 1 file + 15 in the engine)

* `backend/collector.py`, engine `run_started`/`run_finished`.
* Tests: `tests/test_collector_state.py`.
* **Acceptance:** every status in doc B §5 is reachable and correctly
  labelled; the supervisor survives an injected exception; a stop during a
  bootstrap returns within one chunk (RULE 7); throttling multiplies the
  interval and halves the chunk while a run is active; idle CPU measured
  <1 % over a 5-minute soak against a stub page.

### M4 — Action block (~95 lines)

* `actions/collect_history.py` + registration + `ui/js/stack-dnd.js` entry.
* Tests: `tests/test_collect_history_block.py`.
* **Acceptance:** the six result mappings of doc B §8; settings round-trip
  through `to_dict()`/preset save-load; a `memory_nick` target that does
  not match the open conversation fails instead of mis-filing rows.

### M5 — Media pipeline (~210 lines)

* `backend/media_store.py`, `.gitignore` entry for `media_cache/`.
* Tests: `tests/test_media_store.py`.
* **Acceptance:** the same GIF referenced by 10 messages is stored once;
  oversize files are `skipped` with a reason; eviction frees space and the
  preview falls back to the URL; clipboard export writes a real image
  (asserted through a Qt clipboard stub).

### M6 — Bridge API (~230 lines in `bridge.py`)

* All slots/signals of doc A §9; settings plumbing; `WINDOW_IDS` v2 and the
  Python side of the layout migration.
* Tests: `tests/test_history_bridge.py`,
  `tests/test_grid_layout_v2_migration.py`.
* **Acceptance:** every read answers on its `req_id`; concurrent requests
  never cross; a stored v1 layout upgrades to v2 with the arrangement
  preserved and the three windows appended; an invalid payload is still
  rejected without touching the stored one.

### M7 — UI (~1 300 lines across 5 new + 4 modified files)

Order inside the milestone: **(a)** `sash-core.js` v2 + presets +
`sash-grid.js` ids → **(b)** empty panels in `index.html` + `history.css`
→ **(c)** `history-store.js` → **(d)** `history-view.js` → **(e)**
`history-db.js` → **(f)** `collector-panel.js` + header My Nick →
**(g)** `user-table.js` nick link.

* Tests: `tests/test_grid_layout_v2_migration.js`,
  `tests/test_history_lazy_paging.js` (paging math, keep-window trimming,
  scroll-anchor preservation), `tests/test_history_render.js` (escaping,
  no `innerHTML` for message text, images-off chip still carries the ref).
* **Acceptance:** doc C §9 checklist.

### M8 — Hardening, docs, soak (~1 day)

* Performance verification against doc B §4.3 budgets on a real 5 000-
  message conversation.
* README section ("Message history & the passive collector"), a
  `DOM_SELECTORS.md` addendum with the message/tab/participant selectors of
  doc A §3, and **RULE 14** added to `AGENT_RULES.md` (doc A §11).
* A 2-hour soak with tab switching, reconnects and a run in parallel; the
  archive is compared against a manual transcript.

**Rough size:** ~3 250 new/changed lines of implementation + ~1 100 lines
of tests, in 13 new files and 8 modified ones. No new pip dependencies.

---

## 3. Test matrix (what proves each requirement)

| Requirement (from the request) | Proven by |
|---|---|
| Store every message, both directions | `test_chat_parser_delta.py`, `test_history_repo.py` |
| Store images and GIFs, display both | `test_media_store.py`, `test_history_render.js` |
| Nick is the key; re-appearing nick merges, never duplicates | `test_history_repo.py::test_merge_same_nick` |
| Action block parses full history and appends new lines | `test_collect_history_block.py` |
| Click a nick in People Memory → preview opens | `test_history_render.js` + manual M8 |
| Full chronological preview with inline media | `test_history_lazy_paging.js` + manual |
| All-time master list, browsable, lazy, preload setting, images toggle | `test_history_lazy_paging.js`, `test_history_bridge.py` |
| Clickable rows → preview | same |
| Selectable/copyable text; click to copy media | `test_history_render.js` (selection CSS + delegated copy), Qt clipboard stub in `test_media_store.py` |
| Search inside one person and globally | `test_history_query.py` |
| Search users by nick | `test_history_query.py` |
| Both nicks shown per history (mine can change) | `test_history_repo.py` (`my_nicks`), render test |
| Background process, no UI freeze | `test_collector_state.py` + M8 soak with frame-time measurement |
| Private chat = exactly 2 people incl. My Nick | `test_collector_state.py::test_detection_table` |
| My Nick configurable in the pinned header, storable | `test_history_bridge.py`, manual |
| Resource-saving parse of a big chat | `test_chat_parser_delta.py` asserts that a steady-state tick performs **zero** node serialisation |
| Three status phrases | `test_collector_state.py` |
| Incremental, non-blocking appends | `test_collector_state.py` (chunk pacing, cancellation) |
| Collector control window | manual M7/M8 |

---

## 4. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | Grid window-set change bricks saved layouts | high if forgotten | high | v2 migration on **both** sides, tests first (M6/M7a) |
| R-2 | `Runtime.addBinding` unavailable/blocked | low | medium | drain fallback already in the protocol (doc B §3.3) |
| R-3 | Angular recycles message nodes, breaking the observer | medium | medium | heartbeat self-heal + `reattach()`, `self_heals` counter surfaced |
| R-4 | Duplicate rows after a reconnect | medium | high (data quality) | deterministic dedupe key + `UNIQUE` + alignment; idempotency test replays every scenario twice |
| R-5 | Date guessing produces wrong days | medium | low | `ts_exact=0` shown as "approx."; ordering never depends on it |
| R-6 | Media cache fills the disk | medium | medium | per-file and total caps, LRU eviction, usage shown in the DB window |
| R-7 | FTS5 missing in the user's Python/SQLite | low | low | probed once, LIKE fallback with `text_lc` |
| R-8 | Collector competes with a run for the CDP socket | medium | medium | priority lease + throttle (D-3), lease held for one evaluate only |
| R-9 | Archive DB corruption | low | high | separate file (A-1), WAL, `PRAGMA integrity_check` on startup, "Vacuum"/backup in the DB window; People list unaffected |
| R-10 | Private-chat false positive (wrong person archived) | low | high | 3 independent signals (tab icon + counter + participants), ambiguity ⇒ refuse to collect |
| R-11 | Untrusted message text injected into the UI | low | high | text nodes only, `_esc()` everywhere, no `innerHTML` for content |
| R-12 | Scope creep into "export/analytics" | medium | low | v1 ships txt/json/html export only; everything else is out of scope here |

---

## 5. Rollout and safety

* `history.enabled` and `collector.enabled` default **on**, but both can be
  switched off in the Collector window — the app must behave exactly as
  today when they are off (no task, no DB file created until the first
  write).
* `history.db` is created lazily on the first append; `integrity_check`
  runs at open, and a failed check renames the file to
  `history.db.corrupt-<timestamp>` and starts a fresh one rather than
  refusing to start.
* Backup: the DB window's ⚙ popover offers "Backup archive…" (a plain file
  copy with WAL checkpoint) — the archive is the only irreplaceable data in
  this app.
* `.gitignore` gains `media_cache/`; `history.db*` is already covered by
  the existing `*.db`, `*.db-wal`, `*.db-shm` patterns.

---

## 6. Open questions for the user (answer before M2/M5)

1. **Date separators** — does the live site render a day divider anywhere
   in the message list? If yes, one selector upgrades every row to an exact
   date (`ts_exact=1`) and the guessing in doc A §6.3 becomes a fallback.
   *(The saved pages contain none.)*
2. **Retention** — keep everything forever (current plan), or auto-prune
   messages older than N months / above M messages per person?
3. **Room chat** — archive the main room too (huge, many speakers), or
   private conversations only (current plan)?
4. **Background private tabs** — collect only the tab the user is looking
   at (current plan, cheapest and matches "monitors open current tab"), or
   also private tabs open in the background when the site keeps them
   mounted?
5. **Auto-backfill** — is it ever acceptable for the collector to scroll
   the chat up on its own to harvest older history (currently only via the
   explicit "Backfill older" button)?
6. **Nick case** — can two different people on this site have nicks that
   differ only in letter case? If not, case-insensitive merging can become
   the default instead of a manual action.

---

## 7. Definition of done (whole feature)

* Every row of §3 passes, and the existing suites stay green.
* A fresh install with an empty `config.json` starts, shows the three new
  windows, and collects a live private conversation end-to-end.
* An install with a **v1 layout** upgrades without the user noticing
  anything except three new windows appearing.
* Closing the app during an active bootstrap loses no committed rows and
  leaves a resumable cursor.
* The four design documents are updated to match whatever the
  implementation had to change — the docs are the spec, and a divergent
  doc is a bug.
