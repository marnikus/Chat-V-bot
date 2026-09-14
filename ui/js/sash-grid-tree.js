/* sash-grid part — sash-grid-tree.js (Round H, H-A3)

   Two collaborating objects (H-A6, RULE 16 object cap):
     SashGridTree             node building + the per-window title controls
     SashGridTreeVisibility   hidden/closed/minimized sync, empty-split and
                              empty-grid state, the visibility watch
   Both merge onto the SashGrid facade — see ui/js/sash-grid.js.
   */

const SashGridTree = {
  _buildNode(node, path) {
    if (SashCore.isLeaf(node)) {
      const win = document.createElement('div');
      win.className = 'sash-window';
      win.dataset.win = node.id;
      const panel = this.winEls[node.id];
      if (panel) win.appendChild(panel);
      return win;
    }
    const el = document.createElement('div');
    el.className = 'sash-split sash-' + node.dir;
    el.dataset.path = path.join('-');
    const n = node.children.length;
    node.children.forEach((child, i) => {
      el.appendChild(this._buildNode(child, path.concat(i)));
      const childEl = el.children[i * 2];
      childEl.style.flex = node.sizes[i] + ' 1 0%';
      if (i < n - 1) {
        const sash = document.createElement('div');
        sash.className = 'sash ' + (node.dir === 'row' ? 'sash-v' : 'sash-h');
        sash.dataset.idx = String(i);
        el.appendChild(sash);
      }
    });
    return el;
  },

  _parsePath(p) {
    return String(p == null ? '' : p).split('-').filter((s) => s !== '').map(Number);
  },

  // ── window controls injection — CLEAN ICONS ──────────────────,

  _ensureWindowControls() {
    if (!this.gridEl) return;
    this.gridEl.querySelectorAll('.sash-window').forEach((winEl) => {
      const id = winEl.dataset.win;
      const panel = winEl.querySelector(':scope > .panel');
      if (!panel) return;
      const title = panel.querySelector(':scope > .win-title');
      if (!title) return;
      const controls = title.querySelector('.win-controls');
      if (controls) {
        this._updateWindowControlIcons(title, id);
        return;
      }
      this._createWindowControls(title, id);
    });
  },

  _createWindowControls(title, id) {
    const controls = document.createElement('span');
    controls.className = 'win-controls';
    // Standard window-control glyphs (dark theme): ─ minimize/restore
    // toggle + ✕ close. The toggle swaps to □ while the window is
    // minimized (visible on the dock strip / windows menu).
    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'win-btn win-toggle';
    toggleBtn.textContent = '─';
    toggleBtn.title = 'Minimize';
    const closeBtn = document.createElement('button');
    closeBtn.className = 'win-btn win-close';
    closeBtn.textContent = '✕';
    closeBtn.title = 'Close';
    controls.appendChild(toggleBtn);
    controls.appendChild(closeBtn);
    this._attachWindowControls(title, controls);
    toggleBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      this.toggleMinimize(id);
    });
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      this.closeWindow(id);
    });
    this._updateWindowControlIcons(title, id);
  },

  _attachWindowControls(title, controls) {
    const existingClose = title.querySelector('#closeConfigBtn');
    if (existingClose) existingClose.style.display = 'none';
    const spacer = title.querySelector('.spacer');
    if (spacer) {
      title.appendChild(controls);
    } else {
      const sp = document.createElement('span');
      sp.className = 'spacer';
      title.appendChild(sp);
      title.appendChild(controls);
    }
  },

  _updateWindowControlIcons(title, id) {
    const toggleBtn = title.querySelector('.win-toggle');
    const closeBtn = title.querySelector('.win-close');
    if (!toggleBtn || !closeBtn) return;
    const name = SashCore.WINDOW_TITLES[id] || id;
    const isMin = this.isMinimized(id);
    // ─ while open (minimize); □ once minimized (restore). A minimized
    // window's title bar is docked at the bottom, so in the grid the toggle
    // is normally seen as ─ only — the □ state lives on the dock strip and
    // in the Windows dropdown (FULL SPEC toggle pair).
    toggleBtn.textContent = isMin ? '□' : '─';
    toggleBtn.title = (isMin ? 'Restore ' : 'Minimize ') + name;
    closeBtn.textContent = '✕';
    closeBtn.title = 'Close ' + name;
  },
};

const SashGridTreeVisibility = {
  // ── hidden windows ──────────────────────────────────────────,

  _panelIsHidden(panel) {
    if (!panel) return false;
    if (panel.classList.contains('hidden')) return true;
    if (panel.style && panel.style.display === 'none') return true;
    try { return getComputedStyle(panel).display === 'none'; } catch (e) { return false; }
  },

  _syncHidden() {
    if (!this.gridEl) return;
    this.gridEl.querySelectorAll('.sash-window').forEach((winEl) => {
      const id = winEl.dataset.win;
      const panel = winEl.querySelector(':scope > .panel');
      const isClosed = this.closedWindows.has(id);
      const isMinimized = this.minimizedWindows.has(id);
      const isHiddenByPanel = this._panelIsHidden(panel);
      // minimized windows release their grid slot exactly like closed ones —
      // the wrapper gets display:none so the visible siblings expand into it.
      const shouldHide = isClosed || isMinimized || isHiddenByPanel;
      winEl.classList.toggle('sash-win-hidden', shouldHide);
      winEl.classList.toggle('sash-win-closed', isClosed);
    });
    this.gridEl.querySelectorAll('.sash-split').forEach((pEl) => {
      const kids = Array.from(pEl.children);
      kids.forEach((el, i) => {
        if (!el.classList || !el.classList.contains('sash')) return;
        const prev = kids[i - 1], next = kids[i + 1];
        const nearHidden = (prev && prev.classList.contains('sash-win-hidden')) ||
                           (next && next.classList.contains('sash-win-hidden'));
        el.classList.toggle('sash-hidden', !!nearHidden);
      });
    });
  },

  // ── FIX FOR BUG #2: empty rows / splits ──────────────────────
  // If all descendant windows of a split are closed/hidden (a minimized
  // window counts as hidden — its content moved to the bottom dock), hide the
  // split itself so no blank row remains.,

  _splitHasVisibleDescendant(splitEl) {
    let visible = false;
    const checkVisible = (el) => {
      if (visible) return;
      if (!el.classList) return;
      if (el.classList.contains('sash-window')) {
        if (!el.classList.contains('sash-win-hidden') && !el.classList.contains('sash-win-closed')) {
          visible = true;
        }
      } else if (el.classList.contains('sash-split')) {
        if (el.classList.contains('sash-split-hidden')) return;
        Array.from(el.children).forEach(checkVisible);
      }
    };
    Array.from(splitEl.children).forEach(checkVisible);
    return visible;
  },

  _syncEmptySplits() {
    if (!this.gridEl) return;
    // bottom-up so child splits are evaluated before parents
    const splits = Array.from(this.gridEl.querySelectorAll('.sash-split')).reverse();
    splits.forEach((splitEl) => {
      splitEl.classList.toggle('sash-split-hidden', !this._splitHasVisibleDescendant(splitEl));
    });
    // also hide sashes that touch hidden splits/windows
    this._hideTouchedSashes();
  },

  _hideTouchedSashes() {
    this.gridEl.querySelectorAll('.sash-split').forEach((pEl) => {
      if (pEl.classList.contains('sash-split-hidden')) return;
      const kids = Array.from(pEl.children);
      kids.forEach((el, i) => {
        if (!el.classList || !el.classList.contains('sash')) return;
        const prev = kids[i - 1], next = kids[i + 1];
        const prevHidden = prev && (prev.classList.contains('sash-win-hidden') || prev.classList.contains('sash-win-closed') || prev.classList.contains('sash-split-hidden'));
        const nextHidden = next && (next.classList.contains('sash-win-hidden') || next.classList.contains('sash-win-closed') || next.classList.contains('sash-split-hidden'));
        if (prevHidden || nextHidden) el.classList.add('sash-hidden');
      });
    });
  },

  _checkEmptyGrid() {
    if (!this.gridEl) return;
    const existing = this.gridEl.querySelector('.sash-grid-empty');
    if (existing) existing.remove();
    const visible = this.gridEl.querySelectorAll('.sash-window:not(.sash-win-hidden):not(.sash-win-closed)');
    const hasVisible = visible.length > 0;
    if (!hasVisible) {
      const allMinimized = this.minimizedWindows.size > 0 && this.closedWindows.size === 0;
      const empty = document.createElement('div');
      empty.className = 'sash-grid-empty';
      empty.innerHTML = allMinimized
        ? '<div style="font-size:28px">▁</div><div>All windows are minimized</div><div style="font-size:11px;opacity:.8">Click a strip at the <b>bottom edge</b> to restore a window</div><button class="btn-small" id="emptyShowAllBtn" style="margin-top:8px">Show all windows</button>'
        : '<div style="font-size:28px">◫</div><div>All windows are closed</div><div style="font-size:11px;opacity:.8">Open windows from the <b>Windows</b> menu in the top bar</div><button class="btn-small" id="emptyShowAllBtn" style="margin-top:8px">Show all windows</button>';
      this.gridEl.appendChild(empty);
      const btn = empty.querySelector('#emptyShowAllBtn');
      if (btn) btn.addEventListener('click', () => {
        this.showAllWindows();
        this.render();
        this._save();
      });
    }
  },

  _setupVisibilityWatch() {
    const mo = new MutationObserver(() => {
      let changed = false;
      this.gridEl.querySelectorAll('.sash-window').forEach((winEl) => {
        const id = winEl.dataset.win;
        const panel = winEl.querySelector(':scope > .panel');
        const panelHidden = this._panelIsHidden(panel);
        const shouldHide = this.closedWindows.has(id) || this.minimizedWindows.has(id) || panelHidden;
        if (winEl.classList.contains('sash-win-hidden') !== shouldHide) changed = true;
        winEl.classList.toggle('sash-win-hidden', shouldHide);
      });
      if (changed) {
        this._syncHidden();
        this._syncEmptySplits();
        this._updateWindowsMenu();
        this._checkEmptyGrid();
      }
    });
    Object.values(this.winEls).forEach((el) => {
      mo.observe(el, { attributes: true, attributeFilter: ['class', 'style'] });
    });
  },
};
