/* ═══════════════════════════════════════════════════════════════
   sash-grid.js — DOM layer for the flexible grid ("sash layout")

   Renders the SashCore split tree into the #sashGrid container:
     • .sash-split  — flex row/column container (one node of the tree)
     • .sash-window — frame around ONE persistent panel element
     • .sash        — 6px draggable separator (col-resize / row-resize)

   Interactions
     • drag a window by its title bar (h3.win-title)
     • sash resize, double-click reset, Escape cancel
     • layout menu + windows menu (open/close/minimize/restore)

   Window states (open / minimized / closed)
     • open      — panel visible in the grid at its normal slot
     • minimized — the window releases its grid space (same mechanism as
                   closed) and its title bar docks in the strip at the
                   bottom edge (.sash-min-dock); click the strip to restore
     • closed    — hidden, reopened from the Windows dropdown

   Every open window title bar shows ─ (Minimize) and ✕ (Close). The
   docked strip shows □ (Restore/Maximize) and ✕. No full-grid maximize.
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const SashGrid = {
  STORAGE_KEY: 'chatbot.sashLayout.v1',
  STORAGE_CLOSED: 'chatbot.sashWindows.closed.v1',
  STORAGE_MINIMIZED: 'chatbot.sashWindows.minimized.v1',
  PRESET_FORMAT: 'chat-v-bot.window-preset',
  PRESET_SCHEMA_VERSION: 1,
  APP_VERSION: '0.1.0',

  THRESHOLD: 4,
  MIN_PX: 96,
  SASH_W: 6,

  gridEl: null,
  dockEl: null,
  root: null,
  winEls: {},
  _drag: null,
  _resize: null,

  closedWindows: null,
  minimizedWindows: null,

  WIN_ICONS: {
    stats: 'bar_chart', filters: 'filter_list', stack: 'view_list',
    config: 'tune', composer: 'chat', people: 'people', log: 'terminal',
    history: 'forum', userdb: 'storage', collector: 'radar',
    labels: 'sell', dbconn: 'dns',
  },

  init() {
    this.gridEl = document.getElementById('sashGrid');
    if (!this.gridEl) { console.warn('sash-grid: #sashGrid missing'); return; }
    this._ensureDock();

    const winElIds = {
      stats: 'winStats', filters: 'winFilters', stack: 'winStack',
      config: 'blockConfigPanel', composer: 'winComposer',
      people: 'winPeople', log: 'winLog',
      history: 'winHistory', userdb: 'winUserDb', collector: 'winCollector',
      labels: 'winLabels', dbconn: 'winDbconn',
    };
    for (const w of SashCore.WINDOWS) {
      const el = document.getElementById(winElIds[w.id]);
      if (!el) { console.warn('sash-grid: panel for \"' + w.id + '\" missing'); continue; }
      this.winEls[w.id] = el;
    }

    this.closedWindows = new Set();
    this.minimizedWindows = new Set();

    this.root = this._loadTree() || SashCore.defaultTree();
    this._loadWindowStates();
    this.render();
    this._loadFromBackend();

    this.gridEl.addEventListener('pointerdown', this._onDown = this._pointerDown.bind(this));
    this.gridEl.addEventListener('dblclick', this._onDbl = this._onDblClick.bind(this));
    this._setupLayoutMenu();
    this._setupWindowsMenu();
    this._setupVisibilityWatch();
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

  flushPersistence() {
    if (!this.root) return false;
    const payload = SashCore.serialize(this.root);
    try { localStorage.setItem(this.STORAGE_KEY, payload); } catch (e) {}
    try { this._saveWindowStates(); } catch (e) {}
    try {
      if (typeof App !== 'undefined' && App.bridge && typeof App.bridge.save_grid_layout === 'function') {
        App.bridge.save_grid_layout(payload);
        return true;
      }
    } catch (e) {
      console.warn('sash-grid: close-time backend save failed', e);
    }
    if (typeof App !== 'undefined' && App.recordGlobal) App.recordGlobal('grid', payload, { localOnly: true });
    return false;
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

  _screenSnapshot(rect) {
    const width = (typeof window !== 'undefined' && window.innerWidth) || rect.width || 1;
    const height = (typeof window !== 'undefined' && window.innerHeight) || rect.height || 1;
    const dpr = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
    return { width: Math.max(1, Math.round(width)), height: Math.max(1, Math.round(height)),
      device_pixel_ratio: Number(dpr) || 1 };
  },

  _portableBounds(id, gridRect, screen) {
    const panel = this.winEls[id];
    const rect = panel && typeof panel.getBoundingClientRect === 'function'
      ? panel.getBoundingClientRect() : { left: gridRect.left, top: gridRect.top, width: 0, height: 0 };
    const width = Math.max(1, gridRect.width || screen.width);
    const height = Math.max(1, gridRect.height || screen.height);
    const clamp = (value) => Math.max(0, Math.min(1, Number(value) || 0));
    const w = clamp(rect.width / width), h = clamp(rect.height / height);
    return { x: clamp((rect.left - gridRect.left) / width), y: clamp((rect.top - gridRect.top) / height),
      width: w, height: h };
  },

  createPortablePreset(name) {
    const rect = this.gridEl && this.gridEl.getBoundingClientRect
      ? this.gridEl.getBoundingClientRect() : { left: 0, top: 0, width: 1, height: 1 };
    const screen = this._screenSnapshot(rect);
    const states = this.getWindowStates();
    const closed = states.closed.slice();
    SashCore.WINDOW_IDS.forEach((id) => {
      const panel = this.winEls[id];
      if (!closed.includes(id) && !states.minimized.includes(id) &&
          panel && this._panelIsHidden(panel)) closed.push(id);
    });
    const effectiveStates = { closed, minimized: states.minimized.slice() };
    const windows = SashCore.WINDOWS.map((item) => {
      const state = effectiveStates.closed.includes(item.id) ? 'closed'
        : (effectiveStates.minimized.includes(item.id) ? 'minimized' : 'open');
      return { id: item.id, title: item.title, state,
        bounds: this._portableBounds(item.id, rect, screen) };
    });
    const now = new Date().toISOString();
    return { format: this.PRESET_FORMAT, schema_version: this.PRESET_SCHEMA_VERSION,
      app_version: this.APP_VERSION, name: String(name || '').trim() || 'Untitled preset',
      created_at: now, updated_at: now,
      grid: { type: 'sash-tree', version: SashCore.VERSION, window_count: windows.length,
        sizes_unit: 'percent', tree: SashCore.clone(this.root) },
      windows, window_states: effectiveStates, screen };
  },

  _portableStates(doc) {
    const state = doc.window_states;
    if (!state || !Array.isArray(state.closed) || !Array.isArray(state.minimized))
      return { ok: false, error: 'window_states must contain closed and minimized lists' };
    const known = (id) => typeof id === 'string' && SashCore.WINDOW_IDS.includes(id);
    if (!state.closed.every(known) || !state.minimized.every(known))
      return { ok: false, error: 'window_states contains an unknown window' };
    if (new Set(state.closed).size !== state.closed.length || new Set(state.minimized).size !== state.minimized.length)
      return { ok: false, error: 'window_states contains a duplicate window' };
    if (state.closed.some((id) => state.minimized.includes(id)))
      return { ok: false, error: 'closed and minimized window states overlap' };
    return { ok: true, states: { closed: state.closed.slice(), minimized: state.minimized.slice() } };
  },

  _portableWindows(doc, states) {
    if (!Array.isArray(doc.windows) || doc.windows.length !== SashCore.WINDOW_IDS.length)
      return { ok: false, error: 'windows do not contain the current window set' };
    const seen = new Set();
    for (const item of doc.windows) {
      if (!item || typeof item.id !== 'string' || seen.has(item.id) || !SashCore.WINDOW_IDS.includes(item.id))
        return { ok: false, error: 'windows contain an unknown or duplicate id' };
      const wanted = states.closed.includes(item.id) ? 'closed'
        : (states.minimized.includes(item.id) ? 'minimized' : 'open');
      if (item.state !== wanted || !this._validPortableBounds(item.bounds))
        return { ok: false, error: 'window state or normalized bounds are invalid' };
      seen.add(item.id);
    }
    if (seen.size !== SashCore.WINDOW_IDS.length)
      return { ok: false, error: 'windows do not contain the current window set' };
    return { ok: true };
  },

  _validPortableBounds(bounds) {
    if (!bounds || typeof bounds !== 'object') return false;
    const values = ['x', 'y', 'width', 'height'].map((key) => bounds[key]);
    if (!values.every((value) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1)) return false;
    return bounds.x + bounds.width <= 1.001 && bounds.y + bounds.height <= 1.001;
  },

  validatePortablePreset(raw) {
    let doc;
    try { doc = typeof raw === 'string' ? JSON.parse(raw) : SashCore.clone(raw); }
    catch (e) { return { ok: false, error: 'bad JSON: ' + e.message }; }
    if (!doc || typeof doc !== 'object' || Array.isArray(doc)) return { ok: false, error: 'document must be an object' };
    if (doc.format !== this.PRESET_FORMAT || doc.schema_version !== this.PRESET_SCHEMA_VERSION)
      return { ok: false, error: 'unsupported window preset format or schema version' };
    if (typeof doc.app_version !== 'string' || !doc.app_version.trim()) return { ok: false, error: 'app_version is required' };
    if (typeof doc.name !== 'string' || !doc.name.trim() || doc.name.trim().length > 80)
      return { ok: false, error: 'preset name must be 1–80 characters' };
    const grid = doc.grid;
    if (!grid || grid.type !== 'sash-tree' || grid.sizes_unit !== 'percent' || grid.window_count !== SashCore.WINDOW_IDS.length)
      return { ok: false, error: 'grid metadata is invalid' };
    const treeResult = SashCore.deserialize(JSON.stringify({ v: grid.version, tree: grid.tree }));
    if (!treeResult.ok) return { ok: false, error: 'invalid grid tree: ' + treeResult.error };
    const stateResult = this._portableStates(doc);
    if (!stateResult.ok) return stateResult;
    const windowResult = this._portableWindows(doc, stateResult.states);
    if (!windowResult.ok) return windowResult;
    const screen = doc.screen;
    const dpr = screen && screen.device_pixel_ratio === undefined
      ? 1 : screen && screen.device_pixel_ratio;
    if (!screen || typeof screen.width !== 'number' || !Number.isFinite(screen.width) ||
        typeof screen.height !== 'number' || !Number.isFinite(screen.height) ||
        screen.width <= 0 || screen.height <= 0 || typeof dpr !== 'number' ||
        !Number.isFinite(dpr) || dpr <= 0)
      return { ok: false, error: 'screen metadata is invalid' };
    const clean = SashCore.clone(doc);
    clean.name = clean.name.trim();
    clean.app_version = clean.app_version.trim();
    clean.screen.device_pixel_ratio = dpr;
    clean.grid.tree = treeResult.tree;
    clean.grid.version = SashCore.VERSION;
    return { ok: true, document: clean,
      warning: clean.app_version === this.APP_VERSION ? '' : 'preset was created by app ' + clean.app_version };
  },

  applyPortablePreset(raw) {
    const result = this.validatePortablePreset(raw);
    if (!result.ok) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('❌ Window preset not applied: ' + result.error, 'error');
      return false;
    }
    const doc = result.document;
    this.root = SashCore.clone(doc.grid.tree);
    this.closedWindows = new Set(doc.window_states.closed);
    this.minimizedWindows = new Set(doc.window_states.minimized);
    Object.values(this.winEls).forEach((panel) => {
      if (!panel) return;
      panel.classList.remove('hidden');
      if (panel.style && panel.style.display === 'none') panel.style.display = '';
    });
    this.render();
    this._save();
    this._saveWindowStates();
    if (typeof LogConsole !== 'undefined') LogConsole.log('✅ Window preset “' + doc.name + '” restored', 'success');
    return true;
  },

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

  /** Push all derived UI state (grid wrapper classes, empty splits, dock,
   *  windows menu, empty-grid hint) from the closed/minimized sets. */
  _applyStates() {
    this._syncHidden();
    this._syncEmptySplits();
    this._renderDock();
    this._updateWindowsMenu();
    this._checkEmptyGrid();
  },

  // ── minimized dock (bottom strip) ──────────────────────────

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
      const title = w.title || id;
      const chip = document.createElement('div');
      chip.className = 'sash-min-chip';
      chip.dataset.win = id;
      chip.title = 'Restore ' + title;
      const label = document.createElement('span');
      label.className = 'smc-label';
      label.textContent = title;
      chip.appendChild(label);
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
      chip.addEventListener('click', (e) => {
        if (e.target && e.target.closest && e.target.closest('button')) return;
        this.restoreMinimized(id);
      });
      restoreBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.restoreMinimized(id);
      });
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.closeWindow(id);
      });
      this.dockEl.appendChild(chip);
    });
  },

  // ── rendering ───────────────────────────────────────────────

  render() {
    const frag = this._buildNode(this.root, []);
    frag.style.flex = '1 1 0%';
    this.gridEl.replaceChildren(frag);
    this._ensureWindowControls();
    this._applyStates();
  },

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

  // ── window controls injection — CLEAN ICONS ──────────────────

  _ensureWindowControls() {
    if (!this.gridEl) return;
    this.gridEl.querySelectorAll('.sash-window').forEach((winEl) => {
      const id = winEl.dataset.win;
      const panel = winEl.querySelector(':scope > .panel');
      if (!panel) return;
      const title = panel.querySelector(':scope > .win-title');
      if (!title) return;
      let controls = title.querySelector('.win-controls');
      if (controls) {
        this._updateWindowControlIcons(title, id);
        return;
      }
      controls = document.createElement('span');
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
      toggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.toggleMinimize(id);
      });
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.closeWindow(id);
      });
      this._updateWindowControlIcons(title, id);
    });
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

  // ── hidden windows ──────────────────────────────────────────

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
  // split itself so no blank row remains.
  _syncEmptySplits() {
    if (!this.gridEl) return;
    // bottom-up so child splits are evaluated before parents
    const splits = Array.from(this.gridEl.querySelectorAll('.sash-split')).reverse();
    splits.forEach((splitEl) => {
      let hasVisibleDescendant = false;
      const checkVisible = (el) => {
        if (hasVisibleDescendant) return;
        if (!el.classList) return;
        if (el.classList.contains('sash-window')) {
          if (!el.classList.contains('sash-win-hidden') && !el.classList.contains('sash-win-closed')) {
            hasVisibleDescendant = true;
          }
        } else if (el.classList.contains('sash-split')) {
          if (el.classList.contains('sash-split-hidden')) return;
          Array.from(el.children).forEach(checkVisible);
        }
      };
      Array.from(splitEl.children).forEach(checkVisible);
      splitEl.classList.toggle('sash-split-hidden', !hasVisibleDescendant);
    });
    // also hide sashes that touch hidden splits/windows
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

  // ── windows menu — CLEAN ICONS ───────────────────────────────

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
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#windowsMenu') && !e.target.closest('#windowsMenuBtn')) menu.classList.add('hidden');
    });
  },

  _renderWindowsMenu() {
    const listEl = document.getElementById('windowsMenuList');
    if (!listEl) return;
    const items = SashCore.WINDOWS.map((w) => {
      const id = w.id;
      const title = w.title;
      const isClosed = this.isClosed(id);
      const isMin = this.isMinimized(id);
      let stateIcon, stateClass, badge, badgeClass;
      if (isClosed) {
        stateIcon = '○';
        stateClass = 'closed';
        badge = 'Closed';
        badgeClass = 'b-closed';
      } else if (isMin) {
        stateIcon = '─';
        stateClass = 'minimized';
        badge = 'Minimized';
        badgeClass = 'b-min';
      } else {
        stateIcon = '●';
        stateClass = 'open';
        badge = 'Open';
        badgeClass = 'b-open';
      }
      const rowTitle = isClosed ? 'Click to open' : (isMin ? 'Click to restore' : 'Click to close');
      const toggle = isClosed
        ? `<button class="wm-mini-btn" data-action="open" data-win="${id}" title="Open ${title}">●</button>`
        : `<button class="wm-mini-btn" data-action="minimize" data-win="${id}" title="${isMin ? 'Restore' : 'Minimize'} ${title}">${isMin ? '□' : '─'}</button>
          <button class="wm-mini-btn" data-action="close" data-win="${id}" title="Close ${title}">✕</button>`;
      return `<div class="wm-item ${isClosed ? 'wm-closed' : ''}" data-win="${id}" title="${rowTitle} ${title}">
        <span class="wm-state-icon ${stateClass}">${stateIcon}</span>
        <span class="wm-title">${title}</span>
        <span class="wm-badge ${badgeClass}">${badge}</span>
        <span class="wm-actions">${toggle}</span>
      </div>`;
    }).join('');
    listEl.innerHTML = items;
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

  _pointerDown(ev) {
    if (ev.button !== 0) return;
    if (this._drag || this._resize) return;
    const sashEl = ev.target.closest('.sash');
    if (sashEl) { this._startResize(sashEl, ev); return; }
    const title = ev.target.closest('.win-title');
    if (!title || !this.gridEl.contains(title)) return;
    if (ev.target.closest('button, input, select, textarea, a, .chip, .win-controls, .win-btn')) return;
    const winEl = title.closest('.sash-window');
    if (!winEl) return;
    if (winEl.classList.contains('sash-win-hidden') || winEl.classList.contains('sash-win-closed')) return;
    this._startDrag(winEl, ev);
  },

  _startDrag(winEl, ev) {
    this._drag = {
      active: false, winEl, id: winEl.dataset.win,
      startX: ev.clientX, startY: ev.clientY, pointerId: ev.pointerId,
      lastX: ev.clientX, lastY: ev.clientY,
      clone: null, badge: null, indicator: null,
      rects: null, sashes: null,
      lastSpec: null, lastSpecKey: null, targetEl: null,
    };
    this._onDragMove = this._dragMove.bind(this);
    this._onDragUp = this._dragUp.bind(this);
    this._onDragKey = (e) => { if (e.key === 'Escape') this._cancelDrag(); };
    document.addEventListener('pointermove', this._onDragMove, { passive: false });
    document.addEventListener('pointerup', this._onDragUp);
    document.addEventListener('pointercancel', this._onDragCancel = this._cancelDrag.bind(this));
    document.addEventListener('keydown', this._onDragKey, true);
  },

  _beginDrag() {
    const d = this._drag;
    d.active = true;
    d.rects = {};
    this.gridEl.querySelectorAll('.sash-window').forEach((w) => {
      if (w.classList.contains('sash-win-hidden') || w.classList.contains('sash-win-closed')) return;
      if (!w.offsetWidth || !w.offsetHeight) return;
      d.rects[w.dataset.win] = w.getBoundingClientRect();
    });
    d.sashes = [];
    this.gridEl.querySelectorAll('.sash').forEach((s) => {
      if (!s.offsetWidth && !s.offsetHeight) return;
      if (s.classList.contains('sash-hidden')) return;
      d.sashes.push({
        el: s, rect: s.getBoundingClientRect(),
        leftId: this._winIdOf(s.parentElement.children[+s.dataset.idx * 2]),
        rightId: this._winIdOf(s.parentElement.children[+s.dataset.idx * 2 + 2]),
      });
    });
    const rect = d.winEl.getBoundingClientRect();
    d.clone = this._buildDragVisual(d.winEl, d.id, rect);
    d.clone.style.transform = 'translate3d(' + rect.left + 'px,' + rect.top + 'px,0)';
    d.badge = document.createElement('div');
    d.badge.className = 'sash-drag-badge';
    document.body.appendChild(d.badge);
    d.indicator = document.createElement('div');
    d.indicator.className = 'sash-drop-indicator';
    d.indicator.style.display = 'none';
    document.body.appendChild(d.indicator);
    d.winEl.classList.add('sash-drag-source');
    document.body.classList.add('sash-dragging');
  },

  _buildDragVisual(winEl, id, rect) {
    if (winEl.querySelectorAll('*').length < 350) {
      const c = winEl.cloneNode(true);
      c.classList.add('sash-drag-clone');
      c.style.width = rect.width + 'px';
      c.style.height = rect.height + 'px';
      document.body.appendChild(c);
      return c;
    }
    const g = document.createElement('div');
    g.className = 'sash-drag-ghost';
    g.innerHTML = '<span style=\"font-size:18px\">◫</span><span>' + (SashCore.WINDOW_TITLES[id] || id) + '</span>';
    document.body.appendChild(g);
    return g;
  },

  _winIdOf(el) {
    if (!el) return null;
    if (el.dataset && el.dataset.win) return el.dataset.win;
    const inner = el && el.querySelector ? el.querySelector('.sash-window') : null;
    return inner ? inner.dataset.win : null;
  },

  _dragMove(ev) {
    const d = this._drag;
    if (!d) return;
    if (!d.active) {
      if (Math.abs(ev.clientX - d.startX) < this.THRESHOLD && Math.abs(ev.clientY - d.startY) < this.THRESHOLD) return;
      this._beginDrag();
    }
    ev.preventDefault();
    d.lastX = ev.clientX;
    d.lastY = ev.clientY;
    if (d.clone.classList.contains('sash-drag-ghost')) {
      d.clone.style.transform = 'translate3d(' + (ev.clientX + 14) + 'px,' + (ev.clientY + 14) + 'px,0)';
    } else {
      const r = d.winEl.getBoundingClientRect();
      const dx = d.startX - r.left, dy = d.startY - r.top;
      d.clone.style.transform = 'translate3d(' + (ev.clientX - dx) + 'px,' + (ev.clientY - dy) + 'px,0)';
    }
    const spec = this._computeSpec(ev.clientX, ev.clientY);
    const key = spec ? JSON.stringify(spec) : '';
    if (key !== d.lastSpecKey) {
      d.lastSpecKey = key;
      d.lastSpec = spec;
      this._showSpec(spec);
    }
  },

  _computeSpec(x, y) {
    const d = this._drag;
    for (const id of Object.keys(d.rects)) {
      if (id === d.id) continue;
      const r = d.rects[id];
      if (x < r.left || x >= r.right || y < r.top || y >= r.bottom) continue;
      const Z = Math.min(44, Math.max(20, 0.22 * Math.min(r.width, r.height)));
      let zone = 'center';
      if (x < r.left + Z) zone = 'left';
      else if (x > r.right - Z) zone = 'right';
      else if (y < r.top + Z) zone = 'top';
      else if (y > r.bottom - Z) zone = 'bottom';
      if (zone !== 'center') {
        const dir = (zone === 'left' || zone === 'right') ? 'row' : 'col';
        return { kind: 'edge', target: id, zone, dir, newFirst: (zone === 'left' || zone === 'top') };
      }
      const tEl = this.gridEl.querySelector('.sash-window[data-win=\"' + id + '\"]');
      const pEl = tEl && tEl.parentElement;
      if (!pEl || !pEl.classList.contains('sash-split')) {
        const midX = r.left + r.width / 2, midY = r.top + r.height / 2;
        const dir = Math.abs(x - midX) / (r.width / 2) >= Math.abs(y - midY) / (r.height / 2) ? 'row' : 'col';
        const newFirst = dir === 'row' ? x < midX : y < midY;
        return { kind: 'edge', target: id, zone: dir === 'row' ? (newFirst ? 'left' : 'right') : (newFirst ? 'top' : 'bottom'), dir, newFirst };
      }
      const isRow = pEl.classList.contains('sash-row');
      const side = isRow ? (x < r.left + r.width / 2 ? 'before' : 'after') : (y < r.top + r.height / 2 ? 'before' : 'after');
      return { kind: 'sibling', target: id, side, zone: side === 'before' ? (isRow ? 'left' : 'top') : (isRow ? 'right' : 'bottom') };
    }
    for (const s of d.sashes) {
      const r = s.rect;
      if (x < r.left || x >= r.right || y < r.top || y >= r.bottom) continue;
      return { kind: 'sash', left: s.leftId, right: s.rightId };
    }
    return null;
  },

  _showSpec(spec) {
    const d = this._drag;
    if (d.targetEl) d.targetEl.classList.remove('sash-drag-target');
    d.targetEl = null;
    if (!spec) {
      d.indicator.style.display = 'none';
      d.badge.style.display = 'none';
      d.badge.textContent = '';
      return;
    }
    d.badge.style.display = '';
    const draggedTitle = SashCore.WINDOW_TITLES[d.id] || d.id;
    let text, bar = null;
    if (spec.kind === 'edge') {
      const r = d.rects[spec.target];
      const tEl = this.gridEl.querySelector('.sash-window[data-win=\"' + spec.target + '\"]');
      if (tEl) { tEl.classList.add('sash-drag-target'); d.targetEl = tEl; }
      text = draggedTitle + ' → ' + spec.zone + ' of ' + (SashCore.WINDOW_TITLES[spec.target] || spec.target);
      if (spec.dir === 'row') bar = { left: r.left + r.width / 2 - 1.5, top: r.top, width: 3, height: r.height };
      else bar = { left: r.left, top: r.top + r.height / 2 - 1.5, width: r.width, height: 3 };
    } else if (spec.kind === 'sibling') {
      const r = d.rects[spec.target];
      const tEl = this.gridEl.querySelector('.sash-window[data-win=\"' + spec.target + '\"]');
      const pEl = tEl && tEl.parentElement;
      if (tEl) { tEl.classList.add('sash-drag-target'); d.targetEl = tEl; }
      const pRect = pEl ? pEl.getBoundingClientRect() : r;
      text = draggedTitle + ' → ' + spec.zone + ' of ' + (SashCore.WINDOW_TITLES[spec.target] || spec.target);
      if (!pEl) bar = null;
      else if (pEl.classList.contains('sash-row')) {
        const x = spec.zone === 'left' ? r.left : r.right;
        bar = { left: x - 1.5, top: pRect.top, width: 3, height: pRect.height };
      } else {
        const y = spec.zone === 'top' ? r.top : r.bottom;
        bar = { left: pRect.left, top: y - 1.5, width: pRect.width, height: 3 };
      }
    } else if (spec.kind === 'sash') {
      const hit = d.sashes.find((s) => s.leftId === spec.left && s.rightId === spec.right);
      const sEl = hit && hit.el;
      if (sEl) {
        sEl.classList.add('sash-target');
        const pEl = sEl.parentElement;
        const sr = hit.rect;
        const pRect = pEl.getBoundingClientRect();
        if (pEl.classList.contains('sash-row')) bar = { left: sr.left + sr.width / 2 - 1.5, top: pRect.top, width: 3, height: pRect.height };
        else bar = { left: pRect.left, top: sr.top + sr.height / 2 - 1.5, width: pRect.width, height: 3 };
      }
      text = draggedTitle + ' → between ' + (SashCore.WINDOW_TITLES[spec.left] || spec.left) + ' and ' + (SashCore.WINDOW_TITLES[spec.right] || spec.right);
    }
    d.badge.textContent = text;
    d.badge.style.transform = 'translate3d(' + (d.lastX + 16) + 'px,' + (d.lastY + 18) + 'px,0)';
    if (bar) {
      d.indicator.style.display = '';
      d.indicator.style.left = bar.left + 'px';
      d.indicator.style.top = bar.top + 'px';
      d.indicator.style.width = bar.width + 'px';
      d.indicator.style.height = bar.height + 'px';
    } else d.indicator.style.display = 'none';
  },

  _dragUp() {
    const d = this._drag;
    if (!d) return;
    const spec = d.active ? d.lastSpec : null;
    this._cleanupDrag();
    if (spec) {
      this._applyDrop(d.id, spec);
      this.render();
      this._save();
      this._flashLanded(d.id);
      if (typeof LogConsole !== 'undefined') LogConsole.log('🧩 ' + (SashCore.WINDOW_TITLES[d.id] || d.id) + ' → ' + this._specText(spec) + ' (grid updated)', 'info');
    } else if (d.active) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('↩ Window drag cancelled — layout unchanged', 'warn');
    }
  },

  _cancelDrag() {
    const d = this._drag;
    if (!d) return;
    this._cleanupDrag();
    if (d.active && typeof LogConsole !== 'undefined') LogConsole.log('↩ Window drag cancelled — layout unchanged', 'warn');
  },

  _cleanupDrag() {
    const d = this._drag;
    if (!d) return;
    document.removeEventListener('pointermove', this._onDragMove, { passive: false });
    document.removeEventListener('pointerup', this._onDragUp);
    document.removeEventListener('pointercancel', this._onDragCancel);
    document.removeEventListener('keydown', this._onDragKey, true);
    if (d.clone && d.clone.parentNode) d.clone.parentNode.removeChild(d.clone);
    if (d.badge && d.badge.parentNode) d.badge.parentNode.removeChild(d.badge);
    if (d.indicator && d.indicator.parentNode) d.indicator.parentNode.removeChild(d.indicator);
    if (d.targetEl) d.targetEl.classList.remove('sash-drag-target');
    this.gridEl.querySelectorAll('.sash-target').forEach((s) => s.classList.remove('sash-target'));
    if (d.winEl && d.winEl.isConnected) d.winEl.classList.remove('sash-drag-source');
    document.body.classList.remove('sash-dragging');
    this._drag = null;
  },

  _specText(spec) {
    if (spec.kind === 'sash') return 'between ' + (SashCore.WINDOW_TITLES[spec.left] || spec.left) + ' and ' + (SashCore.WINDOW_TITLES[spec.right] || spec.right);
    return spec.zone + ' of ' + (SashCore.WINDOW_TITLES[spec.target] || spec.target);
  },

  _flashLanded(winId) {
    const el = this.gridEl.querySelector('.sash-window[data-win=\"' + winId + '\"]');
    if (!el) return;
    el.classList.remove('sash-landed');
    void el.offsetWidth;
    el.classList.add('sash-landed');
    setTimeout(() => el.classList.remove('sash-landed'), 700);
  },

  _applyDrop(draggedId, spec) {
    this.root = SashCore.moveWindow(this.root, draggedId, {
      kind: spec.kind, target: spec.target, dir: spec.dir, newFirst: spec.newFirst, side: spec.side, left: spec.left, right: spec.right,
    });
    return this.root;
  },

  _startResize(sashEl, ev) {
    const pEl = sashEl.parentElement;
    if (!pEl || !pEl.classList.contains('sash-split')) return;
    const sIdx = parseInt(sashEl.dataset.idx, 10);
    const isRow = pEl.classList.contains('sash-row');
    const childEls = [];
    for (let i = 0; i * 2 < pEl.children.length; i++) childEls.push(pEl.children[i * 2]);
    const axisSize = (el) => { const r = el.getBoundingClientRect(); return isRow ? r.width : r.height; };
    const childSizes = childEls.map(axisSize);
    const sashSizes = Array.from(pEl.children).filter((el) => el.classList.contains('sash')).map(axisSize);
    const z = { pEl, sashEl, sIdx, isRow, childEls, pointerId: ev.pointerId, childSizes, sashSizes, otherWidths: {}, originalFlex: childEls.map((child) => child.style.flex), pointerCaptured: false };
    for (let i = 0; i < childSizes.length; i++) { if (i === sIdx || i === sIdx + 1) continue; z.otherWidths[i] = childSizes[i]; }
    this._resize = z;
    if (ev.pointerId != null && typeof sashEl.setPointerCapture === 'function') {
      try { sashEl.setPointerCapture(ev.pointerId); z.pointerCaptured = true; } catch (e) {}
    }
    sashEl.classList.add('sash-active');
    document.body.classList.add(isRow ? 'sash-resizing-row' : 'sash-resizing-col');
    this._onResizeMove = this._resizeMove.bind(this);
    this._onResizeUp = this._resizeUp.bind(this);
    document.addEventListener('pointermove', this._onResizeMove, { passive: false });
    document.addEventListener('pointerup', this._onResizeUp);
    document.addEventListener('pointercancel', this._onResizeCancel = () => this._cancelResize(true));
    document.addEventListener('keydown', this._onResizeKey = (keyEvent) => {
      if (keyEvent.key === 'Escape') { keyEvent.preventDefault(); this._cancelResize(true); }
    }, true);
    ev.preventDefault();
  },

  _resizePixelAllocation(z, pointer, rect) {
    const axis = z.isRow ? rect.width : rect.height;
    const sashTotal = z.sashSizes.reduce((sum, size) => sum + Math.max(0, size), 0);
    let others = 0;
    for (const k of Object.keys(z.otherWidths)) others += Math.max(0, z.otherWidths[k]);
    const span = axis - others - sashTotal;
    if (span < this.MIN_PX * 2) return null;
    let prefix = 0;
    for (let i = 0; i < z.sIdx; i++) { prefix += Math.max(0, z.childSizes[i]); prefix += Math.max(0, z.sashSizes[i] || 0); }
    const start = (z.isRow ? rect.left : rect.top) + prefix;
    const requested = pointer - start;
    const first = Math.min(Math.max(requested, this.MIN_PX), span - this.MIN_PX);
    const allocation = z.childSizes.slice();
    allocation[z.sIdx] = first;
    allocation[z.sIdx + 1] = span - first;
    return allocation;
  },

  _resizeMove(ev) {
    const z = this._resize;
    if (!z) return;
    ev.preventDefault();
    const rect = z.pEl.getBoundingClientRect();
    const allocation = this._resizePixelAllocation(z, z.isRow ? ev.clientX : ev.clientY, rect);
    if (!allocation) return;
    z.childEls.forEach((child, i) => { const px = allocation[i]; child.style.flex = px > 0 ? `0 0 ${px}px` : '0 0 0px'; });
  },

  _resizeUp() {
    const z = this._resize;
    if (!z) return;
    this._cancelResize(false);
    const rect = z.pEl.getBoundingClientRect();
    const total = z.isRow ? rect.width : rect.height;
    const sashTotal = z.sashSizes.reduce((sum, size) => sum + Math.max(0, size), 0);
    const denom = Math.max(1, total - sashTotal);
    const path = this._parsePath(z.pEl.dataset.path);
    const p = SashCore.nodeAtPath(this.root, path);
    const prev = p ? p.sizes : null;
    const sizes = z.childEls.map((el, i) => {
      const r = el.getBoundingClientRect();
      const w = z.isRow ? r.width : r.height;
      if (w > 1) return (Math.max(w, this.MIN_PX) / denom) * 100;
      return prev ? prev[i] : 100 / z.childEls.length;
    });
    this.root = SashCore.setSplitSizesByPath(this.root, path, sizes);
    this.render();
    this._save();
    if (typeof LogConsole !== 'undefined') LogConsole.log('📏 Grid resized', 'info');
  },

  _cancelResize(restore = true) {
    const z = this._resize;
    if (!z) return;
    document.removeEventListener('pointermove', this._onResizeMove, { passive: false });
    document.removeEventListener('pointerup', this._onResizeUp);
    document.removeEventListener('pointercancel', this._onResizeCancel);
    document.removeEventListener('keydown', this._onResizeKey, true);
    if (restore) z.childEls.forEach((child, i) => { child.style.flex = z.originalFlex[i]; });
    if (z.pointerCaptured && typeof z.sashEl.releasePointerCapture === 'function') {
      try { z.sashEl.releasePointerCapture(z.pointerId); } catch (e) {}
    }
    z.sashEl.classList.remove('sash-active');
    document.body.classList.remove('sash-resizing-row', 'sash-resizing-col');
    this._resize = null;
  },

  _onDblClick(ev) {
    const sashEl = ev.target.closest('.sash');
    if (!sashEl) return;
    const pEl = sashEl.parentElement;
    if (!pEl || !pEl.classList.contains('sash-split')) return;
    const n = (pEl.children.length + 1) / 2;
    const path = this._parsePath(pEl.dataset.path);
    this.root = SashCore.setSplitSizesByPath(this.root, path, new Array(n).fill(100 / n));
    this.render();
    this._save();
    if (typeof LogConsole !== 'undefined') LogConsole.log('📏 Split reset to even sizes', 'info');
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
    menu.querySelectorAll('button[data-layout]').forEach((b) => {
      b.addEventListener('click', () => { menu.classList.add('hidden'); this.setLayout(b.dataset.layout); });
    });
    const resetBtn = document.getElementById('resetLayoutBtn');
    if (resetBtn) resetBtn.addEventListener('click', () => { menu.classList.add('hidden'); this.resetToDefault(); });
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#layoutMenu') && !e.target.closest('#layoutMenuBtn')) menu.classList.add('hidden');
    });
  },

  getTree() { return SashCore.clone(this.root); },
  getWindowStates() {
    return { closed: Array.from(this.closedWindows), minimized: Array.from(this.minimizedWindows) };
  },

  simulateDrop(draggedId, targetId, zone) {
    const drop =
      zone === 'before' ? { kind: 'sibling', target: targetId, side: 'before' } :
      zone === 'after'  ? { kind: 'sibling', target: targetId, side: 'after' } :
      zone === 'left'   ? { kind: 'edge', target: targetId, dir: 'row', newFirst: true } :
      zone === 'right'  ? { kind: 'edge', target: targetId, dir: 'row', newFirst: false } :
      zone === 'top'    ? { kind: 'edge', target: targetId, dir: 'col', newFirst: true } :
      zone === 'bottom' ? { kind: 'edge', target: targetId, dir: 'col', newFirst: false } :
                          (() => { throw new Error('simulateDrop: bad zone ' + zone); })();
    this.root = SashCore.moveWindow(this.root, draggedId, drop);
    this.render();
    this._save();
    return this.getTree();
  },

  simulateResize(pathStr, firstPct) {
    const path = this._parsePath(pathStr);
    const p = SashCore.nodeAtPath(this.root, path);
    if (!p) throw new Error('simulateResize: bad path ' + pathStr);
    const sizes = p.sizes.slice();
    const min = SashCore.MIN_SIZE || 4;
    const maxFirst = 100 - min * (sizes.length - 1);
    sizes[0] = Math.max(min, Math.min(Number(firstPct) || min, maxFirst));
    const rest = 100 - sizes[0];
    const restSum = sizes.slice(1).reduce((a, b) => a + b, 0) || 1;
    for (let i = 1; i < sizes.length; i++) sizes[i] = rest * (sizes[i] / restSum);
    this.root = SashCore.setSplitSizesByPath(this.root, path, sizes);
    this.render();
    this._save();
    return this.getTree();
  },
};

(window.BridgeReady || { ready: (fn) => document.addEventListener('DOMContentLoaded', () => fn(null)) })
  .ready(() => SashGrid.init());
