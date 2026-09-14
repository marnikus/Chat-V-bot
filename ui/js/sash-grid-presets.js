/* sash-grid part — sash-grid-presets.js (Round H, H-A3) */

const SashGridPresets = {
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

  /**
   * Adaptive validation of a portable preset document (2026-09-14):
   * window-set drift is repaired and REPORTED (PresetAdapt), structural
   * corruption still refuses. The canonical output carries the CURRENT
   * window set, so re-saving an imported document round-trips strictly.
   */
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
    const entries = Array.isArray(doc.windows) ? doc.windows : null;
    if (!grid || grid.type !== 'sash-tree' || grid.sizes_unit !== 'percent' ||
        (entries && grid.window_count !== entries.length))
      return { ok: false, error: 'grid metadata is invalid' };
    const treeRes = PresetAdapt.adaptTree(grid.tree, grid.version);
    if (!treeRes.ok) return { ok: false, error: 'invalid grid tree: ' + treeRes.error };
    const statesRes = PresetAdapt.adaptStates(doc.window_states);
    if (!statesRes.ok) return statesRes;
    const winsRes = PresetAdapt.adaptWindows(entries, statesRes.states);
    if (!winsRes.ok) return winsRes;
    return this._cleanPortablePreset(doc, treeRes, statesRes, winsRes);
  },

  _portableScreen(doc) {
    const screen = doc.screen;
    const dpr = screen && screen.device_pixel_ratio === undefined
      ? 1 : screen && screen.device_pixel_ratio;
    if (!screen || typeof screen.width !== 'number' || !Number.isFinite(screen.width) ||
        typeof screen.height !== 'number' || !Number.isFinite(screen.height) ||
        screen.width <= 0 || screen.height <= 0 || typeof dpr !== 'number' ||
        !Number.isFinite(dpr) || dpr <= 0)
      return null;
    return dpr;
  },

  _cleanPortablePreset(doc, treeRes, statesRes, winsRes) {
    const dpr = this._portableScreen(doc);
    if (dpr === null) return { ok: false, error: 'screen metadata is invalid' };
    const clean = SashCore.clone(doc);
    clean.name = clean.name.trim();
    clean.app_version = clean.app_version.trim();
    clean.screen.device_pixel_ratio = dpr;
    clean.grid = { type: 'sash-tree', version: SashCore.VERSION,
      window_count: SashCore.WINDOW_IDS.length, sizes_unit: 'percent',
      tree: treeRes.tree };
    clean.windows = winsRes.windows;
    clean.window_states = statesRes.states;
    return { ok: true, document: clean,
      report: PresetAdapt.buildReport(treeRes, statesRes, winsRes, winsRes.windows),
      warning: clean.app_version === this.APP_VERSION ? '' : 'preset was created by app ' + clean.app_version };
  },

  applyPortablePreset(raw) {
    const result = this.validatePortablePreset(raw);
    if (!result.ok) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('❌ Window preset not applied: ' + result.error, 'error');
      return { ok: false, error: result.error };
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
    this._enforceMinimums();
    this.render();
    this._save();
    this._saveWindowStates();
    if (typeof LogConsole !== 'undefined') {
      LogConsole.log('✅ Window preset “' + doc.name + '” restored — ' +
        result.report.applied.length + ' windows placed' +
        PresetAdapt.reportSummary(result.report), 'success');
    }
    return { ok: true, report: result.report };
  },
};
