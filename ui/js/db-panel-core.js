/* db-panel-core.js — state + bootstrap + bridge for DbPanel facade (H-B2b JS split)

Design: ≤150 LOC.
*/

'use strict';

const DbPanelCore = {
  info: null,
  items: [],
  activePath: '',
  busy: false,
  _wired: false,
  _els: {},
  _seq: 0,
  _pending: '',
  _notice: '',

  init() {
    if (this._wired) return;
    this._wired = true;
    const $ = (id) => document.getElementById(id);
    this._els = {
      panel: $('winDbconn'), active: $('dbActivePath'), stats: $('dbStatsGrid'),
      list: $('dbFileList'), nameInput: $('dbNewNameInput'), createBtn: $('dbCreateBtn'),
      cleanBtn: $('dbCleanBtn'), refreshBtn: $('dbRefreshBtn'), status: $('dbConnStatus'),
    };
    if (!this._els.panel) return;
    if (this._els.createBtn) this._els.createBtn.addEventListener('click', () => this.create());
    if (this._els.nameInput) this._els.nameInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); this.create(); } });
    if (this._els.cleanBtn) this._els.cleanBtn.addEventListener('click', () => this.clean());
    if (this._els.refreshBtn) this._els.refreshBtn.addEventListener('click', () => this.refresh());
    this.render(); this.refresh();
  },

  _bridge(method) {
    if (typeof App === 'undefined' || !App.bridge || !App.bridge[method]) return null;
    return App.bridge;
  },

  refresh() {
    const bridge = this._bridge('db_info');
    if (!bridge) { this.render(); return; }
    this._seq += 1; this._pending = 'db-' + this._seq;
    this.setStatus('Measuring database…'); bridge.db_info(this._pending);
  },

  onInfo(reqId, json) {
    if (this._pending && reqId && reqId !== this._pending) return;
    let payload = json;
    if (typeof json === 'string') { try { payload = JSON.parse(json); } catch (e) { payload = null; } }
    if (!payload) return;
    this.info = payload; this.items = Array.isArray(payload.items) ? payload.items : [];
    this.activePath = payload.path || payload.db_path || this.activePath; this.busy = false;
    if (!this._els.status || !this._els.status.classList.contains('error')) {
      if (this._notice) this.setStatus(this._notice, false); else this.setStatus('');
    }
    this.render();
  },

  onChanged(json) {
    let payload = json;
    if (typeof json === 'string') { try { payload = JSON.parse(json); } catch (e) { payload = null; } }
    this.busy = false;
    if (payload && payload.error) { this._notice = ''; this.refresh(); this.setStatus('⚠ ' + payload.error, true); return; }
    if (payload && payload.switched) { const name = payload.path ? this.baseName(payload.path) : ''; this._notice = 'Fresh world “' + name + '” loaded — all caches cleared'; } else this._notice = '';
    this.refresh();
  },

  setStatus(text, isError) {
    if (!this._els.status) return;
    this._els.status.textContent = text || ''; this._els.status.classList.toggle('error', !!isError);
  },

  baseName(path) { const parts = String(path || '').split(/[\\\\/]/); return parts[parts.length - 1] || ''; },

  bytes(n) {
    const value = Number(n) || 0; if (value < 1024) return value + ' B';
    const units = ['KB', 'MB', 'GB', 'TB']; let v = value / 1024, i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return (v >= 10 ? v.toFixed(0) : v.toFixed(1)) + ' ' + units[i];
  },

  num(n) { return Number(n || 0).toLocaleString('en-US'); },
};

if (typeof window !== 'undefined') window.DbPanelCore = DbPanelCore;
