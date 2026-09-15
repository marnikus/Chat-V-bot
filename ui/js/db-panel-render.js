/* db-panel-render.js — rendering for DbPanel facade (H-B2b JS split)

Design: ≤200 LOC.
*/

'use strict';

const DbPanelRender = {
  render() {
    this.renderActive(); this.renderStats(); this.renderList();
    if (this._els.cleanBtn) this._els.cleanBtn.disabled = !this.activePath || this.busy;
  },

  renderActive() {
    const host = this._els.active; if (!host) return;
    const nodes = []; const dot = document.createElement('span');
    const connected = !!(this.info && this.info.connected);
    dot.className = 'db-dot' + (connected ? ' on' : ''); dot.title = connected ? 'Connected' : 'Not connected'; nodes.push(dot);
    const name = document.createElement('span'); name.className = 'db-active-name'; name.textContent = this.baseName(this.activePath) || 'no database'; name.title = this.activePath || ''; nodes.push(name);
    if (this.activePath) { const path = document.createElement('span'); path.className = 'db-active-path'; path.textContent = this.activePath; nodes.push(path); }
    host.replaceChildren.apply(host, nodes);
  },

  renderStats() {
    const host = this._els.stats; if (!host) return;
    const info = this.info || {};
    const cells = [
      ['Full DB size', this.bytes(info.total_bytes), 'Database file + WAL + the images folder'],
      ['Database file', this.bytes(info.db_bytes), this.baseName(this.activePath) || '—'],
      ['Text size', this.bytes(info.text_bytes), this.num(info.messages) + ' message(s) stored'],
      ['Images folder', this.bytes(info.media_bytes), this.num(info.media_files) + ' file(s) in ' + (info.media_dir || '—')],
      ['People', this.num(info.persons), 'rows in this database'],
      ['Hidden', this.num(info.messages_hidden), 'soft-deleted messages an undo can bring back'],
    ];
    const nodes = cells.map(([label, value, hint]) => {
      const cell = document.createElement('div'); cell.className = 'db-stat'; cell.title = hint || '';
      const k = document.createElement('span'); k.className = 'db-stat-k'; k.textContent = label;
      const v = document.createElement('span'); v.className = 'db-stat-v'; v.textContent = value;
      const h = document.createElement('span'); h.className = 'db-stat-h'; h.textContent = hint || '';
      cell.appendChild(k); cell.appendChild(v); cell.appendChild(h); return cell;
    });
    host.replaceChildren.apply(host, nodes);
  },

  renderList() {
    const host = this._els.list; if (!host) return;
    const nodes = [];
    if (!this.items.length) {
      const empty = document.createElement('div'); empty.className = 'db-empty'; empty.textContent = this.info ? 'No other database files found next to this one.' : 'Reading the database folder…'; nodes.push(empty);
    }
    this.items.forEach((item) => {
      const row = document.createElement('div'); row.className = 'db-row' + (item.active ? ' active' : '') + (item.exists === false ? ' missing' : '');
      const name = document.createElement('span'); name.className = 'db-row-name'; name.textContent = item.name || this.baseName(item.path); name.title = item.path || ''; row.appendChild(name);
      const size = document.createElement('span'); size.className = 'db-row-size'; size.textContent = item.exists === false ? 'missing' : this.bytes(item.bytes); row.appendChild(size);
      const actions = document.createElement('span'); actions.className = 'db-row-actions';
      if (item.active) { const tag = document.createElement('span'); tag.className = 'db-tag'; tag.textContent = 'connected'; actions.appendChild(tag); }
      else if (item.exists !== false) { const load = document.createElement('button'); load.type = 'button'; load.className = 'btn-small'; load.textContent = 'Load'; load.title = 'Disconnect the current database and connect this one'; load.addEventListener('click', () => this.load(item.path)); actions.appendChild(load); }
      const del = document.createElement('button'); del.type = 'button'; del.className = 'btn-small danger'; del.textContent = 'Delete'; del.disabled = item.exists === false || item.can_delete === false; del.title = item.delete_hint || 'Permanently delete this database and its media'; del.addEventListener('click', () => this.remove(item.path)); actions.appendChild(del);
      row.appendChild(actions); nodes.push(row);
    });
    host.replaceChildren.apply(host, nodes);
  },
};

if (typeof window !== 'undefined') window.DbPanelRender = DbPanelRender;
