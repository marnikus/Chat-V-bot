/* ═══════════════════════════════════════════════════════════════
   db-panel.js — the "DB Connection" grid window

   Create · Load · Delete · Clean the message-history database, plus a
   live size read-out (whole database, text only, images folder).

   Nothing here destroys data: delete and clean move the file into
   db_trash/ first, so a single Ctrl+Z brings the database back — the
   backend records every action on the one global undo timeline.

   createElement/textContent only; a file name is user text.
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const DbPanel = {
  info: null,
  items: [],
  activePath: '',
  busy: false,
  _wired: false,
  _els: {},
  _seq: 0,
  _pending: '',

  init() {
    if (this._wired) return;
    this._wired = true;
    const $ = (id) => document.getElementById(id);
    this._els = {
      panel: $('winDbconn'),
      active: $('dbActivePath'),
      stats: $('dbStatsGrid'),
      list: $('dbFileList'),
      folderHint: $('dbFolderHint'),
      nameInput: $('dbNewNameInput'),
      createBtn: $('dbCreateBtn'),
      cleanBtn: $('dbCleanBtn'),
      refreshBtn: $('dbRefreshBtn'),
      status: $('dbConnStatus'),
    };
    if (!this._els.panel) return;

    if (this._els.createBtn)
      this._els.createBtn.addEventListener('click', () => this.create());
    if (this._els.nameInput) {
      this._els.nameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); this.create(); }
      });
    }
    if (this._els.cleanBtn)
      this._els.cleanBtn.addEventListener('click', () => this.clean());
    if (this._els.refreshBtn)
      this._els.refreshBtn.addEventListener('click', () => this.refresh());
    this.render();
    this.refresh();
  },

  _bridge(method) {
    if (typeof App === 'undefined' || !App.bridge || !App.bridge[method])
      return null;
    return App.bridge;
  },

  /** Ask for fresh sizes + the file list. */
  refresh() {
    if (this.busy) return;
    const bridge = this._bridge('db_info');
    if (!bridge) { this.render(); return; }
    this._seq += 1;
    this._pending = 'db-' + this._seq;
    this.setStatus('Measuring database…');
    bridge.db_info(this._pending);
  },

  /** db_info_ready(req_id, json) */
  onInfo(reqId, json) {
    if (this.busy) return; // pre-operation measurements cannot re-enable controls
    if (this._pending && reqId && reqId !== this._pending) return;
    let payload = json;
    if (typeof json === 'string') {
      try { payload = JSON.parse(json); } catch (e) { payload = null; }
    }
    if (!payload) return;
    this.info = payload;
    if (Array.isArray(payload.items)) this.items = this.visibleItems(payload.items);
    this.activePath = payload.path || payload.db_path || payload.active_path || this.activePath;
    // Keep completion/error notices; only clear a progress line.
    if (payload.error || payload.inventory_error)
      this.setStatus('⚠ ' + (payload.error || payload.inventory_error), true);
    else if (this._els.status && this._els.status.textContent === 'Measuring database…')
      this.setStatus('');
    this.render();
  },

  /** db_changed(json) — a create/load/delete/clean landed (or was undone). */
  onChanged(json) {
    let payload = json;
    if (typeof json === 'string') {
      try { payload = JSON.parse(json); } catch (e) { payload = null; }
    }
    this.busy = false;
    this._pending = 'change-' + (++this._seq); // invalidate even without a bridge
    if (payload && Array.isArray(payload.items))
      this.items = this.visibleItems(payload.items); // errors carry real conflicts too
    if (payload && payload.inventory_folder)
      this.info = Object.assign({}, this.info || {}, { inventory_folder: payload.inventory_folder });
    if (payload && payload.ok) {
      if (payload.active_path || payload.path_after)
        this.activePath = payload.active_path || payload.path_after;
      if (payload.op === 'delete' && !Array.isArray(payload.items))
        this.items = this.items.filter((item) => item.path !== payload.path);
    }
    this.render();
    this.refresh();
    // After refresh(), so the measuring line cannot bury the result.
    if (payload && payload.error) this.setStatus('⚠ ' + payload.error, true);
    else if (payload && payload.ok && payload.op === 'create')
      this.setStatus('Created ' + this.baseName(payload.path) +
        '. Click Load to connect. The active database is unchanged.');
  },

  onError(scope, message) {
    if (!String(scope || '').startsWith('db_')) return;
    this.busy = false;
    this._pending = 'error-' + (++this._seq);
    this.setStatus('⚠ ' + message, true);
    this.render();
  },

  setStatus(text, isError) {
    if (!this._els.status) return;
    this._els.status.textContent = text || '';
    this._els.status.classList.toggle('error', !!isError);
  },

  visibleItems(items) {
    return (Array.isArray(items) ? items : []).filter((item) => item && item.path &&
      !item.protected && (item.exists === true || item.blocking === true ||
        (item.exists !== false && item.manageable !== false)));
  },

  manageableItems(items) {
    return this.visibleItems(items).filter((item) => item.manageable !== false &&
      item.compatible !== false && item.kind !== 'file');
  },

  _begin(text) {
    this.busy = true;
    this._pending = 'mutation-' + (++this._seq); // invalidate in-flight info
    this.setStatus(text);
    this.render();
  },

  // ── actions ─────────────────────────────────────────────────
  create() {
    if (this.busy) return;
    const input = this._els.nameInput;
    const name = input ? String(input.value || '').trim() : '';
    if (!name) {
      this.setStatus('Type a name for the new database first', true);
      if (input) input.focus();
      return;
    }
    const bridge = this._bridge('db_create');
    if (!bridge) return;
    this._begin('Creating “' + name + '”…');
    bridge.db_create(name);
    if (input) input.value = '';
  },

  reveal(path) {
    if (this.busy || !path) return;
    const item = this.visibleItems(this.items).find((row) => row.path === path);
    if (!item || item.can_reveal === false) return;
    const bridge = this._bridge('db_reveal');
    if (!bridge) {
      this.setStatus('File reveal is unavailable. Restart the application after updating.', true);
      return;
    }
    // Non-mutating RPC: no _begin(), db_load(), or global undo command.
    this.setStatus('Opening file location…');
    const sequence = this._seq;
    bridge.db_reveal(path, (json) => {
      let result = json;
      if (typeof json === 'string') {
        try { result = JSON.parse(json); } catch (e) { result = null; }
      }
      if (this.busy || sequence !== this._seq) return;
      if (result && result.ok)
        this.setStatus('File location: ' + (result.reveal_path || item.reveal_path || path));
      else this.setStatus('⚠ ' + (result && result.error || 'Cannot open the file location.'), true);
    });
  },

  load(path) {
    if (this.busy || !path || path === this.activePath) return;
    const item = this.manageableItems(this.items).find((row) => row.path === path);
    if (!item || item.can_load === false) return;
    const bridge = this._bridge('db_load');
    if (!bridge) return;
    this._begin('Connecting to ' + this.baseName(path) + '…');
    bridge.db_load(path);
  },

  remove(path) {
    if (this.busy || !path) return;
    const items = this.manageableItems(this.items);
    const item = items.find((row) => row.path === path);
    if (!item) return;
    if (items.length <= 1 || item.can_delete === false) {
      this.setStatus(item.delete_reason ||
        'Cannot delete the last database. Create a new one first.', true);
      return;
    }
    const bridge = this._bridge('db_delete');
    if (!bridge) return;
    PresetsUI.confirm(
      'Delete database?',
      '“' + this.baseName(path) + '” moves to the db_trash folder. ' +
      'Nothing is erased and Ctrl+Z puts it back.',
      'Delete', () => {
        if (this.busy) return;
        this._begin('Moving ' + this.baseName(path) + ' to db_trash…');
        bridge.db_delete(path);
      });
  },

  clean() {
    if (this.busy || !this.activePath) return;
    const bridge = this._bridge('db_clean');
    if (!bridge) return;
    const name = this.baseName(this.activePath) || 'the current database';
    PresetsUI.confirm(
      'Clean database?',
      'Every message, person and media record in “' + name + '” is removed. ' +
      'A full backup goes to db_trash first, so Ctrl+Z restores everything.',
      'Clean', () => {
        if (this.busy) return;
        this._begin('Cleaning ' + name + '…');
        bridge.db_clean();
      });
  },

  // ── formatting ──────────────────────────────────────────────
  baseName(path) {
    const parts = String(path || '').split(/[\\/]/);
    return parts[parts.length - 1] || '';
  },

  bytes(n) {
    const value = Number(n) || 0;
    if (value < 1024) return value + ' B';
    const units = ['KB', 'MB', 'GB', 'TB'];
    let v = value / 1024, i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return (v >= 10 ? v.toFixed(0) : v.toFixed(1)) + ' ' + units[i];
  },

  num(n) {
    return Number(n || 0).toLocaleString('en-US');
  },

  // ── rendering ───────────────────────────────────────────────
  render() {
    this.renderActive();
    this.renderStats();
    this.renderList();
    if (this._els.cleanBtn)
      this._els.cleanBtn.disabled = !this.activePath || this.busy;
    ['createBtn', 'refreshBtn', 'nameInput'].forEach((key) => {
      if (this._els[key]) this._els[key].disabled = this.busy;
    });
  },

  renderActive() {
    const host = this._els.active;
    if (!host) return;
    const nodes = [];
    const dot = document.createElement('span');
    const connected = !!(this.info && this.info.connected);
    dot.className = 'db-dot' + (connected ? ' on' : '');
    dot.title = connected ? 'Connected' : 'Not connected';
    nodes.push(dot);
    const name = document.createElement('span');
    name.className = 'db-active-name';
    name.textContent = this.baseName(this.activePath) || 'no database';
    name.title = this.activePath || '';
    nodes.push(name);
    if (this.activePath) {
      const path = document.createElement('span');
      path.className = 'db-active-path';
      path.textContent = this.activePath;
      nodes.push(path);
    }
    host.replaceChildren.apply(host, nodes);
  },

  renderStats() {
    const host = this._els.stats;
    if (!host) return;
    const info = this.info || {};
    const cells = [
      ['Full DB size', this.bytes(info.total_bytes),
       'Database file + WAL + the images folder'],
      ['Database file', this.bytes(info.db_bytes),
       this.baseName(this.activePath) || '—'],
      ['Text size', this.bytes(info.text_bytes),
       this.num(info.messages) + ' message(s) stored'],
      ['Images folder', this.bytes(info.media_bytes),
       this.num(info.media_files) + ' file(s) in ' + (info.media_dir || '—')],
      ['People', this.num(info.persons), 'rows in this database'],
      ['Hidden', this.num(info.messages_hidden),
       'soft-deleted messages an undo can bring back'],
    ];
    const nodes = cells.map(([label, value, hint]) => {
      const cell = document.createElement('div');
      cell.className = 'db-stat';
      cell.title = hint || '';
      const k = document.createElement('span');
      k.className = 'db-stat-k';
      k.textContent = label;
      const v = document.createElement('span');
      v.className = 'db-stat-v';
      v.textContent = value;
      const h = document.createElement('span');
      h.className = 'db-stat-h';
      h.textContent = hint || '';
      cell.appendChild(k);
      cell.appendChild(v);
      cell.appendChild(h);
      return cell;
    });
    host.replaceChildren.apply(host, nodes);
  },

  renderList() {
    const host = this._els.list;
    if (!host) return;
    const nodes = [];
    const items = this.visibleItems(this.items);
    const archives = this.manageableItems(items);
    if (this._els.folderHint) {
      const folder = this.info && this.info.inventory_folder ||
        this.activePath.replace(/[\\/][^\\/]*$/, '');
      this._els.folderHint.textContent = (folder ? 'Create folder: ' + folder + '. ' : '') +
        'Click a name to reveal its file. Load connects.';
    }
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'db-empty';
      empty.textContent = this.info
        ? 'No other database files found next to this one.'
        : 'Reading the database folder…';
      nodes.push(empty);
    }
    items.forEach((item) => {
      const row = document.createElement('div');
      const manageable = archives.includes(item);
      row.className = 'db-row' + (item.active ? ' active' : '') + (!manageable ? ' conflict' : '');
      row.dataset.path = item.path;
      const file = document.createElement('div');
      file.className = 'db-row-file';
      const name = document.createElement('button');
      name.type = 'button';
      name.className = 'db-row-name';
      name.textContent = item.name || this.baseName(item.path);
      name.title = 'Reveal in file manager: ' + (item.reveal_path || item.path);
      name.disabled = this.busy || item.can_reveal === false;
      name.addEventListener('click', () => this.reveal(item.path));
      file.appendChild(name);
      if (item.detail || !manageable) {
        const detail = document.createElement('div');
        detail.className = 'db-row-detail';
        const label = { empty: 'Empty file', incompatible: 'Incompatible',
          unavailable: 'Unavailable', sidecars: 'Sidecar files only',
          not_file: 'Name occupied', alias: 'File alias', broken_link: 'Broken link',
          legacy: 'Upgrade on Load' }[item.status] || 'Not loadable';
        detail.textContent = label + (item.detail ? ': ' + item.detail : '');
        detail.title = item.path + '\n' + detail.textContent;
        file.appendChild(detail);
      }
      row.appendChild(file);
      const size = document.createElement('span');
      size.className = 'db-row-size';
      size.textContent = this.bytes(item.bytes);
      row.appendChild(size);
      const actions = document.createElement('span');
      actions.className = 'db-row-actions';
      if (item.active) {
        const tag = document.createElement('span');
        tag.className = 'db-tag';
        tag.textContent = 'connected';
        actions.appendChild(tag);
      } else if (manageable && item.can_load !== false) {
        const load = document.createElement('button');
        load.type = 'button';
        load.className = 'btn-small';
        load.textContent = 'Load';
        load.title = 'Validate this database, then connect to it';
        load.disabled = this.busy;
        load.addEventListener('click', () => this.load(item.path));
        actions.appendChild(load);
      }
      if (manageable) {
        const del = document.createElement('button');
        del.type = 'button';
        del.className = 'btn-small danger';
        del.textContent = 'Delete';
        const last = archives.length <= 1 || item.can_delete === false;
        del.disabled = this.busy || last;
        del.title = last ? (item.delete_reason ||
          'Cannot delete the last database. Create a new one first.')
          : 'Move this file to db_trash (undoable)';
        del.addEventListener('click', () => this.remove(item.path));
        actions.appendChild(del);
      } else {
        const tag = document.createElement('span');
        tag.className = 'db-tag readonly';
        tag.textContent = 'read-only';
        tag.title = item.delete_reason || 'Reveal this file to inspect or rename it safely';
        actions.appendChild(tag);
      }
      row.appendChild(actions);
      nodes.push(row);
    });
    host.replaceChildren.apply(host, nodes);
  },
};

if (typeof window !== 'undefined') window.DbPanel = DbPanel;
if (typeof module === 'object' && module.exports) module.exports = DbPanel;
