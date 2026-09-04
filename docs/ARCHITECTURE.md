# ChatFlow Orchestrator — Architecture & Module Design

**Status:** Design (no code yet)
**Version:** 1.1 (refines the v1.0 Technical Design Document with verified site research)
**Hard constraint:** **every Python module file must stay < 150 lines** (enforced by a CI test, see §17.3)

---

## 1. Research Findings — Target Site DOM Contract (verified)

The repository contains two complete saved snapshots of the target app:

| File | View captured |
|------|---------------|
| `Вирт чат.html` | Main room "Гостиная" — 25 user rows, 3 tabs, message form |
| `Вирт чат privat.html` | Private chat "_ШепотНочи_" — 2 user rows + list header, 4 tabs, 1 user row per tab type |

Source URL: `https://ru.virt-chat.com/chat` (title "Вирт чат"). The app is **Angular** with **Angular CDK** (virtual scroll, drag-drop) and **Angular Material (MDC)** components. Third-party scripts present: hCaptcha, Google Tag Manager, ad trackers — confirming the "attach to a logged-in session, never re-authenticate" approach.

### 1.1 Page skeleton (top level)

```
app-root
└─ app-chat
   ├─ app-tab-scroller            → chat tabs (see §1.4)
   ├─ app-messages                → message stream (dynamic, websocket-fed)
   ├─ users-list.users            → left panel (see §1.2)
   └─ mat-toolbar
      ├─ app-settings-menu
      ├─ app-emoji-panel
      └─ app-message-form         → composer (see §1.5)
   └─ input#file[type=file][accept="image/*"]   (hidden, top-level)
```

### 1.2 User list (CDK virtual scroll)

Verified element tree (whitespace in text nodes is real — nicknames and titles carry **trailing spaces**):

```html
<users-list class="users users_showed">
  <div class="search-field">
    <mat-form-field ...>
      <mat-label>Поиск</mat-label>
      <input matinput maxlength="20" ...>                    <!-- search box -->
    </mat-form-field>
  </div>
  <cdk-virtual-scroll-viewport class="cdk-virtual-scroll-viewport
        users-list-viewport cdk-virtual-scrollable
        cdk-virtual-scroll-orientation-vertical" autosize>
    <div class="cdk-virtual-scroll-content-wrapper">
      <container-item>…<users-header-item>…</container-item>  <!-- header row -->
      <container-item>…<user-item>…</container-item>          <!-- one per user -->
      …
    </div>
  </cdk-virtual-scroll-viewport>
</users-list>
```

**User row** (one `container-item` → one `user-item`):

```html
<container-item>
  <div style="min-height: 40px;">
    <user-item>
      <div class="user-container">
        <avatar-item>
          <div class="avatar-wrapper female-avatar">          <!-- or male-avatar;
                                                                  guests also: guest-avatar -->
            <mat-icon class="avatar-icon" data-mat-icon-name="user">…</mat-icon>
            <div class="badge badge-bottom-right registered-badge">…</div>   <!-- registered -->
            <div class="badge badge-bottom-right anonymous-badge">…</div>    <!-- guest (instead) -->
          </div>
        </avatar-item>
        <div class="text-stack">
          <div class="primary-text-line">
            <span class="primary-text"> LadyToi </span>       <!-- NICKNAME, has padding spaces -->
          </div>
          <div class="secondary-text"></div>
        </div>
        <button class="more-button" mat-icon-button>…</button>
      </div>
    </user-item>
  </div>
</container-item>
```

**Header row** (must be skipped — contains `users-header-item` instead of `user-item`):

```html
<container-item>
  <users-header-item>
    <div class="header-container">
      <div class="text-stack">
        <div class="primary-text-line"><span class="primary-text">Пользователи</span></div>
        <div class="secondary-text">…<span class="users-counter">2</span></div>
      </div>
      <button mat-icon-button mat-menu-trigger>…</button>
    </div>
  </users-header-item>
</container-item>
```

Gender/registration signals are **classes on `.avatar-wrapper`**, not icons:

| Class on `.avatar-wrapper` | Meaning |
|---|---|
| `female-avatar` | female |
| `male-avatar` | male |
| `guest-avatar` | guest (anonymous) — combined with a gender class |
| `.registered-badge` descendant | registered account |
| `.anonymous-badge` descendant | anonymous/guest account |

Sample nicknames observed (Cyrillic + emoji + spaces + underscores all occur):
`_ШепотНочи_`, `🎀Ангелина🎀`, `Lt. Jessica Stoner♠️🚔`, `miamia 25`, `Lizalo4ka`, `МилаяКися`, `На работе 25`.

### 1.3 Virtual scroll behaviour

`cdk-virtual-scroll-viewport` (CDK) only renders visible rows (25 rows visible in the snapshot) and **recycles** DOM nodes on scroll. Consequences:

1. Scrolling must be **simulated mouse-wheel deltas** (real input events), not `scrollTop` assignment.
2. Row element handles are **ephemeral** — never cache a `user-item` handle across scrolls; re-query before every click.
3. Newness detection must be by **nickname set**, not DOM identity.
4. After each scroll chunk the app needs a pause for Angular to render (configurable, default ~1.5 s).

### 1.4 Tab scroller

```html
<div role="tablist" class="cdk-drop-list tabs-list">
  <div role="tab" class="cdk-drag mat-ripple tab-item [active]" aria-selected="true|false">
    <mat-icon class="chat-type-icon" data-mat-icon-name="room|user">…</mat-icon>
    <p class="chat-title [disconnected]">
      [<span class="unread">5</span>]                        <!-- unread badge, rooms -->
      Гостиная                                               <!-- trailing space! -->
    </p>
    <button class="tab-close-button"                          <!-- only on closable tabs -->
            aria-label="Закрыть чат _ШепотНочи_">            <!-- trimmed title inside -->
      <mat-icon class="tab-close-icon material-icons">close</mat-icon>
    </button>
  </div>
  …
  <div class="ink-bar"></div>
</div>
```

Verified facts:

- Main room tab: `data-mat-icon-name="room"`, title `Гостиная `, **no close button**.
- Person chat tabs: `data-mat-icon-name="user"`, have `button.tab-close-button`; `aria-label` = `Закрыть чат {nickname}` with a **trimmed** nickname (better matching anchor than the padded `.chat-title` text).
- Active tab: class `active` + `aria-selected="true"`.
- `p.chat-title` may carry class `disconnected` when the peer is offline; text includes optional `span.unread` before the title — **strip the span when reading the title**.
- Tabs are CDK drag-reorderable (`cdkdrag`); we only click, never drag.

### 1.5 Message form (`app-message-form`)

```html
<app-message-form>
  <form class="ng-untouched ng-pristine ng-valid">
    <mat-form-field appearance="fill" class="mat-mdc-form-field mat-mdc-form-field-type-mat-input …">
      <textarea rows="1" autocomplete="off" matinput maxlength="1000" type="text"
                cdktextareaautosize placeholder="Сообщение" required
                id="mat-input-1" …></textarea>
      <div class="mat-mdc-form-field-icon-suffix">
        <button mat-icon-button matsuffix type="submit">      <!-- SEND -->
          <mat-icon class="primary-icon material-icons mat-ligature-font">send</mat-icon>
        </button>
        <button mat-icon-button matsuffix>                    <!-- IMAGE ATTACH -->
          <mat-icon class="primary-icon material-icons mat-ligature-font">image</mat-icon>
        </button>
        <button mat-icon-button matsuffix>                    <!-- EMOJI -->
          <mat-icon class="primary-icon material-icons mat-ligature-font">insert_emoticon</mat-icon>
        </button>
      </div>
      <mat-hint>Наберите сообщение</mat-hint>
      <mat-hint class="mat-form-field-hint-end">0 / 1000</mat-hint>
    </mat-form-field>
  </form>
</app-message-form>
<input id="file" type="file" style="display: none;" accept="image/*">
```

Verified facts:

- The textarea is `required` and capped at **1000 chars** (`maxlength` + live `0 / 1000` hint). The GUI composer must enforce the same cap.
- Icons are Material **ligature font** icons → matched by text content (`send`, `image`, `insert_emoticon`), not by `data-mat-icon-name`.
- The send button is the form's `type="submit"` button — **pressing Enter in the textarea also submits** (useful as an alternate send path).
- Image upload uses the **hidden `input#file`** (accepts `image/*`, `display:none`). This is deterministic: `page.set_input_files("input#file", path)` works without touching the OS file chooser. The design doc's `expect_file_chooser` remains as the *fallback* strategy (e.g., if the app changes to a chooser-only flow).
- After send, the app clears the textarea and increments the counter hint back to `0 / 1000` — a verifiable "send happened" signal.

### 1.6 Final selector contract

All selectors below were **extracted from the saved snapshots**; they are the single source of truth for the `chatflow/browser/selectors.py` module (which will hold them as constants, §6.6).

| Name | Selector | Notes |
|------|----------|-------|
| `VIEWPORT` | `cdk-virtual-scroll-viewport.users-list-viewport` | scroll container |
| `ROW` | `cdk-virtual-scroll-viewport.users-list-viewport container-item` | every row candidate |
| `USER_ROW` | `container-item:user-has(user-item)` | rows that are users |
| `HEADER_ROW` | `container-item:has(users-header-item)` | skip these |
| `NICK` | `user-item .primary-text` | **trim() required** |
| `AVATAR` | `user-item .avatar-wrapper` | gender/registration anchor |
| `FEMALE` | `user-item .avatar-wrapper.female-avatar` | presence = female |
| `MALE` | `user-item .avatar-wrapper.male-avatar` | presence = male |
| `REGISTERED` | `user-item .avatar-wrapper .registered-badge` | presence = registered |
| `ANON` | `user-item .avatar-wrapper .anonymous-badge` | presence = guest |
| `SEARCH_INPUT` | `users-list .search-field input[matinput]` | maxlength 20 |
| `TAB_LIST` | `[role=tablist].tabs-list` | |
| `TAB` | `.tabs-list div[role=tab].tab-item` | |
| `TAB_ACTIVE` | `.tab-item.active` | or `aria-selected=true` |
| `TAB_TITLE` | `div[role=tab] p.chat-title` | strip `span.unread`, **trim()** |
| `TAB_CLOSE` | `div[role=tab] button.tab-close-button` | `aria-label="Закрыть чат {nick}"` |
| `TAB_TYPE_ICON` | `div[role=tab] mat-icon.chat-type-icon` | `data-mat-icon-name` room\|user |
| `TEXTAREA` | `app-message-form textarea[matinput][placeholder="Сообщение"]` | maxlength 1000 |
| `SEND_BTN` | `app-message-form button[type=submit]:has(mat-icon:text-is("send"))` | |
| `IMAGE_BTN` | `app-message-form button:has(mat-icon:text-is("image"))` | not `type=submit` |
| `FILE_INPUT` | `input#file[type=file]` | hidden; primary upload path |
| `CHAR_COUNTER` | `app-message-form mat-form-field mat-hint-end` | "N / 1000" — post-send check |
| `APP_ROOT` | `app-chat` | page liveness check |

Resilience rules (from v1.0 doc, confirmed necessary by the research):

1. Never use `_ngcontent-ng-c*` / `_nghost-ng-c*` attributes (change per build).
2. Never use `mat-input-N` ids (dynamic).
3. Always `trim()` text from `.primary-text` / `.chat-title` (real trailing spaces observed).
4. Every DOM interaction goes through one guarded wrapper (`page_ops.py`) with retry + timeout.
5. Re-query immediately before each interaction (Angular re-renders).

---

## 2. High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│ ChatFlow Orchestrator (PySide6 QApplication)                           │
│                                                                        │
│  ┌──────────────────────────── MAIN THREAD ─────────────────────────┐  │
│  │ QMainWindow (shell, tray, status bar)                            │  │
│  │   └─ QWebEngineView                                              │  │
│  │        └─ ui/index.html  (vanilla HTML/CSS/JS + SortableJS)      │  │
│  │             ▲ js: palette, sequence, tracker, filters, log,      │  │
│  │             │              settings, state                       │  │
│  │   QWebChannel bridge  ◄──────────►  ChatFlowApi (Python)         │  │
│  │        (JS→Py slots / Py→JS signals)                             │  │
│  │   SQLite memory  (users, presets, filter rules, settings)        │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│            │ command queue (thread-safe)        ▲ signal relays         │
│  ┌─────────▼──────────────── WORKER QThread ───┴─────────────────────┐ │
│  │  own asyncio event loop                                           │ │
│  │  Engine (state machine) ── BlockExecutors (registry)              │ │
│  │   ├─ ParseEngine (scroll + extract)  ├─ FilterEngine              │ │
│  │   ├─ MemoryStore (repo calls, marshalled to main thread for DB)   │ │
│  │   └─ Humanizer (jitter, typing, wheel)                            │ │
│  │  Playwright: connect_over_cdp(ws://host:9222) → Page              │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
                         ▲ CDP (port 9222)
          ┌──────────────┴──────────────┐
          │ Chrome (user's, logged in)  │
          │  ru.virt-chat.com/chat      │
          └─────────────────────────────┘
```

### 2.1 Component responsibilities

| Component | Tech | Responsibility |
|-----------|------|----------------|
| `app/` | PySide6 | Entry point, main window, tray, QWebEngineView hosting, channel wiring |
| `bridge/` | QWebChannel | Only code path between JS and Python; JSON payloads both ways |
| `ui/` | HTML/CSS/JS | The whole user interface (palette, builder, tracker, composer, log, settings) |
| `engine/` | asyncio in QThread | State machine, sequence loop, pause/stop, human-like delays |
| `blocks/` | asyncio | One file per action block; pure executors, no UI knowledge |
| `browser/` | Playwright | CDP connect, tab locate, guarded DOM ops, watchdog |
| `parse/` | Playwright | Scroll engine + row extraction (produces `UserRow` DTOs) |
| `filters/` | pure Python | Rule model + AND evaluation over `UserRow` |
| `memory/` | sqlite3 | Users/presets/rules/settings persistence, CSV import/export |
| `core/` | pure Python | Settings, dataclasses, event names, logging |

### 2.2 Threading & concurrency model (critical design)

| Rule | Rationale |
|------|-----------|
| **R1** Playwright is created and used **only** inside the worker QThread, on that thread's own `asyncio` loop. | Playwright's asyncio client is not thread-safe; Qt signals are the only way in/out. |
| **R2** Worker receives commands via a `queue.Queue` (thread-safe): `RUN`, `PAUSE`, `RESUME`, `STOP`, `TEST_CONNECTION`, `SHUTDOWN`. Worker polls the queue in its loop. | No lock juggling; stop/pause are cooperative flags checked at safe points. |
| **R3** Worker emits PySide `Signal`s (defined in `engine/worker.py`); `bridge/signals.py` on the main thread forwards them as `qwebchannel` notifications to JS. | Decouples worker from WebChannel (which lives on the main thread). |
| **R4** SQLite is opened **only on the main thread** (via `bridge/api.py` → `memory/*`). Worker calls that need to persist (e.g. mark MESSAGED) are done one of two ways: (a) the worker sends a `user_event` signal and the main thread writes (default), or (b) a dedicated repo proxy for read-heavy queries (pick target) via `qinvoke`-style marshalling — **decision: (a) for writes; (b) a snapshot-based read: the main thread pushes the "queued nicknames" list to the worker on RUN, worker picks locally.** This avoids any DB handle crossing threads entirely. | sqlite3 handles are not thread-safe across threads by default; snapshot reads keep the worker deterministic and testable. |
| **R5** All JS→Python calls land on the main thread (QWebChannel default). | Standard Qt behaviour; the bridge just forwards to queues/repos. |
| **R6** Worker hard-timeouts: every Playwright op has a per-op timeout; a global "stall watchdog" (no progress for N seconds) pauses the run and raises an event. | Prevents infinite hangs on a dead tab. |

### 2.3 Stop/pause semantics

- **STOP (emergency):** sets `stopping=True`; executor checks the flag between blocks *and* between humanized sub-steps (each character, each wheel tick). Current in-flight Playwright call is allowed to finish (or time out) — never an interrupt mid-keystroke.
- **PAUSE:** executor awaits an `asyncio.Event` (resumed on RESUME). Delays count only while running.
- **Loop termination:** stop flag, or `pick_target` returns "no queued users" for a full pass.

---

## 3. Engine State Machine

```
IDLE ──RUN──► CONNECTING ──ok──► RUNNING ◄──resume── PAUSED
  ▲               │ fail            │  ▲              │ pause
  │               ▼                 │  └──────────────┘
  │             ERROR               ▼
  └──────────────────────────  STOPPING ──done──► IDLE
        (any state) ──tab lost──► DEGRADED (paused + reconnect prompt)
        DEGRADED ──reconnect ok──► RUNNING
```

| State | Meaning | UI status pill |
|-------|---------|----------------|
| `IDLE` | nothing running | gray "Ready" |
| `CONNECTING` | CDP connect + tab locate in progress | blue "Connecting…" |
| `RUNNING` | sequence loop active | green "Running" |
| `PAUSED` | user pause or error-hold | yellow "Paused" |
| `STOPPING` | draining current action | orange "Stopping…" |
| `ERROR` | unrecoverable failure (e.g. CDP refused) | red "Error" |
| `DEGRADED` | tab lost / connection dropped mid-run | red "Reconnect?" |

Transitions are owned by `engine/state.py` (tiny) and executed by `engine/executor.py`.

---

## 4. Data Model & SQLite Schema

File: `<data_dir>/chatflow.db` (default `./data/chatflow.db`), single connection on the main thread, `WAL` mode.

```sql
CREATE TABLE users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  nickname      TEXT    NOT NULL UNIQUE COLLATE NOCASE,   -- case-insensitive unique (site is case-sensitive but dedupe safe)
  nickname_raw  TEXT    NOT NULL,                          -- exact trimmed string as seen
  gender        TEXT    NOT NULL DEFAULT 'UNKNOWN',        -- FEMALE | MALE | UNKNOWN
  registered    INTEGER NOT NULL DEFAULT 0,
  status        TEXT    NOT NULL DEFAULT 'NEW',            -- NEW|QUEUED|MESSAGED|SKIPPED
  skip_reason   TEXT,
  first_seen    TEXT    NOT NULL,                          -- ISO-8601 UTC
  last_seen     TEXT    NOT NULL,
  messaged_at   TEXT,
  message_count INTEGER NOT NULL DEFAULT 0,
  notes         TEXT    DEFAULT ''
);
CREATE INDEX idx_users_status   ON users(status);
CREATE INDEX idx_users_lastseen ON users(last_seen);

CREATE TABLE presets (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL UNIQUE,
  description TEXT DEFAULT '',
  blocks_json TEXT NOT NULL,                               -- list[Block] as JSON
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE filter_rules (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_id TEXT NOT NULL UNIQUE,                            -- uuid
  type    TEXT NOT NULL,       -- CLASS_INCLUDES|CLASS_EXCLUDES|REGEX_MATCH|REGEX_NOT_MATCH
  selector TEXT NOT NULL,    -- CSS class name or 'nickname'
  value   TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL                                       -- JSON-encoded
);
```

Design decisions:

- **Nickname keying:** unique on `COLLATE NOCASE`; display uses `nickname_raw`. Cyrillic/emoji safe (TEXT/UTF-8).
- **Timestamps:** ISO-8601 UTC strings (portable, sortable, trivially serializable to JS).
- **Cooldown:** no column — computed: `messaged_at + cooldown_days < now ⇒ re-eligible`.
- **Statuses:** exactly the four from the v1.0 spec; `SKIPPED` rows store `skip_reason` (which rule failed).
- **Re-discovery:** on each parse, `last_seen` updates for every seen nickname; unknown nicknames are inserted as `NEW` and, if they pass filters, immediately promoted to `QUEUED` in the same transaction (atomic batch upsert).
- **CSV format (F-MS-05):** header `nickname,gender,registered,status,first_seen,last_seen,messaged_at,message_count,notes`; export = all rows; import = upsert by nickname, statuses preserved unless row empty.

---

## 5. Filter Engine

Rules are evaluated **AND-combined**, in `position` order; first failure records `skip_reason = "<rule type>: <selector>"`.

| Type | Operand | Passes when |
|------|---------|-------------|
| `CLASS_INCLUDES` | class name, e.g. `female-avatar` | `user_row.classes` contains it |
| `CLASS_EXCLUDES` | class name, e.g. `registered-badge` | `user_row.classes` does NOT contain it |
| `REGEX_MATCH` | regex on nickname (fullmatch not required; `search`) | `re.search(value, nickname)` |
| `REGEX_NOT_MATCH` | regex | `re.search(value, nickname)` is None |

- `UserRow.classes` = full class list of `.avatar-wrapper` + presence-derived flags (`registered-badge`, `anonymous-badge` mapped to pseudo-classes so rules can target them uniformly).
- Default rule set (F-FC-01/02): `CLASS_INCLUDES female-avatar` + `CLASS_EXCLUDES registered-badge`, both enabled.
- Regexes are validated on save (invalid regex → rule disabled + warning event; engine must never crash on a bad rule — F-NF reliability).
- Evaluation is a pure function `evaluate(row, rules) -> (bool, reason|None)` — trivially unit-testable, no Playwright.

---

## 6. Package Layout, Module Specs & Line Budgets

Root package `chatflow/` + `tests/`. **Budget: 149 lines hard cap** (target ≤ 120 where shown). Every public API below is a *spec*, not code.

### 6.0 Tree

```
chatflow/
├─ __init__.py                      5     version string
├─ app/
│  ├─ __init__.py                   5
│  ├─ main.py                     120     bootstrap: QApplication, args, window, run()
│  ├─ window.py                   130     QMainWindow, tray icon, menu, status bar
│  ├─ webview.py                  110     QWebEngineView + QWebChannel install, qrc load
│  └─ channel.py                  130     QWebChannel setup, ChatFlowApi registration, JS-console → log
├─ core/
│  ├─ __init__.py                  5
│  ├─ config.py                   120     @dataclass Settings (all knobs) + JSON load/save
│  ├─ models.py                   120     UserRow, UserRecord, Block, Preset, FilterRule, enums
│  ├─ events.py                    80     event-name constants + payload builders
│  └─ logconf.py                   90     rotating file handler (7-day retention), level
├─ browser/
│  ├─ __init__.py                  5
│  ├─ selectors.py                140     §1.6 table as constants + text-clean helpers spec
│  ├─ connect.py                  110     CDP connect, tab locate (URL pattern), test-connection
│  ├─ page_ops.py                 140     guarded op wrapper: find/retry/timeout/click/fill/scroll
│  └─ watchdog.py                  90     tab-alive polling loop, drop detection events
├─ parse/
│  ├─ __init__.py                  5
│  ├─ scroll.py                   130     chunked wheel scroll, per-scroll pause, empty-run stop
│  └─ extract.py                  110     read rows → UserRow list (nickname/gender/flags), dedupe set
├─ filters/
│  ├─ __init__.py                  5
│  └─ engine.py                   120     evaluate(), validate_rule(), default_rules()
├─ memory/
│  ├─ __init__.py                  5
│  ├─ db.py                       140     connection factory, schema init, migration hook, WAL
│  ├─ repo_users.py               140     upsert_batch, get_counts, list_paged, set_status, reset_all
│  ├─ repo_presets.py              90     CRUD for presets (blocks_json)
│  ├─ repo_filters.py              70     rule CRUD, ordered fetch
│  └─ csv_io.py                    90     export_all, import_csv (upsert)
├─ blocks/
│  ├─ __init__.py                 15      registry bootstrap (imports executor modules)
│  ├─ base.py                      90     BlockResult, BlockContext, BaseExecutor ABC
│  ├─ context.py                   80     BlockContext impl: page, ops, memory-snapshot, log, rng
│  ├─ registry.py                  70     ACTION_TYPES → executor classes, param defaults
│  ├─ go_main_tab.py               70     click tab by title match (default "Гостиная")
│  ├─ scroll_parse.py              90     drive parse.scroll, filter, emit user events, persist
│  ├─ pick_target.py               70     choose from queued snapshot (top | random)
│  ├─ click_user.py                80     locate row by nickname, click, verify tab opened
│  ├─ type_message.py              90     render template, humanized typing into TEXTAREA
│  ├─ attach_image.py              80     pick random file, set_input_files (chooser fallback)
│  ├─ send_message.py              70     click SEND_BTN, verify counter reset, mark messaged
│  ├─ close_tab.py                 70     click TAB_CLOSE for current chat, verify gone
│  ├─ wait_sleep.py                40     explicit pause (humanized)
│  ├─ loop_marker.py               50     sub-loop bookkeeping (jump target id + count)
│  └─ condition.py                 80     whitelist expression eval over context vars
├─ engine/
│  ├─ __init__.py                  5
│  ├─ worker.py                   140     QThread: asyncio loop, command queue, signal definitions
│  ├─ executor.py                 140     sequence loop, block dispatch, per-block try/catch, pause/stop
│  ├─ state.py                     60     EngineState enum + transition table + guards
│  ├─ delays.py                    70     jittered sleep, min-delay floor
│  └─ humanize.py                 100     char-by-char typing, smooth wheel deltas, micro-pauses
└─ bridge/
   ├─ __init__.py                  5
   ├─ api.py                      140     ChatFlowApi: QWebChannel-exposed slots (run/stop/pause,
   │                                      settings CRUD, presets, tracker queries, csv, test-conn)
   └─ signals.py                   90     wire worker signals → JS notifications (json payloads)

ui/                                  (not Python — no line budget, kept modular)
├─ index.html                       layout per v1.0 §8.1 (3-column + 2 bottom panels)
├─ css/app.css                      dark theme tokens per v1.0 §8.8
├─ js/bridge.js                     QWebChannel bootstrap + typed event subscriptions
├─ js/state.js                      global state, status bar, counts
├─ js/palette.js                    SortableJS palette → sequence
├─ js/sequence.js                   sequence builder (reorder, params, presets)
├─ js/tracker.js                    user tracker table, filters, CSV buttons
├─ js/composer.js                   filter rules list + message composer + image folder
├─ js/log.js                        live log panel
└─ js/settings.js                   settings modal

tests/
├─ test_line_budget.py               asserts every chatflow/**/*.py < 150 lines  ← the guard
├─ test_dom_contract.py              validates §1.6 selectors against saved HTML fixtures
├─ test_filters.py
├─ test_memory.py
├─ test_executor.py                  fake page, dry-run sequence
└─ fixtures → (repo root) saved "Вирт чат*.html" used read-only
requirements.txt                     PySide6, playwright, (beautifulsoup4 test-only)
README.md                            run instructions (CDP port, pip, playwright install)
```

**Total Python: ~45 files, 33 inside `chatflow/`, each budgeted < 150 lines.** The largest files (140) are deliberately split: `page_ops.py` (guarded ops) vs `selectors.py` (constants); `worker.py` (thread plumbing) vs `executor.py` (loop logic) vs `state.py` (machine).

### 6.1 `app/main.py` (120)

- `main()` entry: create `QApplication`, high-DPI attrs, apply `Settings`, build `MainWindow`, show, `app.exec()`.
- Single-instance guard (QLockFile) to avoid double-attach to the same Chrome.
- Signal handlers: clean shutdown → `api.shutdown_worker()`.

### 6.2 `app/window.py` (130)

- `MainWindow(QMainWindow)`: central widget hosts `ChatWebView` (§6.3).
- Menu bar: File (Save/Load preset, CSV export/import, Exit), Tools (Settings, Test Connection, Reopen Chrome debug port hint), Help (About, Selector reference).
- Tray icon with left-click restore + context menu (Show / Stop / Quit); system status pill mirrored in tray tooltip.
- Status bar: Chrome connection pill + user counts (driven by JS via bridge events `status_changed`, `users_counted`).

### 6.3 `app/webview.py` (110)

- `ChatWebView(QWebEngineView)`: loads `qrc:/chatflow/ui/index.html` (embedded via `qt_resource`, so PyInstaller needs no extra files).
- `QWebEnginePage` subclass: JS console messages → Python log (debug observability); devtools shortcut (Ctrl+Shift+I) in dev builds.
- Installs `QWebChannel` with object name `chatflow` on `qWebChannel` JS side (see §7).
- Disables navigation away from the app (only the qrc origin is allowed).

### 6.4 `app/channel.py` (130)

- Wires `ChatFlowApi` (§6.16) into the channel; constructs shared services (repos, settings, worker) once.
- Dependency container pattern: a plain `Services` object (§7.1) passed to window/api/worker — avoids global state, keeps files small.

### 6.5 `core/config.py` (120)

- `@dataclass Settings`: cdp_host, cdp_port, tab_url_pattern, scroll_px, scroll_pause, empty_runs, jitter, typing_cps, typing_var, micro_pause_every, micro_pause_sec, db_path, log_dir, log_level, retention_days, cooldown_days, msg_max_len=1000, image folder, attach_image flag.
- `load(path) / save(path)` JSON; defaults from v1.0 doc; per-key merge so old files keep working.

### 6.6 `browser/selectors.py` (140)

- One constant per §1.6 row (19 selectors) + small pure helpers: `clean_title(text)` (strip unread span text, trim), `tab_close_label(nick)`.
- No Playwright imports → importable from tests and the UI (selector reference dialog).

### 6.7 `browser/connect.py` (110)

- `connect_cdp(host, port) -> Browser` via `playwright.chromium.connect_over_cdp`.
- `find_chat_page(browser, url_pattern) -> Page`: scan contexts/pages for `url` match; if multiple → emit `tab_candidates` event and let user pick; if zero → error with hint.
- `test_connection(host, port) -> dict`: returns `{ok, tab_found, page_url, error}` (F-BR-04).
- F-BR-03: exposes `on_disconnect` callback registration (watchdog uses it).

### 6.8 `browser/page_ops.py` (140)

The **only** module allowed to call Playwright action APIs. API (spec):

- `GuardedOps(page, timeouts, log)` — constructed once per run.
- `find(sel, timeout, retries) -> Locator` — re-query + retry with backoff; raises `OpError` after budget.
- `click(sel, **kw)`, `fill_textarea(sel, text, human: Humanizer)`, `scroll(sel, dy)`, `count(sel)`, `text(sel)`, `set_files(sel, path)`, `exists(sel)`.
- Every call: logs selector+outcome, applies global stall timeout, converts Playwright exceptions to `OpError` with a clean message (F-NF "never crash on missing DOM element").

### 6.9 `browser/watchdog.py` (90)

- Async task started with the run: every 5 s, `page.evaluate("1")` ping + `page.url` still matches + `APP_ROOT` exists.
- 2 consecutive failures → emit `connection_lost` → engine enters `DEGRADED`, worker pauses, UI shows reconnect prompt (F-NF recoverability).
- `reconnect()` helper reuses `connect.find_chat_page` on the same browser.

### 6.10 `parse/scroll.py` (130)

- `async scroll_and_collect(ops, viewport_sel, cfg, seen: set[str], emit, stop_flag)`:
  1. focus viewport (single click on its top area),
  2. loop: `ops.scroll(vy=scroll_px)` (humanized wheel deltas), `await sleep(scroll_pause + jitter)`,
  3. snapshot nicknames via `parse.extract`, diff vs `seen`, emit `users_found(new=[…])` per chunk,
  4. stop when `empty_runs` consecutive chunks yield 0 new, or `max_scrolls`, or stop flag.
- Returns final `seen` set (passed in/out so multiple `scroll_parse` blocks in one loop accumulate).

### 6.11 `parse/extract.py` (110)

- `async extract_rows(ops) -> list[UserRow]`: for each `ROW`, skip `HEADER_ROW` (F-UP-07); read `NICK` (trim), presence of `FEMALE`/`MALE`/`REGISTERED`/`ANON`; build `UserRow(nickname, gender, registered, is_guest, classes)`.
- Tolerates partial renders: rows missing `.primary-text` are skipped silently (reliability).

### 6.12 `engine/worker.py` (140)

- `WorkerThread(QThread)` owns: `asyncio.new_event_loop()` (run in `run()`), `queue.Queue` command channel, the `ChatFlowApi`-facing `Engine`.
- Signals (to main thread): `log(level, msg, icon)`, `status(state, detail)`, `users_found(rows)`, `users_updated(users)`, `target_picked(nick)`, `message_sent(nick, text)`, `error(code, msg)`, `connection_lost()`, `finished_run(summary)`.
- `run()` = `loop.run_forever()` with a queue-poller task + watchdog task + engine task; `shutdown()` drains and closes cleanly.
- All Playwright lifecycle happens here (R1).

### 6.13 `engine/executor.py` (140)

- `SequenceExecutor(engine_ctx)`:
  - `run_once()` — one full top-to-bottom pass of enabled blocks (respecting loop markers), returns summary.
  - Dispatch: `registry.get(block.action_type)` → executor instance → `await exec(block, ctx)`.
  - Per-block `try/except OpError` → log, mark block failed, `continue` or `skip_iteration` per `F-EX-03` flag.
  - Checks stop/pause between every block and inside long blocks via `ctx.wait_if_stopped_or_paused()`.
  - Tracks per-target progress so a mid-target failure doesn't mark the user MESSAGED.
- **MESSAGED is set only by `send_message` after the counter-reset verification** — never by other blocks.

### 6.14 `blocks/*` (one file each, all < 100 lines)

Common contract (`blocks/base.py`):

- `BlockResult(ok, data, error)`; `BaseExecutor.execute(ctx: BlockContext, block: Block) -> BlockResult`.
- `BlockContext` (§ `blocks/context.py`): `ops`, `page`, `settings`, `humanizer`, `queued_nicks: list[str]` (snapshot, R4), `seen: set[str]`, `current_target: str|None`, `rng`, `log()`, `wait_if_stopped_or_paused()`, `memory_proxy` (event-based, §2.1 R4).

| File | Action | Params (defaults) | Behaviour notes |
|------|--------|-------------------|-----------------|
| `go_main_tab.py` | `go_main_tab` | `tab_title="Гостиная"` | match `TAB_TITLE` text (cleaned); click; verify `TAB_ACTIVE` moved there |
| `scroll_parse.py` | `scroll_parse` | `px=300, pause=1.5, empty_runs=3, max_scrolls=50` | `parse.scroll` + `filters.evaluate` per new user + emit `users_found`; main thread upserts NEW→QUEUED/SKIPPED; worker updates its queued snapshot from the response |
| `pick_target.py` | `pick_target` | `order="top"\|"random"` | pop from snapshot list; emit `target_picked`; sets `ctx.current_target`; empty list → `no_targets` result (loop may end) |
| `click_user.py` | `click_user` | — | locate `USER_ROW` whose `NICK` text == target; click `user-container`; wait until a tab with title == target appears (dedupe guard: verify tab title, v1.0 §11) |
| `type_message.py` | `type_message` | `source="single"\|"pool"` | render `{nick},{time},{day}`; Humanizer types char-by-char into `TEXTAREA`; respects 1000 cap (truncate + warn) |
| `attach_image.py` | `attach_image` | `folder` (global) | pick random file (GIF/PNG/JPG/WEBP); `ops.set_files(FILE_INPUT, path)`; fallback: click `IMAGE_BTN` + `expect_file_chooser` |
| `send_message.py` | `send_message` | — | click `SEND_BTN`; verify `CHAR_COUNTER` back to `0 / 1000` within timeout; then emit `message_sent` (main thread marks MESSAGED, F-MS-04 timestamps) |
| `close_tab.py` | `close_tab` | — | click `TAB_CLOSE` of active person tab; verify tab gone |
| `wait_sleep.py` | `wait` | `seconds=2` | humanized sleep (jitter) |
| `loop_marker.py` | `loop` | `iterations=3` | sub-loop: executor supports `data.loop_id`; a second marker with same id closes the sub-loop |
| `condition.py` | `condition` | `expr` | whitelisted eval over `{target, nick, queued_count, loop_index, day, time}`; falsy → skip the *next* block (v1.0 F-SB condition semantics) |

### 6.15 `engine/delays.py` + `engine/humanize.py`

- `delays.py` (70): `jittered(base, ±jitter, rng) -> float`; `MIN_DELAY_FLOOR = 0.2 s` (risk table §11: rate-limit protection); `micro_pause_due(counter) -> bool`.
- `humanize.py` (100):
  - `type_text(ops, sel, text, cps, variance, rng)`: per-char `keyboard.type` with `sleep(1/cps · N(1, var))`; occasional (5 %) 2–4 char bursts; stop-flag check each char.
  - `wheel(ops, sel, dy, rng)`: splits `dy` into 3–7 delta ticks of 40–120 px with 30–80 ms gaps (real wheel feel; F-UP-02 "simulate mouse wheel in chunks").
  - Optional benign action: with small probability, mouse-move inside the viewport between targets.

### 6.16 `bridge/api.py` (140) — JS-facing API (QWebChannel slots)

All slots are async-free (main thread), thin, and JSON-friendly:

- `run_sequence(payload)` / `pause()` / `resume()` / `stop()` → command queue
- `test_connection()` → returns result dict (F-BR-04)
- `get_users(filters) -> {rows, counts}` (paged, F-NF 500+ users)
- `user_action(id, action)` (reset status, set note, skip)
- `reset_all_users()` / `export_csv(path)` / `import_csv(path)`
- `get_presets() / save_preset(p) / delete_preset(id)`
- `get_rules() / save_rule(rule) / delete_rule(id)`
- `get_settings() / save_settings(dict)` (validated against `Settings` dataclass)
- `get_image_folder() / set_image_folder(path) -> {ok, count}`
- `save_log(path)` (log panel "Save" button)

### 6.17 `bridge/signals.py` (90)

- Maps worker signals → `ChatFlowApi.notify(name, payload)` (single `@Slot` + `qwebchannel` `invoke`), so JS subscribes with **one** listener `chatflow.onEvent(name, payload)`.
- Event names (constants in `core/events.py`): `status`, `log`, `users_found`, `users_updated`, `target_picked`, `message_sent`, `error`, `connection_lost`, `run_summary`, `tab_candidates`.

---

## 7. JS ↔ Python Bridge Protocol

### 7.1 Setup

1. Python: `QWebChannel(server)`, register object `ChatFlowApi` under name `chatflow`.
2. JS (`ui/js/bridge.js`): `new QWebChannel(qt.webChannelTransport, ch => { api = ch.objects.chatflow; … })`.
3. Single inbound channel: `api.onEvent(name, payload)` (Python→JS push).
4. All JS→Python calls are the §6.16 slots.

### 7.2 Wire format

- Payloads are JSON objects; enums as strings (`"QUEUED"`); timestamps ISO-8601 UTC; booleans real booleans.
- User row payload: `{id, nickname, gender, registered, status, first_seen, last_seen, messaged_at, message_count, skip_reason}`.
- Log payload: `{ts, level, icon, msg}` (icon mirrors v1.0 §8.6 glyphs).
- Block payload (preset JSON): `{block_id, action_type, params{}, delay_after, enabled, position}`.

### 7.3 Sequence of a run (wire-level)

```
JS: run_sequence({blocks, queued? })            // blocks from builder (source of truth: JS)
Py→JS: status{CONNECTING} … status{RUNNING}
Py→JS: log{…}                                   // per step, §8.6 style
Py→JS: users_found{new:[UserRow…]}              // scroll chunks
Py→JS: target_picked{nickname}
Py→JS: message_sent{nickname, text, ts}         // main thread persists MESSAGED here
Py→JS: status{PAUSED} / connection_lost{}       // on degradation
Py→JS: run_summary{sent, skipped, errors, loops, elapsed}
```

Source-of-truth rules: **blocks live in JS** (builder), pushed to the worker on each RUN (worker is stateless about the sequence); **users live in SQLite** (Python), UI is a view; **settings live in SQLite `settings` table**.

---

## 8. UI Specification (QWebEngineView content)

Implements v1.0 §8 mockups exactly (layout, dark theme tokens, status colors). Notes:

- **index.html**: static skeleton of the 5 regions (palette / builder / tracker / filters+composer / log) + control bar (RUN, PAUSE, STOP, SAVE PRESET). No framework; ES modules.
- **SortableJS**: CDN-free — bundled locally at `ui/vendor/sortable.min.js`. Palette → builder (clone), builder → builder (reorder), builder → palette (delete).
- **Sequence builder**: each rendered block = header (icon, name, enabled ✓, ✕) + collapsible param fields generated from the action's param schema (sent from Python once via `get_block_schemas()` — keeps param metadata in one place, `blocks/registry.py`) + footer `delay_after` number input (0.0–60.0, step 0.1).
- **Tracker**: virtualized-ish table (render 200 rows, filter by status + sort by last_seen); row click → detail popup (notes, timestamps, "reset status" / "skip"); CSV buttons; Refresh re-queries `get_users`.
- **Composer**: single/pool mode; pool = one message per line, random pick per send; live `N / 1000` counter mirroring the site cap; variable chips `{nick} {time} {day}`; image folder row with file count (F-MM-04/05).
- **Log**: append-only, auto-scroll toggle, Clear, Save (downloads via bridge to a path).
- **Settings modal**: exactly v1.0 §8.7 (Connection / Human-like / Memory / Logging).
- **Status bar** (inside window, native): connection pill + counts, updated by `status`/`users_counted` events.

---

## 9. Error Handling & Resilience (F-NF, v1.0 §11)

| Failure | Detection | Behaviour |
|---------|-----------|-----------|
| CDP refused / wrong port | `connect_cdp` exception | `ERROR` state; settings hint with `chrome --remote-debugging-port=9222` command; F-BR-04 test button gives the same diagnostic before a run |
| Tab not found | no URL match | `tab_candidates` list shown; user picks or opens the site |
| Tab closed mid-run | watchdog ping fail ×2 | `DEGRADED`: pause, "Reconnect?" prompt; on reconnect resume from last block boundary |
| Element missing at op time | `OpError` from `page_ops` | log warning, retry (2×, backoff), then block fails per F-EX-03 policy (skip block vs skip iteration) |
| Angular re-render orphans a node | `ElementHandle is not valid` | re-query rule (§1.6 #5) — every op re-locates fresh |
| Duplicate nicknames | tab-title mismatch after click | abort that target, mark `SKIPPED(reason="duplicate-nickname")`, continue |
| Send not confirmed (counter not reset) | timeout on `CHAR_COUNTER` | retry send once; if still not confirmed → `ERROR` log, user stays QUEUED, skip iteration |
| Bad regex in a rule | `re.error` on save | disable rule, warn event |
| Message > 1000 chars after rendering | length check | truncate + warn (site hard cap) |
| Stall (no op progress) | global watchdog | pause + `error` event "possible hang" |

**Invariant:** the worker never raises out of the loop; all exceptions are logged and converted to `BlockResult`/`error` events. The app never crashes the UI thread because of automation (R2/R5).

---

## 10. Observability

- In-app live log panel (bridge `log` events) + rotating file log: `logs/chatflow_YYYYMMDD.log`, `TimedRotatingFileHandler`, retention = `retention_days` (default 7), old files pruned on startup.
- Every guarded op logs: selector, attempt #, outcome, duration.
- `run_summary` event at end of each run (sent/skipped/errors/loops/elapsed) — also appended to file log.
- JS console messages from the UI are mirrored to the file log at DEBUG (webview §6.3).

---

## 11. Testing Strategy

1. **DOM contract tests** (`tests/test_dom_contract.py`) — the repo's saved HTML pages are first-class fixtures. Parse `Вирт чат.html` / `Вирт чат privat.html` with BeautifulSoup and assert:
   - every §1.6 selector finds the expected element(s),
   - nickname extraction yields the known nicknames (e.g. `Lizalo4ka`, `_ШепотНочи_`),
   - header rows are detected and excluded,
   - gender/registration flags match the known rows,
   - tab titles + close-button aria-labels parse correctly (trimmed).
   → This pins the selector contract to the real site today, and gives a regression harness when the site changes.
2. **Unit**: filters (pure), memory repos (temp DB), config round-trip, state machine transitions, template rendering, cooldown math.
3. **Executor dry-run**: a `FakeOps` implementing the `page_ops` interface records calls; run a full default sequence and assert call order + user state transitions (NEW→QUEUED→MESSAGED, SKIPPED paths).
4. **Line budget guard** (§16.3).
5. **Manual QA script** (Phase 8): run against a real Chrome with debug port; check-list in README.

No tests require a running Chrome; everything is hermetic.

---

## 12. Packaging

- `pyinstaller --windowed --name ChatFlowOrchestrator` with the `ui/` tree and `qrc` compiled into the binary (no external data dir required for UI).
- Playwright browser **not** bundled — the app attaches to the user's own Chrome (F-BR-01); only the `playwright` driver package is needed, no `playwright install`.
- `data/` and `logs/` created under `%LOCALAPPDATA%\ChatFlowOrchestrator` (overridable in settings).
- README quick-start: launch Chrome with `--remote-debugging-port=9222`, open ru.virt-chat.com, log in, start the bot, Test Connection, RUN.

---

## 13. Implementation Plan (module order = dependency order)

| # | Deliverable | Modules (all < 150 lines each) | Exit criteria |
|---|-------------|-------------------------------|---------------|
| M0 | Skeleton | `chatflow/__init__`, `app/*`, `ui/index.html` (static mock), `requirements.txt`, `tests/test_line_budget.py` | App opens, shows static UI, line-budget CI green |
| M1 | DOM contract pin | `browser/selectors.py`, `tests/test_dom_contract.py` | All §1.6 selectors verified against saved HTML |
| M2 | Memory | `core/models.py`, `core/config.py`, `core/events.py`, `core/logconf.py`, `memory/*` | Repos unit-tested; CSV round-trip green |
| M3 | Browser layer | `browser/connect.py`, `browser/page_ops.py`, `browser/watchdog.py`, `engine/state.py` | Test-Connection works against real Chrome; OpError taxonomy tested with a fake page |
| M4 | Parse + filters | `parse/*`, `filters/engine.py` | Extract on saved-HTML-driven fake page yields correct UserRows; filter unit tests green |
| M5 | Blocks + engine | `blocks/*`, `engine/worker.py`, `engine/executor.py`, `engine/delays.py`, `engine/humanize.py` | Dry-run executor test: full default sequence, states + log order correct |
| M6 | Bridge + UI wiring | `bridge/*`, `ui/js/*` (all panels) | Run/Pause/Stop from JS controls the dry-run worker; tracker updates live |
| M7 | Humanization + media | `attach_image.py` polish, `humanize.py` tuning, `composer` pool mode | Image attach verified on real site (manual QA) |
| M8 | Packaging + docs | PyInstaller spec, README, QA checklist | Windows build launches standalone; full manual run succeeds |

This maps 1:1 onto the v1.0 doc's 8 phases (M0↔Phase 1 … M8↔Phase 8) and keeps every Python file under the 150-line cap by construction.

---

## 14. Deviations from the v1.0 Design Document (and why)

| v1.0 said | This design | Reason (evidenced by the saved pages) |
|-----------|-------------|----------------------------------------|
| File upload via `expect_file_chooser` (F-MM-06) | Primary: `set_input_files` on hidden `input#file`; chooser as fallback | The page contains a persistent hidden file input — deterministic, no OS dialog race |
| Main tab matched by `.chat-title` text only | Match cleaned title **or** `data-mat-icon-name="room"`; prefer exact cleaned text | Titles carry trailing spaces and unread-badge spans |
| Selector `button:has(mat-icon:has-text("send"))` | `button[type=submit]:has(mat-icon:text-is("send"))` scoped to `app-message-form` | `has-text` substring could match future icons; `type=submit` is the stable identity |
| Tab close via "close chat tab" (no selector) | `div[role=tab] button.tab-close-button` (+ `aria-label="Закрыть чат {nick}"` as verification) | Verified present on every closable tab |
| "Комнаты" header example | Header detection: any `container-item` without `user-item` (observed header: "Пользователи") | The saved snapshot's header is "Пользователи", not "Комнаты" — rule must be structural, not text-based |
| DB writes from worker thread (implied) | Main-thread-only DB + queued-snapshot reads in worker (R4) | sqlite3 cross-thread use is unsafe; snapshot reads keep the worker hermetic & testable |
| Send verification not specified | Verify `0 / 1000` counter reset (or textarea cleared) before marking MESSAGED | The form exposes a live counter — a cheap, reliable "delivered" signal |

---

## 15. Open Questions (to confirm before M3)

1. **Re-message loop UX:** when `pick_target` finds an empty queue, should RUN auto-exit (default, F-EX-02) or keep scanning with a "re-scan interval"? → Default: exit with `run_summary`; re-scan only if a `scroll_parse` block precedes `pick_target` in the sequence (which is the natural default preset).
2. **Multiple person-tabs for the same nickname** (site allows several chats): click the *first* matching row, verify the *newly active* tab's title equals the target; if ambiguous, `SKIPPED(duplicate)`.
3. **Search field usage:** v1.0 lists it "for future integration" — agree to leave it unused in v1.0 (we never type into `.search-field`).
4. **Window size default:** 1440×900 with the 3-column grid (280 / 1fr / 360).

---

## 16. Implementation Log (decisions taken during M0–M8)

| # | Decision | Reason |
|---|----------|--------|
| 1 | `engine/worker.py` split into `worker.py` (thread + command pump + pause/stop) and `run_task.py` (one RUN: connect → context → execute → teardown) | kept both files under budget without sacrificing clarity |
| 2 | **`MAX_TARGET_FAILURES = 3`** in `engine/executor.py`: a target whose pass fails 3× in a row is removed from the queue and flagged `SKIPPED (automation-failed)` via a `users_updated` event | without this, a permanently broken target (e.g. send never confirms) requeues itself forever — the run never terminates. Discovered by dry-run test `test_executor_failures`. |
| 3 | A `terminate` signal raised inside a loop body propagates to the enclosing pass (`out["terminated"] = True`) | found by `test_loop_and_condition`: without propagation the pass-loop repeated the sequence forever. |
| 4 | Bridge slots split into mixin files (`api.py` + `api_presets.py` + `api_composer.py`) around one `ChatFlowApi` QObject | QWebChannel exposes a single object; mixins keep every file under budget. All slots take a JSON-string payload and return a JSON string (uniform JS call shape, callback-based results). |
| 5 | Python→JS push via `QWebEngineView.runJavaScript("window.__call(…)")` instead of a JS-registered QWebChannel object | no registration race, one trivial sink function, payloads are JSON strings. |
| 6 | UI loaded from `file://` (resolved relative to the package / `_MEIPASS`) instead of compiled `qrc` | no rcc tooling in dev; PyInstaller bundles `ui/` as data. UI uses classic scripts (no ES modules — `file://` blocks them). |
| 7 | `ui/vendor/dnd.js` (small native HTML5 DnD) instead of SortableJS | the sandbox had no CDN access; the module covers exactly the needed behaviours (palette→builder clone, reorder, drop-at-position). Swapping in SortableJS later is a 10-line change in `palette.js`/`sequence.js`. |
| 8 | Image upload: `set_input_files` on the hidden `input#file` is primary; `expect_file_chooser` after clicking the image button is the automatic fallback | matches the verified DOM (§1.5) — the input is persistent and deterministic. |
| 9 | Worker reads the queued list from the RUN payload (snapshot, R4) and maintains it locally; the main thread is the only DB writer (`users_found` / `message_sent` / `users_updated` events are persisted on the main thread) | no sqlite handle ever crosses threads; worker stays hermetic and fully unit-testable with `FakeOps`. |
| 10 | `test_connection` uses `async_playwright` per call and closes it; a run keeps one Playwright instance for its lifetime | test is side-effect-free (F-BR-04); the run's browser handle is stopped in the run's `finally`. |

---

## 17. Constraint Enforcement

### 17.1 The 150-line rule

- Every `chatflow/**/*.py` file must be **≤ 149 lines** (blank lines and comments included — simplest verifiable rule).
- Any module that outgrows its budget is **split by responsibility first** (see the deliberate splits: `worker/executor/state`, `page_ops/selectors/connect`, `repo_*` per table, one file per block).

### 17.2 Budget table (top-10 largest planned files)

| File | Budget |
|------|--------|
| `engine/worker.py` | 140 |
| `engine/executor.py` | 140 |
| `browser/page_ops.py` | 140 |
| `browser/selectors.py` | 140 |
| `bridge/api.py` | 140 |
| `memory/db.py` | 140 |
| `memory/repo_users.py` | 140 |
| `app/window.py` | 130 |
| `app/channel.py` | 130 |
| `parse/scroll.py` | 130 |

### 17.3 Guard

`tests/test_line_budget.py` (≈25 lines): walks the package, asserts `len(path.read_text().splitlines()) < 150` for every `.py`; prints the worst offenders. Runs in the same CI as the unit tests — the rule can never be violated silently.

---

*End of Architecture Document.*
