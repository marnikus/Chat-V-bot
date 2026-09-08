# ChatBot Automator

A Python/Qt6 desktop application for automating interactions with the
Virt-Chat web platform (`ru.virt-chat.com`) via Chrome DevTools Protocol.

---

## 1. Install Python Dependencies

Make sure you have **Python 3.11+** installed, then run:

```bash
pip install -r requirements.txt
```

This installs:
| Package | Purpose |
|---------|---------|
| PySide6 | Qt6 GUI framework (window, web view, web channel) |
| websockets | WebSocket client for Chrome DevTools Protocol |
| aiohttp | HTTP client for Chrome tab discovery |
| aiosqlite | Async SQLite for user memory storage |
| qasync | Bridges Qt event loop with Python asyncio |

---

## 2. Start Chrome with Remote Debugging

You **must** launch Chrome with the remote debugging port flag:

**Windows — recommended (dedicated profile):**
```cmd
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\chatflow-chrome"
```

`--user-data-dir` starts Chrome on a **separate profile** kept in
`C:\chatflow-chrome`. That is the reliable way to do this:

* it works even when your everyday Chrome is already open — a normal Chrome
  without the flag simply hands the command over to the running instance and
  the debug port never opens;
* your normal profile, cookies, extensions and open tabs are untouched;
* the first launch is a brand-new profile, so log in to the chat once inside
  that window; the login is remembered in `C:\chatflow-chrome` for every
  later launch.

That exact command ships with the repo as **`start-chatflow-chrome.bat`** —
double-click it (or make a shortcut to it) so Chrome always starts the same
way. It also opens the chat page for you.

**Windows — plain (uses your normal profile):**
```cmd
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
```

**macOS:**
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir="$HOME/chatflow-chrome"
```

**Linux:**
```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/chatflow-chrome"
```

> ⚠️ **Important:** without `--user-data-dir`, close ALL Chrome windows before
> running the command. If Chrome is already running without the debug flag,
> the flag is ignored and the app won't be able to connect. With
> `--user-data-dir` you can skip that — the dedicated profile always opens its
> own instance and its own debug port.
>
> Check it worked: open **http://localhost:9222/json/version** in any browser.
> A JSON page means the port is live; "connection refused" means Chrome was
> started without the flag (or the old instance swallowed the command).

In that Chrome window, open **https://ru.virt-chat.com/chat** and log in.

---

## 3. Run the App

```bash
python main.py
```

The app window will open and **automatically detect** your open Chrome tabs.

---

## 4. Connect to Chrome Tab

1. In the app header, find the **dropdown** on the right side
2. Select the **virt-chat.com** tab from the list (click 🔄 refresh if it's empty)
3. Click the **🔗 Connect** button
4. The status dot should turn **green** 🟢 — you're connected!

---

## 5. Using the App

### Build an Action Stack
Add blocks from the **+ Add** menu, or click them to add:
- **Find & Click** — configurable search-and-click block (see below)
- **Click Main Tab** — switch to a chat room tab
- **Scroll Parse** — scroll through the user list and collect users
- **Click User** — click on a specific user to open private chat
- **Wait Page Load** — wait for a page/element to appear
- **Type Message** — type a message (supports `{{nick}}` variable)
- **Click Send** — click the send button
- **Attach Image** — attach an image file
- **Click Back** — return to the main chat list
- **Pause** — add a delay between actions
- **Conditional Skip** — skip users already messaged

### Find & Click — the configurable action-block constructor
A generic search-and-click block that is built entirely in the UI — it is the
way to create your own reusable blocks instead of being limited to the
hardcoded ones. Example: a "Find Settings Button" block.

**The two search fields (CSS selectors):**
- **① Element to find — the clickable box**, e.g. `div[role='tab'].tab-item`
  (the button/rectangle to detect).
- **② Separate text element inside it to confirm**, e.g. `p.chat-title`
  (a *different* element whose text proves this is the right box), plus an
  optional **text to match** (e.g. `Settings`; empty = take the first match).

**Click or not:**
- **Click after found** ticks the box and clicks the found element when the
  match is confirmed.
- **Or click this inner element instead** (CSS, optional) clicks a child of
  the found box rather than the box itself.
- Untick **Click after found** to turn the block into a find/verify-only step.

**Build once, reuse everywhere:**
1. **+ Add** → **🔎 Find & Click**, click the new card to open its config panel.
2. Give it a **custom name** (e.g. `Find Settings Button`) — shown on the card
   and in the run logs.
3. Fill in the two search fields, the text to match, and the click behaviour.
4. Press **Save as new preset** — the block is stored in the single
   `config.json` store and appears as a chip under **Custom blocks** and at the
   top of the **+ Add** menu.
5. Reuse it in any stack by clicking the chip (or its **+ Add** entry) — the
   full configuration comes back. If you edit a saved block and press the
   button again it reads **Update preset “name”** and overwrites that preset.
6. Remove a preset you no longer need with the **×** on its chip (confirmed in
   an in-app dialog). Everything persists across app restarts.

**Keep the config open while you work:** click the 📌 **pin** button in the
Block Config title bar. While pinned, the panel stays open even when no block
is selected (it shows the empty-state hint until you pick one). Click 📌 again
to unpin and restore the default close-on-deselect behaviour; the **×** close
button always closes and unpins. The pin state is remembered across app
restarts, so the panel reopens when you come back.

### Reorder Blocks (drag & drop)
Grab any block (or its **⠿** handle) and drag it up or down. While you move
the mouse you get full visual feedback:
- the dragged block **lifts off** into a floating, tilted card that follows the
  cursor, and its old position turns into a dashed, pulsing **drop slot**
- the other blocks **slide apart** to open the gap
- a **glowing insertion bar** marks exactly the position the block will take if
  you release right now, and a badge next to the cursor shows `3 → 5`
- releasing drops the block there and it **flashes** so you can see where it landed
- the list **auto-scrolls** when you drag near the top/bottom edge
- press **Esc** during a drag to cancel it; nothing is changed
- keyboard alternative: select a block and press **Alt+↑ / Alt+↓**

The reorder engine is bundled with the app (`ui/js/stack-drag.js`) and needs no
internet connection. Reorders are saved to the session snapshot like any other
stack edit.

### Flexible Grid Layout (drag any window anywhere)
Every content window — **Stats, Filters, Action Stack, Block Config,
Message Composer, User Memory, Log Console** — is a draggable tile in a
free-form grid. The top menu bar (app header + URL/Language/Presets toolbar)
stays pinned; everything below it is rearrangeable.

- **Move** — grab a window by its **title bar** (⠿ grip) and drag it:
  - drop on an **edge** of a window → that window **splits in half** and you
    land in the new half (e.g. Composer left | People right)
  - drop on a window's **centre** → you **join its row/column** (the two
    windows share its former space)
  - drop on a **separator (sash)** → you are inserted between the two
    neighbours
  - a glowing line shows exactly where the split/insertion will land, a badge
    next to the cursor names the outcome, **Esc** cancels
- **Resize** — drag any sash; the two neighbours trade space while the rest of
  the grid **adapts proportionally** (structure is never broken). Double-click
  a sash to reset that split to even sizes.
- **Span** — a window next to a group of windows automatically spans their
  full height/width (e.g. the Log Console as a tall side column).
- **Preset layouts** — the **▦ Layouts** button in the header applies ready
  arrangements in one click: **Default**, **A** (stacked rows), **B**
  (Composer | People side by side, Log below) and **C** (Log as full-height
  side column). Your manual arrangement always wins until the next preset.
- The arrangement **persists** across app restarts (validated on load — a
  corrupted layout can never brick the UI).
- Every panel/row has a usable minimum width and height; resizing cannot make
  a neighboring row disappear.
- Grid edits use the same global `Undo` / `Redo` controls and `Ctrl+Z` /
  `Ctrl+Y` history as action-stack edits. There is no second grid history.

Implementation: `ui/js/sash-core.js` (pure split-tree model),
`ui/js/sash-grid.js` (rendering + drag/resize), `ui/css/sash-layout.css`;
design in `docs/SASH_LAYOUT_DESIGN_2026-09-05.md`; tests in
`tests/test_sash_core.py` (node) and `tests/test_sash_webengine.py`
(real Qt WebEngine).

### Save / Load Presets (full action stack)
- **💾 Save** — name the preset and the **complete stack** (block order + every
  block setting) is stored in the single preset file `config.json`.
- Every saved preset appears as a small **chip** under "Saved presets" and in
  the **folder picker list** — click either to load it back. Chips survive an
  app restart (close → reopen → click chip → full stack restored).
- **Save Template / Load Template ▾** work the same way for message templates.
- Deletion is confirmed through an in-app dialog (no browser dialogs needed).

### Session restore on startup
On every start the app restores the previous session from the same single
`config.json` store:
- the **last bookmark** is selected again (chip highlighted, URL field filled);
- an **auto-connect attempt** is made using that bookmark's URL;
- the **last used stack** (or the last named preset) is loaded into the editor;
- all preset/template/URL/custom-block chips are restored;
- the main window's last X/Y position and width/height are restored exactly;
- the People table's current sort remains active while live user updates arrive.

### URL Presets (auto-connect by URL)
The toolbar below the header holds a **URL field** and quick-connect presets:
1. Paste a URL or keyword (e.g. `https://ru.virt-chat.com/chat`) or click a chip.
2. Click **Auto-Connect** — the app parses the URL, matches it against every
   open Chrome tab (exact URL → path → host → keyword) and **automatically
   selects and connects** to the best match.
3. Press **+** to store the current URL as a new preset chip, **×** on a chip
   to remove it. The last selected bookmark is remembered for next startup.

### Closing the app
Clicking the window close button (X) shuts the whole process down cleanly —
background tasks are cancelled, the Chrome connection is closed and the
terminal prompt returns. A watchdog force-exits after 3 s if anything blocks.

### Message Composer
Type your message in the bottom composer area. Use `{{nick}}` to insert the
user's nickname automatically.

### Manage the People List (User Memory)
The bottom-left panel lists every discovered user and is fully editable:
- **Filter nick…** — type to narrow the list
- **checkbox column** — tick individual rows; the header checkbox selects or
  deselects all *currently visible* (filtered) rows
- **🗑 Delete selected (n)** — deletes only the ticked nicks
- **🗑 Delete** on a row — deletes that single nick
- **✔ Done / ↩ Undo** on a row — flips that user's "messaged" flag
- **Reset Messaged** — marks every user as new again (deletes nobody)
- **Clear All** — removes every user from memory
- Click **Nick, Gender, Reg?, Status, First Seen, or Messaged** headers to sort;
  click the same header again to reverse the order. The `▲▼` arrows show the
  active direction.

The list fills in as soon as the app starts (no need to connect to a Chrome
tab first). Every destructive action asks for confirmation in an in-app dialog
first. Nicks may contain quotes and emoji — row actions are delegated, never
inlined, so they keep working for any nick.

### Set Filters (Criteria)
Click the ✏️ edit button in the Filters sidebar to set criteria:
- **MUST HAVE** — only message users matching these classes (e.g. `registered`)
- **MUST NOT HAVE** — skip users with these classes (e.g. `guest`, `anonymous`)

### Run & Debugger
1. Click **▶ Run** in the stack header
2. The app will parse users → filter by criteria → execute the stack for each user
3. Use **⏸ Pause** (click again to resume) and **⏹ Stop** at any time

The **Log Console** is a live step-by-step debugger for every block:
- element searches: how many nodes matched and whether the element was **found**
  (e.g. `✅ Tab found: "Гостиная"`) or **not** (`❌ Failed to find element: …`
  with a candidate list when available)
- whether the found element was **clickable** (visible / disabled checks) and
  whether the click actually happened
- per-step status (`✓ Step 3 OK (0.42s)` / `✗ Step 3 FAILED …`) and which block
  is currently executing (highlighted green in the stack)
- a JSONL run trace for every run is written to
  `logs/run_trace_<timestamp>.jsonl` (path announced in the console)

### Debugging & logs
- Daily logs: `logs/YYYY-MM-DD.log` (Python logging)
- Per-run trace: `logs/run_trace_<timestamp>.jsonl` (step-by-step JSON records)

---

## Message History & the Passive Collector

Everything said in a private chat — both directions, text, images and GIFs —
is archived per nick in a second SQLite database (`history.db`, media bytes
in `saved_media/`). The queue database (`chatbot.db`) is untouched by it:
filters and People-list edits never delete archived messages (docs RULE 14).

### My Nick

The pinned header has a **My Nick** field. Set it to the nick *you* are using
in the chat; it is stored in `config.json` (`collector.my_nick`) and written
next to every archived message, so a conversation always shows both sides
even when your nick changes between sessions.

### The archive windows

They are ordinary grid windows — drag, split, merge and resize them like any
other panel (`📐` menu → *Reset to default* brings them all back). Two more
ordinary windows manage the archive itself: **Label Manager** and
**DB Connection** (see *Person labels* and *The database window* below).

| Window | What it does |
|---|---|
| **Person History** | The whole conversation with one person, oldest first, with inline images/GIFs, day separators and gap markers. Click a nick in **User Memory** to open it. Text is selectable; a left click on an image copies it. Search this conversation, or switch to **All people** for a global search grouped per nick. |
| **Full User Database** | Everyone ever archived, merged by nick (never a duplicate), lazily loaded as you scroll, searchable by nick. Clicking a row opens that person. `Preload` sets how many rows are fetched ahead of the scroll. |
| **Chat Message Collector** | What the background collector is doing right now: *Collecting*, *Collected*, *No new messages* or *Not in private tab now*, plus the partner, my nick, the archive total and the heartbeat. Pause/resume it, force one pass, or turn media downloads off. |

### Only real private chats are archived (two-step gate)

Before a single line is written to a person's history, both checks must pass:

1. **Only two nicks.** The in-page agent parses *the pane that is on screen*
   and reports the distinct authors it saw. Mine + the partner ⇒ fine; a
   third nick (the main room, a group tab, a pane left over from the chat
   you just closed) ⇒ nothing is saved.
2. **The tab names that person.** The active `.tab-item` must be a private
   tab (`chat-type-icon = user`) whose title names the same nick.

If either check fails the collector says so in the Chat Message Collector
window (*“Not a private chat — Макс__Б writes here too (nothing saved for
Ански)”*) and stores nothing. The live push channel obeys the same gate, so
switching tabs mid-conversation can never file room chatter under a person.

### Where the pictures are saved

```
saved_media/
├─ Anski/                     ← Latin folder name (Ански), `_nick.txt` names the owner
│  ├─ images/2026-09-07_001.png
│  └─ gifs/2026-09-07_001.gif
└─ Horosho_Vse/
   └─ images/2026-09-07_001.jpg
```

One folder per conversation (both directions), `images/` and `gifs/` split,
files named `YYYY-MM-DD_NNN.ext` — short, sorted, and safe to open, copy or
drag anywhere. Person History renders the **saved file**, never the
percent-encoded remote URL, and the toolbar's **📂 Files** button opens that
person's folder in Explorer. A left click on a picture puts the file itself
on the clipboard (plus the path as text), so it can be pasted straight into
a chat. Older flat `media_cache/<sha256>.<ext>` files are moved into the new
tree automatically on the first start.

### How collection works (and why it does not freeze the UI)

A tiny agent is injected into the page. Every heartbeat it returns only a
**fingerprint of the head and tail** of the conversation plus a message
count — never the whole DOM. When nothing changed, the pass costs one
`Runtime.evaluate`; when the tail grew, only the *new* messages are
serialised, in chunks with a pause between them, and appended. If the page
trimmed or re-rendered the conversation, the collector re-syncs by overlap
and records a **gap marker** rather than silently losing lines.

The collector keeps running (throttled) during an Action Stack run, so a
long automation never costs you messages.

### The COLLECT_HISTORY block

Add **🗃 Collect Message History** to a stack to archive the conversation on
screen on demand: `target` (current tab or the selected person), `mode`
(delta / full re-scan), `max_messages`, chunk size and pause, media on/off,
and *fail if empty*. It reports progress as `done/total` and honours Stop.

## Managing the archive — delete, labels, databases

Everything in this chapter is **undoable with the same global ↶ / ↷ buttons**
(Ctrl+Z / Ctrl+Y) that undo stack edits and layout changes: one history, one
pair of buttons, no per-window undo (docs RULE 12).

### Removing history

Nothing is ever hard-deleted behind your back. A delete hides the rows
(tombstone `deleted_at`, docs RULE 14) and the undo entry puts them back
byte-for-byte.

| Where | Control | What it does |
|---|---|---|
| **Person History** toolbar | `🧹 Clear chat` | Removes every message of the open conversation, **keeps the person** in the database. |
| **Person History** toolbar | `🗑 Remove person` | Removes the person *and* the whole conversation. |
| **Person History** message | the small `✕` on a message row | Removes that single message. |
| **Full User Database** row | `🧹` / `🗑` | The same two actions for any archived person, straight from the table. |

The People list keeps working the way it did: a person deleted from the
archive is also dropped from the queue table, and the undo restores both
sides together.

### Person labels

Labels are free text tags with a colour, e.g. `Rude`, `VIP`, `Later`. They
live in `config.json` (so they survive restarts) and every change is undoable.

* Labels are drawn as small coloured pills **next to the nick in both the
  People table and the Full User Database table**.
* The `✕` on a pill removes that label **from that person only** — it never
  deletes the label itself.
* One person can carry as many labels as you like.

**Label Manager** (a normal grid window — minimize, maximize, close, drag it
anywhere, it is listed in the `🪟 Windows` menu and remembers its state) has
four sections:

1. **Active Labels** — every label; its `✕` deletes the label *system-wide*
   (and strips it from everyone). This is the only place that can do that.
2. **Create New Label** — a name field, a colour dot that opens the Color
   Picker, and `＋ Add Label`. Empty or duplicate names are refused with a
   message instead of creating junk.
3. **Filter By Labels** — tick labels, then `Include Selected` (green) or
   `Exclude Selected` (red). *Exclusion wins*: a person carrying an excluded
   label is skipped by an Action Stack run even if they also carry an
   included one — so `Rude` can be ignored during auto-messaging. The title
   bar shows the active rule; `Clear` removes it.
4. **Assign To Person** — a `Select Person…` dropdown that automatically
   follows the person you clicked in the People list or the database, the
   label list (labels the person already has are not offered again) and
   `Assign`.

### The Color Picker

A small dark popup (280×320) you can **drag by its title bar**; it remembers
where you left it. Twenty bright presets in a 5×4 grid — Red, Orange, Yellow,
Lime, Green / Teal, Cyan, Sky Blue, Blue, Indigo / Violet, Purple, Magenta,
Pink, Hot Pink / Coral, Amber, Chartreuse, Spring Green, Aqua. The current
colour wears a white ring; picking one closes the popup, so do `Cancel`, the
`✕` and `Esc`.

### The database window

**DB Connection** is a normal grid window. It lists only existing, compatible
chat-history databases beside the active file or in recent locations. The
People queue (`chatbot.db`), undo/internal stores, backups and missing files
are not manageable here. The global undo timeline remains in `config.json`.

| Reading | Meaning |
|---|---|
| **Full DB size** | The active SQLite file, including its `-wal` / `-shm` companions. |
| **Text size** | How many bytes of the messages are actual text. |
| **Images folder** | Size *and* file count of `saved_media/`. |

* **＋ Create** builds and validates an independent empty archive. It does **not**
  connect to it, reset history, or interrupt collection. Click **Load** explicitly
  when you want to switch.
* **Load** validates the target before swapping connections. In-flight writes,
  queries and downloads finish in their original database. An incompatible
  target is refused; the working connection stays open.
* **Delete** moves the file to `db_trash/` and removes it from the list and recents.
  Deleting the active archive first connects to another valid archive. The last
  valid archive cannot be deleted: create another one first.
* **Clean DB** first takes a consistent SQLite backup, then empties the active
  archive transactionally. A failed backup aborts the operation.

Ctrl+Z uses the existing global history. Undo/redo of **Create** concerns the
file, not a connection switch. Restoring an inactive deleted file keeps the
current connection; undoing an active deletion reconnects the restored archive.
Undo/redo waits while a database action is in flight. Settings/undo JSON is
published atomically so a failed save cannot truncate the previous timeline.

### Recovering missing message text

The collector retries partially rendered messages instead of saving timestamps
alone. Text and media captions are captured together. Historical empty rows are
repaired in place when the private chat can supply the text; unknown or
ambiguous content is never invented. If neither text nor media is available,
Person History shows **`[text not captured]`** instead of a blank bubble.

To retry older captures:

1. Open that person's original **private chat** in the connected browser.
2. Ensure the collector is enabled/resumed and your own nick is correct.
3. Click **Backfill older** in Chat Message Collector and keep the chat open.
4. Check the **Text capture** status/log. Successful repairs refresh Person
   History even when no new message was inserted.

Recovery also works with media downloads disabled. Messages no longer exposed
by the website cannot be reconstructed from timestamps alone. If an older build
saved an unusable active path, startup prefers another valid archive; if none
exists, it creates a separately named recovery archive without overwriting the
original files. This startup recovery is not the **Create** button's behavior.

Design and verification:
`docs/DB_CONNECTION_SAFETY_AND_TEXT_RECOVERY_DESIGN_2026-09-08.md`.
Labels design:
`docs/PERSON_LABELS_AND_DB_MANAGEMENT_DESIGN_2026-09-07.md`.

### Settings (config.json)

```jsonc
"history":   { "enabled": true, "db_path": "history.db",
               "media":   { "enabled": true, "max_file_mb": 25,
                            "max_cache_mb": 200, "cache_dir": "saved_media" },
               "preview": { "preload_rows": 40, "page_size": 50,
                            "show_images": true } },
"collector": { "enabled": true, "my_nick": "", "heartbeat_ms": 1500,
               "require_private": true, "download_media": true },
"labels":    { "defs":   [ { "id": "lbl_1", "name": "Rude",
                             "color": "#ff3b30" } ],
               "assign": { "Ангелина": ["lbl_1"] },
               "filter": { "include": [], "exclude": ["lbl_1"] },
               "next_id": 1 },
"state":     { "db_recent": ["history.db", "archive_2026.db"] }
```

`max_file_mb` is the per-file cap of the media cache. Before 2026-09-07 it
defaulted to 2 MB, which silently `skipped` every ordinary chat GIF — stored
configs carrying a value ≤ 2 are migrated up to 25 on startup
(`docs/BACKFILL_MEDIA_RECOVERY_ROOT_CAUSE_2026-09-07.md`).

Design documents: `docs/MESSAGE_HISTORY_ARCHITECTURE_DESIGN_2026-09-06.md`,
`docs/PASSIVE_CHAT_COLLECTOR_DESIGN_2026-09-06.md`,
`docs/HISTORY_UI_WINDOWS_DESIGN_2026-09-06.md`,
`docs/PRIVATE_GATE_AND_MEDIA_TREE_2026-09-07.md`.

---

## Repository Structure

```
├── main.py                  # App entry point
├── requirements.txt         # Python dependencies
├── start-chatflow-chrome.bat # Windows: Chrome + debug port on its own profile
├── backend/
│   ├── cdp_client.py        # Chrome DevTools Protocol WebSocket client
│   ├── action_engine.py     # Stack executor
│   ├── bridge.py            # QWebChannel bridge (JS ↔ Python)
│   ├── user_memory.py       # SQLite user database
│   ├── criteria_engine.py   # User filter engine
│   ├── scroll_parser.py     # Virtual scroll user extractor
│   ├── message_injector.py  # Message typing via CDP
│   ├── media_handler.py     # Image attachment via CDP
│   ├── config_manager.py    # SINGLE JSON file: settings + presets + state
│   ├── history_service.py   # Message archive: db + repo + query + collector
│   ├── history_db.py        # history.db schema/connection (FTS5 when available)
│   ├── history_models.py    # Message/Person/Media records + fingerprints
│   ├── history_repo.py      # Append/align/merge — the archive writer
│   ├── history_query.py     # Paging, search, per-person and DB statistics
│   ├── chat_parser.py       # Delta-aware conversation parser (resource saving)
│   ├── chat_agent_js.py     # Probe expressions for the in-page agent
│   ├── collector.py         # Passive private-chat collector state machine
│   ├── media_store.py       # Image/GIF cache (url + sha256 + bytes on disk)
│   ├── label_store.py       # Person labels: defs, per-person tags, filter rule
│   ├── db_manager.py        # DB Connection: create/load/delete/clean + sizes
│   ├── js/chat_agent.js     # The in-page agent (fingerprints, slices, push)
│   ├── preset_store.py      # JSON-backed stack/template presets (same file)
│   ├── dom_probe.py         # DOM probe JS + result interpreter (debugger)
│   ├── tab_matcher.py       # URL → tab matching (URL presets)
│   └── logger.py            # File + console logging
├── actions/
│   ├── base_action.py       # Action base class + registry
│   ├── custom_find.py       # Configurable Find & Click block (CUSTOM_FIND)
│   ├── click_main_tab.py    # Switch chat tab
│   ├── scroll_parse.py      # Scroll & collect users
│   ├── click_user.py        # Open user private chat
│   ├── wait_page.py         # Wait for element
│   ├── type_message.py      # Type message text
│   ├── click_send.py        # Click send button
│   ├── attach_image.py      # Attach image file
│   ├── click_back.py        # Return to main list
│   ├── pause.py             # Timed delay
│   └── conditional_skip.py  # Skip if already messaged
├── ui/
│   ├── index.html           # Main UI shell
│   ├── css/                 # Stylesheets (dark theme)
│   ├── js/history-model.js  # Archive paging model (lazy loading, live merge)
│   ├── js/history-view.js   # Archive renderer (text-only nodes, copy on click)
│   ├── js/history-store.js  # Person History window
│   ├── js/history-db.js     # Full User Database window
│   ├── js/collector-panel.js# Chat Message Collector window
│   ├── js/labels.js         # Label pills + the Label Manager window
│   ├── js/db-panel.js       # DB Connection window
│   ├── js/color-picker.js   # Draggable 5×4 colour popup
│   └── js/                  # stack-dnd, presets-ui, url-toolbar, composer, log…
├── docs/
│   ├── ARCHITECTURE.md      # Full architecture document
│   ├── DOM_SELECTORS.md     # DOM selector reference
│   ├── FIXES_DESIGN_2026-09-04.md   # v1 fix design (presets/URL/debugger)
│   ├── FIXES2_DESIGN_2026-09-04.md  # v2 fix design (exit/restore/custom blocks)
│   ├── AGENT_RULES.md       # Rules every change must obey (undo, empty states…)
│   └── PERSON_LABELS_AND_DB_MANAGEMENT_DESIGN_2026-09-07.md  # this feature set
└── logs/                    # Runtime log files
```
