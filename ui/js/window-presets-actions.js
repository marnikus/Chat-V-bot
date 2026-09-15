/* window-presets-actions.js — save/load/export/remove for WindowPresets facade (H-B2b JS split)

Design: ≤250 LOC.
*/

'use strict';

const WindowPresetsActions = {
  saveCurrent() {
    if (typeof SashGrid === 'undefined' || !SashGrid.root) { this._message('No grid layout is ready to save.', 'warn'); return; }
    Dialog.promptName('Save window preset', 'e.g. Research desk', 'Save', (name) => {
      const document = SashGrid.createPortablePreset(name);
      this._persistDocument(document);
    });
  },

  _persistDocument(document, imported = false) {
    const checked = SashGrid.validatePortablePreset(document);
    if (!checked.ok) { this._message('Preset was not saved: ' + checked.error, 'error'); return; }
    const clean = checked.document;
    this.selectedName = clean.name;
    const bridge = typeof App !== 'undefined' ? App.bridge : null;
    if (!bridge || !bridge.save_window_preset) {
      this._saveLocalDocument(clean);
      this._message('Window preset “' + clean.name + '” saved locally.', 'success'); return;
    }
    const done = (ok) => {
      if (!ok) { this._message('Preset “' + clean.name + '” could not be written.', 'error'); return; }
      this.selectedName = clean.name; this.refresh();
      this._message((imported ? 'Imported' : 'Saved') + ' window preset “' + clean.name + '”.', 'success');
    };
    try { const result = bridge.save_window_preset(clean.name, JSON.stringify(clean), done); if (typeof result === 'boolean') done(result); }
    catch (error) { done(false); }
  },

  _saveLocalDocument(document) {
    const map = this._localDocuments();
    map[document.name] = document;
    try { localStorage.setItem(this.LOCAL_KEY, JSON.stringify(Object.values(map))); } catch (e) {}
    this.setPresets(Object.values(map).map((item) => ({ name: item.name, window_count: item.grid.window_count, updated_at: item.updated_at, app_version: item.app_version })));
  },

  _localDocuments() {
    const map = {};
    try { const raw = localStorage.getItem(this.LOCAL_KEY); const list = raw ? JSON.parse(raw) : []; if (Array.isArray(list)) list.forEach((item) => { if (item.name) map[item.name] = item; }); } catch (e) {}
    return map;
  },

  load(name) { this._getDocument(name, (document) => { if (document) this._showPreview(document, 'restore'); }); },

  _getDocument(name, callback) {
    const local = this._localDocuments()[name];
    const bridge = typeof App !== 'undefined' ? App.bridge : null;
    if (!bridge || !bridge.load_window_preset) { callback(local || null); return; }
    bridge.load_window_preset(name, (raw) => {
      if (!raw || raw === 'null') { callback(null); return; }
      try { callback(typeof raw === 'string' ? JSON.parse(raw) : raw); }
      catch (e) { this._message('Preset “' + name + '” is not valid JSON.', 'error'); callback(null); }
    });
  },

  exportSelected() { if (this.selectedName) this.export(this.selectedName); },

  export(name) {
    const bridge = typeof App !== 'undefined' ? App.bridge : null;
    if (!bridge || !bridge.export_window_preset) { this._message('Export requires the desktop bridge to choose a folder.', 'error'); return; }
    let handled = false;
    const done = (raw) => { if (handled) return; handled = true; this._handleExportResponse(name, raw); };
    try { const result = bridge.export_window_preset(name, done); if (typeof result === 'string' || (result && typeof result === 'object')) done(result); }
    catch (error) { done(JSON.stringify({ ok: false, error: error.message })); }
  },

  _handleExportResponse(name, raw) {
    let result = raw;
    try { result = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch (error) { result = { ok: false, error: 'invalid export response' }; }
    if (!result || !result.ok) {
      if (result && result.cancelled) this._message('Export cancelled.', 'info');
      else this._message('Export failed: ' + ((result && result.error) || 'unknown error'), 'error'); return;
    }
    this._message('Exported “' + name + '” to ' + result.path + '.', 'success');
  },

  showInFolder(name) {
    const bridge = typeof App !== 'undefined' ? App.bridge : null;
    if (!bridge || !bridge.show_window_preset_in_folder) { this._message('Show in folder requires the desktop bridge.', 'error'); return; }
    let handled = false;
    const done = (ok) => { if (handled) return; handled = true; this._message(ok ? 'Opened the folder for “' + name + '”.' : 'Could not open the folder for “' + name + '”.', ok ? 'success' : 'error'); };
    try { const result = bridge.show_window_preset_in_folder(name, done); if (typeof result === 'boolean') done(result); } catch (error) { done(false); }
  },

  remove(name) {
    Dialog.confirm('Delete window preset?', '“' + name + '” will be removed.', 'Delete', () => {
      const bridge = typeof App !== 'undefined' ? App.bridge : null;
      if (!bridge || !bridge.delete_window_preset) {
        const map = this._localDocuments(); delete map[name];
        try { localStorage.setItem(this.LOCAL_KEY, JSON.stringify(Object.values(map))); } catch (e) {}
        this.selectedName = ''; this.setPresets(Object.values(map)); return;
      }
      const result = bridge.delete_window_preset(name, (ok) => { if (ok) this.refresh(); });
      if (typeof result === 'boolean' && result) this.refresh();
    });
  },

  _message(text, level) {
    const status = document.getElementById('windowPresetStatus');
    if (status) { status.textContent = text; status.classList.remove('success', 'warn', 'error'); if (level) status.classList.add(level); }
    if (typeof LogConsole !== 'undefined') LogConsole.log(text, level);
  },
};

if (typeof window !== 'undefined') window.WindowPresetsActions = WindowPresetsActions;
