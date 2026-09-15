/* user-table-actions.js — selection + actions for UserTable facade (H-B2b JS split)

Design: ≤250 LOC.
*/

'use strict';

const UserTableActions = {
  toggleAll(checked) {
    this._visible().forEach((u) => { if (checked) this.selected.add(u.nick); else this.selected.delete(u.nick); });
    this.render(this.users);
  },

  _syncSelectionUI() {
    const n = this.selected.size;
    const btn = document.getElementById('deleteSelectedBtn');
    if (btn) { btn.disabled = n === 0; btn.textContent = n ? `🗑 Delete selected (${n})` : '🗑 Delete selected'; }
    const counter = document.getElementById('selCount');
    if (counter) { counter.textContent = n ? `${n} selected` : ''; counter.classList.toggle('hidden', n === 0); }
    const all = document.getElementById('selectAllUsers');
    if (all) {
      const vis = this._visible(); const sel = vis.filter((u) => this.selected.has(u.nick)).length;
      all.checked = vis.length > 0 && sel === vis.length; all.indeterminate = sel > 0 && sel < vis.length;
    }
  },

  deleteNick(nick) { if (!this._bridge()) return; this.selected.delete(nick); App.bridge.delete_user(nick); },

  deleteSelected() {
    if (!this._bridge()) return;
    const nicks = Array.from(this.selected);
    if (!nicks.length) { LogConsole.log('⚠ Nothing selected — tick the rows you want to delete', 'warn'); return; }
    App.bridge.delete_users(JSON.stringify(nicks)); this.selected.clear(); this._syncSelectionUI();
  },

  clearAll() {
    if (!this._bridge()) return;
    if (!this.users.length) { LogConsole.log('ℹ User memory is already empty', 'info'); return; }
    this.selected.clear(); App.bridge.clear_memory();
  },

  resetMessaged() { if (!this._bridge()) return; App.bridge.reset_messaged(); },

  toggleMessaged(nick) {
    if (!this._bridge()) return;
    const u = this.users.find((x) => x.nick === nick); if (!u) return;
    App.bridge.set_user_messaged(nick, !u.messaged);
  },

  manualMessage(nick) { LogConsole.log(`👤 Manual message: ${nick}`, 'info'); },

  onPersonFound(payloadJson) {
    let p = null; try { p = JSON.parse(payloadJson || 'null'); } catch (e) { p = null; }
    if (!p || !p.nick) return; this._flashNick = p.nick; requestAnimationFrame(() => this.flashRow(p.nick));
  },

  flashRow(nick) {
    const tbody = document.getElementById('userTableBody'); if (!tbody) return;
    const cb = tbody.querySelector(`input[data-nick=\"${CSS.escape(nick)}\"]`);
    const row = cb ? cb.closest('tr') : Array.from(tbody.querySelectorAll('tr')).find((tr) => tr.textContent.includes(nick));
    if (!row) return; row.classList.remove('row-flash'); void row.offsetWidth; row.classList.add('row-flash'); row.scrollIntoView({ block: 'nearest' }); setTimeout(() => row.classList.remove('row-flash'), 1600);
  },

  onPersonRemoved(payloadJson) {
    let p = null; try { p = JSON.parse(payloadJson || 'null'); } catch (e) { p = null; }
    if (!p || !p.nick) return; this.selected.delete(p.nick); this.users = this.users.filter((u) => u.nick !== p.nick);
    const reason = p.reason ? ` — ${p.reason}` : ''; LogConsole.log(`🗑 Removed “${p.nick}”${reason}`, 'warn'); this.render(this.users);
  },

  onDeleted(nicksJson) {
    try { JSON.parse(nicksJson || '[]').forEach((n) => this.selected.delete(n)); } catch (e) {}
    this._syncSelectionUI();
  },
};

if (typeof window !== 'undefined') window.UserTableActions = UserTableActions;
