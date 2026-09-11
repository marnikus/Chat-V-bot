/* ═══════════════════════════════════════════════════════════════
   history-db.js — the Full User Database window

   Every person the archive has ever seen, merged by nick (one row per
   person, never a duplicate), loaded lazily as the user scrolls, with a
   search over nicks and a live message-count. Clicking a row opens that
   person in the Person History window.
   ═══════════════════════════════════════════════════════════════ */

const HistoryDb = {
  rows: [],
  total: 0,
  hasMore: true,
  loading: false,
  query: '',
  sort: 'recent',
  pageSize: 50,
  preloadRows: 40,
  _seq: 0,
  _els: {},
  // _gen: bumped on every reload — a page response from an older generation
  // must never overwrite a newer view (a delete's page landing after the
  // undo's page used to freeze the list on the pre-undo state forever).
  _gen: 0,
  _flightGen: 0,            // the generation the in-flight page belongs to
  _changeTimer: null,

  init() {
    const $ = (id) => document.getElementById(id);
    this._els = {
      panel: $('winUserDb'),
      list: $('userdbList'),
      body: $('userdbBody'),
      search: $('userdbSearch'),
      foot: $('userdbFoot'),
      preload: $('userdbPreload'),
      refresh: $('userdbRefreshBtn'),
    };
    this._flashNick = '';
    if (!this._els.body) return;
    this._els.list.addEventListener('scroll', () => this._onScroll());
    this._els.body.addEventListener('click', (event) => {
      const row = event.target && event.target.closest
        ? event.target.closest('.userdb-row') : null;
      if (!row) return;
      const nick = row.dataset.nick;
      if (!nick) return;
      const action = (event.target.dataset && event.target.dataset.action) || '';
      if (action) {
        if (event.stopPropagation) event.stopPropagation();
        if (action === 'delete') this.deletePerson(nick);
        else if (action === 'clear') this.clearHistory(nick);
        else if (action === 'label') this.labelPerson(nick);
        return;
      }
      // A click anywhere else opens the conversation and points the Label
      // Manager at this person — one click, one obvious outcome (RULE 10).
      if (typeof Labels !== 'undefined') Labels.setPerson(nick);
      if (typeof HistoryStore !== 'undefined') HistoryStore.openPerson(nick);
    });
    if (this._els.search) {
      this._els.search.addEventListener('input', () => {
        clearTimeout(this._timer);
        this._timer = setTimeout(() => {
          this.query = this._els.search.value.trim();
          this.reload();
        }, 220);
      });
    }
    if (this._els.preload) {
      this._els.preload.addEventListener('change', () => {
        const value = Math.max(5, Math.min(500,
          Number(this._els.preload.value) || 40));
        this.preloadRows = value;
        this._els.preload.value = String(value);
        if (typeof HistoryStore !== 'undefined') {
          HistoryStore.preloadRows = value;
          HistoryStore.saveSettings();
        }
      });
    }
    if (this._els.refresh)
      this._els.refresh.addEventListener('click', () => this.reload());
    this.reload();
  },

  applySettings(settings) {
    const preview = (settings && settings.preview) || {};
    if (preview.preload_rows) {
      this.preloadRows = Number(preview.preload_rows);
      if (this._els.preload) this._els.preload.value = String(this.preloadRows);
    }
    if (preview.page_size) this.pageSize = Number(preview.page_size);
  },

  /** A fresh list from the top. Always issues its request right away — a
      change or a user action must never be deferred behind an in-flight
      page (that is how the list got frozen on the pre-undo state): the
      generation guard simply drops the older response when it lands. */
  reload() {
    if (!App.bridge || !App.bridge.userdb_page) return;
    this._gen += 1;
    this.rows = [];
    this.total = 0;
    this.hasMore = true;
    this.loading = true;
    this._flightGen = this._gen;
    this._requestPage(0);
    this._requestStats();
  },

  _requestPage(offset) {
    const id = 'u' + (++this._seq);
    App.bridge.userdb_page(id, JSON.stringify({
      q: this.query, limit: this.pageSize, offset: offset, sort: this.sort,
    }));
  },

  /** Scroll pagination — one page at a time, no duplicates. */
  _request(offset) {
    if (this.loading || !this.hasMore) return;
    this.loading = true;
    this._flightGen = this._gen;
    this._requestPage(offset);
  },

  _requestStats() {
    if (!App.bridge || !App.bridge.userdb_stats) return;
    App.bridge.userdb_stats('s' + (++this._seq));
  },

  /** A page landed (or the request died): free the in-flight slot. */
  _settle() {
    this.loading = false;
  },

  onPage(reqId, json) {
    let data = null;
    try { data = JSON.parse(json); } catch (e) { data = null; }
    if (!data) { this._settle(); return; }
    if (data.items === undefined) {     // the stats payload, not a page
      this.onStats(data);
      return;
    }
    this._settle();
    if (this._flightGen !== this._gen) return;  // stale page: never overwrite
    const items = data.items || [];
    if (data.offset ? data.offset === 0 : !this.rows.length) this.rows = items;
    else {
      const seen = new Set(this.rows.map((r) => r.nick));
      items.forEach((item) => { if (!seen.has(item.nick)) this.rows.push(item); });
    }
    this.total = data.total != null ? data.total : this.rows.length;
    this.hasMore = !!data.has_more;
    this.render();
  },

  onStats(data) {
    if (!this._els.foot) return;
    const parts = [];
    if (data.persons != null) parts.push(data.persons + ' people');
    if (data.messages != null) parts.push(data.messages + ' messages');
    if (data.media != null) parts.push(data.media + ' media');
    const bytes = data.bytes != null ? data.bytes : data.media_bytes;
    if (bytes != null) parts.push((bytes / 1048576).toFixed(1) + ' MB cached');
    if (data.gaps) parts.push(data.gaps + ' gaps');
    this._els.foot.textContent = parts.join(' · ');
  },

  /** Anything upstream changed (delete, undo, new person, label…). Burst
      coalesced into one reload: an undo fires several wire events at once. */
  onChanged() {
    clearTimeout(this._changeTimer);
    this._changeTimer = setTimeout(() => this.reload(), 250);
  },

  _onScroll() {
    const list = this._els.list;
    if (!list || this.loading || !this.hasMore) return;
    const remaining = list.scrollHeight - list.scrollTop - list.clientHeight;
    if (remaining < 120) this._request(this.rows.length);
  },

  /** Remove the person AND their whole history — behind a confirm, since
      one misclick would erase a person + every one of their messages
      (undoable with Ctrl+Z, but still destructive). */
  deletePerson(nick) {
    if (!App.bridge || !App.bridge.history_delete_person) return;
    const remove = () => App.bridge.history_delete_person(nick, false);
    if (window.Dialog && Dialog.confirm) {
      Dialog.confirm(
        'Remove person?',
        '“' + nick + '” and their entire message history will be removed ' +
        'from the database. Ctrl+Z restores both.',
        'Remove', remove);
      return;
    }
    remove();
  },

  /** Wipe the conversation but keep the person in the database. */
  clearHistory(nick) {
    if (!App.bridge || !App.bridge.history_clear_person) return;
    App.bridge.history_clear_person(nick);
  },

  /** Point the Label Manager at this person and bring the window forward. */
  labelPerson(nick) {
    if (typeof Labels === 'undefined') return;
    Labels.setPerson(nick, { focus: true });
  },

  /**
   * Quick-assign target highlight, called by Labels.setPerson(): move the
   * accent bar to this person's row in place. render() stamps the same
   * class from Labels.person, so the two stay in agreement.
   */
  markLabelTarget(nick) {
    const body = this._els.body;
    if (!body || !body.querySelectorAll) return;
    const clean = String(nick || '').trim();
    body.querySelectorAll('tr[data-nick]').forEach((row) => {
      const on = !!clean && row.dataset.nick === clean;
      row.classList.toggle('row-label-target', on);
      if (on && row.scrollIntoView) row.scrollIntoView({ block: 'nearest' });
    });
  },

  /** Show one person in the database: filter to that nick, flash the row. */
  highlightNick(nick) {
    this._flashNick = String(nick || '').trim();
    if (!this._flashNick) return;
    this.query = this._flashNick;
    if (this._els.search) this._els.search.value = this._flashNick;
    this._flashIfPresent();
    this.reload();
  },

  // ── rendering (createElement only) ───────────────────────────

  /** Flash the row the collector just asked us to highlight, when loaded. */
  _flashIfPresent() {
    if (!this._flashNick || !this._els.body) return;
    const nick = this._flashNick;
    const rows = Array.from(this._els.body.querySelectorAll('.userdb-row') || []);
    const row = rows.find((r) => (r.dataset && r.dataset.nick) === nick);
    if (!row) {
      // The row may be on a later page; the query is already set to the nick,
      // so the next page load will bring it to the top.
      if (typeof HistoryStore !== 'undefined' && this.query === nick) this.reload();
      return;
    }
    row.classList.remove('row-flash');
    void (row.offsetWidth || 0);                    // restart the animation
    row.classList.add('row-flash');
    if (typeof row.scrollIntoView === 'function')
      row.scrollIntoView({ block: 'nearest' });
    clearTimeout(this._flashTimer);
    this._flashTimer = setTimeout(() => {
      row.classList.remove('row-flash');
      if (this._flashNick === nick) this._flashNick = '';
    }, 1800);
  },

  /** Rows left after the Label Manager's include/exclude filter. */
  visibleRows() {
    if (typeof Labels === 'undefined' || !Labels.filterActive) return this.rows;
    return this.rows.filter((person) => Labels.allows(person.nick));
  },

  /** 'YYYY-MM-DD HH:MM:SS' → 'YYYY-MM-DD' (the table only has room for a day). */
  _day(value) {
    return value ? String(value).slice(0, 10) : '—';
  },

  _cell(row, text, cls) {
    const cell = document.createElement('td');
    if (cls) cell.className = cls;
    cell.appendChild(document.createTextNode(text == null ? '' : String(text)));
    row.appendChild(cell);
    return cell;
  },

  /** Per-row buttons: label · clear history · remove person + history. */
  _actions(person) {
    const cell = document.createElement('td');
    cell.className = 'userdb-actions';
    const nick = person.nick || '';
    const button = (action, text, title, cls) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn-row' + (cls ? ' ' + cls : '');
      btn.dataset.action = action;
      btn.textContent = text;
      btn.title = title;
      cell.appendChild(btn);
      return btn;
    };
    button('label', '🏷', 'Label “' + nick + '” in the Label Manager');
    button('clear', '🧹', 'Delete the whole conversation but KEEP “' + nick +
           '” in the database (Ctrl+Z restores it)');
    button('delete', '🗑', 'Remove “' + nick + '” together with their entire ' +
           'history (Ctrl+Z restores both)', 'btn-row-danger');
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
      cell.setAttribute('colspan', '7');
      cell.className = 'history-notice';
      const filtered = this.rows.length && !visible.length;
      cell.appendChild(document.createTextNode(
        filtered
          ? 'Every loaded person is hidden by the label filter — clear it in ' +
            'the Label Manager to see them again.'
          : this.query ? 'No person matches “' + this.query + '”.'
                       : 'The archive is still empty — the collector fills it ' +
                         'while you chat.'));
      empty.appendChild(cell);
      nodes.push(empty);
    }
    visible.forEach((person) => {
      const row = document.createElement('tr');
      row.className = 'userdb-row' + (person.deleted ? ' deleted' : '') +
        ((typeof Labels !== 'undefined' &&
          Labels.person === (person.nick || ''))
          ? ' row-label-target' : '');
      row.dataset.nick = person.nick || '';
      const nickCell = this._cell(row, person.nick, 'userdb-nick');
      nickCell.title = 'Open this conversation';
      // The very same pill renderer the People table uses, so a label can
      // never look different in the two tables.
      if (typeof Labels !== 'undefined') {
        nickCell.appendChild(Labels.pills(person.nick, {
          labels: Array.isArray(person.labels)
            ? person.labels.map((l) => (typeof l === 'string'
              ? Labels.byId(l) : l)).filter(Boolean)
            : undefined,
        }));
      }
      this._cell(row, person.message_count != null ? person.message_count
                                                   : (person.messages || 0));
      this._cell(row, person.media_count != null ? person.media_count
                                                 : (person.media || 0));
      this._cell(row, this._day(person.first_seen || person.first_day));
      this._cell(row, this._day(person.last_seen || person.last_day));
      this._cell(row, Array.isArray(person.my_nicks)
        ? person.my_nicks.join(', ') : (person.my_nick || '—'));
      row.appendChild(this._actions(person));
      nodes.push(row);
    });
    body.replaceChildren.apply(body, nodes);
    this._flashIfPresent();
    if (this._els.foot && this.total)
      this._els.foot.title = this.rows.length + ' of ' + this.total + ' loaded';
  },
};

if (typeof window !== 'undefined') window.HistoryDb = HistoryDb;
