/* ═══════════════════════════════════════════════════════════════
   user-table.js — User Memory table rendering
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const UserTable = {
  users: [],

  render(users) {
    this.users = users;
    const tbody = document.getElementById('userTableBody');
    if (!users.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:24px">No users discovered yet. Connect and run the parser.</td></tr>';
      return;
    }
    tbody.innerHTML = users.map((u, i) => this._row(u, i)).join('');
  },

  _row(u, i) {
    const gender = u.gender === 'female' ? '<span class="gender-badge female">♀ Female</span>'
                 : u.gender === 'male'   ? '<span class="gender-badge male">♂ Male</span>'
                 : '<span class="gender-badge unknown">? Unknown</span>';
    const reg = u.registered ? '<span class="yes">✅ Yes</span>' : '<span class="no">❌ No</span>';
    const status = u.messaged ? 'done' : 'new';
    const statusHtml = `<span class="status-badge ${status}">${u.messaged ? '✅ Done' : '🆕 New'}</span>`;
    const seen = u.first_seen ? u.first_seen.substring(11, 16) || u.first_seen : '—';
    const msg = u.last_messaged ? u.last_messaged.substring(11, 16) || u.last_messaged : '—';
    return `<tr class="${!u.messaged ? 'row-new' : ''}" data-idx="${i}">
      <td style="font-weight:500">${this._esc(u.nick)}</td>
      <td>${gender}</td><td>${reg}</td><td>${statusHtml}</td>
      <td>${seen}</td><td>${msg}</td>
      <td class="row-actions">
        <button onclick="UserTable._action('message','${this._esc(u.nick)}')">Message</button>
        <button onclick="UserTable._action('skip','${this._esc(u.nick)}')">Skip</button>
      </td>
    </tr>`;
  },

  _action(type, nick) {
    if (type === 'message') LogConsole.log(`👤 Manual message: ${nick}`, 'info');
    else LogConsole.log(`⏭ Skipped: ${nick}`, 'warn');
  },

  _esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  },
};
