/* user-table-core.js — state + bootstrap + helpers for UserTable facade (H-B2b JS split)

Design: ≤150 LOC.
*/

'use strict';

const UserTableCore = {
  users: [],
  selected: new Set(),
  filter: '',
  sort: { key: null, direction: 1 },
  _wired: false,

  init() {
    if (this._wired) return;
    this._wired = true;
    const on = (id, ev, fn) => { const el = document.getElementById(id); if (el) el.addEventListener(ev, fn); };
    on('clearMemBtn', 'click', () => this.clearAll());
    on('resetMsgBtn', 'click', () => this.resetMessaged());
    on('deleteSelectedBtn', 'click', () => this.deleteSelected());
    on('selectAllUsers', 'change', (e) => this.toggleAll(e.target.checked));
    on('userSearch', 'input', (e) => { this.filter = (e.target.value || '').trim().toLowerCase(); this.render(this.users); });
    document.querySelectorAll('#userTable th[data-sort]').forEach((th) => {
      th.addEventListener('click', () => this.sortBy(th.dataset.sort));
      th.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.sortBy(th.dataset.sort); } });
    });
    this._updateSortHeaders();
    const tbody = document.getElementById('userTableBody');
    if (tbody) {
      tbody.addEventListener('click', (e) => {
        if (e.target.closest('.label-pill-x')) return;
        const nickCell = e.target.closest('.col-nick[data-nick]');
        if (nickCell) { if (typeof Labels !== 'undefined') Labels.setPerson(nickCell.dataset.nick); if (typeof HistoryStore !== 'undefined') HistoryStore.openPerson(nickCell.dataset.nick); return; }
        const btn = e.target.closest('button[data-act]');
        if (btn) {
          const nick = btn.dataset.nick; const act = btn.dataset.act;
          if (act === 'delete') this.deleteNick(nick); else if (act === 'toggle-messaged') this.toggleMessaged(nick); else if (act === 'message') this.manualMessage(nick); else if (act === 'label') this.labelNick(nick); return;
        }
        if (e.target.closest('.col-select') || e.target.closest('.row-actions')) return;
        const row = e.target.closest('tr[data-nick]'); if (row && typeof Labels !== 'undefined') Labels.setPerson(row.dataset.nick);
      });
      tbody.addEventListener('change', (e) => {
        const cb = e.target.closest('input[type=\"checkbox\"][data-nick]');
        if (!cb) return;
        if (cb.checked) this.selected.add(cb.dataset.nick); else this.selected.delete(cb.dataset.nick);
        this._syncSelectionUI();
      });
    }
    this._syncSelectionUI();
  },

  _visible() {
    let rows = this.users;
    if (this.filter) rows = rows.filter((u) => (u.nick || '').toLowerCase().includes(this.filter));
    if (typeof Labels !== 'undefined' && Labels.filterActive) rows = rows.filter((u) => Labels.allows(u.nick));
    return rows;
  },

  _bridge() {
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend — action ignored', 'warn'); return false; }
    return true;
  },

  _esc(s) { const d = document.createElement('div'); d.textContent = (s === null || s === undefined) ? '' : String(s); return d.innerHTML; },

  _attr(s) { return this._esc(s).replace(/\"/g, '&quot;'); },
};

if (typeof window !== 'undefined') window.UserTableCore = UserTableCore;
