# Fix Design v2 — Clean Exit, Session Restore, Single Preset Store, Custom Find/Click Blocks

**Date:** 2026-09-04
**Status:** Implemented & verified (see §5 — Python integration tests + jsdom E2E UI harnesses passed)
**Scope:**
- BUG #1 — App does not terminate on window close
- BUG #2 — App does not restore last session on startup
- Single Preset Storage (one place for all preset parameters)
- CLEANUP — remove dead "Settings" button/modal
- FEATURE — configurable action-block constructor ("Find & Click")

---

## 1. Problem analysis (from code audit)

### BUG #1 — App keeps running in terminal after X

`main.py` runs `loop.run_forever()` where the qasync `QEventLoop.run_forever()`
calls `QApplication.exec()`. Nothing stops the asyncio/Qt loop explicitly and
no `aboutToQuit` handling exists, so the app relies on the implicit
"last-window-closed" quit. Any asyncio task still scheduled (tab discovery,
CDP receive loop, engine) keeps the interpreter alive after the UI thread has
nothing left to show. There is also no graceful shutdown (CDP disconnect,
SQLite close, task cancellation).

**Fix:** explicit lifecycle:
1. `QApplication.setQuitOnLastWindowClosed(False)` — we control shutdown.
2. `MainWindow.closeEvent` → start an async `shutdown()` coroutine
   (cancel asyncio tasks → stop engine → disconnect CDP → close user DB),
   then `app.quit()` (which makes `run_forever()` return).
3. A watchdog `QTimer` (≈3 s) force-exits with `os._exit(0)` if any Qt
   resource (e.g. QtWebEngine) refuses to release — guarantees the terminal
   prompt returns.
4. `sys.exit(...)` in `__main__`.

### BUG #2 — No session restore + storage is fragmented

Presets are currently split across places: stack/template presets in SQLite
(`PresetStore` tables), URL presets in `config.json`, message text only in
memory, nothing remembers the last used URL/preset. On startup the UI always
starts from the default stack and an empty URL field.

**Fix:** one JSON file (`config.json`) is the **single preset + settings
store**. It holds *all* parameters:
`chrome/scroll/delays/ui` (settings), `url_presets`, `custom_blocks`,
`stack_presets`, `template_presets`, and `state`
(`last_url_preset`, `last_stack_preset`, `last_stack` snapshot).
Legacy presets saved in the old SQLite tables are imported once on startup,
then SQLite is no longer used for presets.

On startup the UI asks for the app state once (`get_app_state`) and then:
1. fills the URL field + highlights the **last selected bookmark**
   (chip pre-selection),
2. **auto-connects** through the URL→tab matcher with that URL,
3. restores the **last used stack** (snapshot, or the named preset),
4. restores custom-block + template + URL chips from the same store.

The state is persisted continuously: URL chip clicks / successful
auto-connect store `last_url_preset`; every stack edit (debounced), run, load
and save store `last_stack`/`last_stack_preset`.

### CLEANUP — Settings button

The header gear and the whole settings modal are dead UI (no behavior behind
them). Remove the button, the modal markup, the JS modal functions and the
now-unused `get_settings`/`save_settings` bridge slots. `ConfigManager`
stays — it is the single store used internally.

### FEATURE — Configurable "Find & Click" block

Existing blocks are hardcoded classes with fixed purposes. Users need a
generic, reusable block: find an element by CSS selector, optionally search
for text inside it, optionally click it, give it a custom name, and save it
as a preset for reuse.

New built-in block `CUSTOM_FIND` ("Find & Click", 🔎) with these editable
fields (matching the existing DOM-probe engine so it gets full debugger
reporting for free):

| Field | Meaning | Example |
|---|---|---|
| `custom_name` | name shown in stack/logs | `Find Settings Button` |
| `selector` | CSS selector of the element to find (the clickable "rectangle") | `div[role='tab'].tab-item` |
| `label_selector` | CSS selector of the element **inside** whose text is searched | `p.chat-title` |
| `match_text` | text to find inside the element (empty = take first) | `Settings` |
| `click_enabled` | click the element after it is found | `true` |
| `click_selector` | optional different element inside to click (empty = click the found element) | `.settings-btn` |
| `pre_delay_ms` | delay before the action | `500` |

Storage: custom blocks are named presets stored in the same single
`config.json` (`custom_blocks`), rendered as chips ("Custom Blocks") and at
the top of the + Add menu; a config-panel action saves the currently edited
block as a preset and deletes an existing one.

Backend execution uses `build_probe(selector=…, label_selector=…,
match_text=…, click=click_enabled, click_root=…)` from `backend/dom_probe.py`
so element search, clickability and click outcome are reported step by step.

---

## 2. Single-file config schema (`config.json`)

```jsonc
{
  "chrome":   { "...": "..." },          // unchanged engine settings
  "scroll":   { "...": "..." },
  "delays":   { "...": "..." },
  "ui":       { "theme": "dark", "language": "ru" },

  // presets & state — ONE place, one file:
  "url_presets":      [ "https://ru.virt-chat.com/chat", "https://ru.virt-chat.com/" ],
  "stack_presets":    { "My Campaign": { "blocks": [ { "block_id": "CLICK_MAIN_TAB", "...": "..." } ],
                                          "updated_at": "2026-09-04T18:00:00" } },
  "template_presets": { "Hello":        { "body": "Hi {{nick}}!", "updated_at": "..." } },
  "custom_blocks":    [ { "name": "Find Settings Button", "updated_at": "...",
                          "block": { "block_id": "CUSTOM_FIND", "custom_name": "Find Settings Button",
                                     "selector": "div[role='tab'].tab-item", "label_selector": "p.chat-title",
                                     "match_text": "Settings", "click_enabled": true,
                                     "click_selector": "", "pre_delay_ms": 500 } } ],

  "state": {
    "last_url_preset":   "https://ru.virt-chat.com/chat",   // last selected bookmark / successful auto-connect
    "last_stack_preset": "My Campaign",                     // last loaded/saved named preset
    "last_stack":        [ { "block_id": "PAUSE", "...": "..." } ]  // live snapshot of last edited/run stack
  }
}
```

---

## 3. Interface contracts

### ConfigManager (additions)
- `get_copy(*keys, default)` — deep copy of stored/default value.
- `update_named(section, name, value)` / `delete_named(section, name)` —
  used by the JSON preset store.
- `state` helpers: `get_state(key)` / `set_state(**updates)` (always saves).
- new `DEFAULTS` keys: `stack_presets:{}`, `template_presets:{}`,
  `custom_blocks:[]`, `state:{}`.

### PresetStore (rewritten, same public API, JSON-backed)
`PresetStore(config=None)` — if no config passed it creates one for
`config.json`.
- `save_stack(name, blocks)` / `load_stack(name)` / `list_stacks()` /
  `delete_stack(name)`
- `save_template(name, body)` / `load_template(name)` / `list_templates()` /
  `delete_template(name)`
- `import_legacy(db_path="chatbot.db")` — one-time import of SQLite presets
  into the JSON store when the JSON store is empty (keeps previously saved
  presets; SQLite is then unused for presets).

### Bridge (new/removed slots)
- REMOVED: `get_settings`, `save_settings` (dead settings modal).
- ADD `get_app_state() → str` — single JSON: `{url_presets, custom_blocks,
  stack_presets, template_presets, state}`.
- ADD `set_last_url_preset(url)`, `snapshot_stack(stack_json)`.
- ADD `list_custom_blocks()`, `save_custom_block(name, block_json)`,
  `delete_custom_block(name)` + signal `custom_blocks_updated(str)`.
- Preset save/load also record `state.last_stack_preset` /
  `state.last_stack` automatically; `run_stack` snapshots the executed stack.

### Actions
- New `actions/custom_find.py` — `class CustomFind(BaseAction)`,
  `block_id = "CUSTOM_FIND"`, name `"Find & Click"`, icon `"🔎"`.
- `BaseAction.display_name` property → `custom_name` if set, else `name`;
  `to_dict()` never serializes the class `name` (only `custom_name`).
- Engine logs/steps use `display_name`.

### Session restore (JS)
`app.js` calls `get_app_state()` after bridge connect and:
- seeds URL chips, custom-block chips, stack/template chips;
- pre-selects the last URL preset (chip highlight + input value);
- restores `state.last_stack` (or loads `state.last_stack_preset`);
- requests tabs and runs the URL→tab auto-connect once.

---

## 4. File change map

| File | Change |
|---|---|
| `main.py` | close-event shutdown, watchdog exit, aboutToQuit wiring |
| `backend/config_manager.py` | new DEFAULTS, copy/state/named helpers |
| `backend/preset_store.py` | rewrite: JSON single-file store + legacy import |
| `backend/bridge.py` | state/custom-block slots, get_app_state, remove settings slots, wire store to config |
| `actions/custom_find.py` | new CUSTOM_FIND block |
| `actions/base_action.py` | `display_name`, to_dict cleanup |
| `actions/__init__.py` | import new action |
| `backend/action_engine.py` | use `display_name` in step logs |
| `ui/index.html` | remove settings button/modal; add Custom Blocks chips row |
| `ui/js/app.js` | remove settings code; add session restore + custom-block signal |
| `ui/js/stack-dnd.js` | CUSTOM_FIND entry, custom names, boolean inputs, snapshot hooks, add-menu custom section |
| `ui/js/presets-ui.js` | custom-block chips + add/delete |
| `ui/js/url-toolbar.js` | chip pre-selection + last-url persistence |
| `ui/css/*` | chip-selected, config action rows, add-menu group |
| `docs/` | this design doc; README update |

---

## 5. Acceptance checks

1. Close (X) terminates: run app, close window → process exits ≤ ~3 s, clean
   shutdown log.
2. Restart restores: seed `state` in config → start → URL field/chip restored,
   auto-connect attempted (log), last stack visible in the editor.
3. Single store: all presets/settings/state live under one `config.json`;
   old SQLite presets imported once.
4. No Settings gear anywhere in the UI.
5. CUSTOM_FIND: add block → set two selectors + text → name it → run: probe
   reports search/clickability/click. Save as preset → chip + Add-menu entry →
   reuse. × deletes preset.
