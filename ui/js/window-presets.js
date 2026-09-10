/* WindowPresets — named grid snapshots, portable JSON transfer, and preview. */
'use strict';

const WindowPresets = {
  LOCAL_KEY: 'chatbot.windowPresets.v1',
  presets: [],
  selectedName: '',
  pending: null,
  initialized: false,

  init() {
    if (this.initialized) return;
    this.initialized = true;
    this._bindButton('saveWindowPresetBtn', () => this.saveCurrent());
    this._bindButton('importWindowPresetBtn', () => this._openFilePicker());
    this._bindButton('exportWindowPresetBtn', () => this.exportSelected());
    this._bindButton('windowPresetPreviewApply', () => this._applyPreview());
    this._bindButton('windowPresetPreviewCancel', () => this._closePreview());
    const input = document.getElementById('windowPresetFileInput');
    if (input) input.addEventListener('change', (event) => this._readFile(event));
    this._loadLocal();
  },

  _bindButton(id, action) {
    const element = document.getElementById(id);
    if (element) element.addEventListener('click', (event) => {
      event.stopPropagation();
      action();
    });
  },

  _loadLocal() {
    try {
      const raw = localStorage.getItem(this.LOCAL_KEY);
      if (raw) this.setPresets(raw);
    } catch (e) { /* backend remains authoritative */ }
  },

  setPresets(raw) {
    try {
      const value = typeof raw === 'string' ? JSON.parse(raw) : raw;
      const list = Array.isArray(value) ? value : [];
      this.presets = list.filter((item) => item && typeof item.name === 'string')
        .map((item) => ({
          name: item.name,
          window_count: item.window_count || (item.grid && item.grid.window_count) || 0,
          updated_at: item.updated_at || '',
          app_version: item.app_version || '',
        }));
    } catch (e) { this.presets = []; }
    if (!this.presets.some((item) => item.name === this.selectedName))
      this.selectedName = this.presets[0] ? this.presets[0].name : '';
    this.render();
  },

  refresh() {
    if (typeof App !== 'undefined' && App.bridge && App.bridge.list_window_presets) {
      App.bridge.list_window_presets((raw) => this.setPresets(raw));
    }
  },

  saveCurrent() {
    if (typeof SashGrid === 'undefined' || !SashGrid.root) {
      this._message('No grid layout is ready to save.', 'warn');
      return;
    }
    Dialog.promptName('Save window preset', 'e.g. Research desk', 'Save', (name) => {
      const document = SashGrid.createPortablePreset(name);
      this._persistDocument(document);
    });
  },

  _persistDocument(document, imported = false) {
    const checked = SashGrid.validatePortablePreset(document);
    if (!checked.ok) {
      this._message('Preset was not saved: ' + checked.error, 'error');
      return;
    }
    const clean = checked.document;
    this.selectedName = clean.name;
    const bridge = typeof App !== 'undefined' ? App.bridge : null;
    if (!bridge || !bridge.save_window_preset) {
      this._saveLocalDocument(clean);
      this._message('Window preset “' + clean.name + '” saved locally.', 'success');
      return;
    }
    const done = (ok) => {
      if (!ok) {
        this._message('Preset “' + clean.name + '” could not be written.', 'error');
        return;
      }
      this.selectedName = clean.name;
      this.refresh();
      this._message((imported ? 'Imported' : 'Saved') + ' window preset “' + clean.name + '”.', 'success');
    };
    try {
      const result = bridge.save_window_preset(clean.name, JSON.stringify(clean), done);
      if (typeof result === 'boolean') done(result);
    } catch (error) { done(false); }
  },

  _saveLocalDocument(document) {
    const map = this._localDocuments();
    map[document.name] = document;
    try { localStorage.setItem(this.LOCAL_KEY, JSON.stringify(Object.values(map))); }
    catch (e) { /* the UI still reports the attempted save */ }
    this.setPresets(Object.values(map).map((item) => ({
      name: item.name, window_count: item.grid.window_count,
      updated_at: item.updated_at, app_version: item.app_version,
    })));
  },

  _localDocuments() {
    const map = {};
    try {
      const raw = localStorage.getItem(this.LOCAL_KEY);
      const list = raw ? JSON.parse(raw) : [];
      if (Array.isArray(list)) list.forEach((item) => { if (item.name) map[item.name] = item; });
    } catch (e) { /* return an empty local store */ }
    return map;
  },

  render() {
    this._renderQuickChips();
    this._renderList();
    const exportButton = document.getElementById('exportWindowPresetBtn');
    if (exportButton) exportButton.disabled = !this.selectedName;
  },

  _renderQuickChips() {
    const host = document.getElementById('windowPresetQuickChips');
    if (!host) return;
    host.replaceChildren();
    if (!this.presets.length) {
      const empty = document.createElement('span');
      empty.className = 'window-preset-empty';
      empty.textContent = 'none saved';
      host.appendChild(empty);
      return;
    }
    this.presets.forEach((item) => host.appendChild(this._presetButton(item.name, false)));
  },

  _presetButton(name, compact) {
    const button = document.createElement('button');
    button.className = compact ? 'window-preset-chip compact' : 'window-preset-chip';
    button.textContent = name;
    button.title = 'Restore window preset “' + name + '”';
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      this.selectedName = name;
      this.load(name);
    });
    return button;
  },

  _renderList() {
    const host = document.getElementById('windowPresetList');
    if (!host) return;
    host.replaceChildren();
    if (!this.presets.length) {
      const empty = document.createElement('div');
      empty.className = 'window-preset-list-empty';
      empty.textContent = 'No saved window presets yet. Save the current grid to create one.';
      host.appendChild(empty);
      return;
    }
    this.presets.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'window-preset-row';
      if (item.name === this.selectedName) row.classList.add('selected');
      const name = document.createElement('span');
      name.className = 'window-preset-name';
      name.textContent = item.name;
      const meta = document.createElement('span');
      meta.className = 'window-preset-meta';
      meta.textContent = (item.window_count || 0) + ' windows · ' + (item.updated_at || '');
      const actions = document.createElement('span');
      actions.className = 'window-preset-row-actions';
      actions.appendChild(this._rowAction('Restore', () => this.load(item.name)));
      actions.appendChild(this._rowAction('Export', () => this.export(item.name)));
      actions.appendChild(this._rowAction('Delete', () => this.remove(item.name), true));
      row.append(name, meta, actions);
      row.addEventListener('click', () => { this.selectedName = item.name; this.render(); });
      host.appendChild(row);
    });
  },

  _rowAction(label, action, danger = false) {
    const button = document.createElement('button');
    button.className = danger ? 'btn-small danger' : 'btn-small';
    button.textContent = label;
    button.addEventListener('click', (event) => { event.stopPropagation(); action(); });
    return button;
  },

  load(name) {
    this._getDocument(name, (document) => {
      if (document) this._showPreview(document, 'restore');
    });
  },

  _getDocument(name, callback) {
    const local = this._localDocuments()[name];
    const bridge = typeof App !== 'undefined' ? App.bridge : null;
    if (!bridge || !bridge.load_window_preset) {
      callback(local || null);
      return;
    }
    bridge.load_window_preset(name, (raw) => {
      if (!raw || raw === 'null') { callback(null); return; }
      try { callback(typeof raw === 'string' ? JSON.parse(raw) : raw); }
      catch (e) { this._message('Preset “' + name + '” is not valid JSON.', 'error'); callback(null); }
    });
  },

  exportSelected() {
    if (this.selectedName) this.export(this.selectedName);
  },

  export(name) {
    this._getDocument(name, (document) => {
      if (!document) {
        this._message('Preset “' + name + '” could not be loaded for export.', 'error');
        return;
      }
      const checked = SashGrid.validatePortablePreset(document);
      if (!checked.ok) { this._message('Export refused: ' + checked.error, 'error'); return; }
      this._download(checked.document);
    });
  },

  _download(preset) {
    const safe = preset.name.replace(/[^a-z0-9_-]+/gi, '-').replace(/^-|-$/g, '') || 'window-preset';
    const blob = new Blob([JSON.stringify(preset, null, 2) + '\n'], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'window-preset-' + safe + '.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 0);
    this._message('Exported “' + preset.name + '” as ' + link.download + '.', 'success');
  },

  _openFilePicker() {
    const input = document.getElementById('windowPresetFileInput');
    if (input) input.click();
  },

  _readFile(event) {
    const file = event.target.files && event.target.files[0];
    event.target.value = '';
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const result = SashGrid.validatePortablePreset(reader.result);
      if (!result.ok) {
        this._message('Import rejected: ' + result.error, 'error');
        return;
      }
      this._showPreview(result.document, 'import');
    };
    reader.onerror = () => this._message('Import failed: the file could not be read.', 'error');
    reader.readAsText(file);
  },

  _showPreview(preset, action) {
    const result = SashGrid.validatePortablePreset(preset);
    if (!result.ok) { this._message('Preview unavailable: ' + result.error, 'error'); return; }
    this.pending = { document: result.document, action };
    const menu = document.getElementById('layoutMenu');
    if (menu) menu.classList.add('hidden');
    const modal = documentById('windowPresetPreviewModal');
    const title = documentById('windowPresetPreviewTitle');
    const meta = documentById('windowPresetPreviewMeta');
    const canvas = documentById('windowPresetPreviewCanvas');
    if (!modal || !title || !meta || !canvas) return;
    title.textContent = 'Preview: ' + result.document.name;
    meta.textContent = this._previewMeta(result.document, result.warning);
    canvas.replaceChildren();
    result.document.windows.forEach((item) => {
      const tile = document.createElement('div');
      tile.className = 'window-preset-preview-tile state-' + item.state;
      tile.style.left = (item.bounds.x * 100) + '%';
      tile.style.top = (item.bounds.y * 100) + '%';
      tile.style.width = (item.bounds.width * 100) + '%';
      tile.style.height = (item.bounds.height * 100) + '%';
      tile.textContent = item.title || item.id;
      canvas.appendChild(tile);
    });
    modal.classList.remove('hidden');
  },

  _previewMeta(document, warning) {
    const resolution = document.screen.width + '×' + document.screen.height;
    const note = SashGrid._screenSnapshot(SashGrid.gridEl && SashGrid.gridEl.getBoundingClientRect
      ? SashGrid.gridEl.getBoundingClientRect() : { width: 1, height: 1 });
    const parts = [document.grid.window_count + ' windows · source screen ' + resolution];
    if (note.width !== document.screen.width || note.height !== document.screen.height)
      parts.push('target screen differs; percentages will adapt');
    if (warning) parts.push(warning);
    return parts.join(' · ');
  },

  _applyPreview() {
    if (!this.pending) return;
    const pending = this.pending;
    this._closePreview();
    if (!SashGrid.applyPortablePreset(pending.document)) return;
    if (pending.action === 'import') this._persistDocument(pending.document, true);
  },

  _closePreview() {
    const modal = documentById('windowPresetPreviewModal');
    if (modal) modal.classList.add('hidden');
    this.pending = null;
  },

  remove(name) {
    Dialog.confirm('Delete window preset?', '“' + name + '” will be removed.', 'Delete', () => {
      const bridge = typeof App !== 'undefined' ? App.bridge : null;
      if (!bridge || !bridge.delete_window_preset) {
        const map = this._localDocuments();
        delete map[name];
        try { localStorage.setItem(this.LOCAL_KEY, JSON.stringify(Object.values(map))); } catch (e) {}
        this.selectedName = '';
        this.setPresets(Object.values(map));
        return;
      }
      const result = bridge.delete_window_preset(name, (ok) => { if (ok) this.refresh(); });
      if (typeof result === 'boolean' && result) this.refresh();
    });
  },

  _message(text, level) {
    const status = document.getElementById('windowPresetStatus');
    if (status) {
      status.textContent = text;
      status.classList.remove('success', 'warn', 'error');
      if (level) status.classList.add(level);
    }
    if (typeof LogConsole !== 'undefined') LogConsole.log(text, level);
  },
};

function documentById(id) { return document.getElementById(id); }
window.WindowPresets = WindowPresets;
