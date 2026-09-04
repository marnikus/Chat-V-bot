# ChatBot Automator — Detailed Architecture Document

**Version:** 1.0.0  
**Date:** 2026-09-04  
**Status:** Design Phase — No Code Implementation Yet

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Repository Audit Findings](#2-repository-audit-findings)
3. [Verified DOM Selectors (from Saved HTML)](#3-verified-dom-selectors)
4. [Module Architecture](#4-module-architecture)
5. [Data Flow Diagrams](#5-data-flow-diagrams)
6. [Module Dependency Map](#6-module-dependency-map)
7. [File Structure & Line Budget](#7-file-structure--line-budget)
8. [Interface Contracts](#8-interface-contracts)
9. [Configuration Schema](#9-configuration-schema)
10. [Database Schema](#10-database-schema)
11. [Error Handling Strategy](#11-error-handling-strategy)
12. [Implementation Order (Milestones)](#12-implementation-order)

---

## 1. Project Overview

A PySide6 (Qt6) desktop application that automates interactions with the
Virt-Chat web platform (`ru.virt-chat.com/chat`) running in an already-open
Google Chrome browser via Chrome DevTools Protocol (CDP).

**Core loop:** Connect to Chrome → Parse user list (scroll simulation) →
Filter users by criteria → Execute action stack (click user → type message →
send → return) → Repeat for all queued users.

---

## 2. Repository Audit Findings

### Current Repository Contents

| File | Description |
|------|-------------|
| `README.md` | Minimal placeholder ("# Chat V bot") |
| `Вирт чат.html` | Saved main chat page (user list view) |
| `Вирт чат privat.html` | Saved private chat view (1-on-1 conversation) |
| `*_files/` directories | CSS, JS bundles, avatar images |

### Key Observations from HTML Analysis

- **Angular 22.0.5** with Material Design (mat-* components)
- **CDK Virtual Scroll** for user list (nodes recycled on scroll)
- **Tabs** use custom `app-tab-scroller` with CDK drag-drop
- **Message form** uses Angular reactive forms with `maxlength=1000`
- **File input** is hidden: `<input id="file" type="file" accept="image/*">`
- **All selectors** below are verified against the actual saved HTML

---

## 3. Verified DOM Selectors (from Saved HTML)

These selectors are **extracted directly from the repository's saved HTML files**
and confirmed to match the live site structure.

### 3.1 User List (Main Chat View)

| Purpose | Selector | Verified Source |
|---------|----------|-----------------|
| Viewport | `cdk-virtual-scroll-viewport.users-list-viewport` | ✓ main HTML |
| Content wrapper | `.cdk-virtual-scroll-content-wrapper` | ✓ main HTML |
| Container item | `container-item` | ✓ main HTML |
| User item | `user-item` > `.user-container` | ✓ main HTML |
| Avatar wrapper | `avatar-item` > `.avatar-wrapper` | ✓ main HTML |
| Female avatar | `.avatar-wrapper.female-avatar` | ✓ main HTML |
| Male avatar | `.avatar-wrapper.male-avatar` | ✓ main HTML |
| Guest avatar | `.avatar-wrapper.guest-avatar` | ✓ main HTML |
| Registered badge | `.badge.registered-badge` | ✓ main HTML |
| Anonymous badge | `.badge.anonymous-badge` | ✓ main HTML |
| Nickname | `.primary-text-line > .primary-text` | ✓ main HTML |
| More button | `.more-button` | ✓ main HTML |
| Search input | `#mat-input-9` (or `input[maxlength="20"]`) | ✓ main HTML |

### 3.2 Chat Area

| Purpose | Selector | Verified Source |
|---------|----------|-----------------|
| Message textarea | `textarea#mat-input-1[placeholder='Сообщение']` | ✓ both HTML |
| Send button | `button[type='submit']` containing `mat-icon` "send" | ✓ both HTML |
| Image button | button containing `mat-icon` with text "image" | ✓ both HTML |
| Emoji button | button containing `mat-icon` "insert_emoticon" | ✓ both HTML |
| Hidden file input | `input#file[type='file']` | ✓ both HTML |
| Message container | `.message-container` | ✓ both HTML |
| Message sender | `.from` (span inside message) | ✓ both HTML |
| Message text | `.message` (span/p inside message) | ✓ both HTML |
| Sent time | `.sent-time` | ✓ both HTML |
| Message status | `.message-status > .sent` | ✓ both HTML |

### 3.3 Tabs (Navigation)

| Purpose | Selector | Verified Source |
|---------|----------|-----------------|
| Tab container | `.tab-scroller-container > .scroll-viewport > .tabs-list` | ✓ both HTML |
| Tab item | `.tab-item` (role="tab") | ✓ both HTML |
| Active tab | `.tab-item.active` | ✓ privat HTML |
| Tab title | `.chat-title` | ✓ both HTML |
| Room icon tab | `mat-icon[data-mat-icon-name='room']` | ✓ both HTML |
| User icon tab | `mat-icon[data-mat-icon-name='user']` | ✓ both HTML |
| Close tab button | `.tab-close-button` | ✓ privat HTML |
| Unread badge | `.unread` (inside chat-title) | ✓ both HTML |

### 3.4 Gender Icons (in Messages)

| Purpose | Selector | Verified Source |
|---------|----------|-----------------|
| Male icon | `mat-icon[data-mat-icon-name='male']` | ✓ both HTML |
| Female icon | `mat-icon[data-mat-icon-name='female']` | ✓ privat HTML |
| Anonymous icon | `mat-icon[data-mat-icon-name='anonymous']` | ✓ both HTML |
| Registered icon | `mat-icon[data-mat-icon-name='registered']` | ✓ main HTML |

### 3.5 Virtual Scroll Spacer

| Purpose | Selector | Verified Source |
|---------|----------|-----------------|
| Spacer (total height) | `.cdk-virtual-scroll-spacer` | ✓ main HTML |
| Content wrapper Y offset | `.cdk-virtual-scroll-content-wrapper` style `translateY` | ✓ main HTML |

---

## 4. Module Architecture

### 4.1 Layer Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                        │
│  PySide6 QMainWindow → QWebEngineView                       │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  HTML/CSS/JS (embedded via QWebChannel)               │  │
│  │  • Dashboard stats  • Action Stack DnD                │  │
│  │  • Criteria editor  • User Memory table               │  │
│  │  • Message composer • Log console                     │  │
│  └───────────────────────┬───────────────────────────────┘  │
│                          │ QWebChannel (JSON messages)       │
├──────────────────────────┼──────────────────────────────────┤
│                    BRIDGE LAYER                              │
│  ┌───────────────────────▼───────────────────────────────┐  │
│  │  bridge.py — Qt↔JS signal routing                     │  │
│  │  • Exposes Python methods to JS                       │  │
│  │  • Emits Qt signals from JS callbacks                 │  │
│  └───────────────────────┬───────────────────────────────┘  │
├──────────────────────────┼──────────────────────────────────┤
│                    BUSINESS LOGIC LAYER                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ cdp_     │ │ scroll_  │ │ criteria_│ │ action_      │   │
│  │ client   │ │ parser   │ │ engine   │ │ engine       │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘   │
│       │             │            │               │           │
│  ┌────▼─────┐ ┌────▼─────┐ ┌────▼─────┐ ┌──────▼───────┐   │
│  │ message_ │ │ media_   │ │ user_    │ │ actions/     │   │
│  │ injector │ │ handler  │ │ memory   │ │ (10 modules) │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                    DATA LAYER                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ SQLite DB    │  │ config.json  │  │ logs/            │  │
│  │ chatbot.db   │  │ Settings     │  │ Daily log files  │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Module Responsibilities

| Module | File | Responsibility | Max Lines |
|--------|------|---------------|-----------|
| **Entry Point** | `main.py` | Qt app init, window setup, startup sequence | ~80 |
| **CDP Client** | `backend/cdp_client.py` | WebSocket connection to Chrome, CDP command send/receive | ~140 |
| **Scroll Parser** | `backend/scroll_parser.py` | Virtual scroll simulation, DOM user extraction | ~130 |
| **Criteria Engine** | `backend/criteria_engine.py` | Filter evaluation against user records | ~90 |
| **User Memory** | `backend/user_memory.py` | SQLite CRUD for users table | ~120 |
| **Action Engine** | `backend/action_engine.py` | Stack execution loop over queued users | ~130 |
| **Message Injector** | `backend/message_injector.py` | CDP textarea value setting with Angular events | ~70 |
| **Media Handler** | `backend/media_handler.py` | Image file injection via DOM.setFileInputFiles | ~80 |
| **Bridge** | `backend/bridge.py` | QWebChannel Python↔JS routing | ~100 |
| **Config Manager** | `backend/config_manager.py` | JSON config load/save/validate | ~60 |
| **Logger** | `backend/logger.py` | Rotating file + console logging | ~50 |

### 4.3 Action Modules (each ≤80 lines)

| Module | File | Block ID |
|--------|------|----------|
| Base Action | `actions/base_action.py` | (abstract) |
| Click Main Tab | `actions/click_main_tab.py` | `CLICK_MAIN_TAB` |
| Scroll Parse | `actions/scroll_parse.py` | `SCROLL_PARSE` |
| Click User | `actions/click_user.py` | `CLICK_USER` |
| Wait Page | `actions/wait_page.py` | `WAIT_PAGE_LOAD` |
| Type Message | `actions/type_message.py` | `TYPE_MESSAGE` |
| Click Send | `actions/click_send.py` | `CLICK_SEND` |
| Attach Image | `actions/attach_image.py` | `ATTACH_IMAGE` |
| Click Back | `actions/click_back.py` | `CLICK_BACK` |
| Pause | `actions/pause.py` | `PAUSE` |
| Conditional Skip | `actions/conditional_skip.py` | `CONDITIONAL_SKIP` |

---

## 5. Data Flow Diagrams

### 5.1 User Parse Flow

```
JS (WebView)                    Python Backend                  Chrome (CDP)
     │                               │                              │
     │  [User clicks "Parse"]        │                              │
     │──────────────────────────────▶│                              │
     │  QWebChannel: start_parse()   │                              │
     │                               │                              │
     │                               │──▶ scroll_parser.parse()     │
     │                               │    │                         │
     │                               │    │  Runtime.evaluate ─────▶│
     │                               │    │  "document.querySelector │
     │                               │    │   ('user-item')..."     │
     │                               │    │                         │
     │                               │    │◀── DOM nodes (JSON) ───│
     │                               │    │                         │
     │                               │    │  extract_user() × N     │
     │                               │    │                         │
     │                               │◀── List[UserRecord]          │
     │                               │                              │
     │                               │──▶ criteria_engine.evaluate()│
     │                               │◀── filtered List[UserRecord] │
     │                               │                              │
     │                               │──▶ user_memory.upsert_many() │
     │                               │    (INSERT or UPDATE)        │
     │                               │                              │
     │◀──────────────────────────────│                              │
     │  QWebChannel: users_updated() │                              │
     │  (JSON array of user records) │                              │
     │                               │                              │
     │  JS: update_table()           │                              │
```

### 5.2 Action Stack Execution Flow

```
JS (WebView)                    Python Backend                  Chrome (CDP)
     │                               │                              │
     │  [User clicks "▶ Run"]        │                              │
     │──────────────────────────────▶│                              │
     │  QWebChannel: run_stack()     │                              │
     │                               │                              │
     │                               │──▶ action_engine.execute()   │
     │                               │    │                         │
     │                               │    │  FOR each queued user:  │
     │                               │    │    FOR each block:      │
     │                               │    │      sleep(pre_delay)   │
     │                               │    │      block.execute() ──▶│
     │                               │    │      CDP commands       │
     │                               │    │◀── result ─────────────│
     │                               │    │                         │
     │                               │    │  mark_user_messaged()   │
     │                               │                              │
     │◀──────────────────────────────│                              │
     │  QWebChannel: step_complete() │                              │
     │  (block_name, user_nick)      │                              │
     │                               │                              │
     │  JS: update_log()             │                              │
     │  JS: update_table_row()       │                              │
```

---

## 6. Module Dependency Map

```
main.py
  ├── backend/bridge.py
  │     └── uses: all backend modules (exposes to JS)
  ├── backend/config_manager.py
  └── backend/logger.py

backend/action_engine.py
  ├── backend/cdp_client.py
  ├── backend/user_memory.py
  └── actions/*.py (all 10 action modules)

backend/scroll_parser.py
  ├── backend/cdp_client.py
  └── backend/criteria_engine.py

backend/criteria_engine.py
  └── (standalone, no backend deps)

backend/user_memory.py
  └── (standalone, uses aiosqlite)

backend/message_injector.py
  └── backend/cdp_client.py

backend/media_handler.py
  └── backend/cdp_client.py

backend/cdp_client.py
  └── (standalone, uses websockets)

actions/base_action.py
  └── backend/cdp_client.py (type hints only)

actions/*.py (each)
  └── actions/base_action.py
  └── backend/cdp_client.py
```

---

## 7. File Structure & Line Budget

```
chatbot-automator/
├── main.py                         #  ~80 lines — Entry point
├── config.json                     #  JSON — Default settings
├── requirements.txt                #  ~10 lines
│
├── backend/
│   ├── __init__.py                 #   ~1 line
│   ├── cdp_client.py               # ~140 lines — CDP WebSocket client
│   ├── scroll_parser.py            # ~130 lines — Virtual scroll + DOM extraction
│   ├── criteria_engine.py          #  ~90 lines — Filter evaluation
│   ├── user_memory.py              # ~120 lines — SQLite user CRUD
│   ├── action_engine.py            # ~130 lines — Stack execution loop
│   ├── message_injector.py         #  ~70 lines — Textarea value setting
│   ├── media_handler.py            #  ~80 lines — Image injection
│   ├── bridge.py                   # ~100 lines — QWebChannel routing
│   ├── config_manager.py           #  ~60 lines — Config load/save
│   └── logger.py                   #  ~50 lines — Logging setup
│
├── actions/
│   ├── __init__.py                 #   ~1 line
│   ├── base_action.py              #  ~50 lines — Abstract base class
│   ├── click_main_tab.py           #  ~60 lines
│   ├── scroll_parse.py             #  ~70 lines
│   ├── click_user.py               #  ~70 lines
│   ├── wait_page.py                #  ~60 lines
│   ├── type_message.py             #  ~70 lines
│   ├── click_send.py               #  ~50 lines
│   ├── attach_image.py             #  ~80 lines
│   ├── click_back.py               #  ~50 lines
│   ├── pause.py                    #  ~30 lines
│   └── conditional_skip.py         #  ~30 lines
│
├── ui/
│   ├── index.html                  # ~400 lines — Main SPA shell
│   ├── css/
│   │   ├── variables.css           #  ~80 lines — Theme tokens
│   │   ├── layout.css              # ~150 lines — Grid system
│   │   ├── stack.css               # ~100 lines — DnD stack styles
│   │   ├── table.css               # ~100 lines — User table styles
│   │   └── composer.css            #  ~60 lines — Message editor styles
│   ├── js/
│   │   ├── app.js                  # ~120 lines — Main init, QWebChannel
│   │   ├── stack-dnd.js            # ~100 lines — SortableJS integration
│   │   ├── user-table.js           # ~120 lines — Reactive user list
│   │   ├── criteria-editor.js      # ~100 lines — Filter management
│   │   ├── composer.js             #  ~80 lines — Message template logic
│   │   └── log-console.js          #  ~60 lines — Log display
│   └── assets/
│       └── icons/                  # Material Icons (woff2)
│
└── logs/
    └── .gitkeep
```

**Total Python:** ~1,460 lines across 23 files  
**Total JS/HTML/CSS:** ~1,350 lines across 12 files  
**Average Python file:** ~91 lines (well under 150-line cap)

---

## 8. Interface Contracts

### 8.1 CDP Client Interface

```python
class CDPClient:
    """Async CDP WebSocket client."""
    
    async def connect(host: str, port: int, tab_id: str) -> None
    async def disconnect() -> None
    async def send_command(method: str, params: dict) -> dict
    async def evaluate(expression: str) -> Any
    async def click_at(x: float, y: float) -> None
    async def mouse_wheel(delta_x: float, delta_y: float, x: float, y: float) -> None
    async def get_element_rect(selector: str) -> Optional[dict]
    async def set_file_input_files(selector: str, files: list[str]) -> None
    
    @property
    def is_connected() -> bool
    
    # Signals (Qt signals emitted on state change)
    # connected, disconnected, error_received
```

### 8.2 User Record

```python
@dataclass
class UserRecord:
    nick: str
    gender: str            # "female" | "male" | "unknown"
    registered: bool
    anonymous: bool
    guest: bool
    first_seen: datetime
    last_seen: datetime
    messaged: bool
    message_count: int
    last_messaged: Optional[datetime]
    notes: str
```

### 8.3 Criterion

```python
@dataclass
class Criterion:
    id: int
    label: str
    enabled: bool
    selector: str          # CSS selector (e.g., ".avatar-wrapper")
    class_name: str        # Class to check (e.g., "female-avatar")
    check_type: str        # "MUST_HAVE_CLASS" | "MUST_NOT_HAVE_CLASS"
```

### 8.4 Action Block

```python
class BaseAction(ABC):
    block_id: str
    name: str
    icon: str
    
    @abstractmethod
    async def execute(self, user: UserRecord, cdp: CDPClient) -> ActionResult
    
    def get_config_schema(self) -> dict  # JSON Schema for config form
```

### 8.5 QWebChannel Bridge Methods (exposed to JS)

```python
class Bridge(QObject):
    # Python → JS signals
    users_updated = Signal(list)       # Full user list refresh
    user_status_changed = Signal(str, str)  # nick, new_status
    step_complete = Signal(str, str)   # block_name, user_nick
    stack_complete = Signal()
    log_message = Signal(str, str)     # level, message
    connection_status = Signal(str)    # "connected"|"disconnected"|"error"
    stats_updated = Signal(dict)       # {total, new, queued, done}
    
    # JS → Python slots
    @Slot(result=str)   def get_tabs(self) -> str  # JSON
    @Slot(str)          def connect_tab(self, tab_id: str)
    @Slot(str)          def run_stack(self, stack_json: str)
    @Slot()             def stop_stack(self)
    @Slot()             def pause_stack(self)
    @Slot()             def resume_stack(self)
    @Slot(str)          def save_criteria(self, criteria_json: str)
    @Slot(str)          def save_message(self, message_text: str)
    @Slot()             def reset_messaged(self)
    @Slot()             def clear_memory(self)
    @Slot(str)          def save_stack_preset(self, name: str)
    @Slot(str)          def load_stack_preset(self, name: str)
    @Slot(result=str)   def get_settings(self) -> str
    @Slot(str)          def save_settings(self, settings_json: str)
```

---

## 9. Configuration Schema

### config.json

```json
{
  "chrome": {
    "host": "127.0.0.1",
    "port": 9222,
    "reconnect_interval_s": 5,
    "connection_timeout_s": 10,
    "auto_reconnect": true
  },
  "scroll": {
    "scroll_delta_y": 300,
    "scroll_pause_ms": 800,
    "stall_threshold": 3,
    "max_scrolls": 50,
    "viewport_selector": "cdk-virtual-scroll-viewport.users-list-viewport"
  },
  "delays": {
    "global_pre_action_ms": 500,
    "global_post_action_ms": 200,
    "page_load_timeout_ms": 5000
  },
  "selectors": {
    "user_item": "user-item",
    "avatar_wrapper": ".avatar-wrapper",
    "badge": ".badge",
    "nickname": ".primary-text-line > .primary-text",
    "main_tab": ".tab-item p.chat-title",
    "message_textarea": "textarea[placeholder='Сообщение']",
    "send_button": "button[type='submit']",
    "image_button_suffix": "mat-icon",
    "file_input": "input#file[type='file']",
    "search_input": "input[maxlength='20']"
  },
  "media": {
    "folder_path": "",
    "file_pattern": "*.jpg",
    "rotation_mode": "sequential"
  },
  "ui": {
    "theme": "dark",
    "language": "ru"
  }
}
```

---

## 10. Database Schema

### Users Table

```sql
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nick            TEXT UNIQUE NOT NULL,
    gender          TEXT DEFAULT 'unknown',
    registered      BOOLEAN DEFAULT 0,
    anonymous       BOOLEAN DEFAULT 0,
    guest           BOOLEAN DEFAULT 0,
    first_seen      DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen       DATETIME DEFAULT CURRENT_TIMESTAMP,
    messaged        BOOLEAN DEFAULT 0,
    message_count   INTEGER DEFAULT 0,
    last_messaged   DATETIME,
    notes           TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_users_nick ON users(nick);
CREATE INDEX IF NOT EXISTS idx_users_messaged ON users(messaged);
```

### Stacks Table

```sql
CREATE TABLE IF NOT EXISTS stacks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    blocks      TEXT NOT NULL,  -- JSON array of block configs
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Criteria Table

```sql
CREATE TABLE IF NOT EXISTS criteria (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    criteria    TEXT NOT NULL,  -- JSON array of criterion objects
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Templates Table

```sql
CREATE TABLE IF NOT EXISTS templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    body        TEXT NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 11. Error Handling Strategy

| Error Scenario | Detection | Recovery | User Notification |
|---------------|-----------|----------|-------------------|
| Chrome not running | HTTP GET `/json/version` fails | Show connect dialog with retry | 🔴 Status indicator |
| Tab closed | `/json/list` missing tab_id | Stop execution, alert user | Modal dialog |
| WebSocket disconnect | `websockets` close event | Auto-reconnect (configurable interval) | 🟡 Reconnecting... |
| Element not found (CDP evaluate returns null) | Check return value | Retry 3× with 500ms backoff, then skip user | Log warning |
| Page load timeout | `WAIT_PAGE_LOAD` exceeds `timeout_ms` | Skip user, continue stack | Log warning |
| Send failed (no DOM change) | Verify textarea cleared after send | Retry once, then skip | Log error |
| Rate limit / CAPTCHA detected | Check for error modals in DOM | STOP all execution immediately | Modal alert (loud) |
| Virtual scroll stall | `stall_threshold` consecutive no-new-user scrolls | End parse, proceed with collected | Log info |
| SQLite write error | Exception catch on DB operations | Log error, continue in-memory | Log error |
| JS bridge error | Exception in @Slot method | Log traceback, send error to JS | Log + UI toast |

---

## 12. Implementation Order (Milestones)

### Phase 1: Foundation (Priority P0)

| Step | Module | Depends On | Description |
|------|--------|-----------|-------------|
| 1.1 | `backend/logger.py` | — | Logging setup |
| 1.2 | `backend/config_manager.py` | logger | Config load/save |
| 1.3 | `backend/cdp_client.py` | — | CDP WebSocket client |
| 1.4 | `backend/user_memory.py` | — | SQLite CRUD |
| 1.5 | `main.py` + `backend/bridge.py` | all above | Qt window + QWebChannel |

### Phase 2: Core Logic (Priority P0)

| Step | Module | Depends On | Description |
|------|--------|-----------|-------------|
| 2.1 | `backend/scroll_parser.py` | cdp_client | User list parsing |
| 2.2 | `backend/criteria_engine.py` | — | Filter evaluation |
| 2.3 | `backend/message_injector.py` | cdp_client | Message sending |
| 2.4 | `actions/base_action.py` | — | Abstract base |
| 2.5 | `actions/click_main_tab.py` | base_action, cdp | Click main room tab |
| 2.6 | `actions/scroll_parse.py` | base_action, scroll_parser | Scroll + parse |
| 2.7 | `actions/click_user.py` | base_action, cdp | Click user in list |
| 2.8 | `actions/wait_page.py` | base_action, cdp | Wait for element |
| 2.9 | `actions/type_message.py` | base_action, injector | Type message |
| 2.10 | `actions/click_send.py` | base_action, cdp | Click send |
| 2.11 | `actions/click_back.py` | base_action, cdp | Return to main |
| 2.12 | `actions/pause.py` | base_action | Simple delay |
| 2.13 | `actions/conditional_skip.py` | base_action | Skip if messaged |
| 2.14 | `backend/action_engine.py` | all actions, user_memory | Stack executor |

### Phase 3: UI (Priority P0-P1)

| Step | Module | Depends On | Description |
|------|--------|-----------|-------------|
| 3.1 | `ui/index.html` + `ui/css/variables.css` | — | Shell + theme |
| 3.2 | `ui/css/layout.css` | — | Grid system |
| 3.3 | `ui/js/app.js` | — | QWebChannel init |
| 3.4 | `ui/js/user-table.js` | app.js | User table rendering |
| 3.5 | `ui/js/stack-dnd.js` | app.js, SortableJS | Drag-and-drop stack |
| 3.6 | `ui/js/criteria-editor.js` | app.js | Criteria UI |
| 3.7 | `ui/js/composer.js` | app.js | Message composer |
| 3.8 | `ui/js/log-console.js` | app.js | Log display |
| 3.9 | `ui/css/stack.css` | — | Stack DnD styles |
| 3.10 | `ui/css/table.css` | — | Table styles |
| 3.11 | `ui/css/composer.css` | — | Composer styles |

### Phase 4: Media & Polish (Priority P1-P2)

| Step | Module | Depends On | Description |
|------|--------|-----------|-------------|
| 4.1 | `actions/attach_image.py` | base_action, cdp | Image attachment |
| 4.2 | `backend/media_handler.py` | cdp_client | File rotation logic |
| 4.3 | Stack save/load | bridge, DB | Preset management |
| 4.4 | Integration testing | all | End-to-end validation |

---

## Appendix A: Angular Component Mapping

From the saved HTML, the Angular app structure is:

| Component | Selector | Purpose |
|-----------|----------|---------|
| AppComponent | `app-root` | Root |
| ChatComponent | `app-chat` | Main chat layout |
| TabScrollerComponent | `app-tab-scroller` | Tab navigation |
| MessagesComponent | `app-messages` | Message list |
| UsersListComponent | `users-list` | User sidebar |
| UserItemComponent | `user-item` | Single user row |
| AvatarItemComponent | `avatar-item` | Avatar with badge |
| MessageFormComponent | `app-message-form` | Text input + buttons |
| EmojiPanelComponent | `app-emoji-panel` | Emoji picker |
| SettingsMenuComponent | `app-settings-menu` | Settings dropdown |

## Appendix B: CDP Commands Used

| CDP Domain | Method | Purpose |
|------------|--------|---------|
| `Runtime` | `evaluate` | Execute JS in page context |
| `DOM` | `enable` | Enable DOM events |
| `Input` | `dispatchMouseEvent` | Click simulation |
| `Input` | `dispatchMouseEvent` (mouseWheel) | Scroll simulation |
| `DOM` | `setFileInputFiles` | File upload bypass |
| `Page` | `enable` | Page lifecycle events |

---

*This document is the single source of truth for implementation planning.
All selectors, schemas, and contracts must be implemented as specified.*
