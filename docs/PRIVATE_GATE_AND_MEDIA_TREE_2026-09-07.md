# Private-chat gate & the readable media tree — 2026-09-07

Fixes for the bug report of 2026-09-07 (screenshot: 1450 messages archived
under «Ански», one of them written by `Макс__Б` in the main room; a GIF shown
as a broken image because the window pointed at
`https://images.virt-chat.com/images/m_%D0%A5%D0%BE…gif`).

Three items were reported. Two were bugs, one turned out to be already
implemented and is only re-verified here.

---

## 1. Wrong private-chat detection → a two-step gate

### What actually went wrong

Two independent holes, both visible in the screenshot:

1. **The agent parsed the whole document.** `document.querySelectorAll(
   'div.message-container')` returns the message nodes of *every* pane the
   site keeps alive — the main room plus each open private tab. Whatever pane
   the user had open, the union was reported to Python.
2. **The push channel trusted nothing.** `Collector.handle_push()` appended
   the pushed lines to `self._nick` — the last partner seen — without
   re-checking the tab, the partner or the authors. Switching from a private
   tab to the main room therefore filed room chatter under that person, which
   is exactly the `Макс__Б` line in «Ански»'s history.

### The gate

Nothing is written unless **both** steps pass, on **every** path that saves
(heartbeat tick, live push, and the `COLLECT_HISTORY` action block):

| Step | Check | Data it uses |
|---|---|---|
| 1 | the conversation contains only two distinct nicks — mine and the partner's | `in_authors` / `out_authors` reported by the agent, or the authors of the pushed records themselves |
| 2 | the ACTIVE tab is a private tab whose title names that same partner | `.tab-item.active` + `mat-icon.chat-type-icon[data-mat-icon-name="user"]` + `p.chat-title` |

Any failure ⇒ **save nothing**, say why in the collector window, and disarm
the push channel until a tick verifies the conversation again.

```
backend/chat_parser.py
    verify_private(state, nick, my_nick, items=None) -> PrivateCheck
        ok reason detail me partner strangers
        reasons: ok | not_private | no_partner | title_mismatch |
                 self_chat | strangers | no_author_data
```

Notes

* **My Nick may be empty.** Outbound lines are identified by the CSS class
  (`my-message-background`), so when exactly one nick wrote the outbound
  lines it is adopted as “me”. Two different outbound authors ⇒ refused.
* **Titles are normalised** (case, inner spacing, the trailing space the site
  puts in `p.chat-title`) and a title that *contains* the nick counts, so an
  unread badge or a status suffix does not break collection.
* **Fail closed.** An agent that cannot report authors (`no_author_data`)
  collects nothing; the collector re-installs an agent older than
  `chat_agent_js.AGENT_VERSION` before it trusts a probe.

### Agent v4 (`backend/js/chat_agent.js`)

* `visiblePane()` groups message nodes by their `.messages-root` /
  `app-messages` ancestor and keeps the pane that is actually on screen
  (`hidden`, `aria-hidden`, `offsetParent` up the chain). `containers()`,
  `walk()`, `slice()` and the observer all work on that pane only.
* `state()` now reports `title`, `authors`, `in_authors`, `out_authors` and
  `panes`; the push payload carries the same fields.
* Every probe calls `reattach()`: if the visible pane changed (the user
  switched tabs), the observer moves with it and the buffer of the old pane
  is dropped rather than re-attributed.

Tests: `tests/test_private_gate.py` (31), `tests/test_private_scope_js.js`
(11).

---

## 2. Media that a human can actually use

### Before

`media_cache/<sha256><ext>` — one flat folder of 64-character names, and the
UI fell back to the remote percent-encoded URL, which renders as a broken
image once the site expires it.

### Now

```
saved_media/
├─ Anski/                 ← Ански
│  ├─ _nick.txt           ← the exact nick, so the folder is self-describing
│  ├─ images/2026-09-07_001.png
│  └─ gifs/2026-09-07_001.gif
└─ Horosho_Vse/           ← Хорошо Все
   └─ images/2026-09-07_001.jpg
```

* **Latin only.** `slugify_nick()` transliterates Cyrillic (`Хорошо Все` →
  `Horosho_Vse`, `Ански` → `Anski`, `Макс__Б` → `Maks__B`), keeps ASCII nicks
  as they are, and appends a 4-hex suffix only when the nick cannot be
  transliterated faithfully (emoji, CJK, punctuation) or hits a Windows
  reserved name. Two nicks that map to the same Latin folder are separated by
  the `_nick.txt` marker + a hash suffix.
* **One folder per conversation**, both directions, because that is what
  “everything I exchanged with Ански” means to the user.
* **Short dated names** `YYYY-MM-DD_NNN.ext`, numbered per day and per
  folder, using the day of the message when known.
* **Absolute paths in the DB** (`media.cache_path`), plus new columns
  `media.owner` and `media.day` (added in place on old databases).
* **The UI shows the file**: `HistoryModel.fileUrl()` turns the stored path
  into `file:///…` (Windows drives and non-ASCII folders included),
  `HistoryView.mediaSrc()` prefers it over the remote URL, and
  `HistoryView.applyMediaPath()` swaps a picture in place when it finishes
  caching (`media_ready`).
* **Copy-paste**: the clipboard now carries the file URL *and* the path text
  *and* (for stills) the pixels, so a GIF can be pasted into a chat as a
  file. `📂 Files` in the Person History toolbar opens the person's folder
  (`Bridge.open_media_folder`).
* **Migration**: `MediaStore.migrate_layout()` moves an old flat cache into
  the tree on the first start; it is idempotent and survives missing files.

Tests: `tests/test_media_layout.py` (21), `tests/test_media_paths_js.js`
(10).

---

## 3. People-list actions in the global undo history — already shipped

Verified, not rewritten: `Bridge._do_delete_one/_do_delete_many/_do_clear/
_do_reset/_do_set_messaged` each snapshot the people rows before and after
and push one `people` entry onto the single global undo timeline, and
`ui/js/user-table.js` deliberately has **no confirmation dialogs** — Ctrl+Z
is the safety net. Covered by `tests/test_people_undo.py` (11 tests,
including `test_no_confirmation_dialogs_on_remove_or_reset`).

---

## Files touched

| File | Change |
|---|---|
| `backend/js/chat_agent.js` | v4: pane scoping, authors, title, observer re-attach |
| `backend/chat_agent_js.py` | `AGENT_VERSION = 4` |
| `backend/chat_parser.py` | `PrivateCheck`, `verify_private()`, `title_matches()`, gate inside `sync_conversation()` |
| `backend/collector.py` | gate on every tick, `_refuse()`, verified push channel |
| `backend/media_store.py` | `slugify_nick()`, person folders, dated names, `owner`/`day`, `migrate_layout()`, `folder_for()` |
| `backend/history_db.py` | `media.owner`, `media.day` + in-place column migration |
| `backend/history_repo.py` | passes the conversation nick and day to the media store |
| `backend/history_service.py` | default `saved_media`, runs the layout migration on init |
| `backend/bridge.py` | `media_folder`, `open_media_folder`, file-aware clipboard |
| `ui/js/history-model.js` | `fileUrl()`, `toRows()`, `media.src` |
| `ui/js/history-view.js` | `mediaSrc()`, `applyMediaPath()` |
| `ui/js/history-store.js` | `onMediaReady()`, `openFolder()` |
| `ui/js/app.js`, `ui/index.html` | `media_ready` wiring, `📂 Files` button |
