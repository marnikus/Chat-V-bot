# Chat V Bot

A Python/Qt6 desktop application for automating interactions with the
Virt-Chat web platform (`ru.virt-chat.com`) via Chrome DevTools Protocol.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design document.

See [docs/DOM_SELECTORS.md](docs/DOM_SELECTORS.md) for verified DOM selectors
extracted from the saved HTML pages in this repository.

## Tech Stack

- **GUI Framework:** PySide6 (Qt6) with QWebEngineView
- **Browser Control:** Chrome DevTools Protocol (CDP) via WebSocket
- **Data Storage:** SQLite via aiosqlite
- **Async Runtime:** asyncio + qasync (Qt event loop integration)
- **UI Layer:** HTML5/CSS3/JS with SortableJS for drag-and-drop

## How It Works

1. Connect to an already-open Chrome browser (launched with `--remote-debugging-port=9222`)
2. Parse the user list via simulated scrolling (CDK virtual scroll)
3. Filter users by configurable criteria (gender, registration status)
4. Execute an action stack for each queued user:
   - Click user → Wait for private chat → Type message → Send → Return
5. Track all interactions in SQLite memory

## Repository Contents

| File | Description |
|------|-------------|
| `Вирт чат.html` | Saved main chat page (user list) for DOM analysis |
| `Вирт чат privat.html` | Saved private chat page for DOM analysis |
| `docs/ARCHITECTURE.md` | Full architecture and design document |
| `docs/DOM_SELECTORS.md` | Verified DOM selector reference |
| `requirements.txt` | Python dependencies |

## Status

📐 **Design Phase** — Architecture documentation complete, no code implementation yet.
