# Fix Design — Preset Save/Load, URL Parse Preset, Step Debugger

**Date:** 2026-09-04
**Status:** Implemented & verified (see Acceptance Checks below + test results)
**Scope:** BUG #1 (Preset Save/Load), FEATURE #2 (URL Parse Preset), BUG #3 (Debugger/Logging)

---

## 1. Root-Cause Analysis (from code audit)

### BUG #1 — Preset Save/Load is Broken

Code paths involved:

| File | Current behavior | Problem |
|------|------------------|---------|
| `ui/js/stack-dnd.js` `saveStackBtn` | `prompt(name)` → `bridge.save_stack_preset(name)` | Only the **name** is sent. The visible stack the user is editing is **never** transmitted. |
| `backend/bridge.py` `_save_preset` | stores `self._engine.get_stack()` | The engine's stack is only populated on **Run** (`run_stack` → `engine.load_stack`). Saving before a run stores `[]`; after a run stores the last-run copy, not the edited stack. |
| `ui/js/stack-dnd.js` `loadStackBtn` | `bridge.load_stack_preset(name)` then `setTimeout(300ms)` + `get_stack_json` | Fragile async race; preset contents may not be reflected; no list UI exists at all, so the user can never see what was saved. |
| `ui/js/composer.js` template buttons | only `LogConsole.log(...)` | Save/Load Template are fake — nothing persisted. |

**Fix contract**

1. Save must transmit the **full current UI stack** to the backend: `save_stack_preset(name, stack_json)`.
2. Presets are stored persistently in SQLite (`stacks` table) so that *close → reopen → load* works.
3. The UI shows saved presets as an always-visible list of **small clickable chip buttons** in the Action Stack panel; the folder button opens a picker list with **Load / Delete** for each preset.
4. Loading a preset restores the full stack (block order + every per-block setting) into the editor **and** the engine, synchronously via the slot return value — no `setTimeout` polling.
5. Same store pattern fixes Message Template save/load (real persistence + chips).

### FEATURE #2 — URL Parse Preset

**Missing:** no URL field, no URL presets, no URL→tab matching.

**Fix contract**

1. A compact **URL toolbar** below the app header: URL input + "Auto-Connect" button + saved **URL preset chips** (click a chip → it auto-runs the match/connect). New presets can be added from the input (`+`), removed via chip `×`; stored in `config.json` (survives restart).
2. Backend URL matching (`backend/tab_matcher.py`, pure & unit-testable):
   - Parse/normalize the query (strip protocol, lower-case, handle paths, plain keywords).
   - Score every open Chrome tab: exact URL > hostname+path > hostname > keyword substring (title+URL).
   - Return best matches; JS auto-selects the best tab in the dropdown **and connects to it**, logging the decision.
3. No tab matches → clear error log telling the user to open the site / refresh tabs.

### BUG #3 — No Debugger / Logging

**Missing:** element-search level detail is written only to `logging` (file/console, invisible in the app); the UI log console only receives one coarse line per block (`🏠 Click Main Tab → ok`) and nothing about element search success/failure or clickability.

**Fix contract**

1. **Structured DOM probe** (new `backend/dom_probe.py`) — every click-style action runs one JS probe that returns a JSON diagnostic: how many nodes the selector matched, whether a text-matching element was **found**, whether it is **visible / disabled / clickable**, whether the click **succeeded**, plus the first candidate elements for debugging.
2. **Live step reporting** — `BaseAction.execute(user, cdp, engine)` gains an optional reporter; each action streams detail lines (via a new `engine.debug_msg` signal → bridge → UI log console) such as:
   - `🔍 Search [tab item selector] for "Гостиная" → 12 node(s) scanned`
   - `✅ Tab found — clickable: yes — clicked`
   - `❌ Failed to find element: no tab with text "Гостиная"` (+ candidate list)
3. **Step lifecycle + highlight** — engine emits `step_started(index, block_id, nick)`; UI marks the running stack item; log shows `▶ Step 3/8 …` and final `✓/✗` per step with timing.
4. **Persistent run trace** — every run cycle writes a JSONL trace to `logs/trace_<run_id>.jsonl` (per step: user, block, status, detail lines, duration) so issues can be traced after the run; the path is announced in the log console.
5. `wait_page` reports per-attempt probes (throttled) + final timeout; `type_message`/`click_send`/`attach_image`/`scroll_parse` all report their element search and failure reasons with the same vocabulary.

---

## 2. Module / File Map

### New backend modules

| File | Responsibility |
|------|----------------|
| `backend/preset_store.py` | SQLite store for stack presets + message templates (sync `sqlite3`, WAL, busy timeout). Methods: `save_stack/load_stack/list_stacks/delete_stack`, `save_template/load_template/list_templates/delete_template`. |
| `backend/dom_probe.py` | Builds the JS probe expression; helpers to interpret probe JSON into log lines (`found`, `clickable`, `clicked`, candidates). |
| `backend/tab_matcher.py` | Pure URL→tab matching/scoring (no I/O) — unit-testable. |

### Backend edits

| File | Change |
|------|--------|
| `backend/bridge.py` | Slots: `save_stack_preset(name, stack_json)`, `list_stack_presets()` (returns JSON), `load_stack_preset(name)` (returns JSON + loads engine), `delete_stack_preset(name)`; template equivalents; URL preset config slots; `find_tab_by_url(query)` emits `tab_match_result`; connect `engine.debug_msg` → `log_message` with real levels; `engine.step_started` passthrough. |
| `backend/action_engine.py` | `debug_msg` signal; `step_started` signal; `report(msg, level)` method with current-step context; per-step timing & status; JSONL run trace writer; clearer phase logs (parse → queue → per-user). |
| `backend/config_manager.py` | Default `url_presets` (virt-chat chat/root); helpers `get_list`/`save`. |
| `backend/message_injector.py` | Accept optional `report` callback; probe-based detail for `type_message` and `click_send`. |
| `backend/media_handler.py` | Accept optional `report`; detail on folder/file-input search. |
| `backend/scroll_parser.py` | Optional `log_cb` for per-scroll progress + "viewport not found". |

### Actions edits (all)

`base_action.py` + `click_main_tab.py`, `click_back.py`, `click_user.py`, `wait_page.py`, `type_message.py`, `click_send.py`, `attach_image.py`, `pause.py`, `scroll_parse.py`, `conditional_skip.py`:

- New signature `execute(user_nick, cdp, engine=None)`; every action reports detailed success/failure lines through `engine.report(...)` while keeping existing return codes (`OK/FAIL/SKIP`) so the engine logic is unchanged.

### UI edits

| File | Change |
|------|--------|
| `ui/index.html` | URL toolbar row; preset chip container + picker markup in Action Stack panel; template chip row in composer bar; Clear button in Log panel header; include `url-toolbar.js` / `presets-ui.js`. |
| `ui/css/layout.css`, `ui/css/stack.css` | Styles for URL toolbar, chips, preset picker, running-step highlight. |
| `ui/js/stack-dnd.js` | Send full stack on save; render/refresh preset chips + picker; `setRunningBlock(idx)` highlight; remove `setTimeout` polling. |
| `ui/js/composer.js` | Real template preset save/load via backend + chips. |
| `ui/js/app.js` | Connect new signals (`tab_match_result`, `step_started`, …); init preset/template/URL UI after bridge ready. |
| `ui/js/criteria-editor.js` | Fix broken inline handler `CriteriaEditor addCriterion()` → `CriteriaEditor.addCriterion()`. |
| `ui/js/log-console.js` | Keep levels, add `clear` wiring. |

### Docs
- `README.md` — updated usage (presets chips, URL auto-connect, debugger).
- This design doc kept in `docs/` as the record of the new structure.

---

## 3. Interface Contracts (new/changed)

### Preset store (SQLite `chatbot.db`, tables `stacks`, `templates`)

```python
class PresetStore:
    def save_stack(self, name: str, blocks: list[dict]) -> None            # upsert
    def load_stack(self, name: str) -> list[dict] | None
    def list_stacks(self) -> list[dict]     # [{name, blocks_count, updated_at}]
    def delete_stack(self, name: str) -> bool
    def save_template(self, name: str, body: str) -> None                  # upsert
    def load_template(self, name: str) -> str | None
    def list_templates(self) -> list[dict]
    def delete_template(self, name: str) -> bool
```

### DOM probe JS result

```jsonc
{
  "query": "div[role='tab'].tab-item",   // selector used
  "total": 12,                            // nodes matched by selector
  "found": true,                          // an element satisfied text match
  "index": 3, "text": "Гостиная",
  "visible": true, "disabled": false,
  "clickable": true, "clicked": true,
  "clicked_target": "div[role='tab'].tab-item",
  "candidates": [ { "index":0, "text":"Гостиная", "visible":true, "clickable":true }, ... ],
  "error": null
}
```

### Tab matcher

```python
def best_matches(query: str, tabs: list[TabInfo], top_n: int = 5) -> list[dict]
# each: {title, url, ws_url, score, kind}  kind ∈ {url_exact, url_path, host, keyword}
```

### Engine reporting API (used by actions)

```python
# engine (or None) is passed as 3rd arg to BaseAction.execute
engine.report(message: str, level: str = "info")   # level ∈ info|success|warn|error
```

---

## 4. Acceptance Checks

1. **Presets:** edit stack → Save (name) → chip appears → close app → reopen → chip still there → click chip (or folder → Load) → stack identical (order + settings). DB `stacks` row contains the full block list.
2. **URL preset:** with Chrome open on `ru.virt-chat.com/chat`, click the preset chip (or paste the URL) → matching tab auto-selected & connected, green status, log line with matched title/URL.
3. **Debugger:** run a stack → log console shows per-block detail (`search → found/failed`, `clickable: yes/no`, click outcome), running block highlighted in the stack, final per-step statuses with timings, and `logs/trace_<id>.jsonl` written with the full step-by-step trace.
