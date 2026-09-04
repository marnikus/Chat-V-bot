/* ═══════════════════════════════════════════════════════════════
   stack-dnd.js — SortableJS-based drag-and-drop action stack
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const AVAILABLE_BLOCKS = [
  { block_id:'CLICK_MAIN_TAB', name:'Click Main Tab',   icon:'🏠',
    defaults:{selector:"div[role='tab'].tab-item", child_selector:"p.chat-title", tab_name:'Гостиная', pre_delay_ms:500},
    labels:{selector:'Tab element selector', child_selector:'Child text selector', tab_name:'Tab name (text match)', pre_delay_ms:'Pre-delay (ms)'} },
  { block_id:'FIND_ELEMENT',  name:'Find Element',      icon:'🔎',
    defaults:{name:'Find Element', selector:"div[role='tab'].tab-item", child_selector:'', text:'', click:true, click_index:0, pre_delay_ms:300},
    labels:{name:'Block name', selector:'CSS selector (e.g. div[role=\'tab\'].tab-item)', child_selector:'Child text selector (optional)', text:'Required text (optional)', click:'Click after found', click_index:'Match to click (0=first, -1=last)', pre_delay_ms:'Pre-delay (ms)'} },
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
  _sortable: null,
  _running: false,

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

  _renderStack() {
    const list = document.getElementById('stackList');
    if (!this.stack.length) {
      list.innerHTML = '<div class="stack-empty">Drag blocks here or click + to add</div>';
      return;
    }
    list.innerHTML = this.stack.map((b, i) => {
      const meta = AVAILABLE_BLOCKS.find(a => a.block_id === b.block_id) || { name: b.block_id, icon:'?' };
      const displayName = b.name || meta.name;
      const summary = Object.entries(b)
        .filter(([k]) => !['block_id','pre_delay_ms','name'].includes(k))
        .map(([k,v]) => String(v).substring(0,22))
        .join(' · ') || `delay: ${b.pre_delay_ms||0}ms`;
      const sel = i === this.selectedIdx ? ' active' : '';
      return `<div class="stack-item${sel}" data-idx="${i}">
        <span class="drag-handle">⠿</span>
        <span class="block-icon">${meta.icon}</span>
        <div class="block-info">
          <div class="block-name">${displayName}</div>
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
        const item = this.stack.splice(evt.oldIndex, 1)[0];
        this.stack.splice(evt.newIndex, 0, item);
        this._renderStack();
      },
    });
  },

  _setupAddMenu() {
    const btn = document.getElementById('addBlockBtn');
    const menu = document.getElementById('addBlockMenu');
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      menu.classList.toggle('hidden');
      if (!menu.classList.contains('hidden')) {
        const rect = btn.getBoundingClientRect();
        menu.style.top = rect.bottom + 4 + 'px';
        menu.style.left = rect.left + 'px';
      }
    });
    menu.innerHTML = AVAILABLE_BLOCKS.map(b =>
      `<div class="menu-item" data-block="${b.block_id}">
        <span class="mi-icon">${b.icon}</span> ${b.name}
      </div>`
    ).join('');
    menu.querySelectorAll('.menu-item').forEach(el => {
      el.addEventListener('click', () => {
        const bid = el.dataset.block;
        const meta = AVAILABLE_BLOCKS.find(b => b.block_id === bid);
        this.stack.push({ block_id: bid, pre_delay_ms: 500, ...(meta?.defaults || {}) });
        this._renderStack();
        menu.classList.add('hidden');
      });
    });
    document.addEventListener('click', () => menu.classList.add('hidden'));
  },

  _setupButtons() {
    document.getElementById('runBtn').addEventListener('click', () => {
      if (!App.bridge) return;
      this._running = true;
      document.getElementById('runBtn').disabled = true;
      document.getElementById('pauseBtn').disabled = false;
      document.getElementById('stopBtn').disabled = false;
      App.bridge.run_stack(JSON.stringify(this.stack));
      LogConsole.log('▶ Stack execution started', 'success');
    });
    document.getElementById('pauseBtn').addEventListener('click', () => {
      if (App.bridge) App.bridge.pause_stack();
    });
    document.getElementById('stopBtn').addEventListener('click', () => {
      if (App.bridge) App.bridge.stop_stack();
    });
    document.getElementById('saveStackBtn').addEventListener('click', () => this.openStackPresets());
    document.getElementById('loadStackBtn').addEventListener('click', () => this.openStackPresets());
  },

  // ── stack preset manager ─────────────────────────────────────
  openStackPresets() {
    const modal = document.getElementById('stackPresetModal');
    modal.classList.remove('hidden');
    this.renderStackPresets();
  },

  renderStackPresets() {
    const list = document.getElementById('stackPresetList');
    if (App.bridge) {
      App.bridge.list_stack_presets((json) => {
        let items = [];
        try { items = JSON.parse(json) || []; } catch (e) { items = []; }
        list.innerHTML = items.map(p => `
          <div class="preset-row">
            <span class="preset-name">${p.name}</span>
            <span class="preset-meta">${p.block_count || 0} blocks</span>
            <button onclick="StackDnD.loadStackPreset('${p.name.replace(/'/g, "\\'")}')">Load</button>
            <button class="btn-danger-text" onclick="StackDnD.deleteStackPreset('${p.name.replace(/'/g, "\\'")}')">Delete</button>
          </div>
        `).join('') || '<div class="preset-empty">No saved stack presets yet</div>';
      });
    }
    document.getElementById('stackPresetName').value = '';
    document.getElementById('stackPresetSaveBtn').onclick = () => {
      const name = document.getElementById('stackPresetName').value.trim();
      if (!name) { LogConsole.log('⚠ Enter a preset name', 'warn'); return; }
      if (App.bridge) {
        App.bridge.save_stack_preset(name, JSON.stringify(this.stack));
        this.renderStackPresets();
      }
    };
    document.getElementById('stackPresetCloseBtn').onclick = () => {
      document.getElementById('stackPresetModal').classList.add('hidden');
    };
  },

  loadStackPreset(name) {
    if (App.bridge) {
      App.bridge.load_stack_preset(name);
      const modal = document.getElementById('stackPresetModal');
      if (modal) modal.classList.add('hidden');
    }
  },

  deleteStackPreset(name) {
    if (App.bridge) {
      App.bridge.delete_stack_preset(name);
      this.renderStackPresets();
    }
  },

  // ── element / finder presets ─────────────────────────────────
  loadFinderPresets() {
    if (!App.bridge) { App.finderPresets = []; this.populateFinderPresetSelect(); return; }
    App.bridge.list_finder_presets((json) => {
      try { App.finderPresets = JSON.parse(json) || []; }
      catch (e) { App.finderPresets = []; }
      this.populateFinderPresetSelect();
    });
  },

  populateFinderPresetSelect() {
    const sel = document.getElementById('finderPresetSelect');
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="">— Choose preset —</option>';
    (App.finderPresets || []).forEach(p => {
      const o = document.createElement('option');
      o.value = p.name;
      o.textContent = p.name;
      sel.appendChild(o);
    });
    if (current && (App.finderPresets || []).some(p => p.name === current)) sel.value = current;
  },

  saveFinderPresetFromBlock() {
    const block = this.stack[this.selectedIdx];
    if (!block) return;
    const nameInput = document.getElementById('finderPresetNameInput');
    const name = (nameInput ? nameInput.value.trim() : '') || block.name || 'Find Element';
    const config = {
      name: block.name || name,
      selector: block.selector || '',
      child_selector: block.child_selector || '',
      text: block.text || '',
      click: !!block.click,
      click_index: Number.isFinite(Number(block.click_index)) ? Number(block.click_index) : 0,
      pre_delay_ms: Number.isFinite(Number(block.pre_delay_ms)) ? Number(block.pre_delay_ms) : 300,
    };
    if (App.bridge) App.bridge.save_finder_preset(name, JSON.stringify(config));
    else LogConsole.log('⚠ No bridge available', 'warn');
  },

  loadFinderPresetIntoBlock() {
    const sel = document.getElementById('finderPresetSelect');
    const name = sel ? sel.value : '';
    if (!name) { LogConsole.log('⚠ Choose a preset to load', 'warn'); return; }
    if (!App.bridge) return;
    App.bridge.get_finder_preset(name, (json) => {
      try {
        const cfg = JSON.parse(json);
        const block = this.stack[this.selectedIdx];
        if (!block) return;
        Object.assign(block, cfg, { block_id: 'FIND_ELEMENT' });
        if (!block.name) block.name = name;
        this._renderStack();
        this._showConfig(this.selectedIdx);
        LogConsole.log(`🎨 Element preset loaded: ${name}`, 'success');
      } catch (e) {
        LogConsole.log(`❌ Load element preset error: ${e}`, 'error');
      }
    });
  },

  deleteFinderPreset() {
    const sel = document.getElementById('finderPresetSelect');
    const name = sel ? sel.value : '';
    if (!name) { LogConsole.log('⚠ Choose a preset to delete', 'warn'); return; }
    if (App.bridge) {
      App.bridge.delete_finder_preset(name);
      this.loadFinderPresets();
    }
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
  },

  setRunning(val) {
    this._running = val;
    if (!val) {
      document.getElementById('runBtn').disabled = false;
      document.getElementById('pauseBtn').disabled = true;
      document.getElementById('stopBtn').disabled = true;
    }
  },

  _showConfig(idx) {
    const panel = document.getElementById('blockConfigPanel');
    const form = document.getElementById('blockConfigForm');
    const block = this.stack[idx];
    if (!block) { panel.classList.add('hidden'); return; }
    panel.classList.remove('hidden');
    const meta = AVAILABLE_BLOCKS.find(b => b.block_id === block.block_id) || {};
    const labels = meta.labels || {};
    const displayName = block.name || meta.name || block.block_id;
    form.innerHTML = `<div class="form-row"><label>Block</label><span style="font-weight:600">${meta.icon||''} ${displayName}</span></div>`;
    for (const [key, val] of Object.entries(block)) {
      if (key === 'block_id') continue;
      const labelText = labels[key] || key;
      if (typeof val === 'boolean') {
        form.innerHTML += `<div class="form-row">
          <label>${labelText}</label>
          <input data-key="${key}" type="checkbox" ${val ? 'checked' : ''}>
        </div>`;
      } else if (typeof val === 'number') {
        form.innerHTML += `<div class="form-row">
          <label>${labelText}</label>
          <input data-key="${key}" type="number" value="${val}">
        </div>`;
      } else {
        form.innerHTML += `<div class="form-row">
          <label>${labelText}</label>
          <input data-key="${key}" type="text" value="${String(val).replace(/"/g, '&quot;')}">
        </div>`;
      }
    }
    if (block.block_id === 'FIND_ELEMENT') {
      form.innerHTML += `
        <div class="finder-preset-bar">
          <label>Element preset (reusable search + click)</label>
          <select id="finderPresetSelect"></select>
          <input id="finderPresetNameInput" placeholder="Preset name (e.g. Find Setting Button)" value="${(block.name || '').replace(/"/g, '&quot;')}">
          <div class="finder-preset-actions">
            <button class="btn-small" onclick="StackDnD.saveFinderPresetFromBlock()">💾 Save As Preset</button>
            <button class="btn-small" onclick="StackDnD.loadFinderPresetIntoBlock()">Load Into Block</button>
            <button class="btn-small btn-danger-text" onclick="StackDnD.deleteFinderPreset()">Delete Preset</button>
          </div>
        </div>`;
      this.loadFinderPresets();
    }
    form.querySelectorAll('input[data-key]').forEach(inp => {
      inp.addEventListener('change', () => {
        const k = inp.dataset.key;
        if (inp.type === 'checkbox') block[k] = inp.checked;
        else if (inp.type === 'number') block[k] = Number(inp.value);
        else block[k] = inp.value;
        this._renderStack();
      });
    });
    document.getElementById('closeConfigBtn').onclick = () => panel.classList.add('hidden');
  },
};

document.addEventListener('DOMContentLoaded', () => StackDnD.init());
