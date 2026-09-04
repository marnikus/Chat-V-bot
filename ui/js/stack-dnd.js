/* ═══════════════════════════════════════════════════════════════
   stack-dnd.js — SortableJS-based drag-and-drop action stack
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const AVAILABLE_BLOCKS = [
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
      const summary = Object.entries(b)
        .filter(([k]) => !['block_id','pre_delay_ms'].includes(k))
        .map(([k,v]) => `${k}=${String(v).substring(0,20)}`)
        .join(' · ') || `delay: ${b.pre_delay_ms||0}ms`;
      const sel = i === this.selectedIdx ? ' active' : '';
      return `<div class="stack-item${sel}" data-idx="${i}">
        <span class="drag-handle">⠿</span>
        <span class="block-icon">${meta.icon}</span>
        <div class="block-info">
          <div class="block-name">${meta.name}</div>
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
    document.getElementById('saveStackBtn').addEventListener('click', () => {
      this._openPresetModal('save');
    });
    document.getElementById('loadStackBtn').addEventListener('click', () => {
      this._openPresetModal('load');
    });
  },

  _openPresetModal(mode) {
    const modal = document.getElementById('presetModal');
    const title = document.getElementById('presetModalTitle');
    const nameRow = document.getElementById('presetNameRow');
    const saveBtn = document.getElementById('presetSaveBtn');
    const closeBtn = document.getElementById('presetCloseBtn');
    title.textContent = mode === 'save' ? '💾 Save Stack Preset' : '📂 Load Stack Preset';
    nameRow.style.display = mode === 'save' ? '' : 'none';
    saveBtn.style.display = mode === 'save' ? '' : 'none';
    if (mode === 'save') {
      document.getElementById('presetNameInput').value = '';
      saveBtn.onclick = () => {
        const name = document.getElementById('presetNameInput').value.trim();
        if (name && App.bridge) {
          App.bridge.save_stack_preset(name);
          document.getElementById('presetNameInput').value = '';
          LogConsole.log('💾 Saving preset: ' + name, 'info');
        }
      };
    }
    closeBtn.onclick = () => modal.classList.add('hidden');
    modal.classList.remove('hidden');
    document.getElementById('presetListArea').innerHTML = '<div style="color:var(--text-muted);padding:8px">Loading...</div>';
    if (App.bridge) App.bridge.get_preset_list();
  },

  _renderPresetList(json) {
    const area = document.getElementById('presetListArea');
    if (!area) return;
    let presets;
    try { presets = JSON.parse(json); } catch(e) { return; }
    if (!presets.length) {
      area.innerHTML = '<div style="color:var(--text-muted);padding:8px">No saved presets yet</div>';
      this._updatePresetBar([]);
      return;
    }
    area.innerHTML = presets.map(p => {
      const blockNames = p.blocks.map(b => {
        const meta = AVAILABLE_BLOCKS.find(a => a.block_id === b.block_id);
        return meta ? meta.icon + meta.name : b.block_id;
      }).join(', ');
      return `<div style="display:flex;align-items:center;gap:8px;padding:8px 4px;border-bottom:1px solid var(--border)">
        <span style="flex:1;font-weight:500">${p.name}</span>
        <span style="font-size:10px;color:var(--text-muted)">${p.blocks.length} blocks</span>
        <button onclick="StackDnD._loadPreset('${p.name}')" class="btn-small" style="font-size:11px">📂 Load</button>
        <button onclick="StackDnD._deletePreset('${p.name}')" class="btn-small btn-danger-text" style="font-size:11px">🗑</button>
      </div>
      <div style="font-size:10px;color:var(--text-secondary);padding:0 4px 6px">${blockNames}</div>`;
    }).join('');
    this._updatePresetBar(presets);
  },

  _loadPreset(name) {
    if (!App.bridge) return;
    App.bridge.load_stack_preset(name);
    document.getElementById('presetModal').classList.add('hidden');
    LogConsole.log('📂 Loading preset: ' + name, 'info');
  },

  _deletePreset(name) {
    if (!App.bridge || !confirm('Delete preset "' + name + '"?')) return;
    App.bridge.delete_stack_preset(name);
    LogConsole.log('🗑 Deleted preset: ' + name, 'warn');
  },

  _updatePresetBar(presets) {
    let bar = document.getElementById('presetBar');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'presetBar';
      bar.style.cssText = 'display:flex;gap:4px;flex-wrap:wrap;padding:4px 0;border-top:1px solid var(--border);margin-top:4px';
      const list = document.getElementById('stackList');
      list.parentNode.insertBefore(bar, list.nextSibling);
    }
    if (!presets || !presets.length) {
      bar.innerHTML = '<span style="font-size:10px;color:var(--text-muted)">No presets saved</span>';
      return;
    }
    bar.innerHTML = '<span style="font-size:10px;color:var(--text-secondary);line-height:24px">Presets:</span>' +
      presets.map(p => `<button onclick="StackDnD._loadPreset('${p.name}')" class="btn-small" style="font-size:10px;padding:2px 8px">${p.name}</button>`).join('');
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
    form.innerHTML = `<div class="form-row"><label>Block</label><span style="font-weight:600">${meta.icon||''} ${meta.name||block.block_id}</span></div>`;
    for (const [key, val] of Object.entries(block)) {
      if (key === 'block_id') continue;
      const inputType = typeof val === 'number' ? 'number' : 'text';
      const labelText = labels[key] || key;
      form.innerHTML += `<div class="form-row">
        <label>${labelText}</label>
        <input data-key="${key}" value="${val}" type="${inputType}">
      </div>`;
    }
    form.querySelectorAll('input[data-key]').forEach(inp => {
      inp.addEventListener('change', () => {
        const k = inp.dataset.key;
        block[k] = inp.type === 'number' ? Number(inp.value) : inp.value;
        this._renderStack();
      });
    });
    document.getElementById('closeConfigBtn').onclick = () => panel.classList.add('hidden');
  },
};

document.addEventListener('DOMContentLoaded', () => StackDnD.init());
