/* history-db-render.js — rendering for HistoryDb facade (H-B2b JS split)

Design: ≤250 LOC.
*/

'use strict';

const HistoryDbRender = {
  _flashIfPresent() {
    if (!this._flashNick || !this._els.body) return;
    const nick = this._flashNick;
    const rows = Array.from(this._els.body.querySelectorAll('.userdb-row') || []);
    const row = rows.find((r) => (r.dataset && r.dataset.nick) === nick);
    if (!row) { if (typeof HistoryStore !== 'undefined' && this.query === nick) this.reload(); return; }
    row.classList.remove('row-flash');
    void (row.offsetWidth || 0);
    row.classList.add('row-flash');
    if (typeof row.scrollIntoView === 'function') row.scrollIntoView({ block: 'nearest' });
    clearTimeout(this._flashTimer);
    this._flashTimer = setTimeout(() => { row.classList.remove('row-flash'); if (this._flashNick === nick) this._flashNick = ''; }, 1800);
  },

  visibleRows() {
    if (typeof Labels === 'undefined' || !Labels.filterActive) return this.rows;
    return this.rows.filter((person) => Labels.allows(person.nick));
  },

  _day(value) { return value ? String(value).slice(0, 10) : '—'; },

  _cell(row, text, cls) {
    const cell = document.createElement('td');
    if (cls) cell.className = cls;
    cell.appendChild(document.createTextNode(text == null ? '' : String(text)));
    row.appendChild(cell);
    return cell;
  },

  _actions(person) {
    const cell = document.createElement('td');
    cell.className = 'userdb-actions';
    const nick = person.nick || '';
    const button = (action, text, title, cls) => {
      const btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'btn-row' + (cls ? ' ' + cls : '');
      btn.dataset.action = action; btn.textContent = text; btn.title = title;
      cell.appendChild(btn); return btn;
    };
    button('label', '🏷', 'Label “' + nick + '” in the Label Manager');
    button('clear', '🧹', 'Delete the whole conversation but KEEP “' + nick + '” in the database (Ctrl+Z restores it)');
    button('delete', '🗑', 'Remove “' + nick + '” together with their entire history (Ctrl+Z restores both)', 'btn-row-danger');
    return cell;
  },

  render() {
    const body = this._els.body;
    if (!body) return;
    const nodes = [];
    const visible = this.visibleRows();
    if (!visible.length) {
      const empty = document.createElement('tr');
      const cell = document.createElement('td');
      cell.setAttribute('colspan', '7'); cell.className = 'history-notice';
      const filtered = this.rows.length && !visible.length;
      cell.appendChild(document.createTextNode(filtered ? 'Every loaded person is hidden by the label filter — clear it in the Label Manager to see them again.' : this.query ? 'No person matches “' + this.query + '”.' : 'The archive is still empty — the collector fills it while you chat.'));
      empty.appendChild(cell); nodes.push(empty);
    }
    visible.forEach((person) => {
      const row = document.createElement('tr');
      row.className = 'userdb-row' + (person.deleted ? ' deleted' : '') + ((typeof Labels !== 'undefined' && Labels.person === (person.nick || '')) ? ' row-label-target' : '');
      row.dataset.nick = person.nick || '';
      const nickCell = this._cell(row, person.nick, 'userdb-nick');
      nickCell.title = 'Open this conversation';
      if (typeof Labels !== 'undefined') {
        nickCell.appendChild(Labels.pills(person.nick, { labels: Array.isArray(person.labels) ? person.labels.map((l) => (typeof l === 'string' ? Labels.byId(l) : l)).filter(Boolean) : undefined }));
      }
      this._cell(row, person.message_count != null ? person.message_count : (person.messages || 0));
      this._cell(row, person.media_count != null ? person.media_count : (person.media || 0));
      this._cell(row, this._day(person.first_seen || person.first_day));
      this._cell(row, this._day(person.last_seen || person.last_day));
      this._cell(row, Array.isArray(person.my_nicks) ? person.my_nicks.join(', ') : (person.my_nick || '—'));
      row.appendChild(this._actions(person));
      nodes.push(row);
    });
    body.replaceChildren.apply(body, nodes);
    this._flashIfPresent();
    if (this._els.foot && this.total) this._els.foot.title = this.rows.length + ' of ' + this.total + ' loaded';
  },
};

if (typeof window !== 'undefined') window.HistoryDbRender = HistoryDbRender;
