# History UI — three new windows, lazy loading, copy & search

Date: 2026-09-06
Status: **DESIGN ONLY — no code written for this feature yet**
Parent: `MESSAGE_HISTORY_ARCHITECTURE_DESIGN_2026-09-06.md` (doc A)
Sibling: `PASSIVE_CHAT_COLLECTOR_DESIGN_2026-09-06.md` (doc B)

---

## 1. What is added to the shell

### 1.1 Three new grid windows (decision D-2)

They join `SashCore.WINDOWS` and behave exactly like Stats/People/Log —
draggable by the title bar, splittable, resizable, hideable, persisted.

| id | Title | Purpose |
|---|---|---|
| `history` | 💬 **Person History** | the conversation preview for ONE person |
| `userdb` | 🗃 **Message DB — All Users** | the all-time master list |
| `collector` | 📥 **Chat Message Collector** | status + controls for the background process |

Default placement after migration (see §2): a new bottom row
`[ userdb | history ]` at 34 % height, and `collector` inserted next to
`stats` in the top-left column. Both are only *defaults* — the user drags
them anywhere afterwards.

### 1.2 Pinned-header "My Nick" field

The request asks for it in the pinned head window, storable:

```html
<div class="mynick-wrap" title="Your nick in the chat — recorded on every
     archived message; it may differ between sessions">
  <span class="material-icons">badge</span>
  <input id="myNickInput" list="myNickRecent" maxlength="40" spellcheck="false"
         placeholder="My Nick…">
  <datalist id="myNickRecent"></datalist>
  <button id="detectMyNickBtn" class="btn-icon" title="Detect from the open private tab">
    <span class="material-icons">person_search</span></button>
  <span id="collectorDot" class="status-dot" title="Collector status"></span>
</div>
```

* debounced 400 ms → `bridge.set_my_nick()` → `config.collector.my_nick`
  (persisted immediately, RULE: storable);
* `detect` → `bridge.detect_my_nick()` reads the bold participant row
  (doc B §2.4) and *proposes* it; the user confirms;
* `myNickRecent` is filled from `state.my_nick_recent` (last 5);
* the dot mirrors the collector LED so the status is visible even when the
  Collector window is hidden or buried;
* the field and the Collector window's copy are two views of one value
  (`my_nick_changed` keeps them in sync — RULE 10: one decision, one truth).

---

## 2. Grid migration v1 → v2 (blocking dependency, do this first)

**The hazard.** The window set is validated in two places —
`SashCore.validate()` (JS) and `Bridge._parse_grid_payload()` (Python) —
and a payload whose leaf set does not match exactly is **rejected**
(RULE 13). Adding three windows would therefore make every existing saved
layout invalid on first start: the user silently loses their arrangement,
and the close-time flush would keep failing.

**The migration.**

```
serialize()   → {"v": 2, "tree": …}
deserialize(raw):
    v == 2 → validate against the 10-window set  (as today)
    v == 1 → validate against the LEGACY 7-window set
             → if valid: upgrade(tree)  → returns a v2 tree
             → if invalid: fall back to defaultTree() (as today)

upgrade(tree):
    append a bottom row  split('col', [tree, split('row',[userdb, history],[45,55])], [66,34])
    insert `collector` as a sibling of `stats` (or top-level if stats is missing)
    normalise sizes, validate, and SAVE the upgraded payload once
```

Symmetric rules:

* `Bridge.WINDOW_IDS` gains the three ids; `Bridge.LEGACY_WINDOW_IDS_V1`
  keeps the old set for upgrades; `_parse_grid_payload` accepts `v:1`
  (upgrading) and `v:2` (validating) and always **stores** `v:2`.
* `Bridge._default_grid_tree()` and `SashCore.defaultTree()` grow the same
  three leaves, and the presets A/B/C are extended so "Layout A/B/C" still
  contain every window.
* `resetToDefault()` keeps un-hiding everything (RULE 13's corollary), now
  including the three new panels — each of which has an empty state (§3.6,
  §4.5, §5.4).
* A dedicated test asserts a stored v1 payload survives an app restart with
  the user's arrangement intact plus the new windows appended
  (`tests/test_grid_layout_v2_migration.js` + `.py`).

**Selectability.** `ui/css/sash-layout.css` sets `user-select:none` on
`.win-title` and on `body.sash-dragging *`. Panel *bodies* are not
affected, so message text is selectable by default — but the history panel
explicitly declares `user-select: text; -webkit-user-select: text; cursor:
text` on its message body to be immune to future global changes, and the
drag guard is scoped so a text selection inside the history body never
starts a window drag (`pointerdown` inside `.hist-body` is ignored by the
grid drag handler unless it started on the title bar — which is already the
case; a test locks it in).

---

## 3. Window 1 — 💬 Person History

### 3.1 Layout

```
┌ 💬 Person History ─────────────────────────────────────────────── [⤢][×] ┐
│ ‹ back   «На работе 25»   ⟷  me: HiHoney        1 313 msgs · 84 media   │
│ [🔎 search in this conversation…]  [◀ 3/17 ▶]  [🖼 images ▾] [⧉ copy all]│
├──────────────────────────────────────────────────────────────────────────┤
│  ⌃ load older (50)                                        ← lazy sentinel│
│  ── 05 Sep 2026 (approx.) ─────────────────────────────                  │
│  ┌ На работе 25 · 17:32 ─────────────┐                                   │
│  │ Я Английский онлайн веду          │                          (in)     │
│  └───────────────────────────────────┘                                   │
│                       ┌─ HiHoney · 17:32 ────────────────────────┐       │
│               (out)   │ Онлайн не так заметно) но тоже неплохо   │       │
│                       └──────────────────────────────────────────┘       │
│  ┌ На работе 25 · 18:00 ─────────────┐                                   │
│  │ [ GIF 160×160 ]  click to copy    │                                   │
│  └───────────────────────────────────┘                                   │
│  — history gap (buffer trimmed) —                                        │
│  ⌄ (auto-follow: new messages appear here)                               │
└──────────────────────────────────────────────────────────────────────────┘
```

Header always shows **both** identities, as requested ("each history
display nick of person and my nick"). When `my_nick` changes inside a
conversation, an inline divider says *"— you were: OldNick → NewNick —"*.

### 3.2 Lazy loading (the requested "lazy uploading history system")

* Opens **at the newest end** with `preload_rows` (default 50, setting
  10–500 in the Collector/DB settings popover).
* Scrolling up past a sentinel (`IntersectionObserver`, root margin
  300 px) requests the previous page via
  `history_page(req_id, nick, {before_ord, limit})`; a spinner row holds
  the scroll anchor so the viewport does not jump (`scrollTop +=
  heightDelta` after insert).
* **Windowed DOM**: at most `keep_rendered` (default 1000) rows exist;
  rows scrolled far off-screen are replaced by a spacer of their measured
  height and re-rendered on return. This is what keeps a 50 000-message
  conversation smooth.
* **Auto-follow**: if the view is pinned to the bottom, `history_appended`
  appends live; if the user has scrolled up, a "⌄ 3 new messages" pill
  appears instead of yanking the viewport.
* **Images**: `show_images` off ⇒ media rows render as a compact chip
  (`🖼 image · click to copy link`), which still carries the media
  reference. On ⇒ `<img loading="lazy">` with `width/height` reserved from
  the DB so lazy scroll never reflows; the `src` is resolved through
  `media_path()` (local `file://` when cached, remote URL otherwise), and
  `media_ready` swaps a placeholder in place when a download finishes.

### 3.3 Selection and copying (explicit request)

| Interaction | Behaviour |
|---|---|
| Text selection | native, `user-select:text`, spans across bubbles |
| `Ctrl+C` | native copy of the selection |
| Click on an image/GIF | `bridge.copy_media(ref)` → Qt clipboard; toast "Image copied" / for GIFs "GIF copied as file + link" (doc A §7.1) |
| `Alt`+click on an image | copies the **URL** as text |
| Hover a bubble | small `⧉` button → copies that one message as `HH:MM Nick: text` |
| `⧉ copy all` | whole conversation as plain text (or Markdown, from the ▾ menu) via `copy_text()` |
| Right-click | in-app context menu: copy message / copy image / copy link / open original in Chrome / jump to date |

Clipboard goes through **Python** (`QGuiApplication.clipboard()`), not
`navigator.clipboard`, so no WebEngine permission prompt can break it; the
JS path is only a fallback for plain text.

### 3.4 Search inside the conversation

Field in the header → `history_search(scope:'person')` → the matching
`ord`s come back; the view shows `◀ n/N ▶` navigation, jumps to each hit
(loading the page that contains it if needed) and highlights the term with
`<mark>`. `Esc` clears. Hit rows are counted, never truncated silently — if
`max_results` clamps, the UI says "showing first 200 of 1 042".

### 3.5 Header actions

`⤢` maximise (temporarily gives the window the whole grid — a small
addition usable by any panel), `Export ▾` (txt/json/html), `Delete
history` (confirm modal → tombstone, with an Undo toast), `Re-collect now`
(runs a resync for this nick through the collector).

### 3.6 Empty / loading / error states (RULE 4)

| Case | Shown |
|---|---|
| No person selected | "Click a nick in **User Memory** or in the **Message DB** to preview a conversation." |
| Person exists, zero messages | "No archived messages for «Nick» yet. Open the private tab — the collector will fill this in." + a "Collect now" button |
| Person tombstoned | "This history is deleted. [Restore]" |
| Query failed | red inline strip with the reason + Retry |

---

## 4. Window 2 — 🗃 Message DB — All Users

### 4.1 Layout

```
┌ 🗃 Message DB — All Users ──────────────────────────────────────────────┐
│ [🔎 nick…] [scope: nicks ▾|messages]  1 842 people · 96 210 msgs · 1.2 GB│
│ sort: [last activity ▾]  rows/preload: [50 ▾]  [🖼 show images] [⚙]      │
├─────────────────────────────────────────────────────────────────────────┤
│ Nick                 Msgs   In/Out   Media  Last activity      My nick(s)│
│ На работе 25         1 313  700/613    84   2026-09-06 18:00   HiHoney   │
│ _ШепотНочи_            42    20/22      3   2026-09-05 22:10   HiHoney,… │
│ 🎀Ангелина🎀            8     5/3       0   2026-08-30 12:02   NightOwl  │
│ …                                              (lazy: +50 on scroll)     │
└─────────────────────────────────────────────────────────────────────────┘
```

* Row click → opens that person in the **Person History** window (and
  un-hides it if hidden).
* Lazy paging identical in spirit to §3.2: `userdb_page(offset, limit)`
  with the same `preload_rows` setting; a sticky footer shows
  "showing 150 of 1 842".
* `🖼 show images` toggles a small avatar/last-media thumbnail column and is
  the **same setting** used by the preview (`history.preview.show_images`)
  — one control, one decision (RULE 10).
* Sorts: last activity (default), nick, message count, media count, first
  seen. Sorting happens in SQL, not in JS, so it is correct across pages.

### 4.2 Search

`scope=nicks` → `nick_lc` prefix-then-contains, ranked.
`scope=messages` → global full-text search (doc A §7.2): results render as
grouped cards *(nick — 7 hits — snippet…)*; clicking a snippet opens the
preview anchored at that message.

### 4.3 Maintenance actions (in the ⚙ popover)

Cache usage + "Clear media cache", "Vacuum database", "Show deleted
(tombstones)", "Possible duplicates" (same `nick_lc`, different `nick`) with
an explicit **Merge** action (doc A, A-3), and the storage settings
(`preload_rows`, `show_images`, `cache_enabled`, `max_cache_mb`).

### 4.4 Relationship to the People list

The two lists are joined by nick at read time only (RULE 14, doc A §11):
a person in the DB that is also in the current People list gets a small
👥 badge; deleting from People never deletes archive rows and vice versa.
The DB window states this in its tooltip so the distinction is discoverable
rather than folklore.

### 4.5 Empty state

"No conversations archived yet. Open a private chat — the **Chat Message
Collector** stores everything automatically." + a link that focuses the
Collector window.

---

## 5. Window 3 — 📥 Chat Message Collector

```
┌ 📥 Chat Message Collector ──────────────────────────────────────────────┐
│ ● Collecting — На работе 25 (+3)              [⏸ Pause] [⟳ Resync]      │
│ My Nick: [HiHoney            ] [Detect]   me/partner detected from tab   │
├─────────────────────────────────────────────────────────────────────────┤
│ Session:  parsed 1 313 · added 27 · media 6 · self-heals 0 · errors 0    │
│ Current:  tab=private · participants=2 · agent v3 · latency 180 ms       │
├─────────────────────────────────────────────────────────────────────────┤
│ ☑ Collect automatically      ☑ Save images & GIFs                        │
│ ☑ Only 2-person private tabs ☑ Pause media downloads during a run        │
│ ☑ Keep collecting during runs (throttled ×[4])                           │
│ Heartbeat [1500] ms · idle [3000] ms · batch [40] · chunk [80] / [40] ms │
│ [⬆ Backfill older messages]  [🗑 Reset cursor for this person]           │
├─────────────────────────────────────────────────────────────────────────┤
│ 17:32:04  ✅ archived 3 new messages with «На работе 25»                 │
│ 17:31:12  ℹ️ no new messages                                             │
│ 17:29:58  🔄 bootstrapped 1 310 messages (4.2 s)                         │
└─────────────────────────────────────────────────────────────────────────┘
```

* Status line = doc B §5 verbatim; the LED animates only while working.
* Every control writes straight through `collector_set` and is persisted.
* "Backfill older messages" is the **only** thing that scrolls the user's
  page, is explicit, shows progress, and can be stopped (doc A, A-9).
* The mini event log is local to the panel (last 50 lines); everything also
  goes to the main Log Console at `info`/`warn`.

### 5.4 Empty/edge states

No connection → the whole body dims with "Connect to a Chrome tab to start
collecting"; collector off → a single "Enable" button; error → red strip
with the reason, retry countdown and a "Copy diagnostics" button.

---

## 6. Two access points (the requested wiring)

```
User Memory (this session)                Message DB (all time)
  nick cell → <button data-act="history"> row click / ⏎
        │                                       │
        └──────────────► HistoryStore.open(nick) ◄──────┘
                              │
                    bridge.history_open(req_id, nick, opts)
                              │
                    history_page_ready(req_id, json)
                              │
                    HistoryView.render() + focus/un-hide the window
```

`ui/js/user-table.js` change: the nick cell becomes a link-styled button
carrying `data-act="history" data-nick="…"`. The existing delegated
listener already dispatches on `data-act`, so this is an additive branch;
row checkboxes, sorting and the other row actions are untouched. Middle-
click / `Ctrl`+click opens the history **and** pins it (maximise), for the
"I want to read this properly" case.

---

## 7. Client-side module map

| File | Responsibility |
|---|---|
| `ui/js/history-store.js` | the only place that talks to the history bridge: `req_id` generation, promise correlation with `*_ready` signals, an LRU page cache (last 3 conversations × 10 pages), settings mirror, and a tiny event bus (`open`, `appended`, `settings`) |
| `ui/js/history-view.js` | Person History window: virtual list, bubble rendering, media tiles, copy interactions, in-conversation search, auto-follow |
| `ui/js/history-db.js` | Message DB window: lazy rows, sorting, nick/message search, maintenance popover |
| `ui/js/collector-panel.js` | Collector window + the header My Nick field + the header dot |
| `ui/css/history.css` | all three windows; dark-theme variables from `variables.css`; skeleton loaders; LED animation |

Rendering rules inherited from the codebase: **no inline `onclick`** (nicks
contain quotes and emoji) — everything is delegated with `data-*`
attributes; all user text passes through an `_esc()` helper; message text
renders as text nodes, never `innerHTML`, so a message containing markup
can never inject into the app (the archive is untrusted input from
strangers — this is a security requirement, not a nicety).

---

## 8. Accessibility & keyboard

| Key | Action |
|---|---|
| `Enter` on a DB row / nick link | open the history |
| `Ctrl+F` while the history window has focus | focus the in-conversation search |
| `F3` / `Shift+F3` | next / previous hit |
| `Home` / `End` | jump to the oldest loaded / newest message |
| `Esc` | clear the search, then unfocus |

`aria-live="polite"` on the collector status so a screen reader announces
transitions once; every icon-only button carries a `title` + `aria-label`,
matching the existing header buttons.

---

## 9. Definition of done for the UI half

* Layout v1 payloads survive the upgrade with the user's arrangement intact.
* Text in the history window can be selected with the mouse and copied with
  `Ctrl+C`; clicking an image puts it on the OS clipboard.
* A 20 000-message conversation opens in under 500 ms, scrolls at 60 fps,
  and never holds more than `keep_rendered` rows in the DOM.
* Turning "show images" off makes the preview text-only *without* touching
  what is stored.
* Every one of the three windows shows a meaningful empty state after
  "Reset to default" (RULE 13's corollary).
