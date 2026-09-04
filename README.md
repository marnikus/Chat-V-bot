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

### Configure Blocks
Click on any block in the stack to open its **config panel** on the right.
Each block has its own settings (selectors, text, delays, etc.).

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
internet connection.

### Save / Load Presets (full action stack)
- **💾 Save** — name the preset and the **complete stack** (block order + every
  block setting) is stored in `chatbot.db`.
- Every saved preset appears as a small **chip** under "Saved presets" and in
  the **folder picker list** — click either to load it back. Chips survive an
  app restart (close → reopen → click chip → full stack restored).
- **Save Template / Load Template ▾** work the same way for message templates.
- Deletion is confirmed through an in-app dialog (no browser dialogs needed).

### URL Presets (auto-connect by URL)
The toolbar below the header holds a **URL field** and quick-connect presets:
1. Paste a URL or keyword (e.g. `https://ru.virt-chat.com/chat`) or click a chip.
2. Click **Auto-Connect** — the app parses the URL, matches it against every
   open Chrome tab (exact URL → path → host → keyword) and **automatically
   selects and connects** to the best match.
3. Press **+** to store the current URL as a new preset chip, **×** on a chip
   to remove it.

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

Every destructive action asks for confirmation in an in-app dialog first.

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

## Preview the UI without Chrome/Qt (dev aid)

To click through the interface (people list, deletion, drag & drop) without
launching Qt or Chrome:

```bash
python -m http.server 8080 --directory ui
# then open http://localhost:8080/devpreview/
```

`ui/devpreview/` serves the same UI with `mock-bridge.js` standing in for the
Python backend. The shipped `ui/index.html` never references it.

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
│   ├── config_manager.py    # JSON settings manager
│   ├── preset_store.py      # SQLite stack/template preset store
│   ├── dom_probe.py         # DOM probe JS + result interpreter (debugger)
│   ├── tab_matcher.py       # URL → tab matching (URL presets)
│   └── logger.py            # File + console logging
├── actions/
│   ├── base_action.py       # Action base class + registry
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
│   ├── js/                  # Frontend logic (stack, drag engine, table, criteria, composer, log)
│   └── devpreview/          # Browser-only UI preview with a mock backend (dev aid)
├── docs/
│   ├── ARCHITECTURE.md      # Full architecture document
│   ├── DOM_SELECTORS.md     # DOM selector reference
│   └── FIXES_DESIGN_*.md    # Root-cause + design records for each fix round
└── logs/                    # Runtime log files
```
