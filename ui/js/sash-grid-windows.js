/* sash-grid part — sash-grid-windows.js (Round H, H-A3) */

const SashGridWindowStore = {
  _collectPanels() {
    const winElIds = {
      stats: 'winStats', filters: 'winFilters', stack: 'winStack',
      config: 'blockConfigPanel', composer: 'winComposer',
      people: 'winPeople', log: 'winLog',
      history: 'winHistory', userdb: 'winUserDb', collector: 'winCollector',
      labels: 'winLabels', dbconn: 'winDbconn',
      botchat: 'winBotChat', botprompt: 'winBotPrompt',
    };
    for (const w of SashCore.WINDOWS) {
      const el = document.getElementById(winElIds[w.id]);
      if (!el) { console.warn('sash-grid: panel for "' + w.id + '" missing'); continue; }
      this.winEls[w.id] = el;
    }
  },

  _loadTree() {
    try {
      const raw = localStorage.getItem(this.STORAGE_KEY);
      if (!raw) return null;
      const res = SashCore.deserialize(raw);
      if (res.ok) return res.tree;
      console.warn('sash-grid: persisted layout rejected (' + res.error + ') — using default');
      return null;
    } catch (e) {
      return null;
    }
  },

  _loadWindowStates() {
    try {
      const rawClosed = localStorage.getItem(this.STORAGE_CLOSED);
      if (rawClosed) {
        const arr = JSON.parse(rawClosed);
        if (Array.isArray(arr)) {
          arr.forEach((id) => {
            if (typeof id === 'string' && SashCore.WINDOW_IDS.includes(id)) this.closedWindows.add(id);
          });
        }
      }
      const rawMin = localStorage.getItem(this.STORAGE_MINIMIZED);
      if (rawMin) {
        const arr = JSON.parse(rawMin);
        if (Array.isArray(arr)) {
          arr.forEach((id) => {
            if (typeof id === 'string' && SashCore.WINDOW_IDS.includes(id) && !this.closedWindows.has(id)) this.minimizedWindows.add(id);
          });
        }
      }
      // NOTE: a legacy 'chatbot.sashWindows.maximized.v1' value may exist from
      // older builds — the full-grid maximize state was removed by design, so
      // it is intentionally ignored here (and dropped on the next save).
    } catch (e) {}
  },

  _saveWindowStates() {
    try {
      localStorage.setItem(this.STORAGE_CLOSED, JSON.stringify(Array.from(this.closedWindows)));
      localStorage.setItem(this.STORAGE_MINIMIZED, JSON.stringify(Array.from(this.minimizedWindows)));
    } catch (e) {}
    try {
      if (typeof App !== 'undefined' && App.bridge && App.bridge.save_window_states) {
        const payload = JSON.stringify({
          closed: Array.from(this.closedWindows),
          minimized: Array.from(this.minimizedWindows),
        });
        App.bridge.save_window_states(payload);
      }
    } catch (e) {}
  },

  _save() {
    const payload = SashCore.serialize(this.root);
    try { localStorage.setItem(this.STORAGE_KEY, payload); } catch (e) {}
    let backendAccepted = false;
    try {
      if (typeof App !== 'undefined' && App.bridge && App.bridge.save_grid_layout) {
        backendAccepted = App.bridge.save_grid_layout(payload) !== false;
      }
    } catch (e) {}
    if (typeof App !== 'undefined' && App.recordGlobal && (!App.bridge || !App.bridge.save_grid_layout || backendAccepted)) {
      App.recordGlobal('grid', payload, { localOnly: true });
    }
  },

  _loadFromBackend() {
    try {
      if (typeof App === 'undefined' || !App.bridge) return;
      if (App.bridge.get_grid_layout) {
        App.bridge.get_grid_layout((raw) => {
          if (!raw) return;
          const res = SashCore.deserialize(raw);
          if (!res.ok) return;
          if (raw === SashCore.serialize(this.root)) return;
          this.root = res.tree;
          this._enforceMinimums();
          this.render();
        });
      }
      if (App.bridge.get_window_states) {
        App.bridge.get_window_states((raw) => {
          if (!raw) return;
          try {
            const data = JSON.parse(raw);
            if (!data || typeof data !== 'object') return;
            if (Array.isArray(data.closed)) this.closedWindows = new Set(data.closed.filter((id) => SashCore.WINDOW_IDS.includes(id)));
            if (Array.isArray(data.minimized)) this.minimizedWindows = new Set(data.minimized.filter((id) => SashCore.WINDOW_IDS.includes(id) && !this.closedWindows.has(id)));
            // 'maximized' from old builds is intentionally ignored.
            this.render();
            this._saveWindowStates();
          } catch (e) {}
        });
      }
    } catch (e) {}
  },

  _applySerialized(raw, showAll) {
    if (!raw || raw === 'null') return false;
    const res = SashCore.deserialize(raw);
    if (!res.ok) return false;
    this.root = res.tree;
    if (showAll) this.showAllWindows();
    this.render();
    try { localStorage.setItem(this.STORAGE_KEY, raw); } catch (e) {}
    return true;
  },
};


const SashGridWindows = {
  showAllWindows() {
    this.closedWindows.clear();
    this.minimizedWindows.clear();
    Object.values(this.winEls).forEach((panel) => {
      if (!panel) return;
      panel.classList.remove('hidden');
      if (panel.style.display === 'none') panel.style.display = '';
    });
    this._saveWindowStates();
    this._applyStates();
  },

  resetToDefault() {
    this.root = SashCore.defaultTree();
    this._enforceMinimums();
    this.closedWindows.clear();
    this.minimizedWindows.clear();
    this.showAllWindows();
    this.render();
    let saved = false;
    try {
      if (typeof App !== 'undefined' && App.bridge && App.bridge.reset_grid_layout) {
        App.bridge.reset_grid_layout((raw) => { if (raw) this._applySerialized(raw, true); });
        saved = true;
        if (App.recordGlobal) App.recordGlobal('grid', SashCore.serialize(this.root), { localOnly: true });
      }
    } catch (e) {}
    if (!saved) this._save();
    this._saveWindowStates();
    if (typeof LogConsole !== 'undefined') LogConsole.log('↺ Grid layout reset to default — all windows visible', 'info');
    return true;
  },

  setLayout(name) {
    const fn = SashCore.PRESETS[name];
    if (!fn) return false;
    this.root = fn();
    this._enforceMinimums();
    this.render();
    this._save();
    if (typeof LogConsole !== 'undefined') {
      const label = { default: 'Default', a: 'A — stacked rows', b: 'B — split top row', c: 'C — side column' }[name] || name;
      LogConsole.log('📐 Layout \"' + label + '\" applied', 'info');
    }
    return true;
  },

  isClosed(id) { return this.closedWindows.has(id); },

  isMinimized(id) { return this.minimizedWindows.has(id); },

  closeWindow(id) {
    if (!SashCore.WINDOW_IDS.includes(id)) return false;
    if (this.closedWindows.has(id)) return false;
    this.closedWindows.add(id);
    this.minimizedWindows.delete(id);
    const panel = this.winEls[id];
    if (panel) panel.classList.add('hidden');
    this._saveWindowStates();
    this._applyStates();
    if (typeof LogConsole !== 'undefined') LogConsole.log('🪟 Closed ' + (SashCore.WINDOW_TITLES[id] || id), 'info');
    return true;
  },

  openWindow(id) {
    if (!SashCore.WINDOW_IDS.includes(id)) return false;
    if (!this.closedWindows.has(id)) return false;
    this.closedWindows.delete(id);
    const panel = this.winEls[id];
    if (panel) {
      panel.classList.remove('hidden');
      if (panel.style.display === 'none') panel.style.display = '';
    }
    this._saveWindowStates();
    this._applyStates();
    this._flashLanded(id);
    if (typeof LogConsole !== 'undefined') LogConsole.log('🪟 Opened ' + (SashCore.WINDOW_TITLES[id] || id), 'success');
    return true;
  },

  /** Ensure a window is visible in the grid. Used by collectors / history
   *  jumpers: opens it when closed and restores it when minimized. */
  showWindow(winId) {
    if (!SashCore.WINDOW_IDS.includes(winId)) return false;
    if (this.closedWindows.has(winId)) return this.openWindow(winId);
    if (this.minimizedWindows.has(winId)) return this.restoreMinimized(winId);
    const panel = this.winEls[winId];
    if (!panel) return false;
    panel.classList.remove('hidden');
    if (panel.style.display === 'none') panel.style.display = '';
    this._syncHidden();
    this._syncEmptySplits();
    this._checkEmptyGrid();
    return true;
  },

  toggleWindow(id) {
    if (this.isClosed(id)) return this.openWindow(id);
    if (this.isMinimized(id)) return this.restoreMinimized(id);
    return this.closeWindow(id);
  },

  /** Collapse an open window: its panel leaves the grid and its title bar is
   *  docked in the strip at the bottom edge (.sash-min-dock). The wrapper is
   *  marked hidden — the exact mechanism closeWindow() uses — so every other
   *  open window expands into the freed space and no empty band remains. */
  minimizeWindow(id) {
    if (!SashCore.WINDOW_IDS.includes(id)) return false;
    if (this.isClosed(id)) return false;
    if (this.isMinimized(id)) return false;
    this.minimizedWindows.add(id);
    this._saveWindowStates();
    this._applyStates();
    if (typeof LogConsole !== 'undefined') LogConsole.log('🗕 Minimized ' + (SashCore.WINDOW_TITLES[id] || id) + ' — docked at the bottom strip', 'info');
    return true;
  },

  /** Bring a minimized window back into the grid at its previous slot. */
  restoreMinimized(id) {
    if (!this.isMinimized(id)) return false;
    this.minimizedWindows.delete(id);
    this._saveWindowStates();
    this._applyStates();
    this._flashLanded(id);
    if (typeof LogConsole !== 'undefined') LogConsole.log('🗖 Restored ' + (SashCore.WINDOW_TITLES[id] || id), 'success');
    return true;
  },

  toggleMinimize(id) {
    if (this.isMinimized(id)) return this.restoreMinimized(id);
    return this.minimizeWindow(id);
  },
};


const SashGridMenus = {
  _ensureDock() {
    if (this.dockEl) return;
    if (!this.gridEl || !this.gridEl.parentNode) return;
    let dock = document.getElementById('sashMinDock');
    if (!dock) {
      dock = document.createElement('div');
      dock.id = 'sashMinDock';
      dock.className = 'sash-min-dock hidden';
      this.gridEl.parentNode.insertBefore(dock, this.gridEl.nextSibling);
    }
    this.dockEl = dock;
  },

  _renderDock() {
    this._ensureDock();
    if (!this.dockEl) return;
    this.dockEl.innerHTML = '';
    this.dockEl.classList.toggle('hidden', this.minimizedWindows.size === 0);
    if (this.minimizedWindows.size === 0) return;
    SashCore.WINDOWS.forEach((w) => {
      const id = w.id;
      if (!this.minimizedWindows.has(id)) return;
      this.dockEl.appendChild(this._dockChip(w));
    });
  },

  _dockChip(w) {
    const id = w.id;
    const title = w.title || id;
    const chip = document.createElement('div');
    chip.className = 'sash-min-chip';
    chip.dataset.win = id;
    chip.title = 'Restore ' + title;
    const label = document.createElement('span');
    label.className = 'smc-label';
    label.textContent = title;
    chip.appendChild(label);
    this._dockChipButtons(chip, title, id);
    chip.addEventListener('click', (e) => {
      if (e.target && e.target.closest && e.target.closest('button')) return;
      this.restoreMinimized(id);
    });
    return chip;
  },

  _dockChipButtons(chip, title, id) {
    const restoreBtn = document.createElement('button');
    restoreBtn.className = 'win-btn win-toggle';
    restoreBtn.textContent = '□';
    restoreBtn.title = 'Restore ' + title;
    const closeBtn = document.createElement('button');
    closeBtn.className = 'win-btn win-close';
    closeBtn.textContent = '✕';
    closeBtn.title = 'Close ' + title;
    chip.appendChild(restoreBtn);
    chip.appendChild(closeBtn);
    restoreBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      this.restoreMinimized(id);
    });
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      this.closeWindow(id);
    });
  },

  _setupWindowsMenu() {
    const btn = document.getElementById('windowsMenuBtn');
    const menu = document.getElementById('windowsMenu');
    if (!btn || !menu) return;
    const place = () => {
      if (menu.classList.contains('hidden')) return;
      const r = btn.getBoundingClientRect();
      let left = r.right - 320;
      left = Math.max(8, Math.min(left, window.innerWidth - 328));
      menu.style.left = left + 'px';
      menu.style.top = (r.bottom + 6) + 'px';
    };
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const layoutMenu = document.getElementById('layoutMenu');
      if (layoutMenu) layoutMenu.classList.add('hidden');
      const willShow = menu.classList.contains('hidden');
      menu.classList.toggle('hidden');
      if (willShow) {
        this._renderWindowsMenu();
        place();
      }
    });
    this._wireWindowsMenuActions(menu);
    this._dismissOutside('#windowsMenu', '#windowsMenuBtn', menu);
  },

  _wireWindowsMenuActions(menu) {
    const showAllBtn = document.getElementById('windowsShowAllBtn');
    if (showAllBtn) showAllBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      menu.classList.add('hidden');
      this.showAllWindows();
      this.render();
      this._save();
      if (typeof LogConsole !== 'undefined') LogConsole.log('🪟 All windows shown', 'success');
    });
    const hideAllBtn = document.getElementById('windowsHideAllBtn');
    if (hideAllBtn) hideAllBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      SashCore.WINDOW_IDS.forEach((id) => this.closedWindows.add(id));
      this.minimizedWindows.clear();
      Object.values(this.winEls).forEach((panel) => { if (panel) panel.classList.add('hidden'); });
      this._saveWindowStates();
      this._applyStates();
      menu.classList.add('hidden');
      if (typeof LogConsole !== 'undefined') LogConsole.log('🪟 All windows closed — reopen from Windows menu', 'warn');
    });
  },

  _renderWindowsMenu() {
    const listEl = document.getElementById('windowsMenuList');
    if (!listEl) return;
    listEl.innerHTML = SashCore.WINDOWS.map((w) => this._windowsMenuRow(w)).join('');
    this._wireWindowsMenu(listEl);
  },

  _windowsMenuState(isClosed, isMin) {
    if (isClosed) return { icon: '○', cls: 'closed', badge: 'Closed', badgeCls: 'b-closed' };
    if (isMin) return { icon: '─', cls: 'minimized', badge: 'Minimized', badgeCls: 'b-min' };
    return { icon: '●', cls: 'open', badge: 'Open', badgeCls: 'b-open' };
  },

  _windowsMenuRow(w) {
    const id = w.id;
    const title = w.title;
    const isClosed = this.isClosed(id);
    const isMin = this.isMinimized(id);
    const s = this._windowsMenuState(isClosed, isMin);
    const rowTitle = isClosed ? 'Click to open' : (isMin ? 'Click to restore' : 'Click to close');
    const toggle = isClosed
      ? `<button class="wm-mini-btn" data-action="open" data-win="${id}" title="Open ${title}">●</button>`
      : `<button class="wm-mini-btn" data-action="minimize" data-win="${id}" title="${isMin ? 'Restore' : 'Minimize'} ${title}">${isMin ? '□' : '─'}</button>
        <button class="wm-mini-btn" data-action="close" data-win="${id}" title="Close ${title}">✕</button>`;
    return `<div class="wm-item ${isClosed ? 'wm-closed' : ''}" data-win="${id}" title="${rowTitle} ${title}">
      <span class="wm-state-icon ${s.cls}">${s.icon}</span>
      <span class="wm-title">${title}</span>
      <span class="wm-badge ${s.badgeCls}">${s.badge}</span>
      <span class="wm-actions">${toggle}</span>
    </div>`;
  },

  _wireWindowsMenu(listEl) {
    listEl.querySelectorAll('.wm-item').forEach((el) => {
      el.addEventListener('click', (e) => {
        if (e.target.closest('.wm-actions')) return;
        const id = el.dataset.win;
        this.toggleWindow(id);
        this._renderWindowsMenu();
      });
    });
    listEl.querySelectorAll('.wm-mini-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = btn.dataset.win;
        const action = btn.dataset.action;
        if (action === 'minimize') this.toggleMinimize(id);
        else if (action === 'open') this.openWindow(id);
        else if (action === 'close') this.closeWindow(id);
        this._renderWindowsMenu();
      });
    });
  },

  _updateWindowsMenu() {
    const menu = document.getElementById('windowsMenu');
    if (!menu) return;
    if (!menu.classList.contains('hidden')) this._renderWindowsMenu();
  },

  _setupLayoutMenu() {
    const btn = document.getElementById('layoutMenuBtn');
    const menu = document.getElementById('layoutMenu');
    if (!btn || !menu) return;
    const place = () => {
      if (menu.classList.contains('hidden')) return;
      const r = btn.getBoundingClientRect();
      const width = menu.offsetWidth || Math.min(560, window.innerWidth - 16);
      const left = Math.max(8, Math.min(r.right - width, window.innerWidth - width - 8));
      menu.style.left = left + 'px';
      menu.style.top = (r.bottom + 6) + 'px';
    };
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const winMenu = document.getElementById('windowsMenu');
      if (winMenu) winMenu.classList.add('hidden');
      const willShow = menu.classList.contains('hidden');
      menu.classList.toggle('hidden');
      if (willShow) {
        if (typeof WindowPresets !== 'undefined') {
          WindowPresets.render();
          WindowPresets.refresh();
        }
      }
      place();
    });
    this._wireLayoutMenuActions(menu);
    this._dismissOutside('#layoutMenu', '#layoutMenuBtn', menu);
  },

  _wireLayoutMenuActions(menu) {
    menu.querySelectorAll('button[data-layout]').forEach((b) => {
      b.addEventListener('click', () => { menu.classList.add('hidden'); this.setLayout(b.dataset.layout); });
    });
    const resetBtn = document.getElementById('resetLayoutBtn');
    if (resetBtn) resetBtn.addEventListener('click', () => { menu.classList.add('hidden'); this.resetToDefault(); });
  },

  _dismissOutside(menuSel, btnSel, menu) {
    document.addEventListener('click', (e) => {
      if (!e.target.closest(menuSel) && !e.target.closest(btnSel)) menu.classList.add('hidden');
    });
  },
};
