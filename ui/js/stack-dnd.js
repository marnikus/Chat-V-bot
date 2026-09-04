/* ═══════════════════════════════════════════════════════════════
   stack-dnd.js — SortableJS-based drag-and-drop action stack
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const AVAILABLE_BLOCKS = [
  { block_id:'CLICK_MAIN_TAB', name:'Click Main Tab',   icon:'🏠', defaults:{tab_name:'Гостиная',pre_delay_ms:500} },
  { block_id:'SCROLL_PARSE',   name:'Scroll & Parse',    icon:'📜', defaults:{max_scrolls:50,scroll_pause_ms:800,pre_delay_ms:300} },
  { block_id:'CONDITIONAL_SKIP',name:'If Messaged → Skip',icon:'🔀', defaults:{} },
  { block_id:'CLICK_USER',     name:'Click User',        icon:'👤', defaults:{pre_delay_ms:1000} },
  { block_id:'WAIT_PAGE_LOAD', name:'Wait for Page',     icon:'⏳', defaults:{target_selector:"textarea[placeholder='Сообщение']",timeout_ms:5000,pre_delay_ms:200} },
  { block_id:'TYPE_MESSAGE',   name:'Type Message',      icon:'⌨️', defaults:{message:'',typing_speed_ms:30,pre_delay_ms:500} },
  { block_id:'CLICK_SEND',     name:'Click Send',        icon:'📨', defaults:{pre_delay_ms:300} },
  { block_id:'ATTACH_IMAGE',   name:'Attach Image',      icon:'🖼️', defaults:{folder_path:'',file_pattern:'*.jpg',pre_delay_ms:500} },
  { block_id:'CLICK_BACK',     name:'Return to Main',    icon:'🔙', defaults:{tab_name:'Гостиная',pre_delay_ms:800} },
  { block_id:'PAUSE',          name:'Custom Pause',      icon:'⏸️', defaults:{duration_ms:1000} },
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
      { block_id:'CLICK_MAIN_TAB', pre_delay_ms:500, tab_name:'Гостиная' },
      { block_id:'SCROLL_PARSE',   pre_delay_ms:300, max_scrolls:50, scroll_pause_ms:800 },
      { block_id:'CONDITIONAL_SKIP',pre_delay_ms:0 },
      { block_id:'CLICK_USER',     pre_delay_ms:1000 },
      { block_id:'WAIT_PAGE_LOAD', pre_delay_ms:200, target_selector:"textarea[placeholder='Сообщение']", timeout_ms:5000 },
      { block_id:'TYPE_MESSAGE',   pre_delay_ms:500, message:'', typing_speed_ms:30 },
      { block_id:'CLICK_SEND',     pre_delay_ms:300 },
      { block_id:'CLICK_BACK',     pre_delay_ms:800, tab_name:'Гостиная' },
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
      const name = prompt('Stack preset name:');
      if (name && App.bridge) App.bridge.save_stack_preset(name);
    });
    document.getElementById('loadStackBtn').addEventListener('click', () => {
      const name = prompt('Load preset name:');
      if (name && App.bridge) {
        App.bridge.load_stack_preset(name);
        setTimeout(() => App.bridge.get_stack_json((json) => {
          try { this.stack = JSON.parse(json); this._renderStack(); } catch(e) {}
        }), 300);
      }
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
    form.innerHTML = `<div class="form-row"><label>Block</label><span style="font-weight:600">${meta.icon||''} ${meta.name||block.block_id}</span></div>`;
    for (const [key, val] of Object.entries(block)) {
      if (key === 'block_id') continue;
      const inputType = typeof val === 'number' ? 'number' : 'text';
      form.innerHTML += `<div class="form-row">
        <label>${key}</label>
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
