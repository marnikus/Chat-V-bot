/* ═══════════════════════════════════════════════════════════════
   stack-dnd.js — SortableJS-based drag-and-drop action stack
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const BUILTIN_BLOCKS = [
  { block_id:'CUSTOM_FIND',    name:'Find & Click',     icon:'🔎',
    defaults:{custom_name:'', selector:"div[role='tab'].tab-item", label_selector:'p.chat-title', match_text:'', click_enabled:true, click_selector:'', pre_delay_ms:500},
    labels:{custom_name:'Block name (shown in stack)', selector:'Element to find (CSS)', label_selector:'Text element inside (CSS)', match_text:'Text to match inside (optional)', click_enabled:'Click after found', click_selector:'Element inside to click (optional)', pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'CLICK_MAIN_TAB', name:'Click Main Tab',   icon:'🏠',
    defaults:{selector:"div[role='tab'].tab-item", child_selector:"p.chat-title", tab_name:'Гостиная', pre_delay_ms:500},
    labels:{selector:'Tab element selector', child_selector:'Child text selector', tab_name:'Tab name (text match)', pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'SCROLL_PARSE',   name:'Scroll & Parse',    icon:'📜',
    defaults:{max_scrolls:50,scroll_pause_ms:800,pre_delay_ms:300},
    labels:{max_scrolls:'Max scrolls',scroll_pause_ms:'Scroll pause (ms)',pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'CONDITIONAL_SKIP',name:'If Messaged → Skip',icon:'🔀', defaults:{}, labels:{} },
  { block_id:'CLICK_USER',     name:'Click User',        icon:'👤',
    defaults:{pre_delay_ms:1000},
    labels:{pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'WAIT_PAGE_LOAD', name:'Wait for Page',     icon:'⏳',
    defaults:{target_selector:"textarea[placeholder='Сообщение']",timeout_ms:5000,pre_delay_ms:200},
    labels:{target_selector:'Target CSS selector',timeout_ms:'Timeout (ms)',pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'TYPE_MESSAGE',   name:'Type Message',      icon:'⌨️',
    defaults:{message:'',typing_speed_ms:30,pre_delay_ms:500},
    labels:{message:'Message text (use {{nick}})',typing_speed_ms:'Typing speed (ms)',pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'CLICK_SEND',     name:'Click Send',        icon:'📨',
    defaults:{pre_delay_ms:300},
    labels:{pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'ATTACH_IMAGE',   name:'Attach Image',      icon:'🖼️',
    defaults:{folder_path:'',file_pattern:'*.jpg',pre_delay_ms:500},
    labels:{folder_path:'Image folder path',file_pattern:'File pattern',pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'CLICK_BACK',     name:'Return to Main',    icon:'🔙',
    defaults:{selector:"div[role='tab'].tab-item", child_selector:"p.chat-title", tab_name:'Гостиная', pre_delay_ms:800},
    labels:{selector:'Tab element selector', child_selector:'Child text selector', tab_name:'Tab name', pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'PAUSE',          name:'Custom Pause',      icon:'⏸️',
    defaults:{duration_ms:1000},
    labels:{duration_ms:'Duration (ms)'} },
];

const StackDnD = {
  stack: [],
  selectedIdx: -1,
  customBlocks: [],       // reusable Find & Click presets: [{name, block, updated_at}]
  _sortable: null,
  _running: false,
  _runningIdx: -1,
  _paused: false,
  _restoring: false,
  _snapshotTimer: null,

  init() {
    this._initDefaultStack();
    this._renderStack();
    this._setupAddMenu();
    this._setupButtons();
    this._initSortable();
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

  _summary(b) {
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
      return;
    }
    list.innerHTML = this.stack.map((b, i) => {
      const meta = this._meta(b.block_id);
      const title = this._displayName(b);
      const summary = this._summary(b);
      const sel = i === this.selectedIdx ? ' active' : '';
      const run = i === this._runningIdx && this._running ? ' block-running' : '';
      return `<div class="stack-item${sel}${run}" data-idx="${i}">
        <span class="drag-handle">⠿</span>
        <span class="block-icon">${meta.icon}</span>
        <div class="block-info">
          <div class="block-name">${title}</div>
          <div class="block-summary">${summary}</div>
        </div>
        <span class="block-remove" onclick="event.stopPropagation();StackDnD.removeBlock(${i})">✕</span>
      </div>`;
    }).join('');
    // click to select
    list.querySelectorAll('.stack-item').forEach(el => {
      el.addEventListener('click', () => {
        this.selectBlock(parseInt(el.dataset.idx));
      });
    });
  },

  _initSortable() {
    if (typeof Sortable === 'undefined') {
      // load SortableJS dynamically
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/sortablejs@1.15.0/Sortable.min.js';
      s.onload = () => this._createSortable();
      document.head.appendChild(s);
    } else {
      this._createSortable();
    }
  },

  _createSortable() {
    const list = document.getElementById('stackList');
    this._sortable = new Sortable(list, {
      animation: 150,
      handle: '.drag-handle',
      ghostClass: 'sortable-ghost',
      chosenClass: 'sortable-chosen',
      onEnd: (evt) => {
        if (evt.oldIndex === evt.newIndex) return;
        const item = this.stack.splice(evt.oldIndex, 1)[0];
        this.stack.splice(evt.newIndex, 0, item);
        this._renderStack();
        this.notifyEdited();
      },
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

  _showConfig(idx) {
    const panel = document.getElementById('blockConfigPanel');
    const form = document.getElementById('blockConfigForm');
    const block = this.stack[idx];
    if (!block) { panel.classList.add('hidden'); return; }
    panel.classList.remove('hidden');
    const meta = this._meta(block.block_id);
    const labels = meta.labels || {};
    form.innerHTML = `<div class="form-row"><label>Block</label><span style="font-weight:600">${meta.icon||''} ${this._displayName(block)}</span></div>`;
    for (const [key, val] of Object.entries(block)) {
      if (key === 'block_id') continue;
      const labelText = labels[key] || key;
      if (typeof val === 'boolean') {
        form.innerHTML += `<div class="form-row form-row-check">
          <label>${labelText}</label>
          <input data-key="${key}" type="checkbox" ${val ? 'checked' : ''}>
        </div>`;
      } else {
        const inputType = typeof val === 'number' ? 'number' : 'text';
        const safeVal = String(val).replace(/"/g, '&quot;');
        form.innerHTML += `<div class="form-row">
          <label>${labelText}</label>
          <input data-key="${key}" value="${safeVal}" type="${inputType}">
        </div>`;
      }
    }
    form.querySelectorAll('input[data-key]').forEach(inp => {
      inp.addEventListener('change', () => {
        const k = inp.dataset.key;
        if (inp.type === 'checkbox') block[k] = inp.checked;
        else block[k] = inp.type === 'number' ? Number(inp.value) : inp.value;
        this._renderStack();
        this.notifyEdited();
      });
    });
    document.getElementById('closeConfigBtn').onclick = () => panel.classList.add('hidden');

    // Save Block preset action (only for configurable Find & Click blocks)
    const actions = document.getElementById('customBlockActions');
    if (block.block_id === 'CUSTOM_FIND' && App.bridge) {
      actions.classList.remove('hidden');
      const btn = document.getElementById('saveCustomBlockBtn');
      btn.onclick = () => this._saveBlockPreset(block);
    } else {
      actions.classList.add('hidden');
    }
  },

  _saveBlockPreset(block) {
    if (!App.bridge) return;
    const useName = (name) => {
      block.custom_name = name;
      this._renderStack();
      App.bridge.save_custom_block(name, JSON.stringify(block));
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
