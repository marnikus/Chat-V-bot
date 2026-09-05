/* ═══════════════════════════════════════════════════════════════
   stack-dnd.js — Action Stack editor (blocks, config, run controls)
   Reordering is handled by the bundled StackDrag engine (stack-drag.js)
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const BUILTIN_BLOCKS = [
  { block_id:'CUSTOM_FIND',    name:'Find & Click',     icon:'🔎',
    defaults:{custom_name:'', selector:"div[role='tab'].tab-item", label_selector:'p.chat-title', match_text:'', click_enabled:true, click_selector:'', highlight_enabled:true, confirm_pause_ms:700, highlight_ms:1200, pre_delay_ms:500},
    labels:{custom_name:'Block name (shown in stack & logs)',
            selector:'① Element to find — the clickable box (CSS)',
            label_selector:'② Separate text element inside it to confirm (CSS)',
            match_text:'Text it must contain (empty = first match)',
            click_enabled:'Click after found',
            click_selector:'Or click this inner element instead (CSS, optional)',
            highlight_enabled:'Visual confirmation — 🟥 red outline on found, 🟧 orange on click target',
            confirm_pause_ms:'Pause after found, to eyeball the red outline (ms)',
            highlight_ms:'How long each outline stays visible (ms)',
            pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'CLICK_MAIN_TAB', name:'Click Main Tab',   icon:'🏠',
    defaults:{selector:"div[role='tab'].tab-item", child_selector:"p.chat-title", tab_name:'Гостиная', highlight_enabled:true, confirm_pause_ms:700, pre_delay_ms:500},
    labels:{selector:'Tab element selector', child_selector:'Child text selector', tab_name:'Tab name (text match)', highlight_enabled:'Visual confirmation outlines', confirm_pause_ms:'Pause after found (ms)', pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'SCROLL_PARSE',   name:'Scroll & Parse',    icon:'📜',
    defaults:{max_scrolls:50, scroll_pause_ms:800, scroll_delta_y:300,
              viewport_selector:'cdk-virtual-scroll-viewport.users-list-viewport',
              load_timeout_ms:2500, stall_threshold:3, min_new_users:1,
              person_selector:'user-item', nick_selector:'.primary-text',
              highlight_enabled:true, highlight_ms:900, confirm_pause_ms:500,
              purge_rejected:true,
              filter_female:'yes', filter_registered:'no', filter_guest:'yes',
              filter_anonymous:'no', use_panel_filters:false, pre_delay_ms:300},
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
            filter_female:'① Female', filter_registered:'② Registered',
            filter_guest:'③ Guest', filter_anonymous:'④ Anonymous',
            use_panel_filters:'Also apply Filter panel criteria',
            pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'CONDITIONAL_SKIP',name:'If Messaged → Skip',icon:'🔀', defaults:{}, labels:{} },
  { block_id:'CLICK_USER',     name:'Click User',        icon:'👤',
    defaults:{selector:'user-item', label_selector:'.primary-text',
              click_selector:'.user-container',
              tab_selector:"div[role='tab'].tab-item",
              tab_title_selector:'p.chat-title', verify_new_tab:true,
              tab_pause_ms:800, highlight_enabled:true, confirm_pause_ms:700,
              pre_delay_ms:1000},
    labels:{selector:'Person row selector (CSS)',
            label_selector:'Nickname element inside (CSS)',
            click_selector:'Element to click inside (CSS)',
            tab_selector:'Chat tab selector (for verification)',
            tab_title_selector:'Tab title element (CSS)',
            verify_new_tab:'Confirm a new tab opened',
            tab_pause_ms:'Pause after click, before check (ms)',
            highlight_enabled:'Visual confirmation outlines',
            confirm_pause_ms:'Pause after found (ms)',
            pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'WAIT_PAGE_LOAD', name:'Wait for Page',     icon:'⏳',
    defaults:{target_selector:"textarea[placeholder='Сообщение']",timeout_ms:5000,pre_delay_ms:200},
    labels:{target_selector:'Target CSS selector',timeout_ms:'Timeout (ms)',pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'TYPE_MESSAGE',   name:'Type Message',      icon:'⌨️',
    defaults:{message:'',typing_speed_ms:30,pre_delay_ms:500},
    labels:{message:'Message text (use {{nick}})',typing_speed_ms:'Typing speed (ms)',pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'CLICK_SEND',     name:'Click Send',        icon:'📨',
    defaults:{selector:"button[type='submit']",
              fallback_selector:'button:has(mat-icon)', fallback_text:'send',
              highlight_enabled:true, confirm_pause_ms:700, pre_delay_ms:300},
    labels:{selector:'Send button selector (CSS)',
            fallback_selector:'Fallback button selector (CSS)',
            fallback_text:'Fallback icon text',
            highlight_enabled:'Visual confirmation outlines',
            confirm_pause_ms:'Pause after found (ms)',
            pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'ATTACH_IMAGE',   name:'Attach Image',      icon:'🖼️',
    defaults:{folder_path:'',file_pattern:'*.jpg',pre_delay_ms:500},
    labels:{folder_path:'Image folder path',file_pattern:'File pattern',pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'CLICK_BACK',     name:'Return to Main',    icon:'🔙',
    defaults:{selector:"div[role='tab'].tab-item", child_selector:"p.chat-title", tab_name:'Гостиная', highlight_enabled:true, confirm_pause_ms:700, pre_delay_ms:800},
    labels:{selector:'Tab element selector', child_selector:'Child text selector', tab_name:'Tab name', highlight_enabled:'Visual confirmation outlines', confirm_pause_ms:'Pause after found (ms)', pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'PAUSE',          name:'Custom Pause',      icon:'⏸️',
    defaults:{duration_ms:1000},
    labels:{duration_ms:'Duration (ms)'} },
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

  init() {
    if (this._inited) return;      // guard against a double DOMContentLoaded
    this._inited = true;
    this._initDefaultStack();
    this._renderStack();
    this._setupAddMenu();
    this._setupButtons();
    this._setupKeyboardReorder();
  },

  _initDefaultStack() {
    this.stack = [
      { block_id:'CLICK_MAIN_TAB', pre_delay_ms:500, selector:"div[role='tab'].tab-item", child_selector:"p.chat-title", tab_name:'Гостиная' },
      { block_id:'SCROLL_PARSE',   pre_delay_ms:300, max_scrolls:50, scroll_pause_ms:800 },
      { block_id:'CONDITIONAL_SKIP',pre_delay_ms:0 },
      { block_id:'CLICK_USER',     pre_delay_ms:1000 },
      { block_id:'WAIT_PAGE_LOAD', pre_delay_ms:200, target_selector:"textarea[placeholder='Сообщение']", timeout_ms:5000 },
      { block_id:'TYPE_MESSAGE',   pre_delay_ms:500, message:'', typing_speed_ms:30 },
      { block_id:'CLICK_SEND',     pre_delay_ms:300 },
      { block_id:'CLICK_BACK',     pre_delay_ms:800, selector:"div[role='tab'].tab-item", child_selector:"p.chat-title", tab_name:'Гостиная' },
    ];
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

  // Human-readable card description for the configurable constructor block.
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
    return `${search} ${act}`;
  },

  _summary(b) {
    if (b.block_id === 'CUSTOM_FIND') return this._findDesc(b);
    const parts = [];
    for (const [k, v] of Object.entries(b)) {
      if (['block_id','pre_delay_ms'].includes(k)) continue;
      if (k === 'custom_name') { parts.push(`name="${v}"`); continue; }
      if (k === 'click_enabled') { parts.push(v ? 'click=on' : 'click=off'); continue; }
      if (k === 'click_selector' && !v) continue;
      parts.push(`${k}=${String(v).substring(0, 24)}`);
    }
    return parts.join(' · ') || `delay: ${b.pre_delay_ms || 0}ms`;
  },

  // ── custom Find & Click presets ──────────────────────────────
  setCustomBlocks(list) {
    this.customBlocks = Array.isArray(list)
      ? list.map((c) => ({ ...c, block: c.block ? { ...c.block } : {} }))
      : [];
    this._refreshSaveLabel();
  },

  // "Save as new preset" vs "Update preset “name”" depending on whether the
  // currently selected block's name is already stored as a preset.
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

  // insert a configured block (from built-in defaults or a saved preset)
  addBlockConfig(config) {
    if (!config || typeof config !== 'object' || !config.block_id) return;
    const c = { ...config };
    if (typeof c.pre_delay_ms !== 'number') c.pre_delay_ms = 500;
    this.stack.push(c);
    this._renderStack();
    this.notifyEdited();
  },

  _renderStack() {
    const list = document.getElementById('stackList');
    if (!this.stack.length) {
      list.innerHTML = '<div class="stack-empty">Drag blocks here or click + to add</div>';
      this._attachDrag();
      return;
    }
    list.innerHTML = this.stack.map((b, i) => {
      const meta = this._meta(b.block_id);
      const title = this._esc(this._displayName(b));
      const summary = this._esc(this._summary(b));
      const sel = i === this.selectedIdx ? ' active' : '';
      const run = i === this._runningIdx && this._running ? ' block-running' : '';
      return `<div class="stack-item${sel}${run}" data-idx="${i}">
        <span class="drag-handle" title="Drag to reorder">⠿</span>
        <span class="block-pos">${i + 1}</span>
        <span class="block-icon">${meta.icon}</span>
        <div class="block-info">
          <div class="block-name">${title}</div>
          <div class="block-summary">${summary}</div>
        </div>
        <span class="block-remove" data-remove="${i}" title="Remove block">✕</span>
      </div>`;
    }).join('');

    // click to select / remove (delegated once per render)
    list.querySelectorAll('.stack-item').forEach(el => {
      el.addEventListener('click', (ev) => {
        if (typeof StackDrag !== 'undefined' && StackDrag.dragging) return;
        const rm = ev.target.closest('[data-remove]');
        if (rm) {
          ev.stopPropagation();
          this.removeBlock(parseInt(rm.dataset.remove, 10));
          return;
        }
        this.selectBlock(parseInt(el.dataset.idx, 10));
      });
    });
    this._attachDrag();
  },

  _esc(s) {
    const d = document.createElement('div');
    d.textContent = s === null || s === undefined ? '' : String(s);
    return d.innerHTML;
  },

  /* ── FEATURE #6: drag & drop reordering ────────────────────────
     Previously this used SortableJS pulled from a CDN at runtime; on a
     file:// page inside QWebEngineView that request fails silently (no
     onerror handler existed), so reordering never worked offline.
     StackDrag is bundled with the app and needs no network.          */
  _attachDrag() {
    const list = document.getElementById('stackList');
    if (!list || typeof StackDrag === 'undefined') return;
    StackDrag.attach({
      container: list,
      itemSelector: '.stack-item',
      handleSelector: null,                       // whole card is draggable
      ignoreSelector: '[data-remove], input, textarea, select, button',
      labelOf: (i) => {
        const b = this.stack[i];
        if (!b) return '';
        return this._displayName(b);
      },
      onReorder: (from, to) => this.moveBlock(from, to),
    });
  },

  /** Array-move a block and keep selection / config panel in sync. */
  moveBlock(from, to) {
    if (from === to) return;
    if (from < 0 || from >= this.stack.length) return;
    to = Math.max(0, Math.min(this.stack.length - 1, to));
    const name = this._displayName(this.stack[from]);

    const item = this.stack.splice(from, 1)[0];
    this.stack.splice(to, 0, item);

    // keep the selection pointing at the same logical block
    if (this.selectedIdx === from) this.selectedIdx = to;
    else if (this.selectedIdx > from && this.selectedIdx <= to) this.selectedIdx--;
    else if (this.selectedIdx < from && this.selectedIdx >= to) this.selectedIdx++;
    // same for the running highlight
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
    this.notifyEdited();
  },

  /** Keyboard reordering: Alt+↑ / Alt+↓ on the selected block. */
  _setupKeyboardReorder() {
    document.addEventListener('keydown', (e) => {
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

  // ── + Add menu (built-ins + saved custom Find & Click blocks) ─
  _setupAddMenu() {
    const btn = document.getElementById('addBlockBtn');
    const menu = document.getElementById('addBlockMenu');
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
      html += '<div class="add-menu-section">Custom blocks</div>';
      html += this.customBlocks.map((c, ci) => {
        const blk = c.block || {};
        const icon = '🔎';
        const label = blk.custom_name || c.name || 'Custom block';
        return `<div class="menu-item" data-custom="${ci}">
          <span class="mi-icon">${icon}</span> ${label}
        </div>`;
      }).join('');
      html += '<div class="add-menu-section">Built-in blocks</div>';
    }
    html += BUILTIN_BLOCKS.map(b =>
      `<div class="menu-item" data-block="${b.block_id}">
        <span class="mi-icon">${b.icon}</span> ${b.name}
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
    document.getElementById('runBtn').addEventListener('click', () => {
      if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
      if (!this.stack.length) { LogConsole.log('⚠ Stack is empty — add blocks first', 'warn'); return; }
      this._running = true;
      this._runningIdx = -1;
      this._paused = false;
      document.getElementById('runBtn').disabled = true;
      document.getElementById('pauseBtn').disabled = false;
      document.getElementById('stopBtn').disabled = false;
      App.bridge.run_stack(JSON.stringify(this.stack));
      LogConsole.log('▶ Stack execution started', 'success');
    });
    document.getElementById('pauseBtn').addEventListener('click', () => {
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
    document.getElementById('stopBtn').addEventListener('click', () => {
      if (App.bridge) App.bridge.stop_stack();
    });

    // BUG #1 fix: save the FULL visible stack (order + every setting)
    document.getElementById('saveStackBtn').addEventListener('click', () => {
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

    // Load button opens the saved-presets picker list (small Load buttons)
    document.getElementById('loadStackBtn').addEventListener('click', () => {
      if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
      App.bridge.list_stack_presets((json) => {
        PresetsUI.setStackPresets(json);
        PresetsUI.toggleStackPicker(document.getElementById('loadStackBtn'));
      });
    });
  },

  // ── session snapshot (BUG #2) ────────────────────────────────
  notifyEdited() {
    if (this._running || this._restoring || !App.bridge) return;
    clearTimeout(this._snapshotTimer);
    this._snapshotTimer = setTimeout(() => {
      if (!this._running && App.bridge) {
        App.bridge.snapshot_stack(JSON.stringify(this.stack));
      }
    }, 800);
  },

  // ── programmatic stack replacement (preset load / session) ───
  setStack(blocks, opts) {
    if (!Array.isArray(blocks)) return;
    opts = opts || {};
    const prev = this._restoring;
    if (opts.silent) this._restoring = true;
    this.stack = blocks.map((b) => ({ ...b }));
    this.selectedIdx = -1;
    this._runningIdx = -1;
    this._renderStack();
    const panel = document.getElementById('blockConfigPanel');
    if (panel) panel.classList.add('hidden');
    if (opts.silent) this._restoring = prev; else this.notifyEdited();
  },

  refreshPresets() {
    if (typeof PresetsUI !== 'undefined' && App.bridge) {
      App.bridge.list_stack_presets((json) => PresetsUI.setStackPresets(json));
    }
  },

  // ── run-state helpers (debugger highlight) ───────────────────
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
    this.stack.splice(idx, 1);
    if (this.selectedIdx >= this.stack.length) this.selectedIdx = this.stack.length - 1;
    this._renderStack();
    this.notifyEdited();
  },

  // Deterministic config-field order: follow the block's declared default
  // key order, then any extra keys that were loaded from saved configs.
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
    if (!block) { panel.classList.add('hidden'); return; }
    panel.classList.remove('hidden');
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
        html += `<div class="form-row form-row-check">
          <label>${labelText}</label>
          <input data-key="${key}" type="checkbox" ${val ? 'checked' : ''}>
        </div>`;
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
    form.querySelectorAll('input[data-key], select[data-key]').forEach(inp => {
      inp.addEventListener('change', () => {
        const k = inp.dataset.key;
        if (inp.tagName === 'SELECT') block[k] = inp.value;
        else if (inp.type === 'checkbox') block[k] = inp.checked;
        else block[k] = inp.type === 'number' ? Number(inp.value) : inp.value;
        this._renderStack();
        this.notifyEdited();
      });
    });
    document.getElementById('closeConfigBtn').onclick = () => panel.classList.add('hidden');

    // Save / Update preset action (only for the configurable block)
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
