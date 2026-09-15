/* user-table-render.js — rendering + sort for UserTable facade (H-B2b JS split)

Design: ≤250 LOC.
*/

'use strict';

const UserTableRender = {
  render(users) {
    this.users = Array.isArray(users) ? users : [];
    const live = new Set(this.users.map((u) => u.nick));
    this.selected.forEach((n) => { if (!live.has(n)) this.selected.delete(n); });
    const tbody = document.getElementById('userTableBody');
    if (!tbody) return;
    const rows = this._visible().slice().sort((a, b) => this._compare(a, b));
    this._updateSortHeaders();
    if (!this.users.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="table-placeholder">No users discovered yet. Connect and run the parser.</td></tr>';
    } else if (!rows.length) {
      const labelled = typeof Labels !== 'undefined' && Labels.filterActive;
      tbody.innerHTML = '<tr><td colspan="9" class="table-placeholder">' + (this.filter ? `No nick matches “${this._esc(this.filter)}”.` : labelled ? 'Every person is hidden by the label filter — clear it in the Label Manager to see them again.' : 'No users to show.') + '</td></tr>';
    } else { tbody.innerHTML = rows.map((u) => this._row(u)).join(''); this._paintLabels(tbody); }
    this._syncSelectionUI();
  },

  sortBy(key) { if (!key) return; if (this.sort.key === key) this.sort.direction *= -1; else { this.sort.key = key; this.sort.direction = 1; } this.render(this.users); },

  _sortValue(user, key) {
    if (key === 'gender') return ({ female: 'female', male: 'male' }[user.gender] || 'unknown');
    if (key === 'order') return (user.messaged || !Number.isInteger(user.order)) ? null : user.order;
    if (key === 'registered' || key === 'messaged' || key === 'status') return key === 'status' ? (user.messaged ? 1 : 0) : (user[key] ? 1 : 0);
    if (key === 'first_seen' || key === 'last_messaged') {
      const raw = user[key]; if (!raw) return null; const timestamp = Date.parse(raw); return Number.isNaN(timestamp) ? String(raw).toLowerCase() : timestamp;
    }
    return String(user[key] || '').toLowerCase();
  },

  _compare(a, b) {
    const key = this.sort.key; if (!key) return 0;
    const av = this._sortValue(a, key); const bv = this._sortValue(b, key);
    if (av === null || av === '') return (bv === null || bv === '') ? 0 : 1;
    if (bv === null || bv === '') return -1;
    let result; if (typeof av === 'number' && typeof bv === 'number') result = av - bv; else result = String(av).localeCompare(String(bv), undefined, { sensitivity: 'base', numeric: true });
    return result === 0 ? 0 : result * this.sort.direction;
  },

  _updateSortHeaders() {
    document.querySelectorAll('#userTable th[data-sort]').forEach((th) => {
      const active = th.dataset.sort === this.sort.key; const arrow = th.querySelector('.sort-arrow');
      if (arrow) arrow.textContent = window.UIHelpers.sortArrow(active, this.sort.direction);
      th.setAttribute('aria-sort', active ? (this.sort.direction > 0 ? 'ascending' : 'descending') : 'none');
      th.classList.toggle('sort-active', active);
    });
  },

  _row(u) {
    const nick = this._esc(u.nick); const attr = this._attr(u.nick);
    const gender = u.gender === 'female' ? '<span class="gender-badge female">♀ Female</span>' : u.gender === 'male' ? '<span class="gender-badge male">♂ Male</span>' : '<span class="gender-badge unknown">? Unknown</span>';
    const reg = u.registered ? '<span class="yes">✅ Yes</span>' : '<span class="no">❌ No</span>';
    const statusHtml = `<span class="status-badge ${u.messaged ? 'done' : 'new'}">${u.messaged ? '✅ Done' : '🆕 New'}</span>`;
    const seen = u.first_seen ? (u.first_seen.substring(11, 16) || u.first_seen) : '—';
    const msg = (!u.messaged || !u.last_messaged) ? '—' : (u.last_messaged.substring(11, 16) || u.last_messaged);
    const order = (!u.messaged && Number.isInteger(u.order)) ? u.order : null;
    const checked = this.selected.has(u.nick) ? ' checked' : '';
    const rowCls = [!u.messaged ? 'row-new' : '', this.selected.has(u.nick) ? 'row-selected' : '', (typeof Labels !== 'undefined' && Labels.person === u.nick) ? 'row-label-target' : ''].filter(Boolean).join(' ');
    return `<tr class="${rowCls}" data-nick="${attr}">\n      <td class="col-select"><input type="checkbox" data-nick="${attr}"${checked} aria-label="Select ${nick}"></td>\n      <td class="col-order" title="${order ? `Processed ${order}.` : 'No processing order (already messaged)'}">${order === null ? '—' : order}</td>\n      <td class="col-nick nick-link" data-nick="${attr}" title="Open the full message history with ${attr}">${nick}</td>\n      <td>${gender}</td><td>${reg}</td><td>${statusHtml}</td>\n      <td>${seen}</td><td>${msg}</td>\n      <td class="row-actions"><button data-act="toggle-messaged" data-nick="${attr}" title="${u.messaged ? 'Mark as new again' : 'Mark as already messaged'}">${u.messaged ? '↩ Undo' : '✔ Done'}</button><button data-act="label" data-nick="${attr}" title="Label this person in the Label Manager">🏷</button><button data-act="delete" data-nick="${attr}" class="btn-row-danger" title="Delete this nick from user memory">🗑 Delete</button></td>\n    </tr>`;
  },

  _paintLabels(tbody) {
    if (typeof Labels === 'undefined') return;
    tbody.querySelectorAll('.col-nick[data-nick]').forEach((cell) => {
      const nick = cell.dataset.nick; const pills = Labels.pills(nick); if (pills.childNodes.length) cell.appendChild(pills);
    });
  },

  labelNick(nick) { if (typeof Labels === 'undefined') return; Labels.setPerson(nick, { focus: true }); },

  markLabelTarget(nick) {
    const tbody = document.getElementById('userTableBody'); if (!tbody || !tbody.querySelectorAll) return;
    const clean = String(nick || '').trim();
    tbody.querySelectorAll('tr[data-nick]').forEach((tr) => { const on = !!clean && tr.dataset.nick === clean; tr.classList.toggle('row-label-target', on); if (on && tr.scrollIntoView) tr.scrollIntoView({ block: 'nearest' }); });
  },
};

if (typeof window !== 'undefined') window.UserTableRender = UserTableRender;
