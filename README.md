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

**Windows:**
```cmd
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
```

**macOS:**
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
```

**Linux:**
```bash
google-chrome --remote-debugging-port=9222
```

> ⚠️ **Important:** Close ALL Chrome windows before running this command.
> If Chrome is already running without the debug flag, the flag will be ignored
> and the app won't be able to connect.

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
button always closes and unpins.

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

## Repository Structure

```
├── main.py                  # App entry point
├── requirements.txt         # Python dependencies
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
│   └── js/                  # stack-dnd, presets-ui, url-toolbar, composer, log…
├── docs/
│   ├── ARCHITECTURE.md      # Full architecture document
│   ├── DOM_SELECTORS.md     # DOM selector reference
│   ├── FIXES_DESIGN_2026-09-04.md   # v1 fix design (presets/URL/debugger)
│   └── FIXES2_DESIGN_2026-09-04.md  # v2 fix design (exit/restore/custom blocks)
└── logs/                    # Runtime log files
```
