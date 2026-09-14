/* stack-dnd part — stack-dnd-menu.js (Round H, H-A4) */

const StackDnDMenu = {
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
    const c = this._migrateBlock(config);
    if (!c) return;
    this.stack.push(c);
    this._renderStack();
    this.pushHistory();
    this.notifyEdited();
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
      html += '<div class="add-menu-section">Custom blocks</div>';
      html += this._customMenuRows();
      html += '<div class="add-menu-section">Built-in blocks</div>';
    }
    html += BUILTIN_BLOCKS.map(b =>
      `<div class="menu-item" data-block="${b.block_id}">
        <span class="mi-icon">${b.icon}</span> ${b.name}
      </div>`
    ).join('');
    menu.innerHTML = html;
    this._wireMenu(menu);
  },

  _customMenuRows() {
    return this.customBlocks.map((c, ci) => {
      const blk = c.block || {};
      const icon = '🔎';
      const label = blk.custom_name || c.name || 'Custom block';
      return `<div class="menu-item" data-custom="${ci}">
        <span class="mi-icon">${icon}</span> ${label}
      </div>`;
    }).join('');
  },

  _wireMenu(menu) {
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
    this._wireRunButton();
    this._wirePauseButton();
    this._wireStopButton();
    this._wireSaveLoadButtons();
    this._wireImportExportButtons();
  },

  _wireRunButton() {
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
  },

  _wirePauseButton() {
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
  },

  _wireStopButton() {
    const stopBtn = document.getElementById('stopBtn');
    if (stopBtn) stopBtn.addEventListener('click', () => {
      if (App.bridge) App.bridge.stop_stack();
    });
  },

  _wireSaveLoadButtons() {
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

  _wireImportExportButtons() {
    // Portable export/import (FEATURE) — the format and validation live
    // in the backend (services/preset_io); PresetsUI moves the JSON and
    // renders the preview.
    const exportBtn = document.getElementById('exportStackBtn');
    if (exportBtn) exportBtn.addEventListener('click', () => {
      PresetsUI.exportCurrentStack();
    });
    const importBtn = document.getElementById('importStackBtn');
    if (importBtn) importBtn.addEventListener('click', () => {
      PresetsUI.importStack();
    });
    const importBlockBtn = document.getElementById('importBlockBtn');
    if (importBlockBtn) importBlockBtn.addEventListener('click', () => {
      PresetsUI.importBlock();
    });
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
};
