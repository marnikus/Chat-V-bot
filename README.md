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

### Find & Click — configurable action block
A generic reusable block that is configured entirely through the UI:
1. Add **🔎 Find & Click** and click it to open its config panel.
2. Two search fields (CSS selectors):
   - **Element to find** — the clickable element (the "rectangle"),
     e.g. `div[role='tab'].tab-item`.
   - **Text element inside** — the element *inside* whose text is searched,
     e.g. `p.chat-title`, plus an optional **text to match** (`Settings`).
3. Tick **Click after found** to click it (or leave it to find-only).
4. Give the block a **custom name** (e.g. "Find Settings Button") — the name
   is shown in the stack and logs.
5. Press **Save Block as Preset** — it becomes a chip under "Custom blocks"
   and an entry at the top of the **+ Add** menu for reuse in other stacks.
   Use **×** on a chip to remove a preset you no longer need.

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
- all preset/template/URL/custom-block chips are restored.

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
