/* ═══════════════════════════════════════════════════════════════
   user-table.js — User Memory (people list)

   BUG #4  — "Clear All" / "Reset Messaged" had markup but NO listener,
             so nothing ever reached the (working) backend slots.
   FEAT #5 — Delete an individual nick, or an arbitrary selection,
             instead of only wiping the whole table.

   Notes
     · every destructive action is confirmed through the in-app modal
       (Qt WebEngine does not reliably support window.confirm)
     · nicks may contain quotes / emoji ⇒ NO inline onclick handlers,
       values travel in data-nick and are read by delegated listeners
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const UserTable = {
  users: [],
  selected: new Set(),
  filter: '',
  _wired: false,

  // ── setup ───────────────────────────────────────────────────
  init() {
    if (this._wired) return;
    this._wired = true;

    const on = (id, ev, fn) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener(ev, fn);
    };

    // BUG #4 — the two dead buttons finally get their listeners
    on('clearMemBtn', 'click', () => this.clearAll());
    on('resetMsgBtn', 'click', () => this.resetMessaged());
    // FEATURE #5 — bulk delete of the current selection
    on('deleteSelectedBtn', 'click', () => this.deleteSelected());
    on('selectAllUsers', 'change', (e) => this.toggleAll(e.target.checked));
    on('userSearch', 'input', (e) => {
      this.filter = (e.target.value || '').trim().toLowerCase();
      this.render(this.users);
    });

    // delegated row events (safe for any nick content)
    const tbody = document.getElementById('userTableBody');
    if (tbody) {
      tbody.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-act]');
        if (!btn) return;
        const nick = btn.dataset.nick;
        const act = btn.dataset.act;
        if (act === 'delete') this.deleteNick(nick);
        else if (act === 'toggle-messaged') this.toggleMessaged(nick);
        else if (act === 'message') this.manualMessage(nick);
      });
      tbody.addEventListener('change', (e) => {
        const cb = e.target.closest('input[type="checkbox"][data-nick]');
        if (!cb) return;
        if (cb.checked) this.selected.add(cb.dataset.nick);
        else this.selected.delete(cb.dataset.nick);
        this._syncSelectionUI();
      });
    }
    this._syncSelectionUI();
  },

  // ── rendering ───────────────────────────────────────────────
  render(users) {
    this.users = Array.isArray(users) ? users : [];
    // drop selections for rows that no longer exist
    const live = new Set(this.users.map((u) => u.nick));
    this.selected.forEach((n) => { if (!live.has(n)) this.selected.delete(n); });

    const tbody = document.getElementById('userTableBody');
    if (!tbody) return;
    const rows = this._visible();

    if (!this.users.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="table-placeholder">' +
        'No users discovered yet. Connect and run the parser.</td></tr>';
    } else if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="table-placeholder">' +
        `No nick matches “${this._esc(this.filter)}”.</td></tr>`;
    } else {
      tbody.innerHTML = rows.map((u) => this._row(u)).join('');
    }
    this._syncSelectionUI();
  },

  _visible() {
    if (!this.filter) return this.users;
    return this.users.filter(
      (u) => (u.nick || '').toLowerCase().includes(this.filter));
  },

  _row(u) {
    const nick = this._esc(u.nick);
    const attr = this._attr(u.nick);
    const gender = u.gender === 'female'
      ? '<span class="gender-badge female">♀ Female</span>'
      : u.gender === 'male'
        ? '<span class="gender-badge male">♂ Male</span>'
        : '<span class="gender-badge unknown">? Unknown</span>';
    const reg = u.registered ? '<span class="yes">✅ Yes</span>'
                             : '<span class="no">❌ No</span>';
    const statusHtml = `<span class="status-badge ${u.messaged ? 'done' : 'new'}">` +
      `${u.messaged ? '✅ Done' : '🆕 New'}</span>`;
    const seen = u.first_seen ? (u.first_seen.substring(11, 16) || u.first_seen) : '—';
    const msg = u.last_messaged ? (u.last_messaged.substring(11, 16) || u.last_messaged) : '—';
    const checked = this.selected.has(u.nick) ? ' checked' : '';
    const rowCls = [
      !u.messaged ? 'row-new' : '',
      this.selected.has(u.nick) ? 'row-selected' : '',
    ].filter(Boolean).join(' ');

    return `<tr class="${rowCls}">
      <td class="col-select">
        <input type="checkbox" data-nick="${attr}"${checked}
               aria-label="Select ${nick}"></td>
      <td class="col-nick" title="${attr}">${nick}</td>
      <td>${gender}</td><td>${reg}</td><td>${statusHtml}</td>
      <td>${seen}</td><td>${msg}</td>
      <td class="row-actions">
        <button data-act="toggle-messaged" data-nick="${attr}"
                title="${u.messaged ? 'Mark as new again' : 'Mark as already messaged'}">
          ${u.messaged ? '↩ Undo' : '✔ Done'}</button>
        <button data-act="delete" data-nick="${attr}" class="btn-row-danger"
                title="Delete this nick from user memory">🗑 Delete</button>
      </td>
    </tr>`;
  },

  // ── selection ───────────────────────────────────────────────
  toggleAll(checked) {
    this._visible().forEach((u) => {
      if (checked) this.selected.add(u.nick);
      else this.selected.delete(u.nick);
    });
    this.render(this.users);
  },

  _syncSelectionUI() {
    const n = this.selected.size;
    const btn = document.getElementById('deleteSelectedBtn');
    if (btn) {
      btn.disabled = n === 0;
      btn.textContent = n ? `🗑 Delete selected (${n})` : '🗑 Delete selected';
    }
    const counter = document.getElementById('selCount');
    if (counter) {
      counter.textContent = n ? `${n} selected` : '';
      counter.classList.toggle('hidden', n === 0);
    }
    const all = document.getElementById('selectAllUsers');
    if (all) {
      const vis = this._visible();
      const sel = vis.filter((u) => this.selected.has(u.nick)).length;
      all.checked = vis.length > 0 && sel === vis.length;
      all.indeterminate = sel > 0 && sel < vis.length;
    }
  },

  // ── actions ─────────────────────────────────────────────────
  deleteNick(nick) {
    if (!this._bridge()) return;
    PresetsUI.confirm('Delete user?',
      `“${nick}” will be permanently removed from user memory.`,
      'Delete', () => {
        this.selected.delete(nick);
        App.bridge.delete_user(nick);
      });
  },

  deleteSelected() {
    if (!this._bridge()) return;
    const nicks = Array.from(this.selected);
    if (!nicks.length) {
      LogConsole.log('⚠ Nothing selected — tick the rows you want to delete', 'warn');
      return;
    }
    const preview = nicks.slice(0, 6).join(', ') + (nicks.length > 6 ? ', …' : '');
    PresetsUI.confirm(`Delete ${nicks.length} user(s)?`,
      `${preview}\n\nThese nicks will be permanently removed from user memory.`,
      `Delete ${nicks.length}`, () => {
        App.bridge.delete_users(JSON.stringify(nicks));
        this.selected.clear();
        this._syncSelectionUI();
      });
  },

  clearAll() {
    if (!this._bridge()) return;
    if (!this.users.length) {
      LogConsole.log('ℹ User memory is already empty', 'info');
      return;
    }
    PresetsUI.confirm('Clear ALL users?',
      `All ${this.users.length} user(s) will be permanently removed from user ` +
      'memory. This cannot be undone.',
      'Clear all', () => {
        this.selected.clear();
        App.bridge.clear_memory();
      });
  },

  resetMessaged() {
    if (!this._bridge()) return;
    PresetsUI.confirm('Reset messaged flags?',
      'Every user will be marked as “new” again, so the bot may message them ' +
      'a second time. No user is deleted.',
      'Reset', () => App.bridge.reset_messaged());
  },

  toggleMessaged(nick) {
    if (!this._bridge()) return;
    const u = this.users.find((x) => x.nick === nick);
    if (!u) return;
    App.bridge.set_user_messaged(nick, !u.messaged);
  },

  manualMessage(nick) {
    LogConsole.log(`👤 Manual message: ${nick}`, 'info');
  },

  /**
   * React to the backend's person_found signal: a person was just collected
   * mid-scroll. Briefly flash their row so the new entry is noticeable.
   */
  onPersonFound(payloadJson) {
    let p = null;
    try { p = JSON.parse(payloadJson || 'null'); } catch (e) { p = null; }
    if (!p || !p.nick) return;
    this._flashNick = p.nick;
    // The table is re-rendered by users_updated right after this signal, so
    // flash on the next frame once the new row actually exists.
    requestAnimationFrame(() => this.flashRow(p.nick));
  },

  /** Briefly highlight one row by nickname. */
  flashRow(nick) {
    const tbody = document.getElementById('userTableBody');
    if (!tbody) return;
    const cb = tbody.querySelector(`input[data-nick="${CSS.escape(nick)}"]`);
    const row = cb ? cb.closest('tr')
                   : Array.from(tbody.querySelectorAll('tr')).find(
                       (tr) => tr.textContent.includes(nick));
    if (!row) return;
    row.classList.remove('row-flash');
    void row.offsetWidth;            // restart the animation
    row.classList.add('row-flash');
    row.scrollIntoView({ block: 'nearest' });
    setTimeout(() => row.classList.remove('row-flash'), 1600);
  },

  /**
   * React to the backend's person_removed signal: the person failed the
   * filter and their record was destroyed. Drop the row right away.
   */
  onPersonRemoved(payloadJson) {
    let p = null;
    try { p = JSON.parse(payloadJson || 'null'); } catch (e) { p = null; }
    if (!p || !p.nick) return;
    this.selected.delete(p.nick);
    this.users = this.users.filter((u) => u.nick !== p.nick);
    const reason = p.reason ? ` — ${p.reason}` : '';
    LogConsole.log(`🗑 Removed “${p.nick}”${reason}`, 'warn');
    this.render(this.users);
  },

  /** React to the backend's users_deleted signal. */
  onDeleted(nicksJson) {
    try {
      JSON.parse(nicksJson || '[]').forEach((n) => this.selected.delete(n));
    } catch (e) { /* ignore */ }
    this._syncSelectionUI();
  },

  // ── helpers ─────────────────────────────────────────────────
  _bridge() {
    if (!App.bridge) {
      LogConsole.log('⚠ Not connected to backend — action ignored', 'warn');
      return false;
    }
    return true;
  },

  _esc(s) {
    const d = document.createElement('div');
    d.textContent = (s === null || s === undefined) ? '' : String(s);
    return d.innerHTML;
  },

  /** Escape for use inside a double-quoted HTML attribute. */
  _attr(s) {
    return this._esc(s).replace(/"/g, '&quot;');
  },
};

document.addEventListener('DOMContentLoaded', () => UserTable.init());
