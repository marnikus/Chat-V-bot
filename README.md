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
Drag blocks from the **+ Add** menu into the stack area, or click them to add:
- **Click Main Tab** — switch to a chat room tab
- **Find Element** — generic search + click block (choose any CSS selector, optional text, and whether to click after it is found). Saves reusable element presets
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

### Message Composer
Type your message in the bottom composer area. Use `{{nick}}` to insert the
user's nickname automatically.

### Set Filters (Criteria)
Click the ✏️ edit button in the Filters sidebar to set criteria:
- **MUST HAVE** — only message users matching these classes (e.g. `registered`)
- **MUST NOT HAVE** — skip users with these classes (e.g. `guest`, `anonymous`)

### Run
1. Click **▶ Run** in the stack header
2. The app will parse users → filter by criteria → execute the stack for each user
3. Use **⏸ Pause** and **⏹ Stop** at any time
4. Progress is shown in the **Log Console** at the bottom

### Save / Load
- **Save Stack** / **Load Stack** — open the Stack Presets panel. It shows saved presets as a list with **Load** / **Delete**. Saving stores the **full action stack list**, so a preset is restored exactly as-built.
- **Element Presets** — in any **Find Element** block's config panel you can save the current selector + click options under a name (e.g. `Find Setting Button`) and load/delete it later for quick reuse.
- **URL Presets** — in the header, pick or save a URL pattern (e.g. `ru.virt-chat.com`). On Connect the matching Chrome tab is auto-selected automatically.
- **Save Template** / **Load Template** — save and restore message templates

### Debugger / Logging
Every step is traced in the Log Console:
- each **search** logs success/failure and how many elements were found,
- after finding an element it logs whether the element was **clickable** and whether it was clicked,
- the final **result of each stack step** (`ok` / `fail` / `skip`) is shown along with the block index.

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
│   └── js/                  # Frontend logic (stack, table, criteria, composer, log)
├── docs/
│   ├── ARCHITECTURE.md      # Full architecture document
│   └── DOM_SELECTORS.md     # DOM selector reference
└── logs/                    # Runtime log files
```
