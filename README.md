# ChatFlow Orchestrator

Desktop automation tool (PySide6 + QWebEngine + Playwright/CDP) that attaches to an
**already-running, logged-in Chrome** session of a web chat app, parses the
virtual-scroll user list, applies filter rules, remembers every user in SQLite,
and executes a drag-and-drop configurable action sequence with human-like pacing.

**Design:** see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — it contains the
verified DOM contract extracted from the saved site snapshots in this repo.

## Quick start (development)

```bat
:: 1. Python 3.11+
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

:: 2. Start Chrome with the debug port.
::    IMPORTANT (Chrome 136+): the flag is IGNORED with the default profile —
::    you MUST pass a separate --user-data-dir. Log in once; the login then
::    persists in that folder, so reuse the same path every time.
::    "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
::        --remote-debugging-port=9222 --user-data-dir="C:\chatflow-chrome"

::    Verify the port is live: open http://127.0.0.1:9222/json/version
::    in that Chrome window — JSON with "webSocketDebuggerUrl" = CDP is up.
::    Then open the chat site in that window and log in manually.

:: 3. Run the app
python -m chatflow.app.main
```

**Settings → Connection:** host `127.0.0.1`, port `9222`, tab URL pattern
`virt-chat.com` (plain substring match; `*` or empty = first open tab).
**Tools → Test Connection** must say "OK … matching tab found" before you RUN.

The app stores its data (SQLite DB, settings, logs) under
`%LOCALAPPDATA%\ChatFlowOrchestrator` on Windows, `~/.local/share/ChatFlowOrchestrator` elsewhere.

Typical flow: **Tools → Test Connection** → configure filter rules & message
composer (bottom panel) → build the sequence (middle panel, drag from the
palette) → **▶ RUN LOOP**. **⏹ STOP** is safe at any time — it finishes the
current action, never kills mid-keystroke.

## Layout

```
chatflow/
  app/       Qt shell: window, tray, QWebEngineView, channel wiring, entry point
  bridge/    QWebChannel API (JS→Python slots) + event forwarding (Python→JS)
  blocks/    one module per action-block executor + registry (11 block types)
  browser/   CDP connect, guarded Playwright ops, watchdog, verified selectors
  core/      data models, settings, event names, logging
  engine/    worker QThread, run task, sequence executor, state machine,
             delays, humanizer
  filters/   rule evaluation (pure)
  memory/    SQLite: users, presets, filter rules, settings, CSV import/export
  parse/     virtual-scroll scroll engine + row extraction
ui/          the web UI (vanilla HTML/CSS/JS, no framework)
tests/       pytest suite — hermetic, no Chrome needed
```

Every Python file is hard-capped at **< 150 lines** (`tests/test_line_budget.py`
enforces it in CI).

## Tests

```
pytest tests/
```

34 tests, all hermetic:

- `test_dom_contract` — pins the verified selectors to the saved site snapshots
- `test_filters` / `test_memory` / `test_state` — pure logic
- `test_executor` / `test_executor_failures` — full dry-runs against a stateful
  fake page (call order, state transitions, requeue/drop-on-failure policy)

## Default sequence (loaded on first start)

🏠 Go to Main Tab → 🔄 Scroll & Parse → 🎯 Pick Next Target → 👤 Click User →
⌨️ Type Message → 📷 Attach Image → 📤 Send → 🚪 Close Tab

## Notes & limitations

- The target site is an Angular app with CDK virtual scroll: rows are recycled
  on scroll, so the bot re-queries the DOM before every action and detects new
  users by nickname set, never by DOM identity.
- Image upload uses the page's hidden `input#file` (`set_input_files`); the
  OS file-chooser path is the automatic fallback.
- A user that fails 3 passes in a row is dropped from the queue and flagged
  `SKIPPED (automation-failed)` — a broken target can never loop the run forever.
- `pyinstaller --windowed` packaging: bundle the `ui/` folder as data
  (`--add-data "ui;ui"`); Playwright is imported but no browser is installed
  (we attach to the user's own Chrome).
