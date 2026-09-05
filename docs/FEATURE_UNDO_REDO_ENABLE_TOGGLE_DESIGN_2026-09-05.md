# Feature Design: Undo/Redo History + Enable/Disable Toggle for Action Blocks
**Date:** 2026-09-05
**Branch:** arena/01a0722f-chat-v-bot
**Status:** Design Complete → Implementation

---

## 1. Problem Analysis

### 1.1 Current Behavior
- **Storable values:** All settings, presets, and last session state live in single `config.json` via `ConfigManager`. Key path: `state.last_stack` holds live stack snapshot, `stack_presets` holds named presets.
- **Stack editing:** `ui/js/stack-dnd.js` owns `StackDnD.stack` array. Every edit calls `notifyEdited()` → debounced `bridge.snapshot_stack(JSON)` → `ConfigManager.set_state(last_stack=blocks)` → saves to disk. No history.
- **Preset load:** `bridge.load_stack_preset(name)` → `engine.load_stack(blocks)` + `set_state(last_stack=blocks, last_stack_preset=name)` + emits `stack_loaded` → UI `setStack(blocks)`. Overwrites custom settings irreversibly.
- **Action execution:** `backend/action_engine.py` `ActionEngine.load_stack()` builds `BaseAction` instances from dicts, `execute()` iterates sequentially. No concept of disabled block.

### 1.2 Requirements Recap
**Feature #1 — Undo/Redo History:**
- Auto-record every change to storable values (action stack) as user makes them.
- Undo/Redo buttons, up to 100 records (title says 20, requirement says 100 → implement 100 with constant).
- Undo must work after loading preset — return to previous custom settings.
- History must persist across sessions (storable).

**Feature #2 — Enable/Disable Toggle:**
- On/Off toggle bar per Action Block.
- When off, block skipped during execution but remains in stack.
- Enabled/disabled state storable and persists across sessions and preset saves.

---

## 2. Design: Undo/Redo History

### 2.1 Data Model
Extend `config.json` `state` with two new keys:

```json
{
  "state": {
    "last_stack": [...],
    "last_stack_preset": "",
    "stack_history": [ [block, ...], [block, ...], ... ],  // list of stacks, oldest → newest
    "stack_history_index": 1  // pointer to current position in history
  }
}
```

- `stack_history`: array of deep-copied stacks (each stack = array of block dicts).
- `stack_history_index`: integer 0..len-1 pointing to current stack that matches `last_stack`.
- Max length = 100 (configurable constant `MAX_HISTORY = 100`).
- On overflow, drop oldest entry and adjust index.

### 2.2 Backend Changes

#### `backend/config_manager.py`
- Add defaults: `state.stack_history = []`, `state.stack_history_index = -1`
- No special logic needed; existing `set_state` can handle it.

#### `backend/bridge.py`
New methods:
- `@Slot(result=str) get_stack_history()` → returns JSON `{history: [...], index: N}`
- `@Slot(str) push_stack_history(stack_json)` → called from frontend when stack changes; handles deduplication, truncation, max limit, saves to `config.json`.
- `@Slot(str) save_stack_history(history_json, index)` → bulk save from frontend (for persistence sync).
- Internal helper `_push_history(blocks)` used by `snapshot_stack`, `load_stack_preset`, `save_stack_preset`.

Update existing:
- `snapshot_stack(stack_json)`: after saving `last_stack`, also push to history if changed (avoid duplicate pushes via deep equality check).
- `load_stack_preset(name)`: before overwriting, push current `last_stack` to history (so undo can return), then push loaded stack.
- `save_stack_preset`: also push? No, save doesn't change current stack, but we should ensure history contains current.

History persistence across sessions:
- `get_app_state()` includes `stack_history` and `stack_history_index` in payload → frontend restores on startup.

#### `backend/preset_store.py`
- No changes needed; stack presets already store full blocks including enabled flag (future).

### 2.3 Frontend Changes

#### `ui/js/stack-dnd.js`
Add history subsystem:
```js
history: [],           // array of stacks
historyIndex: -1,      // current position
MAX_HISTORY: 100,
_isRestoringHistory: false,  // guard to avoid pushing when undo/redo sets stack
```

Methods:
- `pushHistory(stack, {force})` — deep copy, dedup (JSON string compare), truncate future if not at tip, push, enforce MAX_HISTORY, update UI buttons, persist via `bridge.save_stack_history`.
- `undo()` — if canUndo, decrement index, setStack(history[index], {isHistory:true, silent:false})? But silent should not push again. So use flag `_isRestoringHistory`.
- `redo()` — increment index, setStack.
- `canUndo()`, `canRedo()`.
- `updateHistoryButtons()` — enable/disable Undo/Redo buttons.
- `loadHistoryFromState(payload)` — called from `restoreSession`.

Integration points:
- `addBlockConfig()`, `removeBlock()`, `moveBlock()`, `_showConfig()` input change, toggle enabled (feature 2) → after `_renderStack()` call `pushHistory()` and `notifyEdited()`.
- `setStack(blocks, opts)` — if `opts.isHistory` is true, don't push; else push. `opts.silent` still used for session restore but history should still be loaded, not pushed.
- `notifyEdited()` — already snapshots; now also ensures history push happens via `pushHistory` (debounced separately? Actually push should be immediate, snapshot debounced).

#### `ui/index.html`
Add Undo/Redo buttons in stack panel header:
```html
<button id="undoBtn" class="btn-icon-sm" title="Undo (Ctrl+Z)"><span class="material-icons">undo</span></button>
<button id="redoBtn" class="btn-icon-sm" title="Redo (Ctrl+Y)"><span class="material-icons">redo</span></button>
```

#### `ui/js/app.js`
- `restoreSession()` — after restoring stack, also restore history: if payload.state.stack_history exists, set `StackDnD.history = payload.state.stack_history`, `historyIndex = payload.state.stack_history_index`.
- If history empty but last_stack exists, seed history with last_stack.
- Call `StackDnD.updateHistoryButtons()`.

#### CSS `ui/css/stack.css`
- Styles for disabled undo/redo buttons (already handled by `:disabled`).
- Maybe add history info.

#### Keyboard shortcuts
- Ctrl+Z → Undo, Ctrl+Y / Ctrl+Shift+Z → Redo (listen in `stack-dnd.js`).

### 2.4 Edge Cases
- Duplicate detection: don't push if new stack JSON equals current history tip.
- Rapid edits: debounce history push? Requirement says auto-record every change. We'll push immediately but also snapshot debounced for disk. To avoid flooding, we can still push on each edit but limit to 100; for config edits (typing in input), push on change event (which fires on blur/enter), not on every keystroke.
- Loading preset: push old stack, then new stack as two steps? Actually requirement: undo after loading preset returns to previous custom settings. So we need to push current before load, then push loaded as new tip. Undo will go back to previous.
- Session restore: if history exists, don't push again.
- Max 100: when exceeding, shift oldest and decrement index accordingly.

---

## 3. Design: Enable/Disable Toggle for Action Blocks

### 3.1 Data Model
Each block dict gets new boolean field `enabled`:
```js
{
  block_id: "CLICK_USER",
  pre_delay_ms: 1000,
  enabled: true,   // default true, false = disabled/skipped
  ...other props
}
```

- Default: true if missing (backward compatibility).
- Stored in `last_stack`, `stack_presets`, `custom_blocks` → automatically persists because those structures store full block dicts.

### 3.2 Backend Changes

#### `actions/base_action.py`
- Add `enabled` attribute:
  ```python
  def __init__(self, pre_delay_ms=500, enabled=True, **kwargs):
      self.pre_delay_ms = pre_delay_ms
      self.enabled = bool(enabled) if enabled is not None else True
      self.config = kwargs
  ```
- `to_dict()` must include `enabled`:
  ```python
  d["enabled"] = getattr(self, "enabled", True)
  ```
- Ensure all subclasses call super().__init__ with enabled (they already use **kw, but explicit handling needed).

#### `backend/action_engine.py`
- `load_stack()`: ensure each block dict has `enabled` default True if missing.
- `_execute_for_user()` loop: before executing block, check `if not getattr(block, 'enabled', True): log skip and continue`
  ```python
  if not getattr(block, 'enabled', True):
      self.debug_msg.emit(f"⏭ Skipped disabled block [{block.block_id}] {block.display_name}", "warn")
      self._tracer.note({"type":"step_skip","reason":"disabled", **self._ctx})
      continue
  ```
- Also skip disabled `SCROLL_PARSE` and `CONDITIONAL_SKIP` handling accordingly.
- Need to ensure standalone detection counts only enabled user-scoped blocks? Simpler: count enabled blocks only for queue logic, but keep existing logic and just skip disabled during execution; empty queue warning should consider enabled blocks.

#### `backend/bridge.py`
- No specific change needed beyond history handling; `snapshot_stack` and preset save/load already handle full block dicts including `enabled`.

### 3.3 Frontend Changes

#### `ui/js/stack-dnd.js`
- `_initDefaultStack()` — add `enabled: true` to each default block.
- `addBlockConfig()` — ensure `c.enabled = c.enabled !== undefined ? c.enabled : true`.
- `_renderStack()` — render toggle bar:
  ```html
  <div class="stack-item ${enabled? '' : ' disabled'}">
    <label class="toggle-switch"><input type="checkbox" data-toggle="${i}" ${enabled?'checked':''}><span class="toggle-slider"></span></label>
    ... existing ...
  </div>
  ```
- Event delegation for toggle: on change, update `stack[i].enabled`, re-render, push history, notifyEdited.
- `_showConfig()` — also show enabled toggle in config panel.
- `setStack()` — normalize enabled field for backward compat.

#### `ui/css/stack.css`
Add toggle switch styles and disabled block styling:
```css
.stack-item.disabled { opacity: 0.5; background: var(--bg-card-disabled); }
.stack-item.disabled .block-name { text-decoration: line-through; }
.toggle-switch { position: relative; width: 36px; height: 20px; }
.toggle-switch input { opacity:0; width:0; height:0; }
.toggle-slider { position:absolute; cursor:pointer; inset:0; background:var(--bg-input); border-radius:999px; transition:.2s; }
.toggle-slider:before { content:""; position:absolute; height:14px; width:14px; left:3px; bottom:3px; background:white; border-radius:50%; transition:.2s; }
input:checked + .toggle-slider { background:var(--accent); }
input:checked + .toggle-slider:before { transform:translateX(16px); }
```

Also add toggle bar container: `.block-toggle` etc.

#### `ui/index.html`
No structural change needed beyond toggle being injected via JS, but ensure header has undo/redo.

### 3.4 Persistence
- `enabled` is part of block dict → saved via `snapshot_stack` → `config.json` `state.last_stack`.
- Preset save: `save_stack_preset` saves full blocks including enabled → persists across preset saves.
- Custom blocks: same.

### 3.5 Execution Semantics
- Disabled blocks are completely skipped: no pre_delay, no execute, no step_started/complete signals.
- Logs show "⏭ Skipped disabled block".
- If all blocks disabled, stack execution completes immediately with warning.

---

## 4. Implementation Order

1. **Backend BaseAction + ConfigManager**
   - Add `enabled` field handling.
   - Add history defaults.

2. **Backend ActionEngine**
   - Skip disabled blocks.

3. **Backend Bridge**
   - Add history get/push/save slots.
   - Update `get_app_state()` to include history.
   - Update `snapshot_stack` and `load_stack_preset` to push history.

4. **Frontend CSS**
   - Add toggle switch styles.
   - Add disabled block styles.
   - Add undo/redo button styles.

5. **Frontend StackDnD**
   - Implement history array, index, push, undo, redo, button updates, keyboard shortcuts.
   - Implement enabled toggle rendering and handling.
   - Ensure all mutation points call pushHistory.

6. **Frontend App + Index.html**
   - Add Undo/Redo buttons.
   - Wire up restoreSession to load history.

7. **Testing**
   - Test toggle: disable block, run stack, check logs show skip.
   - Test preset save/load with disabled states.
   - Test history: edit stack, undo, redo, load preset, undo to return, restart app and check history persists.

---

## 5. Risks & Mitigations
- **Backward compat:** Old config.json without `enabled` → default true. Old history without enabled → normalized.
- **History size:** 100 stacks * avg 8 blocks * ~500 bytes ≈ 400KB, acceptable for config.json.
- **Performance:** Deep copy via JSON parse/stringify is okay for 100 items; use structuredClone if available.
- **Race:** `notifyEdited` debounced, `pushHistory` immediate → ensure both use same stack snapshot.
- **UI clutter:** Toggle must not interfere with drag handle; place left of position badge or right side.

---

## 6. Verification Checklist
- [ ] Undo/Redo buttons visible and functional.
- [ ] Every stack edit creates history entry (add, remove, move, config change, toggle, preset load).
- [ ] History limited to 100.
- [ ] Undo after preset load returns to previous custom settings.
- [ ] History persists after app restart (config.json contains stack_history).
- [ ] Each block shows On/Off toggle bar.
- [ ] Toggling off skips block during execution (log shows skip).
- [ ] Disabled state persists across sessions and preset saves.
- [ ] Existing tests pass.
