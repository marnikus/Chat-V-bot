/* sash-grid part — sash-grid-menus.js (Round H, H-A3/H-A6)

Three collaborating objects:
  SashGridMenus        the Windows dropdown (state + actions)
  SashGridDock         the bottom minimize dock strip + chips
  SashGridLayoutMenu   the Layout dropdown (presets, reset, dismiss)
All merge onto the SashGrid facade — see ui/js/sash-grid.js.
   */
const SashGridMenus = {
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
};


const SashGridDock = {
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
};


const SashGridLayoutMenu = {
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
