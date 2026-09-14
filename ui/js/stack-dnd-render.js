/* stack-dnd part — stack-dnd-render.js (Round H, H-A4) */

const StackDnDRender = {
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
    if (b.block_id === 'SPEED_MULTIPLIER') {
      const base = 'All waits ' + this._speedDesc(b.multiplier);
      return b.enabled === false ? base + ' · OFF' : base;
    }
    const parts = [];
    for (const [k, v] of Object.entries(b)) {
      const part = this._summaryPart(k, v, b);
      if (part !== null) parts.push(part);
    }
    const base = parts.join(' · ') || `delay: ${b.pre_delay_ms || 0}ms`;
    return b.enabled === false ? `${base} · OFF` : base;
  },

  _summaryPart(k, v, b) {
    if (['block_id', 'pre_delay_ms', 'enabled'].includes(k)) return null;
    if (k === 'custom_name') return `name="${v}"`;
    if (k === 'click_enabled') return v ? 'click=on' : 'click=off';
    if (k === 'click_selector' && !v) return null;
    if (k === 'use_composer') return v ? 'text: Message Composer' : null;
    if (k === 'respect_order') return v ? 'respect Order (#)' : null;
    if (k === 'use_person_from_memory') return v ? 'target: {{nick}} from memory' : null;
    if (b.block_id === 'TAKE_PERSON' && k === 'pick_mode') {
      const t = { random_new: 'pick: random New',
                  random_done: 'pick: random Done',
                  order_first: 'pick: Order #1' }[v];
      return t || null;
    }
    if (b.block_id === 'SEARCH_USERS' && k === 'text') {
      return v ? `search: “${v}”` : 'search: (empty)';
    }
    if (k === 'message' && b.use_composer) return null;  // composer text is used
    return `${k}=${String(v).substring(0, 24)}`;
  },

  _esc(s) {
    const d = document.createElement('div');
    d.textContent = s === null || s === undefined ? '' : String(s);
    return d.innerHTML;
  },

  _renderStack() {
    const list = document.getElementById('stackList');
    if (!this.stack.length) {
      list.innerHTML = '<div class="stack-empty">Drag blocks here or click + to add</div>';
      this._attachDrag();
      return;
    }
    list.innerHTML = this.stack.map((b, i) => this._stackItemHtml(b, i)).join('');
    this._wireStackList();
    this._attachDrag();
  },

  _stackItemHtml(b, i) {
    const meta = this._meta(b.block_id);
    const title = this._esc(this._displayName(b));
    const summary = this._esc(this._summary(b));
    const sel = i === this.selectedIdx ? ' active' : '';
    const run = i === this._runningIdx && this._running ? ' block-running' : '';
    const disabled = b.enabled === false ? ' disabled' : '';
    const checked = b.enabled !== false ? 'checked' : '';
    return `<div class="stack-item${sel}${run}${disabled}" data-idx="${i}">
      <label class="toggle-switch" title="${b.enabled===false ? 'Enable' : 'Disable'} this block (skipped when off)">
        <input type="checkbox" data-toggle="${i}" ${checked}>
        <span class="toggle-slider"></span>
      </label>
      <span class="drag-handle" title="Drag to reorder">⠿</span>
      <span class="block-pos">${i + 1}</span>
      <span class="block-icon">${meta.icon}</span>
      <div class="block-info">
        <div class="block-name">${title}${b.enabled===false ? ' <span class="off-badge">OFF</span>' : ''}</div>
        <div class="block-summary">${summary}</div>
      </div>
      <span class="block-remove" data-remove="${i}" title="Remove block">✕</span>
    </div>`;
  },

  _wireStackList() {
    const list = document.getElementById('stackList');
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
    this._wireToggles();
  },

  _wireToggles() {
    const list = document.getElementById('stackList');
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
  },
};


const StackDnDListOps = {
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
        if (key === 'z' && !e.shiftKey) {
          e.preventDefault();
          App.undoGlobal();
          return;
        }
        if (key === 'y' || (key === 'z' && e.shiftKey)) {
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

  selectBlock(idx) {
    this.selectedIdx = idx;
    this._renderStack();
    this._showConfig(idx);
  },

  deselectBlock() {
    this.selectedIdx = -1;
    this._renderStack();
    this._showConfig(this.selectedIdx);
  },

  removeBlock(idx) {
    const name = this.stack[idx] ? this._displayName(this.stack[idx]) : '';
    const selectedBefore = this.selectedIdx;
    this.stack.splice(idx, 1);
    if (selectedBefore === -1) {
      this.selectedIdx = -1;
    } else if (idx < selectedBefore) {
      // Keep the selected block selected: removing one before it shifts its
      // index down.
      this.selectedIdx = selectedBefore - 1;
    } else if (idx === selectedBefore) {
      // The selected block is gone; fall back to the block that now sits in
      // that slot (or -1 when the stack is empty).
      this.selectedIdx = Math.min(selectedBefore, this.stack.length - 1);
    } else {
      // Removing an item after the selection leaves the selected index valid.
      this.selectedIdx = selectedBefore;
    }
    this._renderStack();
    // Refresh the Tune panel for the block that fills the selected slot
    // (or, when the selected block was removed and the panel is pinned,
    // keep it open with its empty-state hint).
    this._showConfig(this.selectedIdx);
    this.pushHistory();
    this.notifyEdited();
    if (typeof LogConsole !== 'undefined' && name) {
      LogConsole.log(`🗑 Removed “${name}”`, 'warn');
    }
  },
};
