/* ═══════════════════════════════════════════════════════════════
   stack-dnd.js — Action Stack editor (blocks, config, run controls)
   Reordering is handled by the bundled StackDrag engine (stack-drag.js)
   Features:
   - Undo/Redo history (up to 100 steps, persisted)
   - Enable/Disable toggle per block
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const BUILTIN_BLOCKS = [
  { block_id:'CUSTOM_FIND',    name:'Find & Click',     icon:'🔎',
    defaults:{custom_name:'', selector:"div[role='tab'].tab-item", label_selector:'p.chat-title', match_text:'', click_enabled:true, click_selector:'', highlight_enabled:true, confirm_pause_ms:700, highlight_ms:1200, pre_delay_ms:500, enabled:true},
    labels:{custom_name:'Block name (shown in stack & logs)',
            selector:'① Element to find — the clickable box (CSS)',
            label_selector:'② Separate text element inside it to confirm (CSS)',
            match_text:'Text it must contain (empty = first match)',
            click_enabled:'Click after found',
            click_selector:'Or click this inner element instead (CSS, optional)',
            highlight_enabled:'Visual confirmation — 🟥 red outline on found, 🟧 orange on click target',
            confirm_pause_ms:'Pause after found, to eyeball the red outline (ms)',
            highlight_ms:'How long each outline stays visible (ms)',
            pre_delay_ms:'Pre-delay (ms)',
            enabled:'Enabled (on/off toggle bar)'} },
  { block_id:'CLICK_MAIN_TAB', name:'Click Main Tab',   icon:'🏠',
    defaults:{selector:"div[role='tab'].tab-item", child_selector:"p.chat-title", tab_name:'Гостиная', highlight_enabled:true, confirm_pause_ms:700, pre_delay_ms:500, enabled:true},
    labels:{selector:'Tab element selector', child_selector:'Child text selector', tab_name:'Tab name (text match)', highlight_enabled:'Visual confirmation outlines', confirm_pause_ms:'Pause after found (ms)', pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'SCROLL_PARSE',   name:'Scroll & Parse',    icon:'📜',
    defaults:{max_scrolls:50, scroll_pause_ms:800, scroll_delta_y:300,
              viewport_selector:'cdk-virtual-scroll-viewport.users-list-viewport',
              load_timeout_ms:2500, stall_threshold:3, min_new_users:1,
              person_selector:'user-item', nick_selector:'.primary-text',
              highlight_enabled:true, highlight_ms:900, confirm_pause_ms:500,
              purge_rejected:true, scroll_only:false,
              filter_female:'yes', filter_registered:'no', filter_guest:'yes',
              filter_anonymous:'no', pre_delay_ms:300, enabled:true},
    options:{filter_female:['any','yes','no'], filter_registered:['any','yes','no'],
             filter_guest:['any','yes','no'], filter_anonymous:['any','yes','no']},
    labels:{max_scrolls:'Max scrolls (safety cap)',
            scroll_pause_ms:'Pause after each scroll (ms)',
            scroll_delta_y:'Scroll step (px)',
            viewport_selector:'Scroll viewport (CSS)',
            load_timeout_ms:'Max wait for lazy load (ms)',
            stall_threshold:'Scrolls with no new people = end',
            min_new_users:'Finish after N new un-messaged (0 = all)',
            person_selector:'Person row selector (CSS)',
            nick_selector:'Nickname element inside (CSS)',
            highlight_enabled:'🟢 Highlight each detected person',
            highlight_ms:'Highlight duration (ms)',
            confirm_pause_ms:'Pause after detecting a person (ms)',
            purge_rejected:'🗑 Remove people that fail the filter',
            scroll_only:'🔎 Only scroll, no people adding (find existing un-messaged person)',
            filter_female:'① Female', filter_registered:'② Registered',
            filter_guest:'③ Guest', filter_anonymous:'④ Anonymous',
            pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'CONDITIONAL_SKIP',name:'If Messaged → Skip',icon:'🔀', defaults:{enabled:true}, labels:{enabled:'Enabled'} },
  { block_id:'CLICK_USER',     name:'Click User',        icon:'👤',
    defaults:{selector:'user-item', label_selector:'.primary-text',
              click_selector:'.user-container',
              tab_selector:"div[role='tab'].tab-item",
              tab_title_selector:'p.chat-title', verify_new_tab:true,
              tab_pause_ms:800, highlight_enabled:true, confirm_pause_ms:700,
              pre_delay_ms:1000, enabled:true},
    labels:{selector:'Person row selector (CSS)',
            label_selector:'Nickname element inside (CSS)',
            click_selector:'Element to click inside (CSS)',
            tab_selector:'Chat tab selector (for verification)',
            tab_title_selector:'Tab title element (CSS)',
            verify_new_tab:'Confirm a new tab opened',
            tab_pause_ms:'Pause after click, before check (ms)',
            highlight_enabled:'Visual confirmation outlines',
            confirm_pause_ms:'Pause after found (ms)',
            pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'WAIT_PAGE_LOAD', name:'Wait for Page',     icon:'⏳',
    defaults:{target_selector:"textarea[placeholder='Сообщение']",timeout_ms:5000,pre_delay_ms:200, enabled:true},
    labels:{target_selector:'Target CSS selector',timeout_ms:'Timeout (ms)',pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'TYPE_MESSAGE',   name:'Type Message',      icon:'⌨️',
    defaults:{message:'',typing_speed_ms:30,pre_delay_ms:500, enabled:true},
    labels:{message:'Message text (use {{nick}})',typing_speed_ms:'Typing speed (ms)',pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'CLICK_SEND',     name:'Click Send',        icon:'📨',
    defaults:{selector:"button[type='submit']",
              fallback_selector:'button:has(mat-icon)', fallback_text:'send',
              highlight_enabled:true, confirm_pause_ms:700, pre_delay_ms:300,
              enabled:true},
    labels:{selector:'Send button selector (CSS)',
            fallback_selector:'Fallback button selector (CSS)',
            fallback_text:'Fallback icon text',
            highlight_enabled:'Visual confirmation outlines',
            confirm_pause_ms:'Pause after found (ms)',
            pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'ATTACH_IMAGE',   name:'Attach Image',      icon:'🖼️',
    defaults:{folder_path:'',file_pattern:'*.jpg',pre_delay_ms:500, enabled:true},
    labels:{folder_path:'Image folder path',file_pattern:'File pattern',pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'CLICK_BACK',     name:'Return to Main',    icon:'🔙',
    defaults:{selector:"div[role='tab'].tab-item", child_selector:"p.chat-title", tab_name:'Гостиная', highlight_enabled:true, confirm_pause_ms:700, pre_delay_ms:800, enabled:true},
    labels:{selector:'Tab element selector', child_selector:'Child text selector', tab_name:'Tab name', highlight_enabled:'Visual confirmation outlines', confirm_pause_ms:'Pause after found (ms)', pre_delay_ms:'Pre-delay (ms)', enabled:'Enabled'} },
  { block_id:'PAUSE',          name:'Custom Pause',      icon:'⏸️',
    defaults:{duration_ms:1000, enabled:true},
    labels:{duration_ms:'Duration (ms)', enabled:'Enabled'} },
];

const StackDnD = {
  stack: [],
  selectedIdx: -1,
  customBlocks: [],       // reusable Find & Click presets: [{name, block, updated_at}]
  _inited: false,
  _running: false,
  _runningIdx: -1,
  _paused: false,
  _restoring: false,
  _snapshotTimer: null,

  // ── History (Feature #1) ─────────────────────────────────────
  history: [],
  historyIndex: -1,
  MAX_HISTORY: 100,
  _isRestoringHistory: false,
  _historySaveTimer: null,

  init() {
    if (this._inited) return;
    this._inited = true;
    this._initDefaultStack();
    this._renderStack();
    this._setupAddMenu();
    this._setupButtons();
    this._setupKeyboardReorder();
    this._setupHistoryButtons();
    this.updateHistoryButtons();
  },

  _initDefaultStack() {
    this.stack = [
      { block_id:'CLICK_MAIN_TAB', pre_delay_ms:500, selector:"div[role='tab'].tab-item", child_selector:"p.chat-title", tab_name:'Гостиная', enabled:true },
      { block_id:'SCROLL_PARSE',   pre_delay_ms:300, max_scrolls:50, scroll_pause_ms:800, enabled:true },
      { block_id:'CONDITIONAL_SKIP',pre_delay_ms:0, enabled:true },
      { block_id:'CLICK_USER',     pre_delay_ms:1000, enabled:true },
      { block_id:'WAIT_PAGE_LOAD', pre_delay_ms:200, target_selector:"textarea[placeholder='Сообщение']", timeout_ms:5000, enabled:true },
      { block_id:'TYPE_MESSAGE',   pre_delay_ms:500, message:'', typing_speed_ms:30, enabled:true },
      { block_id:'CLICK_SEND',     pre_delay_ms:300, enabled:true },
      { block_id:'CLICK_BACK',     pre_delay_ms:800, selector:"div[role='tab'].tab-item", child_selector:"p.chat-title", tab_name:'Гостиная', enabled:true },
    ];
  },

  // ── History helpers ──────────────────────────────────────────
  _deepCopy(obj) {
    try {
      return JSON.parse(JSON.stringify(obj));
    } catch (e) {
      // fallback shallow
      if (Array.isArray(obj)) return obj.map(x => ({...x}));
      return {...obj};
    }
  },

  _normalizeBlock(b) {
    if (!b || typeof b !== 'object') return null;
    const nb = {...b};
    if (!('enabled' in nb) || nb.enabled === undefined || nb.enabled === null) {
      nb.enabled = true;
    } else {
      nb.enabled = !!nb.enabled;
    }
    if (typeof nb.pre_delay_ms !== 'number') nb.pre_delay_ms = 500;
    return nb;
  },

  _normalizeStack(stack) {
    if (!Array.isArray(stack)) return [];
    return stack.map(b => this._normalizeBlock(b)).filter(Boolean);
  },

  _stacksEqual(a, b) {
    try {
      return JSON.stringify(a) === JSON.stringify(b);
    } catch (e) {
      return false;
    }
  },

  _getCurrentHistoryStack() {
    if (this.historyIndex >=0 && this.historyIndex < this.history.length) {
      return this.history[this.historyIndex];
    }
    return null;
  },

  pushHistory(stack, opts) {
    opts = opts || {};
    if (this._isRestoringHistory || this._restoring) return;
    if (this._running) return;
    const src = stack || this.stack;
    const normalized = this._normalizeStack(src);
    if (!normalized.length && this.stack.length===0) {
      // allow empty history? but still record if needed
    }

    // dedup: if equal to current tip, skip
    const current = this._getCurrentHistoryStack();
    if (current && this._stacksEqual(current, normalized) && !opts.force) {
      return;
    }

    // truncate future if we are not at tip
    if (this.historyIndex < this.history.length - 1) {
      this.history = this.history.slice(0, this.historyIndex + 1);
    }

    this.history.push(this._deepCopy(normalized));
    this.historyIndex = this.history.length - 1;

    // enforce max
    if (this.history.length > this.MAX_HISTORY) {
      const overflow = this.history.length - this.MAX_HISTORY;
      this.history = this.history.slice(overflow);
      this.historyIndex = Math.max(0, this.historyIndex - overflow);
    }

    this.updateHistoryButtons();
    // StackDnD keeps a projection for compatibility, but App owns the only
    // undo timeline shared with sash-grid.
    if (typeof App !== 'undefined' && App.recordGlobal)
      App.recordGlobal('stack', normalized);
    // console.log(`[History] pushed, len=${this.history.length} idx=${this.historyIndex}`);
  },

  canUndo() {
    return this.historyIndex > 0;
  },

  canRedo() {
    return this.historyIndex >=0 && this.historyIndex < this.history.length - 1;
  },

  undo() {
    if (typeof App !== 'undefined' && App.undoGlobal && App.bridge) {
      return App.undoGlobal();
    }
    if (!this.canUndo()) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('⚠ Nothing to undo', 'warn');
      return false;
    }
    this.historyIndex--;
    const prevStack = this._deepCopy(this.history[this.historyIndex]);
    this._isRestoringHistory = true;
    this.setStack(prevStack, {isHistory:true, silent:false});
    this._isRestoringHistory = false;
    this.updateHistoryButtons();
    this.saveHistoryToBackend();
    if (typeof LogConsole !== 'undefined') {
      LogConsole.log(`↩ Undo — restored ${prevStack.length} block(s) (${this.historyIndex+1}/${this.history.length})`, 'info');
    }
    // also tell backend to set last_stack and index
    if (App.bridge) {
      App.bridge.save_stack_history(JSON.stringify(this.history), this.historyIndex);
      App.bridge.snapshot_stack(JSON.stringify(prevStack));
    }
    return true;
  },

  redo() {
    if (typeof App !== 'undefined' && App.redoGlobal && App.bridge) {
      return App.redoGlobal();
    }
    if (!this.canRedo()) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('⚠ Nothing to redo', 'warn');
      return false;
    }
    this.historyIndex++;
    const nextStack = this._deepCopy(this.history[this.historyIndex]);
    this._isRestoringHistory = true;
    this.setStack(nextStack, {isHistory:true, silent:false});
    this._isRestoringHistory = false;
    this.updateHistoryButtons();
    this.saveHistoryToBackend();
    if (typeof LogConsole !== 'undefined') {
      LogConsole.log(`↪ Redo — restored ${nextStack.length} block(s) (${this.historyIndex+1}/${this.history.length})`, 'info');
    }
    if (App.bridge) {
      App.bridge.save_stack_history(JSON.stringify(this.history), this.historyIndex);
      App.bridge.snapshot_stack(JSON.stringify(nextStack));
    }
    return true;
  },

  updateHistoryButtons() {
    if (typeof App !== 'undefined' && App._updateUndoButtons) {
      App._updateUndoButtons();
      return;
    }
    const undoBtn = document.getElementById('undoBtn');
    const redoBtn = document.getElementById('redoBtn');
    if (undoBtn) {
      undoBtn.disabled = !this.canUndo();
      undoBtn.title = this.canUndo() ? `Undo (Ctrl+Z) — ${this.historyIndex}/${this.history.length-1} steps` : 'Nothing to undo';
    }
    if (redoBtn) {
      redoBtn.disabled = !this.canRedo();
      redoBtn.title = this.canRedo() ? `Redo (Ctrl+Y) — ${this.historyIndex+1}/${this.history.length-1}` : 'Nothing to redo';
    }
  },

  saveHistoryToBackend() {
    // Retained as a no-op compatibility hook. App.recordGlobal() persists
    // every stack edit in the single global history immediately.
  },

  loadHistoryFromState(state) {
    if (!state) return;
    let hist = state.stack_history;
    let idx = state.stack_history_index;
    if (Array.isArray(hist) && hist.length) {
      // normalize each stack
      this.history = hist.map(s => this._normalizeStack(s));
      this.historyIndex = typeof idx === 'number' ? idx : this.history.length - 1;
      // clamp
      if (this.historyIndex < 0) this.historyIndex = 0;
      if (this.historyIndex >= this.history.length) this.historyIndex = this.history.length - 1;
      this.updateHistoryButtons();
      // console.log(`[History] loaded from state: ${this.history.length} entries, idx ${this.historyIndex}`);
    } else {
      // if no history but we have last_stack, seed history with it
      const lastStack = state.last_stack;
      if (Array.isArray(lastStack) && lastStack.length) {
        const norm = this._normalizeStack(lastStack);
        this.history = [this._deepCopy(norm)];
        this.historyIndex = 0;
        this.updateHistoryButtons();
        this.saveHistoryToBackend();
      }
    }
  },

  _setupHistoryButtons() {
    const undoBtn = document.getElementById('undoBtn');
    const redoBtn = document.getElementById('redoBtn');
    if (undoBtn) {
      undoBtn.addEventListener('click', () => App.undoGlobal());
    }
    if (redoBtn) {
      redoBtn.addEventListener('click', () => App.redoGlobal());
    }
  },

  // ── display helpers ──────────────────────────────────────────
  _meta(blockId) {
    return BUILTIN_BLOCKS.find(a => a.block_id === blockId) || { name: blockId, icon:'?' };
  },

  _displayName(b) {
    const meta = this._meta(b.block_id);
    if (b.custom_name && String(b.custom_name).trim()) return String(b.custom_name).trim();
    return meta.name;
  },

  _findDesc(b) {
    const s = String(b.selector || '').trim();
    const ls = String(b.label_selector || '').trim();
    const mt = String(b.match_text || '').trim();
    const box = s || '?';
    let search;
    if (ls && mt) search = `Find “${mt}” in ${ls} within ${box}`;
    else if (ls) search = `Find the first ${ls} within ${box}`;
    else if (mt) search = `Find “${mt}” in ${box}`;
    else search = `Find ${box}`;
    let act;
    if (!b.click_enabled) act = '→ check only (no click)';
    else if (b.click_selector && String(b.click_selector).trim()) {
      act = `→ click ${String(b.click_selector).trim()} inside`;
    } else {
      act = '→ click the found box';
    }
    const dis = b.enabled === false ? ' [OFF]' : '';
    return `${search} ${act}${dis}`;
  },

  _summary(b) {
    if (b.block_id === 'CUSTOM_FIND') return this._findDesc(b);
    const parts = [];
    for (const [k, v] of Object.entries(b)) {
      if (['block_id','pre_delay_ms','enabled'].includes(k)) continue;
      if (k === 'custom_name') { parts.push(`name=\"${v}\"`); continue; }
      if (k === 'click_enabled') { parts.push(v ? 'click=on' : 'click=off'); continue; }
      if (k === 'click_selector' && !v) continue;
      parts.push(`${k}=${String(v).substring(0, 24)}`);
    }
    const base = parts.join(' · ') || `delay: ${b.pre_delay_ms || 0}ms`;
    return b.enabled === false ? `${base} · OFF` : base;
  },

  // ── custom Find & Click presets ──────────────────────────────
  setCustomBlocks(list) {
    this.customBlocks = Array.isArray(list)
      ? list.map((c) => ({ ...c, block: c.block ? { ...c.block } : {} }))
      : [];
    this._refreshSaveLabel();
  },

  _refreshSaveLabel() {
    const btn = document.getElementById('saveCustomBlockBtn');
    const actions = document.getElementById('customBlockActions');
    if (!btn || !actions || actions.classList.contains('hidden')) return;
    const block = this.stack[this.selectedIdx];
    if (!block || block.block_id !== 'CUSTOM_FIND') return;
    const name = block.custom_name ? String(block.custom_name).trim() : '';
    const exists = !!name && this.customBlocks.some((c) => {
      const b = (c && c.block) || {};
      return String(c.name || '') === name || String(b.custom_name || '') === name;
    });
    const lbl = btn.querySelector('[data-label]');
    if (lbl) lbl.textContent = exists ? `Update preset “${name}”` : 'Save as new preset';
  },

  addBlockConfig(config) {
    if (!config || typeof config !== 'object' || !config.block_id) return;
    const c = { ...config };
    if (typeof c.pre_delay_ms !== 'number') c.pre_delay_ms = 500;
    if (!('enabled' in c)) c.enabled = true;
    else c.enabled = !!c.enabled;
    this.stack.push(c);
    this._renderStack();
    this.pushHistory();
    this.notifyEdited();
  },

  _renderStack() {
    const list = document.getElementById('stackList');
    if (!this.stack.length) {
      list.innerHTML = '<div class=\"stack-empty\">Drag blocks here or click + to add</div>';
      this._attachDrag();
      return;
    }
    list.innerHTML = this.stack.map((b, i) => {
      const meta = this._meta(b.block_id);
      const title = this._esc(this._displayName(b));
      const summary = this._esc(this._summary(b));
      const sel = i === this.selectedIdx ? ' active' : '';
      const run = i === this._runningIdx && this._running ? ' block-running' : '';
      const disabled = b.enabled === false ? ' disabled' : '';
      const checked = b.enabled !== false ? 'checked' : '';
      return `<div class=\"stack-item${sel}${run}${disabled}\" data-idx=\"${i}\">
        <label class=\"toggle-switch\" title=\"${b.enabled===false ? 'Enable' : 'Disable'} this block (skipped when off)\">
          <input type=\"checkbox\" data-toggle=\"${i}\" ${checked}>
          <span class=\"toggle-slider\"></span>
        </label>
        <span class=\"drag-handle\" title=\"Drag to reorder\">⠿</span>
        <span class=\"block-pos\">${i + 1}</span>
        <span class=\"block-icon\">${meta.icon}</span>
        <div class=\"block-info\">
          <div class=\"block-name\">${title}${b.enabled===false ? ' <span class=\"off-badge\">OFF</span>' : ''}</div>
          <div class=\"block-summary\">${summary}</div>
        </div>
        <span class=\"block-remove\" data-remove=\"${i}\" title=\"Remove block\">✕</span>
      </div>`;
    }).join('');

    // click to select / remove (delegated once per render)
    list.querySelectorAll('.stack-item').forEach(el => {
      el.addEventListener('click', (ev) => {
        if (typeof StackDrag !== 'undefined' && StackDrag.dragging) return;
        // ignore toggle clicks for selection
        if (ev.target.closest('.toggle-switch')) return;
        const rm = ev.target.closest('[data-remove]');
        if (rm) {
          ev.stopPropagation();
          this.removeBlock(parseInt(rm.dataset.remove, 10));
          return;
        }
        this.selectBlock(parseInt(el.dataset.idx, 10));
      });
    });

    // toggle handlers
    list.querySelectorAll('input[data-toggle]').forEach(inp => {
      inp.addEventListener('change', (ev) => {
        ev.stopPropagation();
        const idx = parseInt(inp.dataset.toggle, 10);
        if (idx >=0 && idx < this.stack.length) {
          this.stack[idx].enabled = inp.checked;
          this._renderStack();
          // if selected block is this one, refresh config panel to show enabled state
          if (this.selectedIdx === idx) {
            this._showConfig(idx);
          }
          this.pushHistory();
          this.notifyEdited();
          const name = this._displayName(this.stack[idx]);
          if (typeof LogConsole !== 'undefined') {
            LogConsole.log(inp.checked ? `✅ Enabled “${name}”` : `⏸ Disabled “${name}” — will be skipped`, inp.checked ? 'success' : 'warn');
          }
        }
      });
      // prevent drag when interacting with toggle
      inp.addEventListener('mousedown', (ev) => ev.stopPropagation());
      inp.addEventListener('click', (ev) => ev.stopPropagation());
    });

    this._attachDrag();
  },

  _esc(s) {
    const d = document.createElement('div');
    d.textContent = s === null || s === undefined ? '' : String(s);
    return d.innerHTML;
  },

  _attachDrag() {
    const list = document.getElementById('stackList');
    if (!list || typeof StackDrag === 'undefined') return;
    StackDrag.attach({
      container: list,
      itemSelector: '.stack-item',
      handleSelector: null,
      ignoreSelector: '[data-remove], input, textarea, select, button, .toggle-switch, .toggle-slider',
      labelOf: (i) => {
        const b = this.stack[i];
        if (!b) return '';
        return this._displayName(b);
      },
      onReorder: (from, to) => this.moveBlock(from, to),
    });
  },

  moveBlock(from, to) {
    if (from === to) return;
    if (from < 0 || from >= this.stack.length) return;
    to = Math.max(0, Math.min(this.stack.length - 1, to));
    const name = this._displayName(this.stack[from]);

    const item = this.stack.splice(from, 1)[0];
    this.stack.splice(to, 0, item);

    if (this.selectedIdx === from) this.selectedIdx = to;
    else if (this.selectedIdx > from && this.selectedIdx <= to) this.selectedIdx--;
    else if (this.selectedIdx < from && this.selectedIdx >= to) this.selectedIdx++;

    if (this._runningIdx === from) this._runningIdx = to;
    else if (this._runningIdx > from && this._runningIdx <= to) this._runningIdx--;
    else if (this._runningIdx < from && this._runningIdx >= to) this._runningIdx++;

    this._renderStack();
    const list = document.getElementById('stackList');
    if (list && typeof StackDrag !== 'undefined') {
      StackDrag.flashLanded(list, '.stack-item', to);
    }
    if (typeof LogConsole !== 'undefined') {
      LogConsole.log(`↕ Moved “${name}” ${from + 1} → ${to + 1}`, 'info');
    }
    this.pushHistory();
    this.notifyEdited();
  },

  _setupKeyboardReorder() {
    document.addEventListener('keydown', (e) => {
      // One global undo/redo timeline covers both the stack and the grid.
      if ((e.ctrlKey || e.metaKey) && !e.altKey) {
        if (e.target && e.target.closest && e.target.closest('#blockConfigForm')) return;
        const key = (e.key || '').toLowerCase();
        if (key === 'z') {
          e.preventDefault();
          App.undoGlobal();
          return;
        }
        if (key === 'y') {
          e.preventDefault();
          App.redoGlobal();
          return;
        }
      }

      if (!e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
      const tag = (document.activeElement && document.activeElement.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      const i = this.selectedIdx;
      if (i < 0 || i >= this.stack.length) return;
      const to = e.key === 'ArrowUp' ? i - 1 : i + 1;
      if (to < 0 || to >= this.stack.length) return;
      e.preventDefault();
      this.moveBlock(i, to);
    });
  },

  _setupAddMenu() {
    const btn = document.getElementById('addBlockBtn');
    const menu = document.getElementById('addBlockMenu');
    if (!btn || !menu) return;
    const open = (e) => {
      e.stopPropagation();
      menu.classList.toggle('hidden');
      if (!menu.classList.contains('hidden')) {
        this._renderMenu(menu);
        const rect = btn.getBoundingClientRect();
        menu.style.top = (rect.bottom + 4) + 'px';
        menu.style.left = (rect.left + 4) + 'px';
      }
    };
    btn.addEventListener('click', open);
    document.addEventListener('click', () => menu.classList.add('hidden'));
  },

  _renderMenu(menu) {
    let html = '';
    if (this.customBlocks.length) {
      html += '<div class=\"add-menu-section\">Custom blocks</div>';
      html += this.customBlocks.map((c, ci) => {
        const blk = c.block || {};
        const icon = '🔎';
        const label = blk.custom_name || c.name || 'Custom block';
        return `<div class=\"menu-item\" data-custom=\"${ci}\">
          <span class=\"mi-icon\">${icon}</span> ${label}
        </div>`;
      }).join('');
      html += '<div class=\"add-menu-section\">Built-in blocks</div>';
    }
    html += BUILTIN_BLOCKS.map(b =>
      `<div class=\"menu-item\" data-block=\"${b.block_id}\">
        <span class=\"mi-icon\">${b.icon}</span> ${b.name}
      </div>`
    ).join('');
    menu.innerHTML = html;
    menu.querySelectorAll('.menu-item[data-block]').forEach(el => {
      el.addEventListener('click', () => {
        const bid = el.dataset.block;
        const meta = this._meta(bid);
        this.addBlockConfig({ block_id: bid, pre_delay_ms: 500, ...(meta.defaults || {}) });
        menu.classList.add('hidden');
      });
    });
    menu.querySelectorAll('.menu-item[data-custom]').forEach(el => {
      el.addEventListener('click', () => {
        const c = this.customBlocks[parseInt(el.dataset.custom)];
        if (c && c.block) this.addBlockConfig(c.block);
        menu.classList.add('hidden');
      });
    });
  },

  _setupButtons() {
    const runBtn = document.getElementById('runBtn');
    if (runBtn) runBtn.addEventListener('click', () => {
      if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
      if (!this.stack.length) { LogConsole.log('⚠ Stack is empty — add blocks first', 'warn'); return; }
      const enabledCount = this.stack.filter(b => b.enabled !== false).length;
      if (enabledCount === 0) { LogConsole.log('⚠ All blocks are disabled — nothing to run', 'warn'); return; }
      this._running = true;
      this._runningIdx = -1;
      this._paused = false;
      document.getElementById('runBtn').disabled = true;
      document.getElementById('pauseBtn').disabled = false;
      document.getElementById('stopBtn').disabled = false;
      App.bridge.run_stack(JSON.stringify(this.stack));
      LogConsole.log('▶ Stack execution started', 'success');
    });
    const pauseBtn = document.getElementById('pauseBtn');
    if (pauseBtn) pauseBtn.addEventListener('click', () => {
      if (!App.bridge) return;
      const btn = document.getElementById('pauseBtn');
      if (this._paused) {
        App.bridge.resume_stack();
        this._paused = false;
        btn.title = 'Pause';
        btn.querySelector('.material-icons').textContent = 'pause';
        LogConsole.log('▶ Resumed', 'success');
      } else {
        App.bridge.pause_stack();
        this._paused = true;
        btn.title = 'Resume';
        btn.querySelector('.material-icons').textContent = 'play_arrow';
        LogConsole.log('⏸ Paused — click again to resume', 'warn');
      }
    });
    const stopBtn = document.getElementById('stopBtn');
    if (stopBtn) stopBtn.addEventListener('click', () => {
      if (App.bridge) App.bridge.stop_stack();
    });

    const saveBtn = document.getElementById('saveStackBtn');
    if (saveBtn) saveBtn.addEventListener('click', () => {
      if (!this.stack.length) {
        LogConsole.log('⚠ Stack is empty — nothing to save', 'warn');
        return;
      }
      if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
      PresetsUI.promptName('Save stack as preset', 'e.g. My Campaign',
        'Save', (name) => {
          App.bridge.save_stack_preset(name, JSON.stringify(this.stack));
        });
    });

    const loadBtn = document.getElementById('loadStackBtn');
    if (loadBtn) loadBtn.addEventListener('click', () => {
      if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
      App.bridge.list_stack_presets((json) => {
        PresetsUI.setStackPresets(json);
        PresetsUI.toggleStackPicker(document.getElementById('loadStackBtn'));
      });
    });
  },

  notifyEdited() {
    if (this._running || this._restoring || this._isRestoringHistory || !App.bridge) return;
    clearTimeout(this._snapshotTimer);
    this._snapshotTimer = setTimeout(() => {
      if (!this._running && App.bridge) {
        App.bridge.snapshot_stack(JSON.stringify(this.stack));
      }
    }, 800);
  },

  setStack(blocks, opts) {
    if (!Array.isArray(blocks)) return;
    opts = opts || {};
    const prev = this._restoring;
    if (opts.silent) this._restoring = true;
    // normalize enabled
    this.stack = blocks.map((b) => {
      const nb = {...b};
      if (!('enabled' in nb)) nb.enabled = true;
      else nb.enabled = !!nb.enabled;
      return nb;
    });
    this.selectedIdx = -1;
    this._runningIdx = -1;
    this._renderStack();
    const panel = document.getElementById('blockConfigPanel');
    if (panel) panel.classList.add('hidden');
    if (opts.silent) {
      this._restoring = prev;
    } else {
      if (!opts.isHistory) {
        this.pushHistory(this.stack, {force: opts.forceHistory});
      }
      this.notifyEdited();
    }
  },

  refreshPresets() {
    if (typeof PresetsUI !== 'undefined' && App.bridge) {
      App.bridge.list_stack_presets((json) => PresetsUI.setStackPresets(json));
    }
  },

  setRunning(val) {
    this._running = val;
    this._paused = false;
    if (!val) this._runningIdx = -1;
    this._renderStack();
    if (!val) {
      const runBtn = document.getElementById('runBtn');
      if (runBtn) runBtn.disabled = false;
      const pauseBtn = document.getElementById('pauseBtn');
      if (pauseBtn) {
        pauseBtn.disabled = true;
        pauseBtn.title = 'Pause';
        const ic = pauseBtn.querySelector('.material-icons');
        if (ic) ic.textContent = 'pause';
      }
      const stopBtn = document.getElementById('stopBtn');
      if (stopBtn) stopBtn.disabled = true;
    }
  },

  setRunningBlock(idx) {
    this._runningIdx = idx;
    if (!this._running) this._running = true;
    const list = document.getElementById('stackList');
    if (!list) return;
    list.querySelectorAll('.stack-item').forEach((el) => {
      const i = parseInt(el.dataset.idx);
      el.classList.toggle('block-running', i === idx && idx >= 0);
    });
  },

  selectBlock(idx) {
    this.selectedIdx = idx;
    this._renderStack();
    this._showConfig(idx);
  },

  removeBlock(idx) {
    const name = this.stack[idx] ? this._displayName(this.stack[idx]) : '';
    this.stack.splice(idx, 1);
    if (this.selectedIdx >= this.stack.length) this.selectedIdx = this.stack.length - 1;
    this._renderStack();
    this.pushHistory();
    this.notifyEdited();
    if (typeof LogConsole !== 'undefined' && name) {
      LogConsole.log(`🗑 Removed “${name}”`, 'warn');
    }
  },

  _configKeys(block, meta) {
    const byKey = {};
    const entries = Object.keys(block);
    entries.forEach((k) => { byKey[k] = block[k]; });
    const order = meta.defaults ? Object.keys(meta.defaults) : [];
    const ordered = [];
    order.forEach((k) => { if (k in byKey && k !== 'block_id') ordered.push(k); });
    entries.forEach((k) => { if (k !== 'block_id' && !ordered.includes(k)) ordered.push(k); });
    return ordered;
  },

  _showConfig(idx) {
    const panel = document.getElementById('blockConfigPanel');
    const form = document.getElementById('blockConfigForm');
    const block = this.stack[idx];
    if (!block) { panel.classList.remove('has-block'); panel.classList.add('hidden'); return; }
    panel.classList.remove('hidden');
    // Marks the panel as populated so its empty-state hint hides.
    panel.classList.add('has-block');
    const meta = this._meta(block.block_id);
    const labels = meta.labels || {};
    const isConstructor = block.block_id === 'CUSTOM_FIND';
    const icon = meta.icon || '';
    const safeName = this._esc(this._displayName(block));
    let html = `<div class="form-row form-row--head">
        <label>Block</label><span style="font-weight:600">${icon} ${safeName}</span>
      </div>`;
    if (isConstructor) {
      html += `<p class="form-hint">Configurable search-and-click constructor:
        field ① finds the clickable element (the box / rectangle);
        field ② is the separate element inside it whose text confirms the
        match. Give it a name, then save it as a preset for reuse.</p>`;
    }
    const keys = this._configKeys(block, meta);
    for (const key of keys) {
      if (key === 'block_id') continue;
      const val = block[key];
      const labelText = labels[key] || key;
      const safeVal = String(val).replace(/"/g, '&quot;');
      const choices = (meta.options && meta.options[key]) || null;
      if (typeof val === 'boolean') {
        if (key === 'enabled') {
          // On/Off toggle bar: a disabled block stays in the stack but is
          // skipped at run time.
          html += `<div class="form-row form-row-check form-row-enabled">
            <label>${labelText} — On/Off toggle bar (skipped when off)</label>
            <label class="toggle-switch"><input data-key="${key}" type="checkbox" ${val ? 'checked' : ''}><span class="toggle-slider"></span></label>
          </div>`;
        } else {
          html += `<div class="form-row form-row-check">
            <label>${labelText}</label>
            <input data-key="${key}" type="checkbox" ${val ? 'checked' : ''}>
          </div>`;
        }
      } else if (choices) {
        // tri-state / enumerated setting -> dropdown
        const opts = choices.map((o) => {
          const sel = String(val) === String(o) ? ' selected' : '';
          return `<option value="${this._esc(o)}"${sel}>${this._esc(o)}</option>`;
        }).join('');
        html += `<div class="form-row">
          <label>${labelText}</label>
          <select data-key="${key}">${opts}</select>
        </div>`;
      } else {
        const inputType = typeof val === 'number' ? 'number' : 'text';
        const rowCls = isConstructor ? 'form-row form-row--stack' : 'form-row';
        html += `<div class="${rowCls}">
          <label>${labelText}</label>
          <input data-key="${key}" value="${safeVal}" type="${inputType}">
        </div>`;
      }
    }
    form.innerHTML = html;
    // NOTE: must include select[data-key] — the tri-state filter dropdowns
    // are <select>, and binding only inputs would silently drop their edits.
    form.querySelectorAll('input[data-key], select[data-key]').forEach(inp => {
      const handler = () => {
        const k = inp.dataset.key;
        if (inp.tagName === 'SELECT') block[k] = inp.value;
        else if (inp.type === 'checkbox') block[k] = inp.checked;
        else block[k] = inp.type === 'number' ? Number(inp.value) : inp.value;
        this._renderStack();
        this.pushHistory();
        this.notifyEdited();
        if (k === 'enabled') {
          const name = this._displayName(block);
          if (typeof LogConsole !== 'undefined') {
            LogConsole.log(block.enabled ? `✅ Enabled “${name}”` : `⏸ Disabled “${name}” — will be skipped`, block.enabled ? 'success' : 'warn');
          }
        }
      };
      inp.addEventListener('change', handler);
      // also listen to input for text to update summary live? but history on change only
    });
    document.getElementById('closeConfigBtn').onclick = () => {
      panel.classList.add('hidden');
      panel.classList.remove('has-block');
    };

    const actions = document.getElementById('customBlockActions');
    if (block.block_id === 'CUSTOM_FIND' && App.bridge) {
      actions.classList.remove('hidden');
      const btn = document.getElementById('saveCustomBlockBtn');
      btn.onclick = () => this._saveBlockPreset(block);
      this._refreshSaveLabel();
    } else {
      actions.classList.add('hidden');
    }
  },

  _saveBlockPreset(block) {
    if (!App.bridge) return;
    const finish = () => {
      this._renderStack();
      this._showConfig(this.selectedIdx);
      this.pushHistory();
      this.notifyEdited();
    };
    const useName = (name) => {
      block.custom_name = name;
      App.bridge.save_custom_block(name, JSON.stringify(block));
      finish();
    };
    if (block.custom_name && String(block.custom_name).trim()) {
      useName(String(block.custom_name).trim());
    } else {
      PresetsUI.promptName('Save block as preset (also used as the block name)',
        'e.g. Find Settings Button', 'Save', useName);
    }
  },
};

document.addEventListener('DOMContentLoaded', () => StackDnD.init());
