# Message History — remaining bugs design — 2026-09-07

Date: 2026-09-07
Status: **DESIGN — then implemented in the same turn**

> Update 2026-09-07 (second pass): new follow-up request — when a verified
> private chat opens with a partner who is **not yet** in the archive DB
> (`history.db`) **or** the People list (`chatbot.db.users`), the collector
> must add the person to **both** stores and collect the full history. This is
> the current live report (screenshot): Partner `_Насnоха`, My nick `—`,
> In archive `0`, Added `0`, warning “My Nick is not set”.

This document is the research/design step for the three remaining bugs in the
message-history feature. Private-chat detection already landed
(`PRIVATE_GATE_AND_MEDIA_TREE_2026-09-07.md`); this document only addresses:

| # | Bug | Root cause (after the audit) | Fix |
|---|---|---|---|
| 1 | First messages are missing | The passive collector only starts from the messages that are already in the DOM. The chat virtualises history, so the earliest lines are not in the DOM until the pane is scrolled to the top. Nothing ever scrolled it, and the head-changed backfill only fires when the *user* scrolls. | A controlled scroll-to-top backfill, executed once per conversation when the archive has not yet done a full check, then marked complete so it is never repeated on every heartbeat. |
| 2 | Same message saved twice / three times | Identity was `fp = f(direction, author, HH:MM, kind, payload, occ)` + day. `occ` is global within the current DOM run and `day` is resolved relative to “now”. When older duplicates are prepended (or a sync crosses midnight), the same physical line gets a new `occ`/`day` and is treated as a new row. | Store a deterministic **dedupe key** `k = f(direction, author, HH:MM, kind, payload)` (timestamp + content), dedupe before insert, and add a unique index `(person_id, dup_key)`. The site has no message id, so timestamp+content is the practical unique identity — exactly what the bug report asks for. |
| 3 | Media still shows percent-encoded URLs and no folders | The folder/readable-name work exists, but bytes are only fetched by an in-page `fetch()`. A cross-origin image host without CORS headers makes that fetch fail, so `media.state` stays `pending`/`failed` and the UI falls back to the remote percent-encoded URL. | Keep the in-page fetch as a first try, then fall back to a Python `aiohttp` download using the CDP session cookies (same cookies the browser uses; no CORS). Existing failed/uncached rows are re-queued once so previously missed images/GIFs are migrated into `saved_media/<person>/images|gifs/…`. |

---

## 1. Bug 1 — full-history check

### 1.1 Decisions

| # | Decision |
|---|---|
| B-1 | The collector may scroll the conversation pane to the top **on its own** (this overrides the old A-9 conservative rule). The current bug report explicitly requires “check full message history from the beginning”. The user has no other automatic way to get the earliest lines. |
| B-2 | The full check runs **once per conversation**. The `cursors` table gets `full_scan_complete` / `full_scan_at`. After a successful top-to-bottom scan, later heartbeat ticks never re-scroll that person. |
| B-3 | The scroll is **restored** after the read so the user’s viewport is not left at the top. Reading is done from the DOM snapshot, so restoring afterwards cannot lose anything already read. |
| B-4 | A manual `backfill_older` collector command clears the flag and forces one more full check. The `COLLECT_HISTORY` block with `mode=full` also clears the cursor and runs the same path. |
| B-5 | The in-page agent grows a `scrollToTop()` / `restoreScroll(top)` probe (agent **v5**). Python waits for the top to settle (count stable for two polls, bounded by a small timeout), then runs the existing `sync_conversation` which already handles prepended-older history through `_prepend()`. |
| B-6 | If the page cannot scroll or does not grow, the sync still runs on the visible range, and the backfill is recorded only when the agent confirms it reached the top. |

### 1.2 Flow

```
tick / CollectHistory(full)
  state()  → cursor.full_scan_complete?
     no + auto_backfill
        parser.scroll_to_top()
        poll state() until scroll.atTop && count stable (≤ ~2 s)
        sync_conversation(...)     # existing align/prepend logic
        restoreScroll(oldTop)
        repo.mark_backfilled()
     yes
        normal incremental sync    # cheap
```

Performance: the expensive full check is **one time per person** (stored in
the cursor), so opening the archive nor the heartbeat never re-reads or
re-scrolls a whole conversation repeatedly.

---

## 2. Bug 2 — deduplicate by timestamp + content

### 2.1 Data change

`messages` gains:

```sql
dup_key TEXT NOT NULL DEFAULT ''
CREATE UNIQUE INDEX idx_messages_dup_key
    ON messages(person_id, dup_key) WHERE dup_key <> '';
```

`dup_key` is the 64-bit FNV fingerprint of:

```
direction ⌁ from_nick ⌁ HH:MM ⌁ kind ⌁ payload   (occ = 0, no day)
```

`fp` and `day` stay in the row for diagnostics and day grouping; the *identity*
used by the writer is `dup_key`.

### 2.2 Migration

On `HistoryDB.init()` for existing databases:

1. add the column;
2. back-fill `dup_key` from each row’s existing fields;
3. delete rows whose `dup_key` is already present earlier for the same person
   (keep the lowest `id`);
4. recount persons, resequence `ord`, rebuild the tail fingerprints;
5. create the unique index.

### 2.3 Consequences

* Same text, same HH:MM, same author, same direction is **one row** — even if
  the same “Nice” was rendered twice by the page, or the same message is read
  again on another day.
* The old test `identical_text_in_the_same_minute_stays_distinct` is updated:
  with no message-id on the site, three identical same-minute lines are
  considered the same archived record (this is the bug report’s requested
  key). `same_text_on_two_days_is_two_rows` is likewise updated.

---

## 3. Bug 3 — readable media tree + GIF support

### 3.1 Current state (verified)

* `MediaStore` already creates `saved_media/<slug>/images|gifs/YYYY-MM-DD_NNN.ext`
  and the UI already renders `file://…` for cached files.
* What was missing: the **bytes** were only fetched by in-page `fetch()`, which
  can be blocked by CORS on `images.virt-chat.com`. The fallback to the remote
  percent-encoded URL then looks like “still not fixed”.

### 3.2 Fix

`MediaStore._fetch_one()` becomes:

1. try in-page `fetch()` (existing path — fastest, uses page origin);
2. if it fails, try **Python `aiohttp`** with:
   * cookie header from `CDPClient.get_cookies()` (via `Network.getAllCookies`);
   * `Referer: https://ru.virt-chat.com/` and a browser user-agent;
   * the same size cap and SHA-256 twin-file logic;
3. if both fail → `state='failed'` with the real reason (no silent broken image).

GIF support needs **no** extra engine: a `.gif` file saved with the `.gif`
extension is rendered/animated natively by `<img>` in Qt WebEngine. The bug was
that the file was never saved; once cached, `file:///…/gifs/…gif` animates.

### 3.3 Re-queue previously failed media

`HistoryService.init()` runs `MediaStore.retry_failed_uncached()` once so rows
that were marked `failed` (and have no `cache_path`) get another chance with
the Python CORS-free downloader.

---

## 4. Follow-up: unknown private partner must enter both stores

| # | Decision |
|---|---|
| U-1 | A verified private chat creates the partner in **both** stores: `history.persons` (archive) *and* `chatbot.db.users` (People list). The archive row is created before the sync so it exists even if the conversation is empty. |
| U-2 | People discovery is **passive**: it refreshes `first_seen`/`last_seen`, never sets `messaged=1` and never bumps `message_count`. Appearing in a chat is not the same as being messaged by a run. |
| U-3 | `Collector` receives the shared `UserMemory` (wired in `main.py` through `HistoryService(memory=…)`). It exposes `people_changed`, which `Bridge.attach_history()` connects to `refresh_users()` so the People window updates immediately. |
| U-4 | My Nick is **detected automatically** in a verified two-person chat when it is not configured: the page’s `me` is used first, otherwise the single outbound author is adopted. It is session-only (not written to `config.json`), but shown in the panel; the “My Nick is not set” warning disappears when detection succeeds. The part `my_nick` is used for both the private-chat gate and the message rows. |
| U-5 | Full-history collection for a new person is already triggered by the existing `auto_backfill` cursor flag; creating the person in both stores does not change that. |

---

## 5. Follow-up (third pass): wrong-pane regression — messages exist but not collected

### Symptoms from the live report

1. Active private tab `AlisskaBi`, visible messages exist, but the collector
   says `NO NEW MESSAGES` / `0` in archive.
2. After a subsequent tick the gate reports:
   `NOT A PRIVATE CHAT — АУРЕЛИЯ, SSSSA777, ПИРАНЖУЛЯЯ... WRITE HERE TOO`,
   i.e. authors from the **main room** were treated as author evidence for the
   private conversation.

### Root cause

`visiblePane()` in agent **v5** preferred the pane with the most message nodes
when more than one pane existed. The site keeps every open chat alive; the
main-room pane is typically much longer than a private chat and can still
report a measurable `offsetParent` even when the private tab is active. The
agent therefore handed Python the room pane, which had (a) the wrong messages
(→ 0, “no new messages”) and (b) room authors (→ the “not a private chat”
strangers error).

### Fix (agent v6)

Pane selection is now **identity-first**, not “biggest pane wins”:

* For each pane it first computes the cheap author evidence (distinct inbound /
  outbound nicks from the node cache), then scores it:
  * inbound authors are exactly the active partner → strong positive;
  * every inbound author that is *not* the partner → strong negative;
  * a single outbound author (or one matching My Nick) → small positive;
  * measurably visible (`offsetParent` etc.) remains a small tie-breaker.
* A room pane containing `АУРЕЛИЯ / SSSSA777 / ПИРАНЖУЛЯЯ` scores deeply
  negative against the active partner `AlisskaBi` and can never beat the real
  private pane, even when the room is longer and not `display:none`.
* If the active tab is a room, the tab is still reported as `room`, Gate step
  1 rejects it (`not_private`), and nothing is saved — the previous behaviour
  is preserved.

`AGENT_VERSION = 6`.

### Tests locked

`tests/test_private_scope_js.js`

* a visible, longer room pane never wins over the active private pane;
* among two private panes, the one matching the active partner wins;
* pane-switch test now also switches the active tab before asserting the room.

---

## 6. Follow-up (fourth pass): backfill_older scrolls the wrong element

### Symptom

Clicking **⬆ Backfill older** "did nothing": `full_scan_complete` could even be
set while `In archive` stayed at `0`.

### Root cause

`messagesRoot()` (the MutationObserver target) returns the **content wrapper**
inside `.messages-root`, not the element that owns the scrollbar. The old
`scrollBox()` walked upward from that wrapper and stopped on the first element
whose `scrollHeight > clientHeight`. The wrapper has `clientHeight = 0`, so it
was selected and `scrollTop` was set on a non-scrolling `<div>` — the real
`.messages-root` (which has `overflow-y: scroll`) never moved, no older
messages were loaded, and after the short "settle" the archive was marked as
fully checked.

### Fix

Agent **v7**:

* `scrollerCandidates()` walks up from the message wrapper and selects the
  actual scrollers: `.messages-root` / `app-messages`, any
  `cdk-virtual-scrollable` / virtual-scroll viewport, or an ancestor whose
  computed `overflow-y` is `scroll`/`auto`. A bare content wrapper is never a
  candidate.
* `scrollInfo()`/`state().scroll` reports the **real scroller** (`atTop` is
  truthful).
* `scrollToTop()` sets `scrollTop = 0` on every real scroller (using
  `scrollTo({top:0})` when available), records each scroller’s old position,
  and dispatches a scroll event. `restoreScroll()` restores each recorded
  position.
* Python `settle_after_top()` now waits longer and requires the DOM count to
  stay stable for **3 consecutive polls** (initial default 6 s), and
  `sync_conversation()` only marks `full_scan_complete` when that settle
  actually succeeded. A slow page is retried instead of being permanently
  flagged "done".

### Tests locked

* JS: `scrollToTop drives the real scroller, not the wrapped message content`
  — sets scrollTop on the content wrapper to `999`, ignores it, and checks
  that the `.messages-root` position is used and moved.
* Python: existing backfill tests now run through the longer settle path.

---

## 7. Follow-up (fifth pass): "private win" but the DB still has 0 messages

### Symptom

The collector reports the real private chat (it no longer picks the room
pane), but `In archive` stays at `0` and clicking **⬆ Backfill older** either
does nothing or reports `NO NEW MESSAGES`.

### Root causes now covered

The live DOM has **more than one `div.container`**: the main room and each
open private tab keep their own `.container` with an `app-messages` **and** a
`users-list`. Three things were still read from *document order* instead of
from the active conversation:

1. **`.users-counter`** was taken from the first list in the document. If the
   room's user list (978 users) came first, the collector thought the private
   tab was a group tab and refused to write anything — DB stays 0.
2. **`.primary-text.bold`** (My Nick) was likewise read globally, so the gate
   could compare against the wrong "me".
3. When scroll-to-top made the active pane momentarily empty, the old
   `visiblePane()` fell back to the **first `.messages-root` in the document**,
   which is the room/another tab. `state()` then reported that pane's count and
   scroll (a non-empty conversation is made to look empty, or worse a stranger
   pane gets selected), so no rows were ever written.

### Fix (agent v8 + collector)

* `describeTab()` reads only the active tab (kind/partner/title).
  `describe()` scopes `.users-counter` and `.primary-text.bold` to the
  `.container` that owns the selected pane, so a room list in front never
  leaks 17 / 978 participants or the wrong My Nick.
* `visiblePane()` keeps `lastPane` and the last partner. If that pane is still
  mounted but its message nodes were removed while it loads, the agent reports
  `count=0` for the active pane instead of selecting another `.messages-root`.
* `sync_conversation()` waits for the post-scroll count to come **back to the
  pre-scroll floor** (`minimum_count`), needs 3 stable polls, and if the pane
  never comes back it **restores the viewport**, reads the visible window, and
  leaves `full_scan_complete` off. The collector marks such a pass
  `backfill_pending` and does not re-scroll on every heartbeat; the user can
  ask again with **⬆ Backfill older**.

### Diagnosis surface

The Collector window now shows the numbers it actually read, so the next
report is not a guess:

* `Page count` — `state().count` of the selected pane;
* `People` — `participants · panes · pane_source` (`last`, `first`,
  `last-empty`, …);
* `Sync` — the last `sync_conversation` reason (`added`, `no_new`,
  `unchanged`, `empty`, `gap`, …);
* `Backfill` — `full scan pending retry` when a scroll could not be proven
  complete.

The same data is in the JSON state returned by `collector_state`, under
`last_probe` / `sync_reason`.

### Tests locked

* `participants and My Nick come from the active container, not the first one`
  — a room container with 17 users / `RoomMe` is prepended, but the private
  chat still reports 2 and the real My Nick.
* `a momentarily empty pane does not fall back to another .messages-root` —
  room nodes exist and come first, yet an emptied active pane reports 0.
* `scroll_that_empties_the_pane_is_retried_not_marked_done` — after a
  scroll that clears the DOM the visible window is still archived and
  `full_scan_complete` stays false.

---

## 8. Files that change

| File | Change |
|---|---|
| `backend/js/chat_agent.js` | v5: `scrollToTop`, `restoreScroll`, stable `scroll` info |
| `backend/chat_agent_js.py` | `AGENT_VERSION=5`, new probe expressions |
| `backend/chat_parser.py` | `scroll_to_top`, `restore_scroll`, `_backfill_to_top`, `backfill_older` in `sync_conversation` |
| `backend/history_db.py` | `messages.dup_key`, cursor full-scan columns, unique index, migration/dedupe |
| `backend/history_models.py` | `dedupe_key()`, `MessageRecord.dup_key` |
| `backend/history_repo.py` | pre-insert dedupe, `mark_backfilled`, cursor fields |
| `backend/collector.py` | `auto_backfill` setting, per-conversation full check, `backfill_older` |
| `backend/cdp_client.py` | `get_cookies()` |
| `backend/media_store.py` | Python download fallback, `retry_failed_uncached` |
| `backend/history_service.py` | re-queue failed media on init |
| `backend/bridge.py` | `collector_command('backfill_older')` |
| `actions/collect_history.py` | `full` mode uses the scroll backfill |
| tests | new/existing coverage for scroll, dedupe, media-fallback |
| `backend/js/chat_agent.js` | **v8** — per-container `.users-counter`/`.primary-text.bold`, last-pane fallback when empty |
| `backend/chat_agent_js.py` | `AGENT_VERSION=8` |
| `backend/chat_parser.py` | `minimum_count` settle, restore-and-read fallback, `backfill_pending` |
| `backend/history_models.py` | `SyncResult.backfill_pending` |
| `backend/collector.py` | `_backfill_pending` gate so a failed full scan is not repeated every heartbeat |
| `tests/dom_stub.js` | real per-conversation `.container` + `users-list` shape, `prependContainer()` |
