/* window-presets-core.js — state + bootstrap + render for WindowPresets facade (H-B2b JS split)

Design: ≤200 LOC.
*/

'use strict';

const WindowPresetsCore = {
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
    if (element) element.addEventListener('click', (event) => { event.stopPropagation(); action(); });
  },

  _loadLocal() {
    try { const raw = localStorage.getItem(this.LOCAL_KEY); if (raw) this.setPresets(raw); } catch (e) {}
  },

  setPresets(raw) {
    try {
      const value = typeof raw === 'string' ? JSON.parse(raw) : raw;
      const list = Array.isArray(value) ? value : [];
      this.presets = list.filter((item) => item && typeof item.name === 'string').map((item) => ({
        name: item.name, window_count: item.window_count || (item.grid && item.grid.window_count) || 0,
        updated_at: item.updated_at || '', app_version: item.app_version || '',
      }));
    } catch (e) { this.presets = []; }
    if (!this.presets.some((item) => item.name === this.selectedName)) this.selectedName = this.presets[0] ? this.presets[0].name : '';
    this.render();
  },

  refresh() {
    if (typeof App !== 'undefined' && App.bridge && App.bridge.list_window_presets) {
      App.bridge.list_window_presets((raw) => this.setPresets(raw));
    }
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
      const empty = document.createElement('span'); empty.className = 'window-preset-empty'; empty.textContent = 'none saved'; host.appendChild(empty); return;
    }
    this.presets.forEach((item) => host.appendChild(this._presetButton(item.name, false)));
  },

  _presetButton(name, compact) {
    const button = document.createElement('button');
    button.className = compact ? 'window-preset-chip compact' : 'window-preset-chip';
    button.textContent = name; button.title = 'Restore window preset “' + name + '”';
    button.addEventListener('click', (event) => { event.stopPropagation(); this.selectedName = name; this.load(name); });
    return button;
  },

  _renderList() {
    const host = document.getElementById('windowPresetList');
    if (!host) return;
    host.replaceChildren();
    if (!this.presets.length) {
      const empty = document.createElement('div'); empty.className = 'window-preset-list-empty'; empty.textContent = 'No saved window presets yet. Save the current grid to create one.'; host.appendChild(empty); return;
    }
    this.presets.forEach((item) => {
      const row = document.createElement('div'); row.className = 'window-preset-row'; if (item.name === this.selectedName) row.classList.add('selected');
      const name = document.createElement('span'); name.className = 'window-preset-name'; name.textContent = item.name;
      const meta = document.createElement('span'); meta.className = 'window-preset-meta'; meta.textContent = (item.window_count || 0) + ' windows · ' + (item.updated_at || '');
      const actions = document.createElement('span'); actions.className = 'window-preset-row-actions';
      actions.appendChild(this._rowAction('Restore', () => this.load(item.name)));
      actions.appendChild(this._rowAction('Export', () => this.export(item.name)));
      actions.appendChild(this._rowAction('Show in folder', () => this.showInFolder(item.name)));
      actions.appendChild(this._rowAction('Delete', () => this.remove(item.name), true));
      row.append(name, meta, actions);
      row.addEventListener('click', () => { this.selectedName = item.name; this.render(); });
      host.appendChild(row);
    });
  },

  _rowAction(label, action, danger = false) {
    const button = document.createElement('button'); button.className = danger ? 'btn-small danger' : 'btn-small'; button.textContent = label;
    button.addEventListener('click', (event) => { event.stopPropagation(); action(); });
    return button;
  },
};

if (typeof window !== 'undefined') window.WindowPresetsCore = WindowPresetsCore;
